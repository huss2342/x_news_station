"""Provider reachability helpers and runtime health checks."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

import config
from modules.audio_studio import VoiceGenerator
from modules.runtime_settings import RuntimeSettings, load_runtime_settings
from modules.twitter_setup import create_twscrape_api, get_twitter_db_path

VOICE_OPTIONS = list(config.VOICE_OPTIONS)
LLM_BACKEND_OPTIONS = ["Ollama", "LM Studio", "OpenAI-Compatible", "Simple"]
LM_STUDIO_DEFAULT_BASE_URL = "http://localhost:1234/v1"
LM_STUDIO_BASE_URL_CANDIDATES = [
    LM_STUDIO_DEFAULT_BASE_URL,
    "http://127.0.0.1:1234/v1",
]
SHOW_STYLE_LABELS = {
    "Hybrid": "hybrid",
    "Talk Radio": "talk_radio",
    "Straight News": "straight_news",
}
IDLE_FORMAT_LABELS = {
    "Two Voices": "two_host",
    "One Host": "solo_host",
    "Music First": "music_first",
}
CURATED_FILLER_TOPICS = [
    "AI industry rivalry",
    "Open-source launches",
    "Developer tools worth watching",
    "Cybersecurity basics",
    "Space and science",
    "Tech policy and regulation",
    "Startup power shifts",
    "Creator economy changes",
    "Hardware supply chain moves",
    "Software engineering habits",
]
TWITTER_ACCOUNT_LINE_FORMAT = "username,password,email,email_password"
TWITTER_SETUP_LINES = [
    "Real Twitter mode uses a project-local twscrape account store. There is no Twitter secret in station_settings.ini.",
    "1. Install dependencies: pip install -r requirements.txt",
    "2. Safer option: open the launcher, paste username plus auth_token and ct0, then click Import Session Cookie.",
    "3. Full Cookie String is optional. You do not need every browser cookie if you already have auth_token and ct0.",
    "4. Those values are used once and saved only in the local twscrape DB.",
    "5. CLI fallback: create a local file like twitter_accounts.txt with one account per line.",
    f"6. Format each line as: {TWITTER_ACCOUNT_LINE_FORMAT}",
    f"7. Import accounts: twscrape add_accounts twitter_accounts.txt {TWITTER_ACCOUNT_LINE_FORMAT}",
    "8. Save login cookies: twscrape login_accounts",
    "9. If email verification appears, retry with twscrape login_accounts --manual or --email-first.",
    "10. In station settings, turn off mock mode.",
]


@dataclass(slots=True)
class HealthCheckResult:
    """Single health-check result item."""

    name: str
    status: str
    message: str


def show_style_label_from_value(value: str) -> str:
    for label, stored_value in SHOW_STYLE_LABELS.items():
        if stored_value == value:
            return label
    return "Hybrid"


def show_style_value_from_label(label: str) -> str:
    return SHOW_STYLE_LABELS.get(label, "hybrid")


def idle_format_label_from_value(value: str) -> str:
    for label, stored_value in IDLE_FORMAT_LABELS.items():
        if stored_value == value:
            return label
    return "Two Voices"


def idle_format_value_from_label(label: str) -> str:
    return IDLE_FORMAT_LABELS.get(label, "two_host")


def _http_get_json(url: str, headers: dict[str, str] | None = None, timeout: int = 10) -> dict[str, Any]:
    request = urllib_request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Could not reach {url}: {exc}") from exc

    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Endpoint {url} did not return valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"Endpoint {url} returned an unexpected JSON payload.")
    return decoded


def fetch_openai_compatible_models(api_base_url: str, api_key: str = "") -> list[str]:
    """Return model IDs from an OpenAI-compatible endpoint."""
    base_url = api_base_url.strip().rstrip("/")
    if not base_url:
        raise ValueError("API base URL is required.")

    headers = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    payload = _http_get_json(f"{base_url}/models", headers=headers)
    model_ids = [item.get("id", "").strip() for item in payload.get("data", []) if isinstance(item, dict)]
    return [model_id for model_id in model_ids if model_id]


def resolve_api_key(api_key: str, api_key_env_var: str) -> str:
    """Resolve API key from direct value or named environment variable."""
    if api_key.strip():
        return api_key.strip()
    env_var = api_key_env_var.strip()
    if not env_var:
        return ""
    return os.environ.get(env_var, "").strip()


def fetch_ollama_models(base_url: str) -> list[str]:
    """Return model names from an Ollama endpoint."""
    trimmed = base_url.strip().rstrip("/")
    if not trimmed:
        raise ValueError("Ollama base URL is required.")

    payload = _http_get_json(f"{trimmed}/api/tags")
    names = [item.get("name", "").strip() for item in payload.get("models", []) if isinstance(item, dict)]
    return [name for name in names if name]


def detect_lm_studio_endpoint(candidates: list[str] | None = None) -> tuple[str, list[str]]:
    """Return the first reachable LM Studio base URL and its models."""
    attempted: list[str] = []
    for candidate in candidates or LM_STUDIO_BASE_URL_CANDIDATES:
        try:
            models = fetch_openai_compatible_models(candidate)
            return candidate, models
        except Exception as exc:
            attempted.append(f"{candidate} -> {exc}")

    raise RuntimeError("LM Studio was not reachable on common local endpoints:\n" + "\n".join(attempted))


def provider_from_backend_label(label: str) -> str:
    """Map a GUI label to the underlying provider config value."""
    normalized = label.strip().lower()
    if normalized == "ollama":
        return "ollama"
    if normalized == "simple":
        return "simple"
    return "openai_compatible"


def backend_label_from_settings(settings: RuntimeSettings) -> str:
    """Map runtime settings to a GUI-friendly backend label."""
    if settings.llm_provider == "ollama":
        return "Ollama"
    if settings.llm_provider == "simple":
        return "Simple"
    normalized_base = settings.llm_api_base_url.strip().rstrip("/").lower()
    if normalized_base in {candidate.lower() for candidate in LM_STUDIO_BASE_URL_CANDIDATES}:
        return "LM Studio"
    return "OpenAI-Compatible"


def _describe_voice_generator(voice_generator: VoiceGenerator) -> str:
    describe_backend = getattr(voice_generator, "describe_backend", None)
    if callable(describe_backend):
        return describe_backend()
    if getattr(voice_generator, "_using_builtin_wave_fallback", False):
        return "built-in tone fallback"
    if getattr(voice_generator, "_using_windows_speech_fallback", False):
        return "Windows SpeechSynthesizer fallback"
    if getattr(voice_generator, "_pyttsx3", None) is not None:
        return "pyttsx3 fallback"
    if getattr(voice_generator, "_kokoro", None) is not None:
        return "kokoro-onnx"
    return "unknown audio mode"


async def _collect_async_iterable(async_iterable: Any) -> list[Any]:
    return [item async for item in async_iterable]


def _try_normalize_iterable(maybe_iterable: Any) -> list[Any] | None:
    if maybe_iterable is None:
        return []
    if inspect.isawaitable(maybe_iterable):
        try:
            maybe_iterable = asyncio.run(maybe_iterable)
        except Exception:
            return None
    if inspect.isasyncgen(maybe_iterable):
        try:
            return asyncio.run(_collect_async_iterable(maybe_iterable))
        except Exception:
            return None
    try:
        return list(maybe_iterable)
    except TypeError:
        return None


def _detect_twscrape_account_count(api: Any) -> int | None:
    pool = getattr(api, "pool", None)
    if pool is None:
        return None

    for method_name in ("accounts_info", "accounts", "get_all"):
        method = getattr(pool, method_name, None)
        if not callable(method):
            continue
        try:
            result = method()
        except Exception:
            continue

        normalized = _try_normalize_iterable(result)
        if normalized is None:
            continue
        return len(normalized)

    return None


def _check_llm(settings: RuntimeSettings) -> HealthCheckResult:
    if settings.llm_provider == "simple":
        return HealthCheckResult("LLM", "pass", "Simple rewriter selected. No external LLM connection required.")

    if settings.llm_provider == "openai_compatible":
        try:
            models = fetch_openai_compatible_models(
                settings.llm_api_base_url,
                resolve_api_key(settings.llm_api_key, settings.llm_api_key_env_var),
            )
        except Exception as exc:
            return HealthCheckResult("LLM", "fail", str(exc))

        if settings.llm_api_model and settings.llm_api_model not in models:
            preview = ", ".join(models[:5]) if models else "none"
            return HealthCheckResult(
                "LLM",
                "fail",
                f"Selected model '{settings.llm_api_model}' was not listed by the server. Available: {preview}",
            )
        preview = ", ".join(models[:5]) if models else "none"
        return HealthCheckResult("LLM", "pass", f"OpenAI-compatible endpoint reachable. Models: {preview}")

    try:
        models = fetch_ollama_models(settings.ollama_base_url)
    except Exception as exc:
        return HealthCheckResult("LLM", "fail", str(exc))

    if settings.ollama_model and settings.ollama_model not in models:
        preview = ", ".join(models[:5]) if models else "none"
        return HealthCheckResult(
            "LLM",
            "fail",
            f"Selected Ollama model '{settings.ollama_model}' was not listed by the server. Available: {preview}",
        )
    preview = ", ".join(models[:5]) if models else "none"
    return HealthCheckResult("LLM", "pass", f"Ollama endpoint reachable. Models: {preview}")


def _check_audio(settings: RuntimeSettings) -> HealthCheckResult:
    try:
        voice_generator = VoiceGenerator()
        sample = voice_generator.generate("Health check audio sample.", settings.anchor_voice_id)
    except Exception as exc:
        return HealthCheckResult("Audio", "fail", f"Audio generation failed: {exc}")

    mode = _describe_voice_generator(voice_generator)
    return HealthCheckResult("Audio", "pass", f"Audio generation works via {mode}. Sample: {sample.name}")


def _check_music(settings: RuntimeSettings) -> HealthCheckResult:
    if not settings.use_music:
        return HealthCheckResult("Music", "pass", "Music disabled in settings.")

    music_path = config.get_project_root() / settings.music_file
    if not music_path.exists():
        return HealthCheckResult("Music", "warn", f"Music is enabled but file is missing: {music_path}")

    try:
        importlib.import_module("pygame")
    except Exception:
        return HealthCheckResult(
            "Music",
            "warn",
            f"Music file exists at {music_path}, but pygame is not installed so idle music will stay disabled.",
        )

    return HealthCheckResult("Music", "pass", f"Music file is present and pygame is available: {music_path}")


def _check_twitter(settings: RuntimeSettings) -> HealthCheckResult:
    if settings.use_mock_twitter:
        return HealthCheckResult("Twitter", "pass", "Mock Twitter mode is enabled.")

    try:
        twscrape_module = importlib.import_module("twscrape")
    except ImportError:
        return HealthCheckResult(
            "Twitter",
            "fail",
            "twscrape is not installed. Install requirements and import accounts before disabling mock mode.",
        )

    try:
        api = create_twscrape_api()
    except Exception as exc:
        return HealthCheckResult("Twitter", "fail", f"twscrape could not initialize: {exc}")

    account_count = _detect_twscrape_account_count(api)
    if account_count == 0:
        return HealthCheckResult(
            "Twitter",
            "fail",
            (
                "twscrape is installed, but no saved accounts were detected in "
                f"{get_twitter_db_path()}. Use the launcher's Import Session Cookie button "
                "or add_accounts/login_accounts first."
            ),
        )
    if account_count is None:
        return HealthCheckResult(
            "Twitter",
            "warn",
            f"twscrape initialized against {get_twitter_db_path()}, but saved-login state could not be verified automatically.",
        )

    return HealthCheckResult(
        "Twitter",
        "pass",
        f"twscrape is configured with {account_count} saved account(s) in {get_twitter_db_path()}.",
    )


def run_health_checks(settings: RuntimeSettings) -> list[HealthCheckResult]:
    """Run a conservative preflight across the configured subsystems."""
    return [
        _check_llm(settings),
        _check_audio(settings),
        _check_music(settings),
        _check_twitter(settings),
    ]


def run_health_checks_from_path(settings_path: Any) -> tuple[RuntimeSettings, list[str], list[HealthCheckResult]]:
    """Load settings and run health checks in one step."""
    settings, notes = load_runtime_settings(settings_path)
    return settings, notes, run_health_checks(settings)


def render_health_check_report(results: list[HealthCheckResult]) -> str:
    """Render health-check results as plain text."""
    lines = [f"[{result.status.upper()}] {result.name}: {result.message}" for result in results]
    return "\n".join(lines)


def health_check_failed(results: list[HealthCheckResult]) -> bool:
    """Return True when any health check failed."""
    return any(result.status == "fail" for result in results)
