# X-News-Station

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey)](#)
[![CI](https://github.com/YOUR_USERNAME/YOUR_REPO/actions/workflows/desktop-smoke.yml/badge.svg)](https://github.com/YOUR_USERNAME/YOUR_REPO/actions/workflows/desktop-smoke.yml)

**A fully-local, AI-powered radio station that monitors Twitter/X accounts and broadcasts them as a live news show — complete with anchor voice, analyst banter, background music, and automatic recaps. No cloud required.**

> **Origin:** I got tired of endlessly scrolling my Twitter/X feed just to catch up on what people I follow were saying. So I built a radio station that does it for me — I can have it playing in the background while I work and just listen. This was developed as a quick side project using AI assistance (Claude) for the bulk of the code.

```
==================================================================

    X  N  E  W  S  -  S  T  A  T  I  O  N

    Turn tweets into a live AI radio broadcast — 100% local

==================================================================
```

---

## What It Does

X-News-Station watches a list of Twitter/X accounts and runs an autonomous radio show on your desktop:

1. **Fetches** new posts from the accounts you choose (real or mock data)
2. **Rewrites** them into broadcast-style headlines using a local LLM (Ollama)
3. **Reads** them aloud with a multi-voice TTS engine (Kokoro or system TTS)
4. **Plays** background music that auto-ducks when speech starts
5. **Runs recaps** every 30 minutes, and fills dead air with AI-generated commentary between stories

All processing happens locally — no API keys needed for the core experience.

---

## Key Features

- **100% local by default** — runs on Ollama (llama3/mistral) + Kokoro TTS, no cloud calls
- **Multi-voice broadcast** — separate anchor voice and analyst voice for natural two-host banter
- **Background music with ducking** — auto-lowers music volume during speech segments
- **Automatic news recaps** — periodic summaries of the top stories at configurable intervals
- **AI filler generation** — fills dead air with on-topic commentary based on configurable themes
- **PySide6 desktop GUI** — settings dashboard, live rundown view, voice preview, and console log
- **Headless / no-GUI mode** — run as a background service with `--no-gui`
- **Graceful fallback chain** — each AI component degrades gracefully if unavailable
  - No Kokoro → pyttsx3 (system TTS)
  - No Ollama → regex-based SimpleRewriter
  - No Twitter creds → built-in mock tweet generator
- **OpenAI-compatible LLM support** — swap Ollama for any OpenAI-compatible API endpoint
- **Cross-platform** — tested on Windows and Linux (CI on both)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Desktop GUI | [PySide6](https://doc.qt.io/qtforpython/) (Qt 6) |
| LLM rewriting | [Ollama](https://ollama.com/) (llama3, mistral, or any local model) |
| Primary TTS | [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) |
| Fallback TTS | [pyttsx3](https://github.com/nateshmbhat/pyttsx3) |
| Audio playback | [pygame](https://www.pygame.org/) |
| Twitter scraping | [twscrape](https://github.com/vladkens/twscrape) |
| Language | Python 3.10+ |
| Packaging | PyInstaller (standalone binary builds) |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO/x_news_station

# 2. Install
pip install -r requirements.txt

# 3. Start Ollama (for LLM rewriting)
ollama serve
ollama pull llama3

# 4. Create your settings file
python main.py --init-config

# 5. Launch
python main.py
```

The GUI opens with mock Twitter data enabled by default — you get a working radio show immediately, no credentials needed.

For headless mode:
```bash
python main.py --no-gui
```

---

## How It Works

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  news_fetcher   │────▶│   news_anchor   │────▶│  audio_studio   │
│                 │     │                 │     │                 │
│ - MockTwitter   │     │ - NewsRewriter  │     │ - VoiceGenerator│
│ - Twitter API   │     │ - SimpleRewrite │     │ - Cache (SHA256)│
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                        ┌─────────────────┐
                        │   radio_loop    │
                        │                 │
                        │  State Machine: │
                        │  IDLE→CHECKING  │
                        │  →BROADCASTING  │
                        │  →RECAPPING     │
                        └─────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │ pygame + PySide6│
                        │  (audio + GUI)  │
                        └─────────────────┘
```

The `radio_loop` state machine orchestrates everything: it polls for new tweets, hands them to the anchor for rewriting, queues TTS audio segments, manages music ducking, and fires periodic recap and filler segments automatically.

---

## Screenshots

> The desktop GUI provides a settings dashboard, live broadcast rundown, console log, and voice preview — all in a single window.

*(Screenshots coming soon — contributions welcome)*

---

## Configuration

Generate a settings file on first run:

```bash
python main.py --init-config
```

This creates `station_settings.ini` (your daily config) and `station_settings.example.ini` (every available option with comments).

### Essential settings

```ini
[station]
use_mock_twitter = true        # Set false to use real Twitter
anchor_voice_id = am_michael   # Kokoro voice for headlines
analyst_voice_id = bf_emma     # Kokoro voice for commentary
show_style = hybrid            # hybrid | anchor_only | two_host

[twitter]
accounts = elonmusk, sama, karpathy
fetch_interval_seconds = 300

[llm]
provider = ollama              # ollama | openai_compatible | simple
model = llama3

[filler]
enabled = true
topics = AI industry rivalry, open-source launches
```

Full documentation is in [`x_news_station/README.md`](x_news_station/README.md).

---

## Requirements

- **Python 3.10+**
- **[Ollama](https://ollama.com/)** running locally (or any OpenAI-compatible endpoint)
- **Kokoro voice model files** (optional — falls back to system TTS without them)
- A background music MP3 at `assets/music/background.mp3` (optional — runs without music)

---

## Twitter/X Notice

This project can use [twscrape](https://github.com/vladkens/twscrape), an unofficial scraping library that reuses browser session cookies. **This is against Twitter/X's Terms of Service.** The default `use_mock_twitter = true` means no Twitter connection is made. Enable real Twitter only if you understand and accept the ToS risk. See the full notice in [`x_news_station/README.md`](x_news_station/README.md#twitterx-terms-of-service-notice).

---

## Project Structure

```
x_news_station/
├── main.py                  # Entry point + CLI flags
├── config.py                # All default constants
├── desktop_app.py           # PySide6 settings & control GUI
├── requirements.txt         # Runtime dependencies
├── requirements-dev.txt     # Dev + test + packaging dependencies
├── modules/
│   ├── news_fetcher.py      # Twitter/mock fetching
│   ├── news_anchor.py       # LLM-based headline rewriting
│   ├── audio_studio.py      # TTS generation + audio cache
│   ├── radio_loop.py        # Main broadcast state machine
│   └── editorial_planner.py # AI filler segment planning
├── tests/
│   ├── test_fetcher.py
│   ├── test_anchor.py
│   ├── test_audio_studio.py
│   └── test_radio_loop.py
└── packaging/
    ├── build_windows.ps1    # PyInstaller Windows bundle
    └── build_linux.sh       # PyInstaller Linux bundle
```

---

## Development

```bash
pip install -r x_news_station/requirements-dev.txt
cd x_news_station
pytest -q
```

CI runs pytest + a health check + a smoke test + a PyInstaller bundle on every push, on both Windows and Ubuntu.

---

## Use Cases

- **Personal news dashboard** — monitor the accounts you follow and hear the day's highlights hands-free
- **Ambient office broadcast** — run as background audio while working, like a talk radio station
- **Local LLM showcase** — a real-world Ollama application with audio output
- **AI audio pipeline prototype** — LLM rewriting → multi-voice TTS → ducked music → scheduled segments
- **Kokoro TTS demo** — hear multiple Kokoro voices in a realistic two-host format
- **PySide6 reference app** — a non-trivial Qt 6 desktop application with a dashboard, nav rail, docked console, and live process management

---

## Searchability — Recommended GitHub Topics

After publishing, add these topics to the repo (Settings → Topics) so GitHub's search and Explore surface it correctly:

```
ollama  local-llm  text-to-speech  tts  kokoro  twitter  pyside6  qt  python
radio  ai  llm  autonomous  news  desktop-application  pygame  twscrape
```

GitHub Topics are the single most effective way to make an open-source project discoverable — they feed GitHub Explore, topic pages, and external search indexing.

---

## Contributing

Pull requests are welcome! This started as a personal side project and there's plenty of room to grow it. Some ideas:

- Support for additional social feed sources (RSS, Bluesky, Mastodon)
- Better editorial planning / story ranking
- More voice personas and show formats
- A proper audio visualizer in the GUI
- Packaging improvements (macOS support, installers)

If you add something useful, open a PR. Keep changes focused and make sure `pytest` passes before submitting.

---

## License

MIT — see [LICENSE](LICENSE).

Copyright (c) 2026 huss2342
