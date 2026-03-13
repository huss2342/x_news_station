"""Thread-safe and process-safe JSON persistence helpers.

These helpers provide:
1. Cross-thread locking within a process.
2. Best-effort cross-process file locking.
3. Atomic JSON writes via temporary files and `os.replace`.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

import config

T = TypeVar("T")

_LOCK_REGISTRY_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.Lock] = {}


def _get_thread_lock(lock_path: Path) -> threading.Lock:
    """Return a stable in-memory lock object for a lock file path."""
    key = str(lock_path.resolve())
    with _LOCK_REGISTRY_GUARD:
        if key not in _THREAD_LOCKS:
            _THREAD_LOCKS[key] = threading.Lock()
        return _THREAD_LOCKS[key]


def _acquire_process_lock(lock_file: Any) -> None:
    """Acquire a non-blocking OS file lock for the lock file handle."""
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_process_lock(lock_file: Any) -> None:
    """Release a previously acquired OS file lock."""
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _locked_path(path: Path) -> Iterator[None]:
    """Lock a sidecar `.lock` file for coordinated JSON access."""
    timeout_seconds = config.JSON_LOCK_TIMEOUT_SECONDS
    retry_seconds = config.JSON_LOCK_RETRY_SECONDS
    lock_path = path.with_suffix(f"{path.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    thread_lock = _get_thread_lock(lock_path)
    if not thread_lock.acquire(timeout=timeout_seconds):
        raise TimeoutError(f"Timed out waiting for thread lock on {lock_path}")

    try:
        with open(lock_path, "a+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()

            start = time.monotonic()
            while True:
                try:
                    _acquire_process_lock(lock_file)
                    break
                except OSError:
                    if time.monotonic() - start >= timeout_seconds:
                        raise TimeoutError(f"Timed out waiting for file lock on {lock_path}")
                    time.sleep(retry_seconds)

            try:
                yield
            finally:
                try:
                    _release_process_lock(lock_file)
                except OSError:
                    # Process is already unwinding from another failure path.
                    _ignored_unlock_error = None
    finally:
        thread_lock.release()


def read_json_file(
    path: Path,
    default_factory: Callable[[], T],
    logger: logging.Logger,
    validator: Callable[[Any], T] | None = None,
) -> T:
    """Read JSON from disk with locking and corruption-safe fallback.

    Args:
        path: JSON file path.
        default_factory: Callable that returns a default value when read fails.
        logger: Logger for diagnostics.
        validator: Optional validator/transformer for parsed JSON.

    Returns:
        Parsed and validated data, or the default value.
    """
    try:
        with _locked_path(path):
            if not path.exists():
                return default_factory()

            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("Failed to read JSON file %s: %s", path, exc)
                return default_factory()

            if not raw.strip():
                return default_factory()

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning("JSON decode failed for %s: %s", path, exc)
                return default_factory()

            if validator is None:
                return parsed

            try:
                return validator(parsed)
            except ValueError as exc:
                logger.warning("JSON validation failed for %s: %s", path, exc)
                return default_factory()
    except TimeoutError as exc:
        logger.warning("JSON read lock timeout for %s: %s", path, exc)
        return default_factory()


def write_json_file(path: Path, payload: Any, logger: logging.Logger) -> bool:
    """Write JSON atomically under lock.

    Args:
        path: Target JSON file path.
        payload: JSON-serializable payload.
        logger: Logger for diagnostics.

    Returns:
        True when persisted successfully, False otherwise.
    """
    temporary_path: str | None = None

    try:
        with _locked_path(path):
            path.parent.mkdir(parents=True, exist_ok=True)

            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=f"{path.name}.",
                suffix=".tmp",
                dir=str(path.parent),
                text=True,
            )
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temporary_path, path)
            temporary_path = None
            return True
    except TimeoutError as exc:
        logger.error("JSON write lock timeout for %s: %s", path, exc)
        return False
    except (TypeError, OSError) as exc:
        logger.error("Failed writing JSON file %s: %s", path, exc)
        return False
    finally:
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                # Non-critical cleanup failure.
                _ignored_cleanup_error = None
