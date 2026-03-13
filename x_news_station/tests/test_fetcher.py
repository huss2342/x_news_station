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
        mock_tweet.inReplyToTweetId = None
        mock_tweet.retweetedTweet = None
        mock_tweet.quotedTweet = None

        # Setup mock API
        mock_api = MagicMock()
        mock_api.user_by_login.return_value = MagicMock(id=12345)
        mock_api.user_tweets.return_value = [mock_tweet]

        with patch("modules.news_fetcher.create_twscrape_api", return_value=mock_api):
            monitor = TwitterMonitor(str(seen_ids_file))

            # First fetch should return the tweet
            tweets1 = monitor.fetch_latest(["testuser"])
            assert len(tweets1) == 1

            # Second fetch should return empty (tweet already seen)
            tweets2 = monitor.fetch_latest(["testuser"])
            assert len(tweets2) == 0

    def test_fetch_latest_handles_errors_gracefully(self, tmp_path: Path) -> None:
        """Test that fetch_latest handles API errors without crashing."""
        seen_ids_file = tmp_path / "seen_ids.json"

        # Setup mock API to raise exception
        mock_api = MagicMock()
        mock_api.user_by_login.return_value = MagicMock(id=12345)
        mock_api.user_tweets.side_effect = Exception("Network error")

        with patch("modules.news_fetcher.create_twscrape_api", return_value=mock_api):
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
        mock_tweet.inReplyToTweetId = None
        mock_tweet.retweetedTweet = None
        mock_tweet.quotedTweet = None

        # Setup mock API
        mock_api = MagicMock()
        mock_api.user_by_login.return_value = MagicMock(id=12345)
        mock_api.user_tweets.return_value = [mock_tweet]

        with patch("modules.news_fetcher.create_twscrape_api", return_value=mock_api):
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
        mock_tweet.inReplyToTweetId = None
        mock_tweet.retweetedTweet = None
        mock_tweet.quotedTweet = None

        mock_user = MagicMock()
        mock_user.id = 987654321

        mock_api = MagicMock()
        mock_api.user_by_login.return_value = mock_user
        mock_api.user_tweets.return_value = [mock_tweet]

        with patch("modules.news_fetcher.create_twscrape_api", return_value=mock_api):
            monitor = TwitterMonitor(str(seen_ids_file))
            monitor.fetch_latest(["cirnosad"])

        mock_api.user_by_login.assert_called_once_with("cirnosad")
        mock_api.user_tweets.assert_called_once_with(987654321, limit=5)

    def test_fetch_latest_applies_source_type_filters_and_metadata(self, tmp_path: Path) -> None:
        seen_ids_file = tmp_path / "seen_ids.json"

        original = MagicMock()
        original.id = "tweet-original"
        original.rawContent = "Original tweet"
        original.date = datetime.now()
        original.inReplyToTweetId = None
        original.retweetedTweet = None
        original.quotedTweet = None
        original.likeCount = 3
        original.retweetCount = 1
        original.quoteCount = 0
        original.replyCount = 2
        original.url = "https://x.com/test/status/1"

        quote = MagicMock()
        quote.id = "tweet-quote"
        quote.rawContent = "Quote tweet"
        quote.date = datetime.now()
        quote.inReplyToTweetId = None
        quote.retweetedTweet = None
        quote.quotedTweet = object()
        quote.likeCount = 5
        quote.retweetCount = 2
        quote.quoteCount = 1
        quote.replyCount = 0
        quote.url = "https://x.com/test/status/2"

        reply = MagicMock()
        reply.id = "tweet-reply"
        reply.rawContent = "Reply tweet"
        reply.date = datetime.now()
        reply.inReplyToTweetId = "parent"
        reply.retweetedTweet = None
        reply.quotedTweet = None
        reply.likeCount = 1
        reply.retweetCount = 0
        reply.quoteCount = 0
        reply.replyCount = 1
        reply.url = "https://x.com/test/status/3"

        mock_api = MagicMock()
        mock_api.user_by_login.return_value = MagicMock(id=12345)
        mock_api.user_tweets.return_value = [original, quote, reply]

        with patch("modules.news_fetcher.create_twscrape_api", return_value=mock_api):
            with patch("config.INCLUDE_ORIGINAL_POSTS", True), patch("config.INCLUDE_QUOTE_POSTS", True), patch(
                "config.INCLUDE_REPLIES", False
            ), patch("config.INCLUDE_REPOSTS", False):
                monitor = TwitterMonitor(str(seen_ids_file))
                tweets = monitor.fetch_latest(["testuser"])

        assert [tweet.id for tweet in tweets] == ["tweet-original", "tweet-quote"]
        assert tweets[0].source_type == "original"
        assert tweets[0].like_count == 3
        assert tweets[1].is_quote is True
        assert tweets[1].source_type == "quote"


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
