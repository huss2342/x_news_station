"""Tests for the bounded smoke test."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from modules.runtime_settings import RuntimeSettings
from modules.smoke_test import run_smoke_test


def test_smoke_test_runs_headline_and_filler_pipelines(tmp_path: Path) -> None:
    settings = RuntimeSettings.from_current_config()
    settings.llm_provider = "simple"
    settings.use_mock_twitter = True
    settings.use_music = False
    settings.anchor_voice_id = "am_michael"
    settings.analyst_voice_id = "bf_emma"

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
        with patch("modules.smoke_test.VoiceGenerator", FakeVoiceGenerator):
            results = run_smoke_test(settings)

    names = [result.name for result in results]
    assert "Headline Pipeline" in names
    assert "Filler Pipeline" in names
    assert all(result.status != "fail" for result in results)
