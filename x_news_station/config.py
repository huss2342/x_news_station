"""Configuration for X-News-Station.

All runtime-adjustable values live in this module so operational behavior can be
changed without code edits.
"""

from pathlib import Path

# Twitter/X settings
TWITTER_ACCOUNTS: list[str] = ["elonmusk", "sama", "karpathy"]
TWITTER_FETCH_LIMIT: int = 5
FETCH_INTERVAL_SECONDS: int = 300
USE_MOCK_TWITTER: bool = True
MOCK_TWEET_BATCH_SIZE: int = 5
SEEN_IDS_FILE: str = "cache/seen_ids.json"
TWITTER_ACCOUNTS_DB_FILE: str = "accounts.db"
INCLUDE_ORIGINAL_POSTS: bool = True
INCLUDE_QUOTE_POSTS: bool = True
INCLUDE_REPLIES: bool = False
INCLUDE_REPOSTS: bool = False

# Recap and story retention settings
RECAP_INTERVAL_SECONDS: int = 1800
RECAP_STORY_COUNT: int = 3
RECAP_LOOKBACK_HOURS: int = 1
STORY_RETENTION_HOURS: int = 24
STORY_LOG_FILE: str = "cache/story_log.json"
RUNDOWN_STATE_FILE: str = "cache/rundown_state.json"

# Filler segment settings for dead-air moments
FILLER_ENABLED: bool = True
FILLER_INTERVAL_SECONDS: int = 900
FILLER_TOPICS: list[str] = [
    "AI safety best practices",
    "local-first software tools",
    "open-source project highlights",
    "daily developer productivity habits",
    "simple cybersecurity hygiene reminders",
]

# Editorial rundown settings
EDITORIAL_SEGMENT_INTERVAL_SECONDS: int = 90
EDITORIAL_CANDIDATE_LOOKBACK_MINUTES: int = 180
EDITORIAL_REPEAT_COOLDOWN_MINUTES: int = 45
EDITORIAL_MAX_CONSECUTIVE_SAME_SOURCE: int = 2
EDITORIAL_DEFAULT_RUNDOWN_STRATEGY: str = "editorial"
EDITORIAL_SEGMENT_TYPES: list[str] = [
    "fresh_headline",
    "quick_reset",
    "compare_updates",
    "why_it_matters",
    "watchlist_discussion",
    "music_break",
]
EDITORIAL_SEGMENT_TYPE_LABELS: dict[str, str] = {
    "fresh_headline": "Fresh Headline",
    "quick_reset": "Quick Reset",
    "compare_updates": "Compare Updates",
    "why_it_matters": "Why It Matters",
    "watchlist_discussion": "Watchlist Discussion",
    "music_break": "Music Break",
}

# Ollama settings
OLLAMA_MODEL: str = "llama3"
OLLAMA_FALLBACK_MODEL: str = "mistral"
OLLAMA_BASE_URL: str = "http://localhost:11434"
OLLAMA_MAX_RETRIES: int = 3
OLLAMA_BACKOFF_FACTOR: float = 1.0

# LLM provider settings
# Supported: "ollama", "openai_compatible", "simple"
LLM_PROVIDER: str = "ollama"
LLM_API_BASE_URL: str = "https://api.openai.com/v1"
LLM_API_MODEL: str = "gpt-4o-mini"
LLM_API_KEY: str = ""
LLM_API_KEY_ENV_VAR: str = "OPENAI_API_KEY"

# TTS settings
VOICE_OPTIONS: list[str] = [
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_heart",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
    "ef_dora",
    "em_alex",
    "em_santa",
    "ff_siwis",
    "hf_alpha",
    "hf_beta",
    "hm_omega",
    "hm_psi",
    "if_sara",
    "im_nicola",
    "jf_alpha",
    "jf_gongitsune",
    "jf_nezumi",
    "jf_tebukuro",
    "jm_kumo",
    "pf_dora",
    "pm_alex",
    "pm_santa",
    "zf_xiaobei",
    "zf_xiaoni",
    "zf_xiaoxiao",
    "zf_xiaoyi",
    "zm_yunjian",
    "zm_yunxi",
    "zm_yunxia",
    "zm_yunyang",
]
VOICE_ID: str = "am_michael"
ANCHOR_VOICE_ID: str = VOICE_ID
ANALYST_VOICE_ID: str = "bf_emma"
SHOW_STYLE: str = "hybrid"
IDLE_FORMAT: str = "two_host"
BUILTIN_TTS_SAMPLE_RATE: int = 22050
BUILTIN_TTS_FREQUENCY_HZ: int = 220
BUILTIN_TTS_SECONDS: float = 0.6

# Music and audio playback settings
MUSIC_FILE: str = "assets/music/background.mp3"
MUSIC_VOLUME_IDLE: float = 0.8
MUSIC_VOLUME_DUCKED: float = 0.2
MUSIC_FADE_DURATION_SECONDS: float = 2.0
VOLUME_FADE_STEPS_PER_SECOND: int = 10
AUDIO_PLAYBACK_POLL_SECONDS: float = 0.1
INITIAL_IDLE_SLEEP_SECONDS: float = 1.0
AUDIO_CACHE_DIR: str = "cache/"
MAX_CACHE_FILES: int = 200

# Main loop resilience settings
MAIN_LOOP_ERROR_BACKOFF_SECONDS: float = 2.0

# JSON persistence and locking settings
JSON_LOCK_TIMEOUT_SECONDS: float = 3.0
JSON_LOCK_RETRY_SECONDS: float = 0.05

# Logging settings
LOG_LEVEL: str = "INFO"
LOG_FILE: str = "logs/app.log"

# UI settings
UI_THEME: str = "broadcast_warm"
UI_ADVANCED_MODE: bool = False
UI_SHOW_CONSOLE: bool = True

# Runtime settings files
SETTINGS_FILE: str = "station_settings.ini"
SETTINGS_EXAMPLE_FILE: str = "station_settings.example.ini"


def get_project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent


def get_music_path() -> Path:
    """Return the resolved path to the music file."""
    return get_project_root() / MUSIC_FILE


def get_cache_dir() -> Path:
    """Return the resolved path to the cache directory."""
    return get_project_root() / AUDIO_CACHE_DIR


def get_log_file() -> Path:
    """Return the resolved path to the log file."""
    return get_project_root() / LOG_FILE


def get_seen_ids_file() -> Path:
    """Return the resolved path to the seen IDs file."""
    return get_project_root() / SEEN_IDS_FILE


def get_twitter_accounts_db_file() -> Path:
    """Return the resolved path to the project-local twscrape accounts DB."""
    return get_project_root() / TWITTER_ACCOUNTS_DB_FILE


def get_story_log_file() -> Path:
    """Return the resolved path to the story log file."""
    return get_project_root() / STORY_LOG_FILE


def get_rundown_state_file() -> Path:
    """Return the resolved path to the rundown state file."""
    return get_project_root() / RUNDOWN_STATE_FILE


def get_settings_file() -> Path:
    """Return the resolved path to the runtime settings file."""
    return get_project_root() / SETTINGS_FILE


def get_settings_example_file() -> Path:
    """Return the resolved path to the runtime settings example file."""
    return get_project_root() / SETTINGS_EXAMPLE_FILE
