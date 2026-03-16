# X-News-Station — Detailed Reference

> **Project overview and quick start:** see the [root README](../README.md).

A fully local "Twitter-to-Radio" application that monitors Twitter/X accounts, turns posts into a live radio-style show with headline reads and filler chatter, converts them to speech, and plays idle music between spoken segments.

```
==================================================================

    X  N  E  W  S  -  S  T  A  T  I  O  N

    Twitter-to-Radio News Station

==================================================================
```

## Prerequisites

- **Python 3.10+** - Required for modern type hints and features
- **Ollama** - Local LLM server for news rewriting
  - Install from: https://ollama.com/
  - Default model: `llama3` (falls back to `mistral` if unavailable)
- **Kokoro voice models** (recommended) - For high-quality local TTS
  - Without Kokoro, the app falls back to system TTS

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd x_news_station
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install and start Ollama:**
   ```bash
   # Download from https://ollama.com/ and follow install instructions
   ollama serve
   ```

4. **Pull a language model:**
   ```bash
   ollama pull llama3
   # Or use mistral as fallback
   ollama pull mistral
   ```

5. **Create editable runtime settings (recommended):**
   ```bash
   python main.py --init-config
   ```
   This creates:
   - `station_settings.ini` (main user options)
   - `station_settings.example.ini` (full advanced template with all options)

## Twitter Login

To use real Twitter data instead of mock data, the app relies on a project-local `twscrape` account store in `accounts.db`. It does not store Twitter secrets in `station_settings.ini`.

1. **Install twscrape (included in requirements):**
   ```bash
   pip install twscrape
   ```

2. **Preferred safer option:** run the launcher and import a live browser session:
   ```bash
   python main.py
   ```
   Then open the `Twitter Setup` section and paste:
   - your Twitter username
   - `auth_token`
   - `ct0`

   `Full Cookie String` is optional. If you already have `auth_token` and `ct0`, that is enough for the launcher import path.
   Those values are used once and saved only into the local `accounts.db` store.

3. **CLI fallback:** create a local account file like `twitter_accounts.txt` with one account per line:
   ```text
   username,password,email,email_password
   ```

4. **Import the accounts into twscrape:**
   ```bash
   twscrape add_accounts twitter_accounts.txt username,password,email,email_password
   ```

5. **Run login to save cookies:**
   ```bash
   twscrape login_accounts
   ```

6. **Disable mock mode in `station_settings.ini`:**
   ```ini
   [station]
   use_mock_twitter = false
   ```

## Twitter/X Terms of Service Notice

> **Important:** This project uses [twscrape](https://github.com/vladkens/twscrape), an unofficial Twitter/X scraping library that operates by reusing browser session cookies (`auth_token`, `ct0`). **This method of accessing Twitter/X is against Twitter/X's Terms of Service.**
>
> - You are solely responsible for how you use this software and for compliance with Twitter/X's ToS and applicable law.
> - This project is intended for local, personal, and educational use only.
> - The authors make no warranties about the legality of this approach in your jurisdiction.
> - Twitter/X may suspend or ban accounts used with unofficial scrapers.
> - Consider using the [official Twitter/X API](https://developer.twitter.com/en/docs) for production or commercial use.
>
> The `USE_MOCK_TWITTER = True` default keeps the station running without any Twitter connection. **Enable real Twitter only if you understand and accept these risks.**

## Adding Music

Place your background music file in the correct location:

1. **Format:** MP3 format recommended
2. **Location:** `assets/music/background.mp3`
3. **Volume:** The launcher exposes `Music Volume` and `Speech Duck Level` sliders so you can tune idle loudness and how far the music drops under speech

Example:
```bash
mkdir -p assets/music
cp your-music-file.mp3 assets/music/background.mp3
```

## Easy Shareable Setup (No Flags Needed)

For easiest use and sharing:

1. Run once:
   ```bash
   python main.py --init-config
   ```
2. Edit `station_settings.ini` in the project root.
3. Start the app with:
   ```bash
   python main.py
   ```

That opens the launcher GUI by default. Use `python main.py --no-gui` if you want the headless station loop directly.

You can share your `station_settings.ini` file with others so they do not need to memorize CLI options.

## Configuration

### Primary user settings file

Use `station_settings.ini` for day-to-day configuration:

```ini
[station]
use_mock_twitter = true
voice_id = am_michael
anchor_voice_id = am_michael
analyst_voice_id = bf_emma
show_style = hybrid
idle_format = two_host
use_music = true
log_level = INFO

[twitter]
accounts = elonmusk, sama, karpathy
fetch_interval_seconds = 300
fetch_limit = 5

[recap]
interval_seconds = 1800
story_count = 3

[llm]
# provider: ollama | openai_compatible | simple
provider = ollama
model = llama3
base_url = http://localhost:11434

[filler]
enabled = true
interval_seconds = 900
topics = AI industry rivalry, open-source launches
```

For every available setting (music fade controls, cache limits, retries, API-provider fields, and more), use `station_settings.example.ini` as the full template.

### Optional secret handling

If you use `provider = openai_compatible`, keep API keys out of files:
- Set `api_key_env_var = YOUR_ENV_VAR_NAME` in `station_settings.ini`
- Export that environment variable in your shell/session

### Advanced defaults

Advanced fallback/default constants are still available in [`config.py`](config.py), but the recommended user workflow is to edit `station_settings.ini`.

| Setting | Default | Description |
|---------|---------|-------------|
| `TWITTER_ACCOUNTS` | `["elonmusk", "sama", "karpathy"]` | Accounts to monitor |
| `FETCH_INTERVAL_SECONDS` | `300` (5 min) | How often to check for new tweets |
| `RECAP_INTERVAL_SECONDS` | `1800` (30 min) | How often to do a news recap |
| `RECAP_STORY_COUNT` | `3` | Number of stories in each recap |
| `OLLAMA_MODEL` | `"llama3"` | LLM model for rewriting |
| `OLLAMA_BASE_URL` | `"http://localhost:11434"` | Ollama server URL |
| `VOICE_ID` | `"am_michael"` | Legacy anchor voice fallback |
| `ANCHOR_VOICE_ID` | `"am_michael"` | Main voice for headlines and recaps |
| `ANALYST_VOICE_ID` | `"bf_emma"` | Secondary voice for filler discussions |
| `MUSIC_VOLUME_IDLE` | `0.8` | Music volume when not broadcasting |
| `MUSIC_VOLUME_DUCKED` | `0.2` | Music volume during broadcasts |
| `USE_MOCK_TWITTER` | `True` | Use mock data instead of real Twitter |

### Voice Options

The launcher exposes the full Kokoro voice list when the model files are present, plus a `Preview Voices` button so you can hear the anchor and analyst voices before starting the station.

## Running

### Basic Usage

```bash
# Open the launcher GUI
python main.py

# Run the station headless
python main.py --no-gui

# Generate editable settings templates
python main.py --init-config

# Use a specific settings file
python main.py --config station_settings.ini

# Run with real Twitter data (requires credentials)
python main.py --no-gui
# Make sure use_mock_twitter=false in station_settings.ini

# Run a bounded functional test
python main.py --smoke-test

# Use a different voice
python main.py --voice bf_emma

# Disable background music
python main.py --no-music

# Enable debug logging
python main.py --log-level DEBUG
```

### Stopping the Station

Press `Ctrl+C` to stop the application gracefully. The app will:
1. Stop background music
2. Clean up audio cache
3. Save story log
4. Exit cleanly

## Architecture

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”     â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”     â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  news_fetcher   â”‚â”€â”€â”€â”€â–¶â”‚   news_anchor   â”‚â”€â”€â”€â”€â–¶â”‚  audio_studio   â”‚
â”‚                 â”‚     â”‚                 â”‚     â”‚                 â”‚
â”‚ - MockTwitter   â”‚     â”‚ - NewsRewriter  â”‚     â”‚ - VoiceGeneratorâ”‚
â”‚ - Twitter API   â”‚     â”‚ - SimpleRewrite â”‚     â”‚ - Cache (SHA256)â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜     â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜     â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
         â”‚                       â”‚                       â”‚
         â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                 â–¼
                        â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                        â”‚   radio_loop    â”‚
                        â”‚                 â”‚
                        â”‚  State Machine: â”‚
                        â”‚  IDLEâ†’CHECKING  â”‚
                        â”‚  â†’BROADCASTING  â”‚
                        â”‚  â†’RECAPPING     â”‚
                        â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                 â”‚
                                 â–¼
                        â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                        â”‚     pygame      â”‚
                        â”‚  (audio output) â”‚
                        â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

## Troubleshooting

### "No TTS engine available!"

The app couldn't find kokoro-onnx or pyttsx3. Install at least one:
```bash
pip install pyttsx3          # System TTS (always works)
pip install kokoro-onnx      # High-quality TTS (requires models)
```

### "Ollama not available, using SimpleRewriter fallback"

Make sure Ollama is running:
```bash
ollama serve
```

Then pull a model:
```bash
ollama pull llama3
```

### "Music file not found"

Add a music file:
```bash
mkdir -p assets/music
cp your-music.mp3 assets/music/background.mp3
```

Or run with `--no-music` flag.

### Import errors for twscrape/ollama/kokoro

These are optional dependencies. The app will gracefully fall back:
- No twscrape -> Use mock Twitter data
- No ollama -> Use SimpleRewriter (regex cleaning)
- No kokoro -> Use pyttsx3 (system TTS)
- No pyttsx3 -> Use built-in WAV fallback tone generation

### OpenAI-compatible API mode

To use API-based rewriting:
1. Set in `station_settings.ini`:
   ```ini
   [llm]
   provider = openai_compatible
   api_base_url = https://api.openai.com/v1
   api_model = gpt-4o-mini
   api_key_env_var = OPENAI_API_KEY
   ```
2. Set the environment variable in your shell/session before running.

### Audio cache growing too large

Cache is automatically cleaned when it exceeds 200 files. You can manually clear it:
```python
from modules.audio_studio import VoiceGenerator
vg = VoiceGenerator()
vg.clear_cache()
```

## Project Structure

```
x_news_station/
â”œâ”€â”€ main.py                  # Entry point
â”œâ”€â”€ config.py                # All settings
â”œâ”€â”€ requirements.txt         # Dependencies
â”œâ”€â”€ README.md               # This file
â”œâ”€â”€ TASKS.md                # Development progress
â”œâ”€â”€ DECISIONS.md            # Architecture decisions
â”œâ”€â”€ assets/music/           # Background music
â”œâ”€â”€ cache/                  # Audio cache
â”œâ”€â”€ logs/                   # Log files
â”œâ”€â”€ modules/
â”‚   â”œâ”€â”€ news_fetcher.py     # Twitter fetching
â”‚   â”œâ”€â”€ news_anchor.py      # LLM rewriting
â”‚   â”œâ”€â”€ audio_studio.py     # TTS generation
â”‚   â””â”€â”€ radio_loop.py       # Main loop
â””â”€â”€ tests/
    â”œâ”€â”€ test_fetcher.py
    â”œâ”€â”€ test_anchor.py
    â”œâ”€â”€ test_audio_studio.py
    â””â”€â”€ test_radio_loop.py
```

## Testing

Run all tests:
```bash
pytest
```

Run specific test file:
```bash
pytest tests/test_fetcher.py -v
```

## License

This project is licensed under the **MIT License** — see the [LICENSE](../LICENSE) file for details.

Copyright (c) 2026 huss2342

