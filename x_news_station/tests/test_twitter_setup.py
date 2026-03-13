"""Tests for safer Twitter session import helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules import twitter_setup


def test_build_twitter_cookie_string_accepts_direct_tokens() -> None:
    cookie_value = twitter_setup.build_twitter_cookie_string(auth_token="token-123", ct0="csrf-456")
    assert cookie_value == "auth_token=token-123; ct0=csrf-456"


def test_build_twitter_cookie_string_merges_cookie_blob_with_overrides() -> None:
    with patch("modules.twitter_setup._parse_cookie_string", return_value={"auth_token": "old", "ct0": "old-ct0", "kdt": "keep"}):
        cookie_value = twitter_setup.build_twitter_cookie_string(
            cookie_string="auth_token=old; ct0=old-ct0; kdt=keep",
            auth_token="new-token",
            ct0="new-ct0",
        )
    assert cookie_value == "auth_token=new-token; ct0=new-ct0; kdt=keep"


def test_build_twitter_cookie_string_requires_both_core_fields() -> None:
    with pytest.raises(ValueError):
        twitter_setup.build_twitter_cookie_string(auth_token="token-only")


def test_normalize_script_manifest_handles_unquoted_keys() -> None:
    manifest = '{ondemand:"abc123",vendor:"def456"}'
    assert twitter_setup._normalize_script_manifest(manifest) == {
        "ondemand": "abc123",
        "vendor": "def456",
    }


def test_create_twscrape_api_uses_project_local_db(tmp_path: Path) -> None:
    captured: list[str] = []

    class FakeAPI:
        def __init__(self, db_file: str) -> None:
            captured.append(db_file)

    with patch("modules.twitter_setup.get_twitter_db_path", return_value=tmp_path / "accounts.db"):
        with patch("modules.twitter_setup.patch_twscrape_script_parser", return_value=True):
            with patch.dict(sys.modules, {"twscrape": SimpleNamespace(API=FakeAPI)}):
                twitter_setup.create_twscrape_api()

    assert captured == [str(tmp_path / "accounts.db")]


def test_import_twitter_session_saves_cookie_session_without_plaintext_password_file(tmp_path: Path) -> None:
    created_pools: list[FakeAccountsPool] = []

    class FakeAccount:
        def __init__(self) -> None:
            self.cookies: dict[str, str] = {}
            self.active = False
            self.error_msg: str | None = None

    class FakeAccountsPool:
        def __init__(self, db_file: str, raise_when_no_account: bool = False) -> None:
            _ = raise_when_no_account
            self.db_file = db_file
            self.added: dict[str, str] | None = None
            self.saved: FakeAccount | None = None
            created_pools.append(self)

        async def get_account(self, username: str) -> FakeAccount | None:
            _ = username
            return None

        async def add_account(self, **kwargs: str) -> None:
            self.added = kwargs

        async def accounts_info(self) -> list[dict[str, object]]:
            return [{"username": "kahaka007", "active": True}]

        async def save(self, account: FakeAccount) -> None:
            self.saved = account

    with patch("modules.twitter_setup.get_twitter_db_path", return_value=tmp_path / "accounts.db"):
        with patch("modules.twitter_setup.patch_twscrape_script_parser", return_value=True):
            with patch("modules.twitter_setup._parse_cookie_string", return_value={"auth_token": "token-123", "ct0": "csrf-456"}):
                with patch.dict(sys.modules, {"twscrape": SimpleNamespace(AccountsPool=FakeAccountsPool)}):
                    result = twitter_setup.import_twitter_session(
                        username="@kahaka007",
                        auth_token="token-123",
                        ct0="csrf-456",
                    )

    assert result.username == "kahaka007"
    assert result.db_path == tmp_path / "accounts.db"
    assert result.active is True
    assert result.account_count == 1
    assert created_pools[0].added is not None
    assert created_pools[0].added["username"] == "kahaka007"
    assert created_pools[0].added["password"] == twitter_setup.COOKIE_PLACEHOLDER_PASSWORD
    assert created_pools[0].added["cookies"] == "auth_token=token-123; ct0=csrf-456"


def test_load_saved_twitter_account_returns_tokens(tmp_path: Path) -> None:
    class FakeAccount:
        username = "kahaka007"
        active = True
        error_msg = None
        last_used = None
        cookies = {"auth_token": "token-123", "ct0": "csrf-456"}

    class FakeAccountsPool:
        def __init__(self, db_file: str, raise_when_no_account: bool = False) -> None:
            _ = (db_file, raise_when_no_account)

        async def get_account(self, username: str):
            assert username == "kahaka007"
            return FakeAccount()

        async def accounts_info(self) -> list[dict[str, object]]:
            return [{"username": "kahaka007", "active": True, "logged_in": False, "error_msg": ""}]

    db_path = tmp_path / "accounts.db"
    db_path.write_text("placeholder", encoding="utf-8")
    with patch("modules.twitter_setup.get_twitter_db_path", return_value=db_path):
        with patch("modules.twitter_setup.patch_twscrape_script_parser", return_value=True):
            with patch.dict(sys.modules, {"twscrape": SimpleNamespace(AccountsPool=FakeAccountsPool)}):
                account = twitter_setup.load_saved_twitter_account("kahaka007")

    assert account.username == "kahaka007"
    assert account.auth_token == "token-123"
    assert account.ct0 == "csrf-456"
    assert account.has_auth_token is True
    assert account.has_ct0 is True
