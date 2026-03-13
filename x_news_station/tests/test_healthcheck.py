"""Tests for health check helpers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from modules import healthcheck
from modules.runtime_settings import RuntimeSettings


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = (exc_type, exc, tb)


def test_provider_label_round_trip_for_lm_studio() -> None:
    settings = RuntimeSettings.from_current_config()
    settings.llm_provider = "openai_compatible"
    settings.llm_api_base_url = healthcheck.LM_STUDIO_DEFAULT_BASE_URL
    assert healthcheck.backend_label_from_settings(settings) == "LM Studio"
    assert healthcheck.provider_from_backend_label("LM Studio") == "openai_compatible"


def test_show_style_label_round_trip() -> None:
    assert healthcheck.show_style_label_from_value("talk_radio") == "Talk Radio"
    assert healthcheck.show_style_value_from_label("Straight News") == "straight_news"
    assert healthcheck.idle_format_label_from_value("two_host") == "Two Voices"
    assert healthcheck.idle_format_value_from_label("Music First") == "music_first"


def test_fetch_openai_compatible_models_parses_response() -> None:
    payload = {"data": [{"id": "model-a"}, {"id": "model-b"}]}
    with patch("modules.healthcheck.urllib_request.urlopen", return_value=_FakeResponse(payload)):
        models = healthcheck.fetch_openai_compatible_models("http://localhost:1234/v1")
    assert models == ["model-a", "model-b"]


def test_detect_lm_studio_endpoint_tries_multiple_candidates() -> None:
    attempts: list[str] = []

    def fake_fetch(base_url: str, api_key: str = "") -> list[str]:
        _ = api_key
        attempts.append(base_url)
        if base_url == "http://localhost:1234/v1":
            raise RuntimeError("down")
        return ["qwen-test"]

    with patch("modules.healthcheck.fetch_openai_compatible_models", side_effect=fake_fetch):
        base_url, models = healthcheck.detect_lm_studio_endpoint(
            ["http://localhost:1234/v1", "http://127.0.0.1:1234/v1"]
        )
    assert attempts == ["http://localhost:1234/v1", "http://127.0.0.1:1234/v1"]
    assert base_url == "http://127.0.0.1:1234/v1"
    assert models == ["qwen-test"]


def test_resolve_api_key_uses_environment(monkeypatch) -> None:
    monkeypatch.setenv("XNS_API_KEY", "secret-key")
    assert healthcheck.resolve_api_key("", "XNS_API_KEY") == "secret-key"


def test_run_health_checks_passes_for_simple_mock_mode(tmp_path: Path) -> None:
    settings = RuntimeSettings.from_current_config()
    settings.llm_provider = "simple"
    settings.use_mock_twitter = True
    settings.use_music = False
    settings.anchor_voice_id = "am_michael"
    sample_path = tmp_path / "sample.wav"
    sample_path.write_bytes(b"audio")

    class FakeVoiceGenerator:
        def __init__(self) -> None:
            self._using_builtin_wave_fallback = False
            self._using_windows_speech_fallback = True
            self._pyttsx3 = None
            self._kokoro = None

        def generate(self, text: str, voice_id: str) -> Path:
            _ = (text, voice_id)
            return sample_path

    with patch("modules.healthcheck.VoiceGenerator", FakeVoiceGenerator):
        results = healthcheck.run_health_checks(settings)

    assert [result.status for result in results] == ["pass", "pass", "pass", "pass"]
    assert "Mock Twitter mode is enabled" in results[-1].message


def test_twitter_setup_lines_reference_current_cli() -> None:
    joined = "\n".join(healthcheck.TWITTER_SETUP_LINES)
    assert "Import Session Cookie" in joined
    assert "add_accounts" in joined
    assert "login_accounts" in joined
