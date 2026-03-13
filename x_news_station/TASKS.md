# X-News-Station: Live Progress Tracker

> **INSTRUCTION**: On any restart, read this file first to understand current progress.
> Check off items as they are completed. Do not mark complete until tests pass.

## Project Overview
A fully local, autonomous "Twitter-to-Radio" application that monitors Twitter/X accounts,
rewrites tweets as professional news bulletins using a local LLM, converts them to 
high-fidelity speech, and broadcasts them over looping background music like a radio station.

---

## Project Structure

```
x_news_station/
├── main.py                  # Entry point
├── config.py                # All user-configurable settings (single source of truth)
├── requirements.txt
├── README.md
├── TASKS.md                 # [THIS FILE] Live progress tracker
├── DECISIONS.md             # Log every architectural decision
├── assets/
│   └── music/
│       └── .gitkeep         # Placeholder, README explains what to put here
├── cache/
│   └── .gitkeep             # Audio cache lives here
├── logs/
│   └── .gitkeep
├── modules/
│   ├── __init__.py
│   ├── news_fetcher.py      # MODULE A: Twitter fetching
│   ├── news_anchor.py       # MODULE B: LLM rewriting
│   ├── audio_studio.py      # MODULE C: TTS generation
│   └── radio_loop.py        # MODULE D: Radio state machine
└── tests/
    ├── __init__.py
    ├── conftest.py          # Shared pytest fixtures
    ├── test_fetcher.py      # TEST A: Fetcher tests
    ├── test_anchor.py       # TEST B: Anchor tests
    ├── test_audio_studio.py # TEST C: Audio tests
    └── test_radio_loop.py   # TEST D: Radio loop tests
```

---

## Task Checklist

### Phase 1: Project Setup

- [x] **Create folder structure**
  - [x] `x_news_station/` root
  - [x] `x_news_station/assets/music/`
  - [x] `x_news_station/cache/`
  - [x] `x_news_station/logs/`
  - [x] `x_news_station/modules/`
  - [x] `x_news_station/tests/`
  - [x] All `.gitkeep` files in place

- [x] **Create config.py**
  - [x] TWITTER_ACCOUNTS list
  - [x] FETCH_INTERVAL_SECONDS = 300
  - [x] RECAP_INTERVAL_SECONDS = 1800
  - [x] RECAP_STORY_COUNT = 3
  - [x] OLLAMA_MODEL = "llama3"
  - [x] OLLAMA_BASE_URL = "http://localhost:11434"
  - [x] VOICE_ID = "am_michael"
  - [x] MUSIC_FILE = "assets/music/background.mp3"
  - [x] MUSIC_VOLUME_IDLE = 0.8
  - [x] MUSIC_VOLUME_DUCKED = 0.2
  - [x] MUSIC_FADE_DURATION_SECONDS = 2.0
  - [x] AUDIO_CACHE_DIR = "cache/"
  - [x] LOG_LEVEL = "INFO"
  - [x] USE_MOCK_TWITTER = True

- [x] **Create requirements.txt**
  - [x] twscrape
  - [x] ollama
  - [x] kokoro-onnx
  - [x] pyttsx3
  - [x] pygame
  - [x] pytest
  - [x] pytest-mock

- [x] **Create DECISIONS.md** (initial entries)

---

### Phase 2: Module A - News Fetcher

**File**: `modules/news_fetcher.py`

- [x] **BaseTweetMonitor (ABC)**
  - [x] Abstract method: `fetch_latest(accounts: list[str]) -> list[TweetData]`
  - [x] TweetData dataclass with id, username, text, timestamp

- [x] **MockTwitterMonitor**
  - [x] Returns 5 realistic fake tweets on first call
  - [x] Returns 0 tweets on subsequent calls
  - [x] Deterministic for testing

- [x] **TwitterMonitor**
  - [x] Uses twscrape to fetch real tweets
  - [x] Tracks seen_ids.json to avoid duplicates
  - [x] Handles AuthenticationError gracefully
  - [x] Handles NetworkError gracefully
  - [x] Handles RateLimitError gracefully
  - [x] On error: log and return empty list

- [x] **Factory function get_monitor()**
  - [x] Returns MockTwitterMonitor if use_mock=True
  - [x] Returns TwitterMonitor otherwise

**File**: `tests/test_fetcher.py`

- [x] Test MockTwitterMonitor returns correct TweetData structure
- [x] Test MockTwitterMonitor returns 0 tweets on second call
- [x] Test TwitterMonitor handles network errors without crashing
- [x] Test get_monitor() factory returns correct class based on flag

**Verification**: `pytest tests/test_fetcher.py -v` passes (15 tests)

---

### Phase 3: Module B - News Anchor

**File**: `modules/news_anchor.py`

- [x] **NewsRewriter class**
  - [x] `__init__` checks Ollama reachability
  - [x] Falls back to SimpleRewriter if Ollama unreachable
  - [x] `rewrite(tweet: TweetData) -> str`
  - [x] Uses exact system prompt provided
  - [x] Retry logic: 3 attempts with exponential backoff
  - [x] In-memory cache keyed by tweet.id

- [x] **SimpleRewriter (fallback)**
  - [x] Strips URLs via regex
  - [x] Strips hashtags
  - [x] Prepends "Breaking news from [Username]..."

**File**: `tests/test_anchor.py`

- [x] Mock ollama.chat() response
- [x] Test rewrite() returns string starting with "Breaking news from"
- [x] Test fallback to SimpleRewriter when Ollama unreachable
- [x] Test retry logic triggers on failure
- [x] Test caching: same tweet ID does not call ollama twice

**Verification**: `pytest tests/test_anchor.py -v` passes (12 tests)

---

### Phase 4: Module C - Audio Studio

**File**: `modules/audio_studio.py`

- [x] **VoiceGenerator class**
  - [x] `__init__` loads kokoro-onnx model
  - [x] Falls back to pyttsx3 if kokoro unavailable
  - [x] Logs WARNING if using pyttsx3
  - [x] `generate(text: str, voice_id: str) -> Path`
  - [x] Caching: SHA256 hash of (text + voice_id)
  - [x] Cache hit: return cached .wav path
  - [x] Cache miss: generate, save, return path
  - [x] `clean_cache(max_files=200)` removes oldest files

**File**: `tests/test_audio_studio.py`

- [x] Mock kokoro model loading
- [x] Test cache hit: same text+voice returns same path
- [x] Test cache miss: new text generates new file
- [x] Test clean_cache() removes oldest when over limit

**Verification**: `pytest tests/test_audio_studio.py -v` passes (16 tests)

---

### Phase 5: Module D - Radio Loop

**File**: `modules/radio_loop.py`

- [x] **State Machine Enum**
  - [x] IDLE
  - [x] CHECKING
  - [x] BROADCASTING
  - [x] RECAPPING
  - [x] ERROR

- [x] **RadioStation class**
  - [x] `start()`: main loop with KeyboardInterrupt handling
  - [x] `_idle()`: play music at IDLE volume, sleep
  - [x] `_check()`: call news_fetcher, return TweetData list
  - [x] `_broadcast(tweets)`: 
    - [x] Rewrite each tweet
    - [x] Generate audio
    - [x] Fade music to DUCKED
    - [x] Play .wav files sequentially
    - [x] Fade music back to IDLE
  - [x] `_recap()`: fetch top 3 from story_log.json, re-broadcast
  - [x] `_log_story()`: append to story_log.json

- [x] **Music handling**
  - [x] pygame.mixer for all audio
  - [x] Background music loops infinitely (-1)
  - [x] Smooth volume ramp in background thread
  - [x] Log warning if music file not found (don't crash)

**File**: `tests/test_radio_loop.py`

- [x] Mock all dependencies (fetcher, anchor, audio, pygame)
- [x] Test state transitions: IDLE → CHECKING → BROADCASTING → IDLE
- [x] Test RECAP triggers after 30 minutes of no new tweets
- [x] Test clean shutdown on KeyboardInterrupt

**Verification**: `pytest tests/test_radio_loop.py -v` passes (19 tests)

---

### Phase 6: Main Entry Point

**File**: `main.py`

- [x] CLI argument parsing:
  - [x] `--mock` (force mock twitter)
  - [x] `--voice [voice_id]`
  - [x] `--no-music`
- [x] Initialize logging (console + logs/app.log)
- [x] Print startup banner with config
- [x] Instantiate RadioStation
- [x] Call start()
- [x] Top-level exception handling

---

### Phase 7: Documentation

**File**: `README.md`

- [x] Section 1: Prerequisites (Python 3.10+, Ollama, kokoro-onnx)
- [x] Section 2: Installation (clone, pip install)
- [x] Section 3: Twitter Login (twscrape commands)
- [x] Section 4: Adding Music (format, location, naming)
- [x] Section 5: Configuration (explain every config.py setting)
- [x] Section 6: Running (python main.py, --mock flag)
- [x] Section 7: Troubleshooting (common errors and fixes)

---

### Phase 8: Integration & Final Verification

- [x] **Integration Test**
  - [x] Run: `python main.py --mock --no-music`
  - [x] Verify startup banner displays
  - [x] Verify state transitions work
  - [x] Verify clean shutdown (Ctrl+C)

- [x] **Full Test Suite**
  - [x] Run: `pytest` from root
  - [x] Confirm 0 failures
  - [x] Fix any failing tests

- [x] **Final Review**
  - [x] All TASKS.md items checked off
  - [x] All code has proper logging (not print)
  - [x] All code has type hints
  - [x] All code has docstrings
  - [x] No hardcoded values outside config.py
  - [x] All functions fully implemented (no stubs)

---

### Phase 9: Post-Implementation Audit (2026-03-04)

- [x] Replace all runtime `print()` usage with structured logging
- [x] Add concurrency-safe JSON persistence (locked + atomic writes) for:
  - [x] `cache/seen_ids.json`
  - [x] `cache/story_log.json`
- [x] Harden loop resilience:
  - [x] Main station loop now logs and recovers from iteration errors
  - [x] Shutdown path is idempotent and always runs
- [x] Harden music fade threading:
  - [x] Single fade worker thread (no unbounded thread spawning)
  - [x] Graceful worker stop on shutdown
- [x] Harden dependency fallbacks:
  - [x] Ollama malformed/failed responses fallback cleanly
  - [x] Voice generation falls back to built-in WAV generator if no TTS engine exists
  - [x] Audio playback selects best available backend (`pygame` or `winsound`)
- [x] Expand test suite coverage for new robustness paths
- [x] Add shared `tests/conftest.py`
- [x] Add shareable runtime settings UX:
  - [x] `station_settings.ini` support in `main.py`
  - [x] Optional environment-variable API-key support
  - [x] `--init-config` template generation flow
- [x] Expand runtime settings to advanced show controls:
  - [x] Full `station_settings.example.ini` with all configurable options
  - [x] LLM provider modes (`ollama`, `openai_compatible`, `simple`)
  - [x] Dead-time filler segment support with configurable topics

---

## Current Status

**Phase**: COMPLETE
**Last Updated**: 2026-03-04
**Completed**: 20/20 phases (100%)

### Test Summary
- 72 tests passing
- 0 tests failing
- Integration test successful
- All modules fully implemented
- All fallbacks working correctly

## Notes

- Remember: Never leave a function as a stub
- Remember: Never move to next module until tests pass
- Remember: If dependency unavailable, implement graceful fallback
- Remember: Log, don't print
