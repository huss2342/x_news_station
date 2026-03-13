"""Tests for the radio_loop module."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from modules.news_anchor import ScriptLine
from modules.news_fetcher import TweetData
from modules.radio_loop import RadioState, RadioStation


def _build_station(tmp_path: Path, **kwargs) -> RadioStation:
    story_log_file = tmp_path / "stories.json"
    with patch("config.get_story_log_file", return_value=story_log_file):
        with patch.object(RadioStation, "_init_pygame", return_value=False):
            return RadioStation(use_music=False, **kwargs)


def test_initial_state_is_idle(tmp_path: Path) -> None:
    station = _build_station(tmp_path)
    assert station.state == RadioState.IDLE


def test_loads_story_log(tmp_path: Path) -> None:
    story_log_file = tmp_path / "stories.json"
    story_log_file.write_text(
        json.dumps(
            [
                {
                    "id": "123",
                    "username": "test",
                    "original_text": "test",
                    "rewritten_text": "test",
                    "timestamp": datetime.now().isoformat(),
                }
            ]
        ),
        encoding="utf-8",
    )
    with patch("config.get_story_log_file", return_value=story_log_file):
        with patch.object(RadioStation, "_init_pygame", return_value=False):
            station = RadioStation(use_music=False)
    assert len(station.story_log) == 1


def test_broadcast_uses_anchor_voice(tmp_path: Path) -> None:
    tweet = TweetData(id="123", username="testuser", text="Test tweet", timestamp=datetime.now())
    mock_rewriter = MagicMock()
    mock_rewriter.rewrite.return_value = "New this hour. @testuser says something happened."
    mock_voice = MagicMock()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake audio")
    mock_voice.generate.return_value = audio_path
    station = _build_station(
        tmp_path,
        rewriter=mock_rewriter,
        voice_generator=mock_voice,
        anchor_voice_id="bf_emma",
        analyst_voice_id="am_eric",
    )
    station._play_audio_file = MagicMock()
    station._broadcast([tweet])
    mock_voice.generate.assert_called_once_with(
        "New this hour. @testuser says something happened.",
        "bf_emma",
    )


def test_recap_triggers_after_interval(tmp_path: Path) -> None:
    station = _build_station(tmp_path)
    station.last_recap_time = datetime.now() - timedelta(minutes=31)
    station.recap_interval = timedelta(minutes=30)
    assert station._should_recap() is True


def test_filler_segment_uses_anchor_and_analyst_voices(tmp_path: Path) -> None:
    audio_path = tmp_path / "filler.wav"
    audio_path.write_bytes(b"fake-audio")
    mock_voice = MagicMock()
    mock_voice.generate.return_value = audio_path
    mock_rewriter = MagicMock()
    mock_rewriter.build_filler_segment.return_value = [
        ScriptLine("anchor", "While the feeds reset, AI rivalry is still driving the pace."),
        ScriptLine("analyst", "That matters because product cycles can turn quickly."),
    ]
    station = _build_station(
        tmp_path,
        rewriter=mock_rewriter,
        voice_generator=mock_voice,
        anchor_voice_id="am_michael",
        analyst_voice_id="bf_emma",
    )
    station._play_audio_file = MagicMock()
    with patch.object(station, "_next_filler_topic", return_value="AI rivalry"):
        station._filler_segment()
    assert mock_voice.generate.call_args_list[0].args[1] == "am_michael"
    assert mock_voice.generate.call_args_list[1].args[1] == "bf_emma"


def test_should_run_filler_when_interval_elapsed(tmp_path: Path) -> None:
    station = _build_station(tmp_path)
    station.filler_enabled = True
    station.filler_interval = timedelta(seconds=10)
    station.last_filler_time = datetime.now() - timedelta(seconds=11)
    assert station._should_run_filler() is True


def test_shutdown_calls_stop_music_when_enabled(tmp_path: Path) -> None:
    story_log_file = tmp_path / "stories.json"
    with patch("config.get_story_log_file", return_value=story_log_file):
        with patch.object(RadioStation, "_init_pygame", return_value=True):
            station = RadioStation(use_music=True)
            station._pygame_initialized = True
            station._stop_music = MagicMock()
            station._shutdown()
    station._stop_music.assert_called_once()


def test_play_music_restarts_if_loop_is_not_busy(tmp_path: Path) -> None:
    story_log_file = tmp_path / "stories.json"
    fake_music = MagicMock()
    fake_music.get_busy.return_value = False
    fake_pygame = MagicMock()
    fake_pygame.mixer.music = fake_music

    with patch("config.get_story_log_file", return_value=story_log_file):
        with patch.object(RadioStation, "_init_pygame", return_value=False):
            station = RadioStation(use_music=True)

    station.use_music = True
    station._pygame_initialized = True
    station._music_ready = True
    station._music_playing = True
    station._current_volume = 0.37

    with patch.dict(sys.modules, {"pygame": fake_pygame}):
        station._play_music()

    fake_music.set_volume.assert_called_with(0.37)
    fake_music.play.assert_called_once()
    assert fake_music.play.call_args.args[0] == -1


def test_parse_timestamp_normalizes_naive_and_aware_values_to_utc(tmp_path: Path) -> None:
    station = _build_station(tmp_path)

    naive = station._parse_timestamp("2026-03-13T03:09:21")
    aware = station._parse_timestamp("2026-03-13T03:09:21+00:00")

    assert naive is not None
    assert aware is not None
    assert naive.tzinfo == timezone.utc
    assert aware.tzinfo == timezone.utc


def test_broadcast_logs_aware_timestamp_without_story_prune_error(tmp_path: Path) -> None:
    tweet = TweetData(
        id="123",
        username="cirnosad",
        text="aware timestamp tweet",
        timestamp=datetime.now(timezone.utc),
    )
    mock_rewriter = MagicMock()
    mock_rewriter.rewrite.return_value = "Fresh update from the timeline."
    mock_voice = MagicMock()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake audio")
    mock_voice.generate.return_value = audio_path

    station = _build_station(
        tmp_path,
        rewriter=mock_rewriter,
        voice_generator=mock_voice,
        anchor_voice_id="am_michael",
        analyst_voice_id="bf_emma",
    )
    station._play_audio_file = MagicMock()

    station._broadcast([tweet])

    assert len(station.story_log) == 1
    assert station.story_log[0]["timestamp"].endswith("+00:00")
