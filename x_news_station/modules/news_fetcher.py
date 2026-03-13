"""Twitter/X fetcher implementations."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import config
from modules.json_storage import read_json_file, write_json_file
from modules.twitter_setup import create_twscrape_api

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TweetData:
    """Normalized tweet data used throughout the station pipeline."""

    id: str
    username: str
    text: str
    timestamp: datetime
    url: str = ""
    is_reply: bool = False
    is_repost: bool = False
    is_quote: bool = False
    like_count: int = 0
    retweet_count: int = 0
    quote_count: int = 0
    reply_count: int = 0
    quoted_text: str = ""
    quoted_username: str = ""
    quoted_url: str = ""
    external_links: list[str] | None = None
    article_title: str = ""
    article_description: str = ""
    article_url: str = ""

    @property
    def source_type(self) -> str:
        """Return a coarse post classification for planner and UI logic."""
        if self.is_repost:
            return "repost"
        if self.is_quote:
            return "quote"
        if self.is_reply:
            return "reply"
        return "original"

    def link_urls(self) -> list[str]:
        """Return normalized external link list."""
        return list(self.external_links or [])


@dataclass(slots=True)
class FetchAccountDiagnostics:
    """Per-account fetch summary for logs and GUI diagnostics."""

    username: str
    raw_count: int = 0
    queued_count: int = 0
    seen_skipped_count: int = 0
    filtered_source_count: int = 0


@dataclass(slots=True)
class PreviewTweet:
    """Non-destructive preview item returned by manual refetch actions."""

    tweet: TweetData
    already_seen: bool = False


class BaseTweetMonitor(ABC):
    """Contract for tweet monitors."""

    @abstractmethod
    def fetch_latest(self, accounts: list[str]) -> list[TweetData]:
        """Fetch latest unseen tweets for the provided accounts."""
        raise NotImplementedError


class MockTwitterMonitor(BaseTweetMonitor):
    """Deterministic monitor for tests and local demos."""

    def __init__(self) -> None:
        """Initialize monitor state."""
        self._first_call = True
        self._mock_tweets = [
            TweetData(
                id="1234567890",
                username="elonmusk",
                text=(
                    "Just launched Starship! This is a historic moment for humanity's "
                    "future in space. #SpaceX #Mars"
                ),
                timestamp=datetime(2024, 3, 1, 12, 0, 0),
            ),
            TweetData(
                id="1234567891",
                username="sama",
                text=(
                    "AI is going to change everything. We're working hard to make sure "
                    "it's a positive change for everyone."
                ),
                timestamp=datetime(2024, 3, 1, 12, 30, 0),
            ),
            TweetData(
                id="1234567892",
                username="karpathy",
                text=(
                    "New blog post on neural network architectures and their training "
                    "dynamics. Check it out! https://example.com/blog"
                ),
                timestamp=datetime(2024, 3, 1, 13, 0, 0),
            ),
            TweetData(
                id="1234567893",
                username="elonmusk",
                text=(
                    "Tesla Full Self-Driving is getting better every day. The future "
                    "of transportation is autonomous."
                ),
                timestamp=datetime(2024, 3, 1, 13, 30, 0),
            ),
            TweetData(
                id="1234567894",
                username="sama",
                text=(
                    "Excited to announce our latest research on AI safety. "
                    "This is critical work for the future."
                ),
                timestamp=datetime(2024, 3, 1, 14, 0, 0),
            ),
        ]
        logger.debug("MockTwitterMonitor initialized")

    def fetch_latest(self, accounts: list[str]) -> list[TweetData]:
        """Return a fixed dataset on first call, then no new tweets."""
        _ = accounts
        if not self._first_call:
            logger.debug("MockTwitterMonitor returning 0 tweets on subsequent call")
            return []

        self._first_call = False
        mock_batch = self._mock_tweets[: config.MOCK_TWEET_BATCH_SIZE]
        logger.info("MockTwitterMonitor returning %s tweets", len(mock_batch))
        return mock_batch


class TwitterMonitor(BaseTweetMonitor):
    """Real monitor backed by `twscrape`."""

    def __init__(self, seen_ids_file: str | Path | None = None) -> None:
        """Initialize monitor and load deduplication state."""
        self.seen_ids_file = Path(seen_ids_file) if seen_ids_file else config.get_seen_ids_file()
        self.seen_ids: set[str] = set()
        self._seen_ids_lock = threading.Lock()
        self._load_seen_ids()
        logger.info("TwitterMonitor initialized with %s seen IDs", len(self.seen_ids))

    @staticmethod
    def _validate_seen_ids_payload(payload: Any) -> set[str]:
        """Validate and normalize seen-ID JSON payload."""
        if not isinstance(payload, dict):
            raise ValueError("seen_ids payload must be an object")

        raw_ids = payload.get("seen_ids", [])
        if not isinstance(raw_ids, list):
            raise ValueError("seen_ids field must be a list")

        return {str(item) for item in raw_ids}

    @staticmethod
    async def _collect_async_iterable(async_iterable: Any) -> list[Any]:
        """Collect an async iterable into a list."""
        return [item async for item in async_iterable]

    def _normalize_tweet_batch(self, tweets_or_iterable: Any) -> list[Any]:
        """Normalize sync/async tweet results into a list."""
        if tweets_or_iterable is None:
            return []

        if inspect.isawaitable(tweets_or_iterable):
            try:
                tweets_or_iterable = asyncio.run(tweets_or_iterable)
            except RuntimeError as exc:
                logger.error("Could not resolve awaited twscrape result: %s", exc)
                return []

        if inspect.isasyncgen(tweets_or_iterable):
            try:
                return asyncio.run(self._collect_async_iterable(tweets_or_iterable))
            except RuntimeError as exc:
                logger.error("Could not iterate async twscrape result: %s", exc)
                return []

        try:
            return list(tweets_or_iterable)
        except TypeError:
            logger.warning("Unexpected twscrape response type: %s", type(tweets_or_iterable))
            return []

    def _resolve_async_value(self, maybe_value: Any) -> Any:
        """Resolve awaitables returned by twscrape into plain Python values."""
        if inspect.isawaitable(maybe_value):
            try:
                return asyncio.run(maybe_value)
            except RuntimeError as exc:
                logger.error("Could not resolve awaited twscrape value: %s", exc)
                return None
        return maybe_value

    def _load_seen_ids(self) -> None:
        """Load seen IDs from JSON with safe defaults."""
        loaded_ids = read_json_file(
            path=self.seen_ids_file,
            default_factory=set,
            logger=logger,
            validator=self._validate_seen_ids_payload,
        )
        self.seen_ids = loaded_ids
        logger.debug("Loaded %s seen IDs from %s", len(self.seen_ids), self.seen_ids_file)

    def _save_seen_ids(self) -> None:
        """Persist current seen IDs under lock."""
        with self._seen_ids_lock:
            payload = {"seen_ids": sorted(self.seen_ids)}
        if write_json_file(self.seen_ids_file, payload, logger):
            logger.debug("Saved %s seen IDs to %s", len(payload["seen_ids"]), self.seen_ids_file)

    @staticmethod
    def _looks_like_x_url(url: str) -> bool:
        try:
            hostname = (urlparse(url).hostname or "").lower()
        except Exception:
            return False
        return hostname.endswith("x.com") or hostname.endswith("twitter.com")

    @staticmethod
    def _normalize_links(raw_links: Any) -> list[str]:
        links: list[str] = []
        for item in raw_links or []:
            url = str(getattr(item, "url", "") or "").strip()
            if not url:
                continue
            if url not in links:
                links.append(url)
        return links

    @classmethod
    def _extract_article_context(cls, tweet: Any, links: list[str]) -> tuple[str, str, str]:
        card = getattr(tweet, "card", None)
        article_title = str(getattr(card, "title", "") or "").strip()
        article_description = str(getattr(card, "description", "") or "").strip()
        article_url = str(getattr(card, "url", "") or "").strip()
        if not article_url:
            article_url = next((url for url in links if not cls._looks_like_x_url(url)), "")
        return article_title, article_description, article_url

    @staticmethod
    def _extract_quote_context(tweet: Any) -> tuple[str, str, str]:
        quoted = getattr(tweet, "quotedTweet", None)
        if quoted is None:
            return "", "", ""
        quoted_text = str(getattr(quoted, "rawContent", "") or "").strip()
        quoted_url = str(getattr(quoted, "url", "") or "").strip()
        quoted_user = getattr(quoted, "user", None)
        quoted_username = str(getattr(quoted_user, "username", "") or "").strip()
        return quoted_text, quoted_username, quoted_url

    @classmethod
    def _normalize_tweet(cls, tweet: Any, username: str) -> TweetData:
        timestamp = getattr(tweet, "date", datetime.now())
        if not isinstance(timestamp, datetime):
            timestamp = datetime.now()

        links = cls._normalize_links(getattr(tweet, "links", []))
        quoted_text, quoted_username, quoted_url = cls._extract_quote_context(tweet)
        article_title, article_description, article_url = cls._extract_article_context(tweet, links)

        return TweetData(
            id=str(getattr(tweet, "id")),
            username=username,
            text=str(getattr(tweet, "rawContent", "")),
            timestamp=timestamp,
            url=str(getattr(tweet, "url", "")),
            is_reply=getattr(tweet, "inReplyToTweetId", None) is not None,
            is_repost=getattr(tweet, "retweetedTweet", None) is not None,
            is_quote=getattr(tweet, "quotedTweet", None) is not None,
            like_count=int(getattr(tweet, "likeCount", 0) or 0),
            retweet_count=int(getattr(tweet, "retweetCount", 0) or 0),
            quote_count=int(getattr(tweet, "quoteCount", 0) or 0),
            reply_count=int(getattr(tweet, "replyCount", 0) or 0),
            quoted_text=quoted_text,
            quoted_username=quoted_username,
            quoted_url=quoted_url,
            external_links=links,
            article_title=article_title,
            article_description=article_description,
            article_url=article_url,
        )

    @staticmethod
    def _should_include_source_type(tweet: Any) -> bool:
        """Apply source-type filters from runtime config."""
        is_repost = getattr(tweet, "retweetedTweet", None) is not None
        is_quote = getattr(tweet, "quotedTweet", None) is not None
        is_reply = getattr(tweet, "inReplyToTweetId", None) is not None

        if is_repost and not config.INCLUDE_REPOSTS:
            return False
        if is_quote and not config.INCLUDE_QUOTE_POSTS:
            return False
        if is_reply and not config.INCLUDE_REPLIES:
            return False
        if not is_repost and not is_quote and not is_reply and not config.INCLUDE_ORIGINAL_POSTS:
            return False
        return True

    def _fetch_from_accounts(
        self,
        accounts: list[str],
        *,
        include_seen: bool,
        mark_seen: bool,
    ) -> tuple[list[TweetData], list[PreviewTweet], list[FetchAccountDiagnostics]]:
        normalized_new: list[TweetData] = []
        preview_items: list[PreviewTweet] = []
        diagnostics: list[FetchAccountDiagnostics] = []

        try:
            api = create_twscrape_api()
        except Exception as exc:
            logger.error("Failed to initialize twscrape API: %s", exc)
            return normalized_new, preview_items, diagnostics

        for username in accounts:
            stats = FetchAccountDiagnostics(username=username)
            diagnostics.append(stats)
            try:
                logger.debug("Fetching tweets for @%s", username)
                user = self._resolve_async_value(api.user_by_login(username))
                user_id = getattr(user, "id", None)
                if user_id is None:
                    logger.warning("Could not resolve user id for @%s", username)
                    continue
                tweet_batch = api.user_tweets(user_id, limit=config.TWITTER_FETCH_LIMIT)
                tweets = self._normalize_tweet_batch(tweet_batch)
            except Exception as exc:
                logger.error("Error fetching tweets for @%s: %s", username, exc)
                continue

            stats.raw_count = len(tweets)
            for tweet in tweets:
                try:
                    if not self._should_include_source_type(tweet):
                        stats.filtered_source_count += 1
                        continue

                    tweet_id = str(getattr(tweet, "id"))
                    with self._seen_ids_lock:
                        already_seen = tweet_id in self.seen_ids
                        if already_seen:
                            stats.seen_skipped_count += 1
                        if mark_seen and not already_seen:
                            self.seen_ids.add(tweet_id)

                    normalized = self._normalize_tweet(tweet, username)
                    if not already_seen:
                        normalized_new.append(normalized)
                        stats.queued_count += 1
                    if include_seen or not already_seen:
                        preview_items.append(PreviewTweet(tweet=normalized, already_seen=already_seen))
                except Exception as exc:
                    logger.warning("Failed to normalize tweet from @%s: %s", username, exc)

            if stats.raw_count and stats.queued_count == 0:
                logger.info(
                    "No new tweets queued for @%s (raw=%s, already_seen=%s, filtered_by_source=%s)",
                    username,
                    stats.raw_count,
                    stats.seen_skipped_count,
                    stats.filtered_source_count,
                )

        return normalized_new, preview_items, diagnostics

    def fetch_latest(self, accounts: list[str]) -> list[TweetData]:
        """Fetch unseen tweets from each account.

        Returns an empty list on dependency or network failures.
        """
        new_tweets, _preview_items, diagnostics = self._fetch_from_accounts(
            accounts,
            include_seen=False,
            mark_seen=True,
        )
        self._save_seen_ids()
        logger.info("Fetched %s new tweets from %s accounts", len(new_tweets), len(accounts))
        logger.debug("Fetch diagnostics: %s", diagnostics)
        return new_tweets

    def preview_latest(self, accounts: list[str], include_seen: bool = True) -> tuple[list[PreviewTweet], list[FetchAccountDiagnostics]]:
        """Preview latest tweets without mutating seen-ID state."""
        _new_tweets, preview_items, diagnostics = self._fetch_from_accounts(
            accounts,
            include_seen=include_seen,
            mark_seen=False,
        )
        return preview_items, diagnostics


def get_monitor(use_mock: bool | None = None) -> BaseTweetMonitor:
    """Return monitor implementation based on config or override."""
    should_use_mock = use_mock if use_mock is not None else config.USE_MOCK_TWITTER
    if should_use_mock:
        logger.info("Using MockTwitterMonitor")
        return MockTwitterMonitor()

    logger.info("Using TwitterMonitor")
    return TwitterMonitor()
