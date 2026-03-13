"""Tests for locked JSON storage helpers."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from modules.json_storage import read_json_file, write_json_file


def test_read_json_file_returns_default_for_missing_file(tmp_path: Path) -> None:
    """Missing files should resolve to default values."""
    path = tmp_path / "missing.json"
    logger = logging.getLogger(__name__)

    result = read_json_file(path=path, default_factory=list, logger=logger)
    assert result == []


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    """Data written with atomic helper should be readable by helper."""
    path = tmp_path / "data.json"
    payload = {"seen_ids": ["1", "2"]}
    logger = logging.getLogger(__name__)

    write_ok = write_json_file(path=path, payload=payload, logger=logger)
    loaded = read_json_file(path=path, default_factory=dict, logger=logger)

    assert write_ok is True
    assert loaded == payload


def test_read_json_file_returns_default_on_corrupt_json(tmp_path: Path) -> None:
    """Corrupt JSON should not crash and should return defaults."""
    path = tmp_path / "corrupt.json"
    path.write_text("{not json", encoding="utf-8")
    logger = logging.getLogger(__name__)

    result = read_json_file(path=path, default_factory=dict, logger=logger)
    assert result == {}


def test_write_json_file_returns_false_for_unserializable_payload(tmp_path: Path) -> None:
    """Non-serializable payloads should fail gracefully."""
    path = tmp_path / "invalid.json"
    logger = logging.getLogger(__name__)

    result = write_json_file(path=path, payload={"data": {1, 2, 3}}, logger=logger)
    assert result is False


def test_concurrent_writes_produce_valid_json(tmp_path: Path) -> None:
    """Concurrent writes should leave a valid JSON file on disk."""
    path = tmp_path / "concurrent.json"
    logger = logging.getLogger(__name__)

    def writer(index: int) -> None:
        assert write_json_file(path=path, payload={"index": index}, logger=logger) is True

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert "index" in parsed
