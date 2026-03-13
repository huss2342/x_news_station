"""Tests for the editorial rundown planner."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from modules.editorial_planner import EditorialRundownPlanner
from modules.news_fetcher import TweetData


def _tweet(
    story_id: str,
    username: str,
    minutes_ago: int = 0,
    *,
    is_quote: bool = False,
    likes: int = 0,
) -> TweetData:
    return TweetData(
        id=story_id,
        username=username,
        text=f"Story {story_id} from {username}",
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        is_quote=is_quote,
        like_count=likes,
    )


def test_next_item_returns_music_break_when_pool_is_empty() -> None:
    planner = EditorialRundownPlanner(segment_types=["music_break"])
    item = planner.next_item(ignore_interval=True)
    assert item is not None
    assert item.segment_type == "music_break"


def test_single_source_pool_changes_segment_type_before_replaying_same_story() -> None:
    planner = EditorialRundownPlanner(
        segment_interval_seconds=1,
        repeat_cooldown_minutes=15,
        max_consecutive_same_source=1,
        segment_types=["fresh_headline", "why_it_matters", "watchlist_discussion", "music_break"],
    )
    planner.ingest_tweets([_tweet("story-1", "solo_account", likes=10)])

    first = planner.next_item(ignore_interval=True)
    assert first is not None
    assert first.segment_type == "fresh_headline"
    planner.mark_aired(first)

    second = planner.next_item(ignore_interval=True)
    assert second is not None
    assert second.primary_story_id == "story-1"
    assert second.segment_type in {"why_it_matters", "watchlist_discussion"}


def test_multiple_sources_avoid_immediate_same_source_repeat() -> None:
    planner = EditorialRundownPlanner(
        segment_interval_seconds=1,
        repeat_cooldown_minutes=15,
        max_consecutive_same_source=1,
        segment_types=["fresh_headline", "quick_reset", "compare_updates"],
    )
    planner.ingest_tweets(
        [
            _tweet("story-a", "account_a", likes=8),
            _tweet("story-b", "account_b", likes=8),
        ]
    )

    first = planner.next_item(ignore_interval=True)
    assert first is not None
    first_story = planner.get_story(first.primary_story_id or "")
    assert first_story is not None
    planner.mark_aired(first)

    second = planner.next_item(ignore_interval=True)
    assert second is not None
    second_story = planner.get_story(second.primary_story_id or "")
    assert second_story is not None
    assert second_story.username != first_story.username


def test_prune_drops_candidates_outside_lookback_window() -> None:
    planner = EditorialRundownPlanner(candidate_lookback_minutes=10)
    old_tweet = _tweet("old-story", "archive", minutes_ago=45)
    fresh_tweet = _tweet("fresh-story", "new", minutes_ago=1)
    planner.ingest_tweets([old_tweet, fresh_tweet])

    story_ids = planner.story_ids()
    assert "fresh-story" in story_ids
    assert "old-story" not in story_ids
