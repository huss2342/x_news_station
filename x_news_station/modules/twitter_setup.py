"""Helpers for project-local twscrape session management."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import config

COOKIE_FIELD_NAMES = ("auth_token", "ct0")
COOKIE_PLACEHOLDER_PASSWORD = "cookie-session"
_SCRIPT_KEY_REGEX = re.compile(r'([{\s,])([A-Za-z0-9_.-]+):')


@dataclass(slots=True)
class TwitterSessionImportResult:
    """Result returned after importing a Twitter session cookie."""

    username: str
    db_path: Path
    active: bool
    account_count: int | None


@dataclass(slots=True)
class SavedTwitterAccount:
    """Project-local twscrape account metadata for launcher management."""

    username: str
    active: bool
    logged_in: bool
    error_msg: str
    last_used: str
    has_auth_token: bool
    has_ct0: bool
    auth_token: str = ""
    ct0: str = ""


def get_twitter_db_path() -> Path:
    """Return the project-local twscrape account database path."""
    return config.get_twitter_accounts_db_file()


def _parse_cookie_string(cookie_string: str) -> dict[str, str]:
    try:
        from twscrape.utils import parse_cookies
    except ImportError as exc:
        raise RuntimeError("twscrape is not installed. Install requirements before importing a Twitter session.") from exc

    try:
        parsed = parse_cookies(cookie_string)
    except Exception as exc:
        raise ValueError(f"Invalid cookie string: {exc}") from exc

    normalized = {str(key).strip(): str(value).strip() for key, value in parsed.items()}
    return {key: value for key, value in normalized.items() if key and value}


def _build_cookie_map(cookie_string: str = "", auth_token: str = "", ct0: str = "") -> dict[str, str]:
    cookie_map: dict[str, str] = {}
    if cookie_string.strip():
        cookie_map.update(_parse_cookie_string(cookie_string.strip()))

    if auth_token.strip():
        cookie_map["auth_token"] = auth_token.strip()
    if ct0.strip():
        cookie_map["ct0"] = ct0.strip()

    missing = [field_name for field_name in COOKIE_FIELD_NAMES if not cookie_map.get(field_name)]
    if missing:
        raise ValueError(
            "Twitter session import requires both auth_token and ct0. "
            "Paste both fields or provide a full cookie string."
        )
    return cookie_map


def build_twitter_cookie_string(cookie_string: str = "", auth_token: str = "", ct0: str = "") -> str:
    """Normalize cookie inputs into a twscrape-compatible cookie string."""
    cookie_map = _build_cookie_map(cookie_string=cookie_string, auth_token=auth_token, ct0=ct0)
    ordered_keys = list(COOKIE_FIELD_NAMES) + [key for key in cookie_map if key not in COOKIE_FIELD_NAMES]
    return "; ".join(f"{key}={cookie_map[key]}" for key in ordered_keys if cookie_map.get(key))


def _normalize_script_manifest(raw_manifest: str) -> dict[str, str]:
    try:
        decoded = json.loads(raw_manifest)
    except json.JSONDecodeError:
        patched_manifest = _SCRIPT_KEY_REGEX.sub(lambda match: f'{match.group(1)}"{match.group(2)}":', raw_manifest)
        decoded = json.loads(patched_manifest)

    if not isinstance(decoded, dict):
        raise ValueError("Unexpected script manifest payload")
    return {str(key): str(value) for key, value in decoded.items()}


def patch_twscrape_script_parser() -> bool:
    """Patch brittle twscrape script parsing for current X responses."""
    try:
        import twscrape.xclid as xclid
    except ImportError:
        return False

    if getattr(xclid, "_xns_parser_patch_applied", False):
        return True

    original_get_scripts_list = xclid.get_scripts_list

    def patched_get_scripts_list(text: str):
        try:
            yield from original_get_scripts_list(text)
            return
        except Exception as exc:
            if "Failed to parse scripts" not in str(exc):
                raise

        try:
            manifest = text.split('e=>e+"."+')[1].split('[e]+"a.js"')[0]
            for key, value in _normalize_script_manifest(manifest).items():
                yield xclid.script_url(key, f"{value}a")
        except Exception as exc:
            raise Exception("Failed to parse scripts") from exc

    xclid.get_scripts_list = patched_get_scripts_list
    xclid._xns_parser_patch_applied = True
    return True


def create_twscrape_api() -> Any:
    """Return a twscrape API bound to the project-local account store."""
    patch_twscrape_script_parser()
    try:
        from twscrape import API
    except ImportError as exc:
        raise RuntimeError("twscrape is not installed. Install requirements before enabling real Twitter mode.") from exc
    return API(str(get_twitter_db_path()))


async def _import_twitter_session_async(username: str, cookie_value: str, db_path: Path) -> TwitterSessionImportResult:
    patch_twscrape_script_parser()
    try:
        from twscrape import AccountsPool
    except ImportError as exc:
        raise RuntimeError("twscrape is not installed. Install requirements before importing a Twitter session.") from exc

    pool = AccountsPool(db_file=str(db_path), raise_when_no_account=False)
    existing = await pool.get_account(username)
    new_cookie_map = _parse_cookie_string(cookie_value)

    if existing is None:
        await pool.add_account(
            username=username,
            password=COOKIE_PLACEHOLDER_PASSWORD,
            email=f"{username}@local.invalid",
            email_password=COOKIE_PLACEHOLDER_PASSWORD,
            cookies=cookie_value,
        )
    else:
        existing.cookies.update(new_cookie_map)
        existing.active = "ct0" in existing.cookies
        existing.error_msg = None
        await pool.save(existing)

    account_count: int | None = None
    active = False
    try:
        info_items = await pool.accounts_info()
    except Exception:
        info_items = []

    if info_items:
        account_count = len(info_items)
        matched = next((item for item in info_items if item.get("username") == username), None)
        if matched is not None:
            active = bool(matched.get("active"))
    elif existing is not None:
        active = bool(existing.active)

    return TwitterSessionImportResult(
        username=username,
        db_path=db_path,
        active=active,
        account_count=account_count,
    )


def _account_from_pool_record(account: Any, info_lookup: dict[str, dict[str, Any]] | None = None) -> SavedTwitterAccount:
    info_lookup = info_lookup or {}
    info = info_lookup.get(account.username, {})
    cookies = getattr(account, "cookies", {}) or {}
    return SavedTwitterAccount(
        username=str(getattr(account, "username", "")),
        active=bool(info.get("active", getattr(account, "active", False))),
        logged_in=bool(info.get("logged_in", False)),
        error_msg=str(info.get("error_msg", getattr(account, "error_msg", "") or "")),
        last_used=str(info.get("last_used") or getattr(account, "last_used", "") or ""),
        has_auth_token=bool(cookies.get("auth_token")),
        has_ct0=bool(cookies.get("ct0")),
        auth_token=str(cookies.get("auth_token", "")),
        ct0=str(cookies.get("ct0", "")),
    )


async def _list_saved_twitter_accounts_async(db_path: Path) -> list[SavedTwitterAccount]:
    patch_twscrape_script_parser()
    try:
        from twscrape import AccountsPool
    except ImportError as exc:
        raise RuntimeError("twscrape is not installed. Install requirements before loading saved accounts.") from exc

    pool = AccountsPool(db_file=str(db_path), raise_when_no_account=False)
    accounts = await pool.get_all()
    try:
        info_items = await pool.accounts_info()
    except Exception:
        info_items = []
    info_lookup = {str(item.get("username", "")): item for item in info_items if isinstance(item, dict)}
    return [_account_from_pool_record(account, info_lookup) for account in accounts]


async def _load_saved_twitter_account_async(username: str, db_path: Path) -> SavedTwitterAccount:
    patch_twscrape_script_parser()
    try:
        from twscrape import AccountsPool
    except ImportError as exc:
        raise RuntimeError("twscrape is not installed. Install requirements before loading saved accounts.") from exc

    pool = AccountsPool(db_file=str(db_path), raise_when_no_account=False)
    account = await pool.get_account(username)
    if account is None:
        raise ValueError(f"No saved Twitter account named @{username} was found.")
    try:
        info_items = await pool.accounts_info()
    except Exception:
        info_items = []
    info_lookup = {str(item.get("username", "")): item for item in info_items if isinstance(item, dict)}
    return _account_from_pool_record(account, info_lookup)


async def _delete_saved_twitter_account_async(username: str, db_path: Path) -> None:
    patch_twscrape_script_parser()
    try:
        from twscrape import AccountsPool
    except ImportError as exc:
        raise RuntimeError("twscrape is not installed. Install requirements before deleting saved accounts.") from exc

    pool = AccountsPool(db_file=str(db_path), raise_when_no_account=False)
    await pool.delete_accounts(username)


async def _reset_twitter_locks_async(db_path: Path) -> None:
    patch_twscrape_script_parser()
    try:
        from twscrape import AccountsPool
    except ImportError as exc:
        raise RuntimeError("twscrape is not installed. Install requirements before resetting locks.") from exc

    pool = AccountsPool(db_file=str(db_path), raise_when_no_account=False)
    await pool.reset_locks()


def list_saved_twitter_accounts() -> list[SavedTwitterAccount]:
    """Return saved accounts from the project-local twscrape store."""
    db_path = get_twitter_db_path()
    if not db_path.exists():
        return []
    return asyncio.run(_list_saved_twitter_accounts_async(db_path))


def load_saved_twitter_account(username: str) -> SavedTwitterAccount:
    """Return one saved account, including auth_token and ct0 when present."""
    normalized_username = username.strip().lstrip("@")
    if not normalized_username:
        raise ValueError("Twitter username is required.")
    db_path = get_twitter_db_path()
    if not db_path.exists():
        raise ValueError(f"No saved Twitter account store exists at {db_path}.")
    return asyncio.run(_load_saved_twitter_account_async(normalized_username, db_path))


def delete_saved_twitter_account(username: str) -> None:
    """Delete one saved account from the project-local twscrape store."""
    normalized_username = username.strip().lstrip("@")
    if not normalized_username:
        raise ValueError("Twitter username is required.")
    db_path = get_twitter_db_path()
    if not db_path.exists():
        return
    asyncio.run(_delete_saved_twitter_account_async(normalized_username, db_path))


def reset_twitter_locks() -> None:
    """Clear twscrape queue locks for the project-local account store."""
    db_path = get_twitter_db_path()
    if not db_path.exists():
        return
    asyncio.run(_reset_twitter_locks_async(db_path))


def import_twitter_session(
    username: str,
    cookie_string: str = "",
    auth_token: str = "",
    ct0: str = "",
) -> TwitterSessionImportResult:
    """Import or update a saved Twitter session without writing secrets to the INI."""
    normalized_username = username.strip().lstrip("@")
    if not normalized_username:
        raise ValueError("Twitter username is required.")

    cookie_value = build_twitter_cookie_string(cookie_string=cookie_string, auth_token=auth_token, ct0=ct0)
    db_path = get_twitter_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_import_twitter_session_async(normalized_username, cookie_value, db_path))
