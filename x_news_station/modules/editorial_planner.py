"""Editorial rundown planning for live station segments."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import config
from modules.news_fetcher import TweetData

EDITORIAL_SEGMENT_PRIORITY = (
    "fresh_headline",
    "quick_reset",
    "compare_updates",
    "why_it_matters",
    "watchlist_discussion",
    "music_break",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(slots=True)
class CandidateRecord:
    """Story candidate retained in the rolling rundown pool."""

    tweet: TweetData
    first_seen_at: datetime
    last_seen_at: datetime
    fetched_count: int = 1


@dataclass(slots=True)
class AirplayRecord:
    """Per-story airplay ledger entry."""

    story_id: str
    source_account: str
    last_aired_at: datetime | None = None
    times_aired: int = 0
    last_segment_type: str = ""


@dataclass(slots=True)
class RundownItem:
    """Single planned on-air segment."""

    segment_type: str
    primary_story_id: str | None = None
    supporting_story_ids: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def story_ids(self) -> list[str]:
        ids = [story_id for story_id in [self.primary_story_id, *self.supporting_story_ids] if story_id]
        return list(dict.fromkeys(ids))


class EditorialRundownPlanner:
    """Plan editorial segments from a rolling pool of fetched tweets."""

    def __init__(
        self,
        segment_interval_seconds: int | None = None,
        candidate_lookback_minutes: int | None = None,
        repeat_cooldown_minutes: int | None = None,
        max_consecutive_same_source: int | None = None,
        default_rundown_strategy: str | None = None,
        segment_types: list[str] | None = None,
    ) -> None:
        self.segment_interval = timedelta(
            seconds=segment_interval_seconds or config.EDITORIAL_SEGMENT_INTERVAL_SECONDS
        )
        self.candidate_lookback = timedelta(
            minutes=candidate_lookback_minutes or config.EDITORIAL_CANDIDATE_LOOKBACK_MINUTES
        )
        self.repeat_cooldown = timedelta(
            minutes=repeat_cooldown_minutes or config.EDITORIAL_REPEAT_COOLDOWN_MINUTES
        )
        self.max_consecutive_same_source = (
            max_consecutive_same_source or config.EDITORIAL_MAX_CONSECUTIVE_SAME_SOURCE
        )
        self.default_rundown_strategy = (
            default_rundown_strategy or config.EDITORIAL_DEFAULT_RUNDOWN_STRATEGY
        )
        self.allowed_segment_types = [
            segment_type
            for segment_type in (segment_types or list(config.EDITORIAL_SEGMENT_TYPES))
            if segment_type in EDITORIAL_SEGMENT_PRIORITY
        ] or list(EDITORIAL_SEGMENT_PRIORITY)

        self._candidates: dict[str, CandidateRecord] = {}
        self._airplay: dict[str, AirplayRecord] = {}
        self._segment_history: list[tuple[datetime, str, str | None]] = []
        self._last_segment_at: datetime | None = None
        self._segment_counter = 0

    def ingest_tweets(self, tweets: list[TweetData], now: datetime | None = None) -> None:
        current_time = _coerce_utc(now or _utc_now())
        for tweet in tweets:
            normalized_tweet = TweetData(
                id=tweet.id,
                username=tweet.username,
                text=tweet.text,
                timestamp=_coerce_utc(tweet.timestamp),
                url=tweet.url,
                is_reply=tweet.is_reply,
                is_repost=tweet.is_repost,
                is_quote=tweet.is_quote,
                like_count=tweet.like_count,
                retweet_count=tweet.retweet_count,
                quote_count=tweet.quote_count,
                reply_count=tweet.reply_count,
            )
            existing = self._candidates.get(normalized_tweet.id)
            if existing is None:
                self._candidates[normalized_tweet.id] = CandidateRecord(
                    tweet=normalized_tweet,
                    first_seen_at=current_time,
                    last_seen_at=current_time,
                )
                continue
            existing.tweet = normalized_tweet
            existing.last_seen_at = current_time
            existing.fetched_count += 1

        self.prune(now=current_time)

    def prune(self, now: datetime | None = None) -> None:
        current_time = _coerce_utc(now or _utc_now())
        cutoff = current_time - self.candidate_lookback
        self._candidates = {
            story_id: candidate
            for story_id, candidate in self._candidates.items()
            if candidate.tweet.timestamp >= cutoff
        }
        self._segment_history = [
            item for item in self._segment_history if item[0] >= current_time - (self.repeat_cooldown * 2)
        ]

    def candidate_records(self) -> list[CandidateRecord]:
        return list(self._candidates.values())

    def story_ids(self) -> list[str]:
        return list(self._candidates.keys())

    def get_story(self, story_id: str) -> TweetData | None:
        candidate = self._candidates.get(story_id)
        return candidate.tweet if candidate is not None else None

    def preview(self, limit: int = 5, now: datetime | None = None) -> list[RundownItem]:
        preview_planner = EditorialRundownPlanner(
            segment_interval_seconds=int(self.segment_interval.total_seconds()),
            candidate_lookback_minutes=int(self.candidate_lookback.total_seconds() // 60),
            repeat_cooldown_minutes=int(self.repeat_cooldown.total_seconds() // 60),
            max_consecutive_same_source=self.max_consecutive_same_source,
            default_rundown_strategy=self.default_rundown_strategy,
            segment_types=list(self.allowed_segment_types),
        )
        preview_planner._candidates = {
            story_id: CandidateRecord(
                tweet=candidate.tweet,
                first_seen_at=candidate.first_seen_at,
                last_seen_at=candidate.last_seen_at,
                fetched_count=candidate.fetched_count,
            )
            for story_id, candidate in self._candidates.items()
        }
        preview_planner._airplay = {
            story_id: AirplayRecord(
                story_id=record.story_id,
                source_account=record.source_account,
                last_aired_at=record.last_aired_at,
                times_aired=record.times_aired,
                last_segment_type=record.last_segment_type,
            )
            for story_id, record in self._airplay.items()
        }
        preview_planner._segment_history = list(self._segment_history)
        preview_planner._last_segment_at = self._last_segment_at
        preview_planner._segment_counter = self._segment_counter

        items: list[RundownItem] = []
        preview_time = _coerce_utc(now or _utc_now())
        for _ in range(limit):
            item = preview_planner.next_item(preview_time, ignore_interval=True)
            if item is None:
                break
            items.append(item)
            preview_planner.mark_aired(item, preview_time)
            preview_time += timedelta(seconds=max(1, int(self.segment_interval.total_seconds())))
        return items

    def time_until_next_segment_seconds(self, now: datetime | None = None) -> float:
        current_time = _coerce_utc(now or _utc_now())
        if self._last_segment_at is None:
            return 0.0
        remaining = (self._last_segment_at + self.segment_interval - current_time).total_seconds()
        return max(0.0, remaining)

    def next_item(self, now: datetime | None = None, ignore_interval: bool = False) -> RundownItem | None:
        current_time = _coerce_utc(now or _utc_now())
        self.prune(current_time)
        if not ignore_interval and self.time_until_next_segment_seconds(current_time) > 0:
            return None

        ranked = self._rank_candidates(current_time)
        if not ranked:
            if "music_break" in self.allowed_segment_types:
                return RundownItem(segment_type="music_break", reason="candidate_pool_empty")
            return None

        segment_type = self._pick_segment_type(ranked, current_time)
        if segment_type == "music_break":
            return RundownItem(segment_type="music_break", reason="cooldown_or_low_variety")

        primary = self._select_primary(ranked, current_time, segment_type)
        if primary is None:
            if "music_break" in self.allowed_segment_types:
                return RundownItem(segment_type="music_break", reason="no_primary_story")
            return None

        supporting = self._select_supporting(primary, ranked, segment_type)
        return RundownItem(
            segment_type=segment_type,
            primary_story_id=primary.tweet.id,
            supporting_story_ids=[item.tweet.id for item in supporting],
            reason=f"selected_from_{len(ranked)}_eligible_candidates",
        )

    def mark_aired(self, item: RundownItem, now: datetime | None = None) -> None:
        current_time = _coerce_utc(now or _utc_now())
        primary_source: str | None = None
        for story_id in item.story_ids:
            story = self.get_story(story_id)
            if story is None:
                continue
            primary_source = primary_source or story.username
            record = self._airplay.get(story_id)
            if record is None:
                record = AirplayRecord(story_id=story_id, source_account=story.username)
                self._airplay[story_id] = record
            record.last_aired_at = current_time
            record.times_aired += 1
            record.last_segment_type = item.segment_type

        self._last_segment_at = current_time
        self._segment_counter += 1
        self._segment_history.append((current_time, item.segment_type, primary_source))

    def _rank_candidates(self, now: datetime) -> list[CandidateRecord]:
        ranked = list(self._candidates.values())
        ranked.sort(key=lambda candidate: self._score_candidate(candidate, now), reverse=True)
        return ranked

    def _score_candidate(self, candidate: CandidateRecord, now: datetime) -> float:
        ledger = self._airplay.get(candidate.tweet.id)
        age_minutes = max(0.0, (now - candidate.tweet.timestamp).total_seconds() / 60.0)
        freshness = max(0.0, self.candidate_lookback.total_seconds() / 60.0 - age_minutes)
        engagement = candidate.tweet.like_count + (candidate.tweet.retweet_count * 2) + (candidate.tweet.quote_count * 3)
        engagement_score = min(4.0, math.log1p(max(0, engagement)))
        unplayed_bonus = 4.0 if ledger is None or ledger.times_aired == 0 else max(0.0, 2.5 - ledger.times_aired)
        # Cooldown penalty is very large so any story in cooldown ranks below ALL stories not in cooldown.
        cooldown_penalty = 100.0 if self._cooldown_active(candidate.tweet.id, now) else 0.0
        source_penalty = 0.0
        if self._would_break_source_streak(candidate.tweet.username):
            source_penalty = 1.2
        source_bonus = 0.5 if candidate.tweet.source_type in {"quote", "original"} else 0.0
        return freshness + engagement_score + unplayed_bonus + source_bonus - cooldown_penalty - source_penalty

    def _cooldown_active(self, story_id: str, now: datetime) -> bool:
        record = self._airplay.get(story_id)
        if record is None or record.last_aired_at is None:
            return False
        return now - record.last_aired_at < self.repeat_cooldown

    def _recent_sources(self) -> list[str]:
        recent = self._segment_history[-self.max_consecutive_same_source :]
        return [source for _timestamp, _segment_type, source in recent if source]

    def _would_break_source_streak(self, username: str) -> bool:
        if self.max_consecutive_same_source <= 0:
            return False
        recent_sources = self._recent_sources()
        if len(recent_sources) < self.max_consecutive_same_source:
            return False
        return all(source == username for source in recent_sources)

    def _select_primary(
        self,
        ranked: list[CandidateRecord],
        now: datetime,
        segment_type: str,
    ) -> CandidateRecord | None:
        # Prefer stories that have never aired or whose cooldown has expired.
        for candidate in ranked:
            record = self._airplay.get(candidate.tweet.id)
            if record is None or not self._cooldown_active(candidate.tweet.id, now):
                return candidate

        # Every candidate is still in cooldown -- pick the one aired the longest ago
        # so we maximise the gap before replaying any single story.
        if ranked:
            def _last_aired(c: CandidateRecord) -> datetime:
                rec = self._airplay.get(c.tweet.id)
                if rec is None or rec.last_aired_at is None:
                    return datetime.min.replace(tzinfo=timezone.utc)
                return rec.last_aired_at

            return min(ranked, key=_last_aired)
        return None

    def _select_supporting(
        self,
        primary: CandidateRecord,
        ranked: list[CandidateRecord],
        segment_type: str,
    ) -> list[CandidateRecord]:
        if segment_type == "fresh_headline":
            return []

        max_items = 2 if segment_type in {"compare_updates", "why_it_matters", "watchlist_discussion"} else 3
        selected: list[CandidateRecord] = []
        used_ids = {primary.tweet.id}
        used_sources = {primary.tweet.username}

        for candidate in ranked:
            if candidate.tweet.id in used_ids:
                continue
            if len(selected) >= max_items:
                break
            if segment_type in {"quick_reset", "compare_updates"} and candidate.tweet.username in used_sources:
                continue
            selected.append(candidate)
            used_ids.add(candidate.tweet.id)
            used_sources.add(candidate.tweet.username)

        if not selected and segment_type in {"compare_updates", "quick_reset"}:
            for candidate in ranked:
                if candidate.tweet.id == primary.tweet.id:
                    continue
                selected.append(candidate)
                if len(selected) >= max_items:
                    break
        return selected

    def _pick_segment_type(self, ranked: list[CandidateRecord], now: datetime) -> str:
        allowed = set(self.allowed_segment_types)
        distinct_sources = {candidate.tweet.username for candidate in ranked}
        fresh_candidates = [candidate for candidate in ranked if not self._cooldown_active(candidate.tweet.id, now)]
        never_aired = [candidate for candidate in ranked if self._airplay.get(candidate.tweet.id) is None]
        top_record = self._airplay.get(ranked[0].tweet.id)
        last_segment_type = self._segment_history[-1][1] if self._segment_history else ""
        single_source_mode = len(distinct_sources) <= 1

        if never_aired and "fresh_headline" in allowed and last_segment_type != "fresh_headline":
            return "fresh_headline"
        if len(ranked) >= 3 and "quick_reset" in allowed and self._segment_counter % 4 == 1:
            return "quick_reset"
        if len(ranked) >= 2 and "compare_updates" in allowed and (len(distinct_sources) > 1 or not single_source_mode):
            if last_segment_type != "compare_updates":
                return "compare_updates"
        if "why_it_matters" in allowed and last_segment_type != "why_it_matters":
            if single_source_mode and top_record is not None and self._cooldown_active(ranked[0].tweet.id, now):
                return "why_it_matters"
            if fresh_candidates:
                return "why_it_matters"
        if "watchlist_discussion" in allowed and last_segment_type != "watchlist_discussion":
            return "watchlist_discussion"
        if "quick_reset" in allowed and len(ranked) >= 2:
            return "quick_reset"
        if "fresh_headline" in allowed:
            return "fresh_headline"
        return "music_break" if "music_break" in allowed else self.allowed_segment_types[0]
