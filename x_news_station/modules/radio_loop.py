"""Main station loop and state machine implementation."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, TypedDict

import config
from modules.audio_studio import VoiceGenerator
from modules.json_storage import read_json_file, write_json_file
from modules.news_anchor import RECAP_INTROS, RECAP_OUTROS, NewsRewriter, ScriptLine, SimpleRewriter
from modules.news_fetcher import BaseTweetMonitor, TweetData, get_monitor

logger = logging.getLogger(__name__)

class StoryRecord(TypedDict):
    """Typed structure for persisted recap stories."""

    id: str
    username: str
    original_text: str
    rewritten_text: str
    timestamp: str


class RadioState(Enum):
    """State machine states for the radio station."""

    IDLE = auto()
    CHECKING = auto()
    BROADCASTING = auto()
    RECAPPING = auto()
    ERROR = auto()


class RadioStation:
    """Main long-running controller for X-News-Station."""

    def __init__(
        self,
        monitor: BaseTweetMonitor | None = None,
        rewriter: NewsRewriter | None = None,
        voice_generator: VoiceGenerator | None = None,
        use_music: bool = True,
        voice_id: str = config.VOICE_ID,
        anchor_voice_id: str | None = None,
        analyst_voice_id: str | None = None,
    ) -> None:
        """Initialize station dependencies and runtime state."""
        self.state = RadioState.IDLE
        self.monitor = monitor or get_monitor()
        self.rewriter = rewriter or NewsRewriter()
        self.voice_generator = voice_generator or VoiceGenerator()
        self.use_music = use_music
        self.voice_id = voice_id
        self.anchor_voice_id = anchor_voice_id or voice_id or config.ANCHOR_VOICE_ID
        self.analyst_voice_id = analyst_voice_id or config.ANALYST_VOICE_ID
        self.show_style = config.SHOW_STYLE
        self.idle_format = config.IDLE_FORMAT

        self.last_check_time: datetime | None = None
        self.last_recap_time = datetime.now()
        self.last_filler_time = datetime.now()
        self.check_interval = timedelta(seconds=config.FETCH_INTERVAL_SECONDS)
        self.recap_interval = timedelta(seconds=config.RECAP_INTERVAL_SECONDS)
        self.filler_interval = timedelta(seconds=config.FILLER_INTERVAL_SECONDS)
        self.filler_enabled = config.FILLER_ENABLED
        self._filler_index = 0
        self._recap_intro_index = 0
        self._recap_outro_index = 0

        self.story_log_file = config.get_story_log_file()
        self.story_log: list[StoryRecord] = []
        self._story_log_lock = threading.Lock()
        self._load_story_log()

        self._pygame_initialized = False
        self._music_ready = False
        self._music_playing = False
        self._current_volume = config.MUSIC_VOLUME_IDLE
        self._audio_backend = self._detect_audio_backend()
        logger.info("Audio playback backend: %s", self._audio_backend)

        self._fade_condition = threading.Condition()
        self._fade_stop_event = threading.Event()
        self._fade_pending = False
        self._fade_target = self._current_volume
        self._fade_duration = config.MUSIC_FADE_DURATION_SECONDS
        self._fade_worker_thread: threading.Thread | None = None

        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False

        if self.use_music and self._init_pygame():
            self._start_fade_worker()

        logger.info("RadioStation initialized with state=%s", self.state.name)

    @staticmethod
    def _validate_story_log_payload(payload: Any) -> list[StoryRecord]:
        """Validate persisted story log payload shape."""
        if not isinstance(payload, list):
            raise ValueError("story_log payload must be a list")

        validated: list[StoryRecord] = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            required_fields = {"id", "username", "original_text", "rewritten_text", "timestamp"}
            if not required_fields.issubset(item):
                continue

            validated.append(
                StoryRecord(
                    id=str(item["id"]),
                    username=str(item["username"]),
                    original_text=str(item["original_text"]),
                    rewritten_text=str(item["rewritten_text"]),
                    timestamp=str(item["timestamp"]),
                )
            )
        return validated

    @staticmethod
    def _parse_timestamp(raw_timestamp: str) -> datetime | None:
        """Parse ISO timestamp string into datetime."""
        try:
            return RadioStation._coerce_utc(datetime.fromisoformat(raw_timestamp))
        except ValueError:
            return None

    @staticmethod
    def _coerce_utc(value: datetime) -> datetime:
        """Normalize naive/aware datetimes into UTC-aware values."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _detect_audio_backend() -> str:
        """Choose the best available audio playback backend."""
        try:
            import pygame  # noqa: F401

            return "pygame"
        except ImportError:
            try:
                import winsound  # noqa: F401

                return "winsound"
            except ImportError:
                return "none"

    def _init_pygame(self) -> bool:
        """Initialize pygame mixer and preload music file."""
        try:
            import pygame

            pygame.mixer.init()
            self._pygame_initialized = True
        except ImportError:
            logger.warning("pygame not installed; music playback disabled")
            self.use_music = False
            return False
        except Exception as exc:
            logger.error("Failed to initialize pygame mixer: %s", exc)
            self.use_music = False
            return False

        music_path = config.get_music_path()
        if not music_path.exists():
            logger.warning("Music file not found: %s", music_path)
            self.use_music = False
            return False

        try:
            pygame.mixer.set_num_channels(16)
            pygame.mixer.music.load(str(music_path))
            pygame.mixer.music.set_volume(config.MUSIC_VOLUME_IDLE)
            self._music_ready = True
            logger.info("Loaded background music from %s", music_path)
            return True
        except Exception as exc:
            logger.error("Failed loading music file %s: %s", music_path, exc)
            self.use_music = False
            self._music_ready = False
            return False

    def _load_story_log(self) -> None:
        """Load story history from disk under lock."""
        loaded = read_json_file(
            path=self.story_log_file,
            default_factory=list,
            logger=logger,
            validator=self._validate_story_log_payload,
        )
        with self._story_log_lock:
            self.story_log = loaded
            self._prune_story_log()
        logger.debug("Loaded %s stories from %s", len(self.story_log), self.story_log_file)

    def _save_story_log(self) -> None:
        """Persist story history using locked atomic write."""
        with self._story_log_lock:
            payload = list(self.story_log)
        write_json_file(self.story_log_file, payload, logger)

    def _prune_story_log(self) -> None:
        """Drop stories older than configured retention window."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=config.STORY_RETENTION_HOURS)
        filtered: list[StoryRecord] = []
        for story in self.story_log:
            parsed = self._parse_timestamp(story["timestamp"])
            if parsed is None:
                continue
            if parsed >= cutoff:
                filtered.append(story)
        self.story_log = filtered

    def _log_story(self, tweet: TweetData, rewritten_text: str) -> None:
        """Append a story record to log for recap playback."""
        story = StoryRecord(
            id=tweet.id,
            username=tweet.username,
            original_text=tweet.text,
            rewritten_text=rewritten_text,
            timestamp=self._coerce_utc(tweet.timestamp).isoformat(),
        )
        with self._story_log_lock:
            self.story_log.append(story)
            self._prune_story_log()
        self._save_story_log()
        logger.debug("Logged story for @%s", tweet.username)

    def _start_fade_worker(self) -> None:
        """Start single background worker that handles all fade requests."""
        if self._fade_worker_thread and self._fade_worker_thread.is_alive():
            return

        self._fade_stop_event.clear()
        self._fade_worker_thread = threading.Thread(
            target=self._fade_worker,
            name="music-fade-worker",
            daemon=True,
        )
        self._fade_worker_thread.start()

    def _fade_worker(self) -> None:
        """Process queued fade requests serially, preempting stale requests."""
        while not self._fade_stop_event.is_set():
            with self._fade_condition:
                while not self._fade_pending and not self._fade_stop_event.is_set():
                    self._fade_condition.wait(timeout=0.2)
                if self._fade_stop_event.is_set():
                    return
                target = self._fade_target
                duration = max(0.01, self._fade_duration)
                start_volume = self._current_volume
                self._fade_pending = False

            steps = max(1, int(duration * config.VOLUME_FADE_STEPS_PER_SECOND))
            sleep_seconds = duration / steps

            for step in range(1, steps + 1):
                if self._fade_stop_event.is_set():
                    return

                with self._fade_condition:
                    if self._fade_pending:
                        break

                next_volume = start_volume + ((target - start_volume) * (step / steps))
                clamped_volume = max(0.0, min(1.0, next_volume))
                try:
                    import pygame

                    pygame.mixer.music.set_volume(clamped_volume)
                    self._current_volume = clamped_volume
                except Exception as exc:
                    logger.debug("Fade step failed: %s", exc)
                    break

                time.sleep(sleep_seconds)
            else:
                self._current_volume = target

    def _fade_volume(self, target_volume: float, duration: float | None = None) -> None:
        """Queue a target volume for fade worker."""
        if not self.use_music or not self._pygame_initialized:
            return

        fade_duration = duration if duration is not None else config.MUSIC_FADE_DURATION_SECONDS
        clamped_target = max(0.0, min(1.0, target_volume))
        with self._fade_condition:
            self._fade_target = clamped_target
            self._fade_duration = max(0.01, fade_duration)
            self._fade_pending = True
            self._fade_condition.notify()

    def _play_music(self) -> None:
        """Start looping background music if not already running."""
        if not self.use_music or not self._pygame_initialized or not self._music_ready:
            return

        try:
            import pygame

            is_busy = bool(pygame.mixer.music.get_busy())
            if not is_busy:
                pygame.mixer.music.set_volume(self._current_volume)
                pygame.mixer.music.play(-1, fade_ms=min(400, int(config.MUSIC_FADE_DURATION_SECONDS * 1000)))
                self._music_playing = True
                logger.debug("Background music started or restarted")
                return
            self._music_playing = True
        except Exception as exc:
            logger.warning("Could not start music playback: %s", exc)
            self._music_playing = False

    def _stop_music(self) -> None:
        """Stop background music playback."""
        if not self._pygame_initialized or not self._music_ready:
            return

        try:
            import pygame

            if pygame.mixer.music.get_busy() or self._music_playing:
                pygame.mixer.music.stop()
            self._music_playing = False
            logger.debug("Background music stopped")
        except Exception as exc:
            logger.warning("Could not stop music playback: %s", exc)

    def _play_audio_file(self, audio_path: Path) -> None:
        """Play a generated WAV file and block until playback is complete."""
        if not audio_path.exists():
            logger.warning("Audio file does not exist: %s", audio_path)
            return

        if self._audio_backend == "pygame":
            try:
                import pygame

                sound = pygame.mixer.Sound(str(audio_path))
                channel = sound.play()
                if channel is None:
                    logger.warning("pygame returned no channel for %s", audio_path)
                    return
                while channel.get_busy():
                    time.sleep(config.AUDIO_PLAYBACK_POLL_SECONDS)
                return
            except Exception as exc:
                logger.warning("pygame playback failed for %s: %s", audio_path, exc)
                self._audio_backend = "winsound"

        if self._audio_backend == "winsound":
            try:
                import winsound

                winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
                return
            except Exception as exc:
                logger.error("winsound playback failed for %s: %s", audio_path, exc)
                self._audio_backend = "none"

        logger.warning("No working audio playback backend available for %s", audio_path)

    def _voice_for_speaker(self, speaker: str) -> str:
        """Map a script speaker to a configured voice."""
        if speaker == "analyst":
            return self.analyst_voice_id
        return self.anchor_voice_id

    def _play_script_lines(self, lines: list[ScriptLine]) -> None:
        """Synthesize and play a scripted sequence line by line."""
        for line in lines:
            text = " ".join(line.text.split())
            if not text:
                continue
            voice_id = self._voice_for_speaker(line.speaker)
            audio_path = self.voice_generator.generate(text, voice_id)
            self._play_audio_file(audio_path)

    def _recent_story_context(self, limit: int = 2) -> list[str]:
        """Return a short list of recent rewritten stories for filler context."""
        recent_stories = self._get_recent_stories()
        return [story["rewritten_text"] for story in recent_stories[-limit:] if story["rewritten_text"].strip()]

    def _next_recap_intro(self) -> str:
        """Return the next rotating recap intro."""
        intro = RECAP_INTROS[self._recap_intro_index % len(RECAP_INTROS)]
        self._recap_intro_index += 1
        return intro

    def _next_recap_outro(self) -> str:
        """Return the next rotating recap outro."""
        outro = RECAP_OUTROS[self._recap_outro_index % len(RECAP_OUTROS)]
        self._recap_outro_index += 1
        return outro

    def _idle(self) -> None:
        """Idle state: keep music running and wait until next fetch window."""
        self.state = RadioState.IDLE
        logger.debug("State=%s", self.state.name)

        if self.use_music:
            self._play_music()
            if abs(self._current_volume - config.MUSIC_VOLUME_IDLE) > 0.001:
                self._fade_volume(config.MUSIC_VOLUME_IDLE)

        if self.last_check_time is None:
            sleep_seconds = config.INITIAL_IDLE_SLEEP_SECONDS
        else:
            elapsed = datetime.now() - self.last_check_time
            remaining = (self.check_interval - elapsed).total_seconds()
            sleep_seconds = max(config.INITIAL_IDLE_SLEEP_SECONDS, remaining)

        logger.debug("Idle sleeping for %.2fs", sleep_seconds)
        time.sleep(sleep_seconds)

    def _check(self) -> list[TweetData]:
        """Checking state: fetch new tweets."""
        self.state = RadioState.CHECKING
        self.last_check_time = datetime.now()
        logger.debug("State=%s", self.state.name)

        try:
            tweets = self.monitor.fetch_latest(config.TWITTER_ACCOUNTS)
            logger.info("Fetched %s candidate tweets", len(tweets))
            return tweets
        except Exception as exc:
            logger.error("Tweet fetch failed: %s", exc)
            return []

    def _broadcast(self, tweets: list[TweetData]) -> None:
        """Broadcasting state: rewrite, synthesize, and play each tweet."""
        if not tweets:
            return

        self.state = RadioState.BROADCASTING
        logger.info("State=%s broadcasting %s stories", self.state.name, len(tweets))

        if self.use_music:
            self._fade_volume(config.MUSIC_VOLUME_DUCKED)
            time.sleep(config.MUSIC_FADE_DURATION_SECONDS)

        try:
            for tweet in tweets:
                logger.info("Broadcasting tweet from @%s", tweet.username)
                try:
                    rewritten = self.rewriter.rewrite(tweet)
                except Exception as exc:
                    logger.error("Rewrite failed for tweet %s: %s", tweet.id, exc)
                    rewritten = SimpleRewriter().rewrite(tweet)

                self._log_story(tweet, rewritten)

                try:
                    audio_path = self.voice_generator.generate(rewritten, self.anchor_voice_id)
                except Exception as exc:
                    logger.error("Audio generation failed for tweet %s: %s", tweet.id, exc)
                    continue

                self._play_audio_file(audio_path)
        finally:
            if self.use_music:
                self._fade_volume(config.MUSIC_VOLUME_IDLE)

    def _get_recent_stories(self) -> list[StoryRecord]:
        """Return stories within recap lookback window."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=config.RECAP_LOOKBACK_HOURS)
        with self._story_log_lock:
            stories = list(self.story_log)

        recent: list[StoryRecord] = []
        for story in stories:
            parsed = self._parse_timestamp(story["timestamp"])
            if parsed is None:
                continue
            if parsed >= cutoff:
                recent.append(story)
        return recent

    def _recap(self) -> None:
        """Recapping state: replay top recent stories."""
        self.state = RadioState.RECAPPING
        self.last_recap_time = datetime.now()
        logger.info("State=%s", self.state.name)

        recent_stories = self._get_recent_stories()
        if len(recent_stories) < config.RECAP_STORY_COUNT:
            logger.debug("Skipping recap; only %s stories available", len(recent_stories))
            return

        top_stories = recent_stories[-config.RECAP_STORY_COUNT :]
        if self.use_music:
            self._fade_volume(config.MUSIC_VOLUME_DUCKED)
            time.sleep(config.MUSIC_FADE_DURATION_SECONDS)

        try:
            try:
                intro_audio = self.voice_generator.generate(self._next_recap_intro(), self.anchor_voice_id)
                self._play_audio_file(intro_audio)
            except Exception as exc:
                logger.error("Recap intro generation/playback failed: %s", exc)

            for story in top_stories:
                try:
                    audio_path = self.voice_generator.generate(story["rewritten_text"], self.anchor_voice_id)
                    self._play_audio_file(audio_path)
                except Exception as exc:
                    logger.error("Recap story playback failed: %s", exc)

            try:
                outro_audio = self.voice_generator.generate(self._next_recap_outro(), self.anchor_voice_id)
                self._play_audio_file(outro_audio)
            except Exception as exc:
                logger.error("Recap outro generation/playback failed: %s", exc)
        finally:
            if self.use_music:
                self._fade_volume(config.MUSIC_VOLUME_IDLE)

    def _build_filler_script(self, topic: str) -> list[ScriptLine]:
        """Build a filler segment script for dead-air moments."""
        if hasattr(self.rewriter, "build_filler_segment"):
            try:
                return self.rewriter.build_filler_segment(
                    topic,
                    recent_stories=self._recent_story_context(),
                    idle_format=self.idle_format,
                )
            except Exception as exc:
                logger.warning("Custom filler generation failed, using fallback script: %s", exc)

        return SimpleRewriter().build_filler_segment(
            topic,
            recent_stories=self._recent_story_context(),
            idle_format=self.idle_format,
        )

    def _next_filler_topic(self) -> str | None:
        """Return the next filler topic using round-robin selection."""
        topics = [topic for topic in config.FILLER_TOPICS if topic.strip()]
        if not topics:
            return None
        topic = topics[self._filler_index % len(topics)]
        self._filler_index += 1
        return topic

    def _should_run_filler(self) -> bool:
        """Return True when configured filler interval has elapsed."""
        if not self.filler_enabled:
            return False
        if not config.FILLER_TOPICS:
            return False
        return datetime.now() - self.last_filler_time >= self.filler_interval

    def _filler_segment(self) -> None:
        """Broadcast a short filler segment to keep the show flowing."""
        topic = self._next_filler_topic()
        if topic is None:
            return

        self.state = RadioState.BROADCASTING
        self.last_filler_time = datetime.now()
        logger.info("Running filler segment on topic: %s", topic)

        if self.use_music:
            self._fade_volume(config.MUSIC_VOLUME_DUCKED)
            time.sleep(config.MUSIC_FADE_DURATION_SECONDS)

        try:
            script_lines = self._build_filler_script(topic)
            self._play_script_lines(script_lines)
        except Exception as exc:
            logger.error("Filler segment failed: %s", exc)
        finally:
            if self.use_music:
                self._fade_volume(config.MUSIC_VOLUME_IDLE)

    def _should_recap(self) -> bool:
        """Return True when recap interval has elapsed."""
        return datetime.now() - self.last_recap_time >= self.recap_interval

    def start(self) -> None:
        """Run station loop forever, logging and recovering from iteration failures."""
        logger.info("=" * 50)
        logger.info("X-News-Station is on the air")
        logger.info("=" * 50)

        try:
            while True:
                try:
                    self._idle()
                    new_tweets = self._check()
                    if new_tweets:
                        self._broadcast(new_tweets)
                    elif self._should_recap():
                        self._recap()
                    elif self._should_run_filler():
                        self._filler_segment()
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    self.state = RadioState.ERROR
                    logger.exception("Main loop iteration failed: %s", exc)
                    time.sleep(config.MAIN_LOOP_ERROR_BACKOFF_SECONDS)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, shutting down station")
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        """Perform idempotent shutdown and cleanup."""
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._shutdown_complete = True

        self._fade_stop_event.set()
        with self._fade_condition:
            self._fade_condition.notify_all()
        if self._fade_worker_thread and self._fade_worker_thread.is_alive():
            self._fade_worker_thread.join(timeout=1.0)

        if self.use_music:
            self._stop_music()

        if self._pygame_initialized:
            try:
                import pygame

                pygame.mixer.quit()
            except Exception as exc:
                logger.debug("pygame mixer quit failed: %s", exc)

        self._save_story_log()

        try:
            deleted = self.voice_generator.clean_cache(config.MAX_CACHE_FILES)
            logger.info("Cache cleanup removed %s files", deleted)
        except Exception as exc:
            logger.warning("Cache cleanup failed: %s", exc)

        logger.info("Shutdown complete")
