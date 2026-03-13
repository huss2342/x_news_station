"""Runtime settings loading, validation, and application helpers."""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, replace
from pathlib import Path

import config

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
VALID_LLM_PROVIDERS = {"ollama", "openai_compatible", "simple"}
VALID_SHOW_STYLES = {"hybrid", "talk_radio", "straight_news"}
VALID_IDLE_FORMATS = {"two_host", "solo_host", "music_first"}
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}

RUNTIME_SETTINGS_TEMPLATE = """# X-News-Station runtime settings (shareable)
# Edit this file and run: python main.py
# The launcher GUI is the default entrypoint. Use --no-gui for headless mode.
# CLI flags still work and override these values.

[station]
use_mock_twitter = true
voice_id = am_michael
anchor_voice_id = am_michael
analyst_voice_id = bf_emma
# show_style: hybrid | talk_radio | straight_news
show_style = hybrid
# idle_format: two_host | solo_host | music_first
idle_format = two_host
# Voice options: the launcher exposes the full Kokoro voice list when available
use_music = true
log_level = INFO

[twitter]
accounts = elonmusk, sama, karpathy
fetch_interval_seconds = 300
fetch_limit = 5
mock_tweet_batch_size = 5

[recap]
interval_seconds = 1800
story_count = 3
lookback_hours = 1
story_retention_hours = 24

[filler]
enabled = true
interval_seconds = 900
topics = AI industry rivalry, open-source launches, startup power shifts, chip manufacturing, creator economy changes

[llm]
# provider: ollama | openai_compatible | simple
provider = ollama
model = llama3
fallback_model = mistral
base_url = http://localhost:11434
max_retries = 3
backoff_factor = 1.0

# Used only when provider=openai_compatible
api_base_url = https://api.openai.com/v1
api_model = gpt-4o-mini
api_key =
api_key_env_var = OPENAI_API_KEY

[music]
file = assets/music/background.mp3
volume_idle = 0.8
volume_ducked = 0.2
fade_duration_seconds = 2.0
fade_steps_per_second = 10

[audio]
cache_dir = cache/
max_cache_files = 200
playback_poll_seconds = 0.1
initial_idle_sleep_seconds = 1.0
builtin_tts_sample_rate = 22050
builtin_tts_frequency_hz = 220
builtin_tts_seconds = 0.6

[resilience]
main_loop_error_backoff_seconds = 2.0
json_lock_timeout_seconds = 3.0
json_lock_retry_seconds = 0.05

[logging]
file = logs/app.log
"""


@dataclass(slots=True)
class RuntimeSettings:
    """User-facing runtime settings loaded from `station_settings.ini`."""

    use_mock_twitter: bool
    voice_id: str
    anchor_voice_id: str
    analyst_voice_id: str
    show_style: str
    idle_format: str
    use_music: bool
    log_level: str

    twitter_accounts: list[str]
    fetch_interval_seconds: int
    twitter_fetch_limit: int
    mock_tweet_batch_size: int

    recap_interval_seconds: int
    recap_story_count: int
    recap_lookback_hours: int
    story_retention_hours: int

    filler_enabled: bool
    filler_interval_seconds: int
    filler_topics: list[str]

    llm_provider: str
    ollama_model: str
    ollama_fallback_model: str
    ollama_base_url: str
    ollama_max_retries: int
    ollama_backoff_factor: float
    llm_api_base_url: str
    llm_api_model: str
    llm_api_key: str
    llm_api_key_env_var: str

    music_file: str
    music_volume_idle: float
    music_volume_ducked: float
    music_fade_duration_seconds: float
    volume_fade_steps_per_second: int

    audio_cache_dir: str
    max_cache_files: int
    audio_playback_poll_seconds: float
    initial_idle_sleep_seconds: float
    builtin_tts_sample_rate: int
    builtin_tts_frequency_hz: int
    builtin_tts_seconds: float

    main_loop_error_backoff_seconds: float
    json_lock_timeout_seconds: float
    json_lock_retry_seconds: float
    log_file: str

    @classmethod
    def from_current_config(cls) -> RuntimeSettings:
        """Build settings object from current in-memory config values."""
        return cls(
            use_mock_twitter=config.USE_MOCK_TWITTER,
            voice_id=config.VOICE_ID,
            anchor_voice_id=config.ANCHOR_VOICE_ID,
            analyst_voice_id=config.ANALYST_VOICE_ID,
            show_style=config.SHOW_STYLE,
            idle_format=config.IDLE_FORMAT,
            use_music=True,
            log_level=config.LOG_LEVEL,
            twitter_accounts=list(config.TWITTER_ACCOUNTS),
            fetch_interval_seconds=config.FETCH_INTERVAL_SECONDS,
            twitter_fetch_limit=config.TWITTER_FETCH_LIMIT,
            mock_tweet_batch_size=config.MOCK_TWEET_BATCH_SIZE,
            recap_interval_seconds=config.RECAP_INTERVAL_SECONDS,
            recap_story_count=config.RECAP_STORY_COUNT,
            recap_lookback_hours=config.RECAP_LOOKBACK_HOURS,
            story_retention_hours=config.STORY_RETENTION_HOURS,
            filler_enabled=config.FILLER_ENABLED,
            filler_interval_seconds=config.FILLER_INTERVAL_SECONDS,
            filler_topics=list(config.FILLER_TOPICS),
            llm_provider=config.LLM_PROVIDER,
            ollama_model=config.OLLAMA_MODEL,
            ollama_fallback_model=config.OLLAMA_FALLBACK_MODEL,
            ollama_base_url=config.OLLAMA_BASE_URL,
            ollama_max_retries=config.OLLAMA_MAX_RETRIES,
            ollama_backoff_factor=config.OLLAMA_BACKOFF_FACTOR,
            llm_api_base_url=config.LLM_API_BASE_URL,
            llm_api_model=config.LLM_API_MODEL,
            llm_api_key=config.LLM_API_KEY,
            llm_api_key_env_var=config.LLM_API_KEY_ENV_VAR,
            music_file=config.MUSIC_FILE,
            music_volume_idle=config.MUSIC_VOLUME_IDLE,
            music_volume_ducked=config.MUSIC_VOLUME_DUCKED,
            music_fade_duration_seconds=config.MUSIC_FADE_DURATION_SECONDS,
            volume_fade_steps_per_second=config.VOLUME_FADE_STEPS_PER_SECOND,
            audio_cache_dir=config.AUDIO_CACHE_DIR,
            max_cache_files=config.MAX_CACHE_FILES,
            audio_playback_poll_seconds=config.AUDIO_PLAYBACK_POLL_SECONDS,
            initial_idle_sleep_seconds=config.INITIAL_IDLE_SLEEP_SECONDS,
            builtin_tts_sample_rate=config.BUILTIN_TTS_SAMPLE_RATE,
            builtin_tts_frequency_hz=config.BUILTIN_TTS_FREQUENCY_HZ,
            builtin_tts_seconds=config.BUILTIN_TTS_SECONDS,
            main_loop_error_backoff_seconds=config.MAIN_LOOP_ERROR_BACKOFF_SECONDS,
            json_lock_timeout_seconds=config.JSON_LOCK_TIMEOUT_SECONDS,
            json_lock_retry_seconds=config.JSON_LOCK_RETRY_SECONDS,
            log_file=config.LOG_FILE,
        )


@dataclass(slots=True)
class RuntimeCliOverrides:
    """CLI-level overrides that should take precedence over files."""

    force_mock: bool = False
    disable_music: bool = False
    voice_id: str | None = None
    log_level: str | None = None


def _parse_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def _parse_positive_int(value: str) -> int | None:
    try:
        parsed = int(value.strip())
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def _parse_positive_float(value: str) -> float | None:
    try:
        parsed = float(value.strip())
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def _parse_unit_float(value: str) -> float | None:
    parsed = _parse_positive_float(value)
    if parsed is None:
        return None
    if parsed > 1.0:
        return None
    return parsed


def _parse_accounts(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_topics(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _load_ini(path: Path, notes: list[str]) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    if not path.exists():
        notes.append(f"Runtime settings file not found at {path}; using defaults.")
        return parser

    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as exc:
        notes.append(f"Failed to parse runtime settings file {path}: {exc}")
    else:
        notes.append(f"Loaded runtime settings from {path}.")
    return parser


def _read_bool(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    notes: list[str],
) -> bool | None:
    if not parser.has_option(section, key):
        return None
    parsed = _parse_bool(parser.get(section, key))
    if parsed is None:
        notes.append(f"Invalid {section}.{key}; expected true/false.")
    return parsed


def _read_int(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    notes: list[str],
) -> int | None:
    if not parser.has_option(section, key):
        return None
    parsed = _parse_positive_int(parser.get(section, key))
    if parsed is None:
        notes.append(f"Invalid {section}.{key}; expected positive integer.")
    return parsed


def _read_float(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    notes: list[str],
) -> float | None:
    if not parser.has_option(section, key):
        return None
    parsed = _parse_positive_float(parser.get(section, key))
    if parsed is None:
        notes.append(f"Invalid {section}.{key}; expected positive number.")
    return parsed


def _read_unit_float(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    notes: list[str],
) -> float | None:
    if not parser.has_option(section, key):
        return None
    parsed = _parse_unit_float(parser.get(section, key))
    if parsed is None:
        notes.append(f"Invalid {section}.{key}; expected number in range (0, 1].")
    return parsed


def _read_text(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
) -> str | None:
    if not parser.has_option(section, key):
        return None
    value = parser.get(section, key).strip()
    return value if value else None


def _pick_alternate_voice(anchor_voice_id: str) -> str:
    for voice_id in config.VOICE_OPTIONS:
        if voice_id != anchor_voice_id:
            return voice_id
    return anchor_voice_id


def _normalize_show_settings(
    settings: RuntimeSettings,
    parser: configparser.ConfigParser,
    notes: list[str],
) -> None:
    if not settings.voice_id:
        settings.voice_id = settings.anchor_voice_id or config.VOICE_ID

    if not settings.anchor_voice_id:
        settings.anchor_voice_id = settings.voice_id or config.ANCHOR_VOICE_ID

    analyst_explicit = parser.has_option("station", "analyst_voice_id")
    if not settings.analyst_voice_id:
        settings.analyst_voice_id = _pick_alternate_voice(settings.anchor_voice_id)
    elif not analyst_explicit and settings.analyst_voice_id == settings.anchor_voice_id:
        settings.analyst_voice_id = _pick_alternate_voice(settings.anchor_voice_id)

    settings.voice_id = settings.anchor_voice_id

    if settings.show_style not in VALID_SHOW_STYLES:
        notes.append(
            f"Invalid station.show_style '{settings.show_style}'. Expected one of: {', '.join(sorted(VALID_SHOW_STYLES))}."
        )
        settings.show_style = config.SHOW_STYLE

    if settings.idle_format not in VALID_IDLE_FORMATS:
        notes.append(
            f"Invalid station.idle_format '{settings.idle_format}'. Expected one of: {', '.join(sorted(VALID_IDLE_FORMATS))}."
        )
        settings.idle_format = config.IDLE_FORMAT


def _apply_ini_overrides(
    parser: configparser.ConfigParser, settings: RuntimeSettings, notes: list[str]
) -> None:
    if (parsed := _read_bool(parser, "station", "use_mock_twitter", notes)) is not None:
        settings.use_mock_twitter = parsed
    if (parsed := _read_bool(parser, "station", "use_music", notes)) is not None:
        settings.use_music = parsed

    if (value := _read_text(parser, "station", "voice_id")) is not None:
        settings.voice_id = value
        settings.anchor_voice_id = value
    if (value := _read_text(parser, "station", "anchor_voice_id")) is not None:
        settings.anchor_voice_id = value
    if (value := _read_text(parser, "station", "analyst_voice_id")) is not None:
        settings.analyst_voice_id = value
    if (value := _read_text(parser, "station", "show_style")) is not None:
        settings.show_style = value.lower()
    if (value := _read_text(parser, "station", "idle_format")) is not None:
        settings.idle_format = value.lower()
    if (value := _read_text(parser, "station", "log_level")) is not None:
        upper = value.upper()
        if upper in VALID_LOG_LEVELS:
            settings.log_level = upper
        else:
            notes.append(
                f"Invalid station.log_level '{upper}'. Expected one of: {', '.join(sorted(VALID_LOG_LEVELS))}."
            )

    if parser.has_option("twitter", "accounts"):
        accounts = _parse_accounts(parser.get("twitter", "accounts"))
        if accounts:
            settings.twitter_accounts = accounts
        else:
            notes.append("Invalid twitter.accounts; expected comma-separated usernames.")

    if (parsed := _read_int(parser, "twitter", "fetch_interval_seconds", notes)) is not None:
        settings.fetch_interval_seconds = parsed
    if (parsed := _read_int(parser, "twitter", "fetch_limit", notes)) is not None:
        settings.twitter_fetch_limit = parsed
    if (parsed := _read_int(parser, "twitter", "mock_tweet_batch_size", notes)) is not None:
        settings.mock_tweet_batch_size = parsed

    if (parsed := _read_int(parser, "recap", "interval_seconds", notes)) is not None:
        settings.recap_interval_seconds = parsed
    if (parsed := _read_int(parser, "recap", "story_count", notes)) is not None:
        settings.recap_story_count = parsed
    if (parsed := _read_int(parser, "recap", "lookback_hours", notes)) is not None:
        settings.recap_lookback_hours = parsed
    if (parsed := _read_int(parser, "recap", "story_retention_hours", notes)) is not None:
        settings.story_retention_hours = parsed

    if (parsed := _read_bool(parser, "filler", "enabled", notes)) is not None:
        settings.filler_enabled = parsed
    if (parsed := _read_int(parser, "filler", "interval_seconds", notes)) is not None:
        settings.filler_interval_seconds = parsed
    if parser.has_option("filler", "topics"):
        topics = _parse_topics(parser.get("filler", "topics"))
        if topics:
            settings.filler_topics = topics
        else:
            notes.append("Invalid filler.topics; expected comma-separated topic names.")

    if (value := _read_text(parser, "llm", "provider")) is not None:
        provider = value.lower()
        if provider in VALID_LLM_PROVIDERS:
            settings.llm_provider = provider
        else:
            notes.append(
                f"Invalid llm.provider '{value}'. Expected one of: {', '.join(sorted(VALID_LLM_PROVIDERS))}."
            )
    if (value := _read_text(parser, "llm", "model")) is not None:
        settings.ollama_model = value
    if (value := _read_text(parser, "llm", "fallback_model")) is not None:
        settings.ollama_fallback_model = value
    if (value := _read_text(parser, "llm", "base_url")) is not None:
        settings.ollama_base_url = value
    if (parsed := _read_int(parser, "llm", "max_retries", notes)) is not None:
        settings.ollama_max_retries = parsed
    if (parsed := _read_float(parser, "llm", "backoff_factor", notes)) is not None:
        settings.ollama_backoff_factor = parsed

    if (value := _read_text(parser, "llm", "api_base_url")) is not None:
        settings.llm_api_base_url = value
    if (value := _read_text(parser, "llm", "api_model")) is not None:
        settings.llm_api_model = value
    if parser.has_option("llm", "api_key"):
        settings.llm_api_key = parser.get("llm", "api_key").strip()
    if (value := _read_text(parser, "llm", "api_key_env_var")) is not None:
        settings.llm_api_key_env_var = value

    if (value := _read_text(parser, "music", "file")) is not None:
        settings.music_file = value
    if (parsed := _read_unit_float(parser, "music", "volume_idle", notes)) is not None:
        settings.music_volume_idle = parsed
    if (parsed := _read_unit_float(parser, "music", "volume_ducked", notes)) is not None:
        settings.music_volume_ducked = parsed
    if (parsed := _read_float(parser, "music", "fade_duration_seconds", notes)) is not None:
        settings.music_fade_duration_seconds = parsed
    if (parsed := _read_int(parser, "music", "fade_steps_per_second", notes)) is not None:
        settings.volume_fade_steps_per_second = parsed

    if (value := _read_text(parser, "audio", "cache_dir")) is not None:
        settings.audio_cache_dir = value
    if (parsed := _read_int(parser, "audio", "max_cache_files", notes)) is not None:
        settings.max_cache_files = parsed
    if (parsed := _read_float(parser, "audio", "playback_poll_seconds", notes)) is not None:
        settings.audio_playback_poll_seconds = parsed
    if (parsed := _read_float(parser, "audio", "initial_idle_sleep_seconds", notes)) is not None:
        settings.initial_idle_sleep_seconds = parsed
    if (parsed := _read_int(parser, "audio", "builtin_tts_sample_rate", notes)) is not None:
        settings.builtin_tts_sample_rate = parsed
    if (parsed := _read_int(parser, "audio", "builtin_tts_frequency_hz", notes)) is not None:
        settings.builtin_tts_frequency_hz = parsed
    if (parsed := _read_float(parser, "audio", "builtin_tts_seconds", notes)) is not None:
        settings.builtin_tts_seconds = parsed

    if (parsed := _read_float(parser, "resilience", "main_loop_error_backoff_seconds", notes)) is not None:
        settings.main_loop_error_backoff_seconds = parsed
    if (parsed := _read_float(parser, "resilience", "json_lock_timeout_seconds", notes)) is not None:
        settings.json_lock_timeout_seconds = parsed
    if (parsed := _read_float(parser, "resilience", "json_lock_retry_seconds", notes)) is not None:
        settings.json_lock_retry_seconds = parsed

    if (value := _read_text(parser, "logging", "file")) is not None:
        settings.log_file = value

    _normalize_show_settings(settings, parser, notes)


def _apply_env_overrides(settings: RuntimeSettings, notes: list[str]) -> None:
    """Use process environment for secret/API overrides only."""
    if not settings.llm_api_key and settings.llm_api_key_env_var:
        env_key = settings.llm_api_key_env_var
        value = os.environ.get(env_key, "").strip()
        if value:
            settings.llm_api_key = value
            notes.append(f"Loaded llm.api_key from environment variable {env_key}.")


def _format_bool(value: bool) -> str:
    """Render booleans consistently for INI output."""
    return "true" if value else "false"


def render_runtime_settings(settings: RuntimeSettings) -> str:
    """Render runtime settings to a stable INI string."""
    normalized = replace(settings)
    normalized.voice_id = settings.anchor_voice_id

    lines = [
        "# X-News-Station runtime settings (shareable)",
        "# Edit this file and run: python main.py",
        "# The launcher GUI is the default entrypoint. Use --no-gui for headless mode.",
        "# CLI flags still work and override these values.",
        "",
        "[station]",
        f"use_mock_twitter = {_format_bool(normalized.use_mock_twitter)}",
        f"voice_id = {normalized.anchor_voice_id}",
        f"anchor_voice_id = {normalized.anchor_voice_id}",
        f"analyst_voice_id = {normalized.analyst_voice_id}",
        "# show_style: hybrid | talk_radio | straight_news",
        f"show_style = {normalized.show_style}",
        "# idle_format: two_host | solo_host | music_first",
        f"idle_format = {normalized.idle_format}",
        "# Voice options: the launcher exposes the full Kokoro voice list when available",
        f"use_music = {_format_bool(normalized.use_music)}",
        f"log_level = {normalized.log_level}",
        "",
        "[twitter]",
        f"accounts = {', '.join(normalized.twitter_accounts)}",
        f"fetch_interval_seconds = {normalized.fetch_interval_seconds}",
        f"fetch_limit = {normalized.twitter_fetch_limit}",
        f"mock_tweet_batch_size = {normalized.mock_tweet_batch_size}",
        "",
        "[recap]",
        f"interval_seconds = {normalized.recap_interval_seconds}",
        f"story_count = {normalized.recap_story_count}",
        f"lookback_hours = {normalized.recap_lookback_hours}",
        f"story_retention_hours = {normalized.story_retention_hours}",
        "",
        "[filler]",
        f"enabled = {_format_bool(normalized.filler_enabled)}",
        f"interval_seconds = {normalized.filler_interval_seconds}",
        f"topics = {', '.join(normalized.filler_topics)}",
        "",
        "[llm]",
        "# provider: ollama | openai_compatible | simple",
        f"provider = {normalized.llm_provider}",
        f"model = {normalized.ollama_model}",
        f"fallback_model = {normalized.ollama_fallback_model}",
        f"base_url = {normalized.ollama_base_url}",
        f"max_retries = {normalized.ollama_max_retries}",
        f"backoff_factor = {normalized.ollama_backoff_factor}",
        "",
        "# Used only when provider=openai_compatible",
        f"api_base_url = {normalized.llm_api_base_url}",
        f"api_model = {normalized.llm_api_model}",
        f"api_key = {normalized.llm_api_key}",
        f"api_key_env_var = {normalized.llm_api_key_env_var}",
        "",
        "[music]",
        f"file = {normalized.music_file}",
        f"volume_idle = {normalized.music_volume_idle}",
        f"volume_ducked = {normalized.music_volume_ducked}",
        f"fade_duration_seconds = {normalized.music_fade_duration_seconds}",
        f"fade_steps_per_second = {normalized.volume_fade_steps_per_second}",
        "",
        "[audio]",
        f"cache_dir = {normalized.audio_cache_dir}",
        f"max_cache_files = {normalized.max_cache_files}",
        f"playback_poll_seconds = {normalized.audio_playback_poll_seconds}",
        f"initial_idle_sleep_seconds = {normalized.initial_idle_sleep_seconds}",
        f"builtin_tts_sample_rate = {normalized.builtin_tts_sample_rate}",
        f"builtin_tts_frequency_hz = {normalized.builtin_tts_frequency_hz}",
        f"builtin_tts_seconds = {normalized.builtin_tts_seconds}",
        "",
        "[resilience]",
        f"main_loop_error_backoff_seconds = {normalized.main_loop_error_backoff_seconds}",
        f"json_lock_timeout_seconds = {normalized.json_lock_timeout_seconds}",
        f"json_lock_retry_seconds = {normalized.json_lock_retry_seconds}",
        "",
        "[logging]",
        f"file = {normalized.log_file}",
        "",
    ]
    return "\n".join(lines)


def save_runtime_settings(path: Path, settings: RuntimeSettings) -> None:
    """Persist runtime settings to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_runtime_settings(settings), encoding="utf-8")


def load_runtime_settings(
    settings_path: Path, include_env_secrets: bool = True
) -> tuple[RuntimeSettings, list[str]]:
    """Load runtime settings from INI file."""
    notes: list[str] = []
    settings = RuntimeSettings.from_current_config()

    parser = _load_ini(settings_path, notes)
    _apply_ini_overrides(parser, settings, notes)
    if include_env_secrets:
        _apply_env_overrides(settings, notes)

    return settings, notes


def apply_cli_overrides(
    settings: RuntimeSettings, overrides: RuntimeCliOverrides, notes: list[str]
) -> None:
    """Apply CLI overrides on top of loaded settings."""
    if overrides.force_mock:
        settings.use_mock_twitter = True
        notes.append("CLI override applied: mock mode forced on.")

    if overrides.disable_music:
        settings.use_music = False
        notes.append("CLI override applied: music disabled.")

    if overrides.voice_id is not None:
        settings.voice_id = overrides.voice_id
        settings.anchor_voice_id = overrides.voice_id
        notes.append(f"CLI override applied: voice_id set to '{settings.voice_id}'.")

    if overrides.log_level is not None:
        settings.log_level = overrides.log_level.upper()
        notes.append(f"CLI override applied: log level set to {settings.log_level}.")


def apply_runtime_settings(settings: RuntimeSettings) -> None:
    """Apply loaded runtime settings to the in-memory config module."""
    config.USE_MOCK_TWITTER = settings.use_mock_twitter
    config.VOICE_ID = settings.anchor_voice_id
    config.ANCHOR_VOICE_ID = settings.anchor_voice_id
    config.ANALYST_VOICE_ID = settings.analyst_voice_id
    config.SHOW_STYLE = settings.show_style
    config.IDLE_FORMAT = settings.idle_format
    config.LOG_LEVEL = settings.log_level

    config.TWITTER_ACCOUNTS = settings.twitter_accounts
    config.FETCH_INTERVAL_SECONDS = settings.fetch_interval_seconds
    config.TWITTER_FETCH_LIMIT = settings.twitter_fetch_limit
    config.MOCK_TWEET_BATCH_SIZE = settings.mock_tweet_batch_size

    config.RECAP_INTERVAL_SECONDS = settings.recap_interval_seconds
    config.RECAP_STORY_COUNT = settings.recap_story_count
    config.RECAP_LOOKBACK_HOURS = settings.recap_lookback_hours
    config.STORY_RETENTION_HOURS = settings.story_retention_hours

    config.FILLER_ENABLED = settings.filler_enabled
    config.FILLER_INTERVAL_SECONDS = settings.filler_interval_seconds
    config.FILLER_TOPICS = settings.filler_topics

    config.LLM_PROVIDER = settings.llm_provider
    config.OLLAMA_MODEL = settings.ollama_model
    config.OLLAMA_FALLBACK_MODEL = settings.ollama_fallback_model
    config.OLLAMA_BASE_URL = settings.ollama_base_url
    config.OLLAMA_MAX_RETRIES = settings.ollama_max_retries
    config.OLLAMA_BACKOFF_FACTOR = settings.ollama_backoff_factor
    config.LLM_API_BASE_URL = settings.llm_api_base_url
    config.LLM_API_MODEL = settings.llm_api_model
    config.LLM_API_KEY = settings.llm_api_key
    config.LLM_API_KEY_ENV_VAR = settings.llm_api_key_env_var

    config.MUSIC_FILE = settings.music_file
    config.MUSIC_VOLUME_IDLE = settings.music_volume_idle
    config.MUSIC_VOLUME_DUCKED = settings.music_volume_ducked
    config.MUSIC_FADE_DURATION_SECONDS = settings.music_fade_duration_seconds
    config.VOLUME_FADE_STEPS_PER_SECOND = settings.volume_fade_steps_per_second

    config.AUDIO_CACHE_DIR = settings.audio_cache_dir
    config.MAX_CACHE_FILES = settings.max_cache_files
    config.AUDIO_PLAYBACK_POLL_SECONDS = settings.audio_playback_poll_seconds
    config.INITIAL_IDLE_SLEEP_SECONDS = settings.initial_idle_sleep_seconds
    config.BUILTIN_TTS_SAMPLE_RATE = settings.builtin_tts_sample_rate
    config.BUILTIN_TTS_FREQUENCY_HZ = settings.builtin_tts_frequency_hz
    config.BUILTIN_TTS_SECONDS = settings.builtin_tts_seconds

    config.MAIN_LOOP_ERROR_BACKOFF_SECONDS = settings.main_loop_error_backoff_seconds
    config.JSON_LOCK_TIMEOUT_SECONDS = settings.json_lock_timeout_seconds
    config.JSON_LOCK_RETRY_SECONDS = settings.json_lock_retry_seconds
    config.LOG_FILE = settings.log_file


def create_settings_file(path: Path, overwrite: bool = False) -> bool:
    """Create a runtime settings file template."""
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(RUNTIME_SETTINGS_TEMPLATE, encoding="utf-8")
    return True


def create_settings_example_file(path: Path, overwrite: bool = False) -> bool:
    """Create an example settings file template."""
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(RUNTIME_SETTINGS_TEMPLATE, encoding="utf-8")
    return True
