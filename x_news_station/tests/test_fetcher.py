"""Tests for the news_fetcher module."""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from modules.news_fetcher import (
    BaseTweetMonitor,
    MockTwitterMonitor,
    TweetData,
    TwitterMonitor,
    get_monitor,
)


class TestTweetData:
    """Tests for TweetData dataclass."""

    def test_tweet_data_creation(self) -> None:
        """Test that TweetData can be created with all fields."""
        timestamp = datetime.now()
        tweet = TweetData(
            id="12345",
            username="testuser",
            text="This is a test tweet",
            timestamp=timestamp,
        )

        assert tweet.id == "12345"
        assert tweet.username == "testuser"
        assert tweet.text == "This is a test tweet"
        assert tweet.timestamp == timestamp


class TestMockTwitterMonitor:
    """Tests for MockTwitterMonitor."""

    def test_returns_correct_structure_on_first_call(self) -> None:
        """Test that MockTwitterMonitor returns correct TweetData structure on first call."""
        monitor = MockTwitterMonitor()
        tweets = monitor.fetch_latest(["elonmusk", "sama"])

        assert len(tweets) == 5

        for tweet in tweets:
            assert isinstance(tweet, TweetData)
            assert isinstance(tweet.id, str)
            assert isinstance(tweet.username, str)
            assert isinstance(tweet.text, str)
            assert isinstance(tweet.timestamp, datetime)
            assert len(tweet.id) > 0
            assert len(tweet.username) > 0
            assert len(tweet.text) > 0

    def test_returns_zero_tweets_on_second_call(self) -> None:
        """Test that MockTwitterMonitor returns 0 tweets on subsequent calls."""
        monitor = MockTwitterMonitor()

        # First call returns 5 tweets
        tweets_first = monitor.fetch_latest(["elonmusk"])
        assert len(tweets_first) == 5

        # Second call returns 0 tweets
        tweets_second = monitor.fetch_latest(["elonmusk"])
        assert len(tweets_second) == 0

        # Third call also returns 0
        tweets_third = monitor.fetch_latest(["elonmusk"])
        assert len(tweets_third) == 0

    def test_deterministic_output(self) -> None:
        """Test that MockTwitterMonitor returns deterministic fake data."""
        monitor1 = MockTwitterMonitor()
        monitor2 = MockTwitterMonitor()

        tweets1 = monitor1.fetch_latest(["test"])
        tweets2 = monitor2.fetch_latest(["test"])

        assert len(tweets1) == len(tweets2) == 5

        for t1, t2 in zip(tweets1, tweets2):
            assert t1.id == t2.id
            assert t1.username == t2.username
            assert t1.text == t2.text
            assert t1.timestamp == t2.timestamp


class TestTwitterMonitor:
    """Tests for TwitterMonitor."""

    def test_initializes_with_empty_seen_ids(self, tmp_path: Path) -> None:
        """Test that TwitterMonitor initializes with empty seen_ids when file doesn't exist."""
        seen_ids_file = tmp_path / "seen_ids.json"
        monitor = TwitterMonitor(str(seen_ids_file))

        assert monitor.seen_ids == set()

    def test_loads_seen_ids_from_file(self, tmp_path: Path) -> None:
        """Test that TwitterMonitor loads seen IDs from existing file."""
        seen_ids_file = tmp_path / "seen_ids.json"
        data = {"seen_ids": ["123", "456", "789"]}
        seen_ids_file.write_text(json.dumps(data))

        monitor = TwitterMonitor(str(seen_ids_file))

        assert monitor.seen_ids == {"123", "456", "789"}

    def test_handles_corrupt_seen_ids_file(self, tmp_path: Path) -> None:
        """Test that TwitterMonitor handles corrupt JSON gracefully."""
        seen_ids_file = tmp_path / "seen_ids.json"
        seen_ids_file.write_text("not valid json")

        monitor = TwitterMonitor(str(seen_ids_file))

        assert monitor.seen_ids == set()

    def test_fetch_latest_skips_seen_tweets(self, tmp_path: Path) -> None:
        """Test that fetch_latest skips already-seen tweets."""
        seen_ids_file = tmp_path / "seen_ids.json"

        # Create mock tweet
        mock_tweet = MagicMock()
        mock_tweet.id = "12345"
        mock_tweet.rawContent = "Test tweet content"
        mock_tweet.date = datetime.now()

        # Setup mock API
        mock_api = MagicMock()
        mock_api.user_by_login.return_value = MagicMock(id=12345)
        mock_api.user_tweets.return_value = [mock_tweet]

        twscrape_mock = MagicMock()
        twscrape_mock.API.return_value = mock_api

        with patch.dict(sys.modules, {"twscrape": twscrape_mock}):
            monitor = TwitterMonitor(str(seen_ids_file))

            # First fetch should return the tweet
            tweets1 = monitor.fetch_latest(["testuser"])
            assert len(tweets1) == 1

            # Second fetch should return empty (tweet already seen)
            tweets2 = monitor.fetch_latest(["testuser"])
            assert len(tweets2) == 0
            assert twscrape_mock.API.call_args.args[0].endswith("accounts.db")

    def test_fetch_latest_handles_errors_gracefully(self, tmp_path: Path) -> None:
        """Test that fetch_latest handles API errors without crashing."""
        seen_ids_file = tmp_path / "seen_ids.json"

        # Setup mock API to raise exception
        mock_api = MagicMock()
        mock_api.user_by_login.return_value = MagicMock(id=12345)
        mock_api.user_tweets.side_effect = Exception("Network error")

        twscrape_mock = MagicMock()
        twscrape_mock.API.return_value = mock_api

        with patch.dict(sys.modules, {"twscrape": twscrape_mock}):
            monitor = TwitterMonitor(str(seen_ids_file))

            # Should return empty list, not raise exception
            tweets = monitor.fetch_latest(["testuser"])
            assert tweets == []

    def test_fetch_latest_saves_seen_ids(self, tmp_path: Path) -> None:
        """Test that fetch_latest saves seen IDs after fetching."""
        seen_ids_file = tmp_path / "seen_ids.json"

        # Create mock tweet
        mock_tweet = MagicMock()
        mock_tweet.id = "12345"
        mock_tweet.rawContent = "Test tweet content"
        mock_tweet.date = datetime.now()

        # Setup mock API
        mock_api = MagicMock()
        mock_api.user_by_login.return_value = MagicMock(id=12345)
        mock_api.user_tweets.return_value = [mock_tweet]

        twscrape_mock = MagicMock()
        twscrape_mock.API.return_value = mock_api

        with patch.dict(sys.modules, {"twscrape": twscrape_mock}):
            monitor = TwitterMonitor(str(seen_ids_file))
            monitor.fetch_latest(["testuser"])

            # Check that seen IDs were saved
            assert seen_ids_file.exists()
            data = json.loads(seen_ids_file.read_text())
            assert "12345" in data["seen_ids"]

    def test_fetch_latest_resolves_user_id_before_requesting_tweets(self, tmp_path: Path) -> None:
        seen_ids_file = tmp_path / "seen_ids.json"
        mock_tweet = MagicMock()
        mock_tweet.id = "12345"
        mock_tweet.rawContent = "Test tweet content"
        mock_tweet.date = datetime.now()

        mock_user = MagicMock()
        mock_user.id = 987654321

        mock_api = MagicMock()
        mock_api.user_by_login.return_value = mock_user
        mock_api.user_tweets.return_value = [mock_tweet]

        twscrape_mock = MagicMock()
        twscrape_mock.API.return_value = mock_api

        with patch.dict(sys.modules, {"twscrape": twscrape_mock}):
            monitor = TwitterMonitor(str(seen_ids_file))
            monitor.fetch_latest(["cirnosad"])

        mock_api.user_by_login.assert_called_once_with("cirnosad")
        mock_api.user_tweets.assert_called_once_with(987654321, limit=5)


class TestGetMonitor:
    """Tests for get_monitor factory function."""

    def test_returns_mock_when_use_mock_true(self) -> None:
        """Test that get_monitor returns MockTwitterMonitor when use_mock=True."""
        monitor = get_monitor(use_mock=True)
        assert isinstance(monitor, MockTwitterMonitor)

    def test_returns_twitter_when_use_mock_false(self) -> None:
        """Test that get_monitor returns TwitterMonitor when use_mock=False."""
        monitor = get_monitor(use_mock=False)
        assert isinstance(monitor, TwitterMonitor)

    @patch("config.USE_MOCK_TWITTER", True)
    def test_uses_config_when_use_mock_none(self) -> None:
        """Test that get_monitor uses config.USE_MOCK_TWITTER when use_mock is None."""
        monitor = get_monitor(use_mock=None)
        assert isinstance(monitor, MockTwitterMonitor)


class TestBaseTweetMonitor:
    """Tests for BaseTweetMonitor abstract base class."""

    def test_cannot_instantiate_abstract_class(self) -> None:
        """Test that BaseTweetMonitor cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseTweetMonitor()  # type: ignore[abstract]

    def test_subclass_must_implement_fetch_latest(self) -> None:
        """Test that subclasses must implement fetch_latest."""

        class IncompleteMonitor(BaseTweetMonitor):
            ...

        with pytest.raises(TypeError):
            IncompleteMonitor()  # type: ignore[abstract]
