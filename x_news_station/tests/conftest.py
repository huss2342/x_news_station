"""Shared pytest fixtures for X-News-Station tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from modules.news_fetcher import TweetData


@pytest.fixture
def sample_tweet() -> TweetData:
    """Return a reusable TweetData fixture."""
    return TweetData(
        id="fixture-1",
        username="fixture_user",
        text="Fixture tweet text",
        timestamp=datetime(2026, 1, 1, 0, 0, 0),
    )
