"""Tests for runtime settings loading and override behavior."""

from __future__ import annotations

from pathlib import Path

from modules.runtime_settings import (
    RuntimeCliOverrides,
    apply_cli_overrides,
    create_settings_example_file,
    create_settings_file,
    load_runtime_settings,
    save_runtime_settings,
)


def test_load_runtime_settings_from_ini(tmp_path: Path) -> None:
    settings_path = tmp_path / "station_settings.ini"
    settings_path.write_text(
        "\n".join(
            [
                "[station]",
                "use_mock_twitter = false",
                "voice_id = am_eric",
                "anchor_voice_id = bf_emma",
                "analyst_voice_id = bf_isabella",
                "show_style = talk_radio",
                "idle_format = solo_host",
                "use_music = false",
                "log_level = WARNING",
                "",
                "[twitter]",
                "accounts = account1, account2",
                "fetch_interval_seconds = 120",
                "fetch_limit = 7",
                "",
                "[filler]",
                "enabled = true",
                "interval_seconds = 600",
                "topics = space updates, ai regulation",
            ]
        ),
        encoding="utf-8",
    )

    settings, _ = load_runtime_settings(settings_path)

    assert settings.use_mock_twitter is False
    assert settings.voice_id == "bf_emma"
    assert settings.anchor_voice_id == "bf_emma"
    assert settings.analyst_voice_id == "bf_isabella"
    assert settings.show_style == "talk_radio"
    assert settings.idle_format == "solo_host"
    assert settings.use_music is False
    assert settings.log_level == "WARNING"
    assert settings.twitter_accounts == ["account1", "account2"]
    assert settings.fetch_interval_seconds == 120
    assert settings.twitter_fetch_limit == 7
    assert settings.filler_topics == ["space updates", "ai regulation"]


def test_legacy_voice_id_migrates_to_anchor_and_analyst(tmp_path: Path) -> None:
    settings_path = tmp_path / "station_settings.ini"
    settings_path.write_text("[station]\nvoice_id = bf_emma\n", encoding="utf-8")
    settings, _ = load_runtime_settings(settings_path)
    assert settings.voice_id == "bf_emma"
    assert settings.anchor_voice_id == "bf_emma"
    assert settings.analyst_voice_id != ""


def test_cli_overrides_take_precedence(tmp_path: Path) -> None:
    settings_path = tmp_path / "station_settings.ini"
    settings_path.write_text("[station]\nuse_mock_twitter = false\nvoice_id = am_eric\n", encoding="utf-8")
    settings, notes = load_runtime_settings(settings_path)
    apply_cli_overrides(
        settings,
        RuntimeCliOverrides(force_mock=True, disable_music=True, voice_id="bf_isabella", log_level="DEBUG"),
        notes,
    )
    assert settings.use_mock_twitter is True
    assert settings.use_music is False
    assert settings.voice_id == "bf_isabella"
    assert settings.anchor_voice_id == "bf_isabella"
    assert settings.log_level == "DEBUG"


def test_invalid_values_fall_back_without_crashing(tmp_path: Path) -> None:
    settings_path = tmp_path / "station_settings.ini"
    settings_path.write_text(
        "\n".join(
            [
                "[station]",
                "use_mock_twitter = maybe",
                "show_style = chaos",
                "idle_format = random",
                "log_level = NOTALEVEL",
                "",
                "[llm]",
                "provider = unknown",
            ]
        ),
        encoding="utf-8",
    )
    settings, notes = load_runtime_settings(settings_path)
    assert settings.show_style in {"hybrid", "talk_radio", "straight_news"}
    assert settings.idle_format in {"two_host", "solo_host", "music_first"}
    assert any("Invalid station.show_style" in note for note in notes)
    assert any("Invalid station.idle_format" in note for note in notes)
    assert any("Invalid llm.provider" in note for note in notes)


def test_template_file_creation(tmp_path: Path) -> None:
    settings_path = tmp_path / "station_settings.ini"
    example_path = tmp_path / "station_settings.example.ini"
    assert create_settings_file(settings_path, overwrite=False) is True
    assert create_settings_example_file(example_path, overwrite=False) is True
    assert create_settings_file(settings_path, overwrite=False) is False
    assert create_settings_example_file(example_path, overwrite=False) is False
    assert "anchor_voice_id" in settings_path.read_text(encoding="utf-8")


def test_api_key_can_come_from_process_env(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "station_settings.ini"
    settings_path.write_text(
        "[llm]\nprovider = openai_compatible\napi_key =\napi_key_env_var = XNS_TEST_API_KEY\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XNS_TEST_API_KEY", "secret-test-key")
    settings, _ = load_runtime_settings(settings_path)
    assert settings.llm_provider == "openai_compatible"
    assert settings.llm_api_key == "secret-test-key"


def test_load_runtime_settings_can_skip_env_secret_injection(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "station_settings.ini"
    settings_path.write_text(
        "[llm]\nprovider = openai_compatible\napi_key =\napi_key_env_var = XNS_TEST_API_KEY\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XNS_TEST_API_KEY", "secret-test-key")
    settings, notes = load_runtime_settings(settings_path, include_env_secrets=False)
    assert settings.llm_api_key == ""
    assert not any("Loaded llm.api_key from environment variable" in note for note in notes)


def test_save_runtime_settings_round_trips_core_fields(tmp_path: Path) -> None:
    settings_path = tmp_path / "station_settings.ini"
    settings, _ = load_runtime_settings(settings_path)
    settings.use_mock_twitter = False
    settings.anchor_voice_id = "bf_emma"
    settings.analyst_voice_id = "am_eric"
    settings.voice_id = "bf_emma"
    settings.show_style = "straight_news"
    settings.idle_format = "music_first"
    settings.twitter_accounts = ["user1", "user2"]
    settings.llm_provider = "openai_compatible"
    settings.llm_api_base_url = "http://localhost:1234/v1"
    settings.llm_api_model = "qwen2.5-7b-instruct"
    settings.llm_api_key = ""
    settings.llm_api_key_env_var = ""
    settings.music_volume_idle = 0.65
    settings.music_volume_ducked = 0.15
    save_runtime_settings(settings_path, settings)
    loaded, _ = load_runtime_settings(settings_path, include_env_secrets=False)
    assert loaded.use_mock_twitter is False
    assert loaded.anchor_voice_id == "bf_emma"
    assert loaded.analyst_voice_id == "am_eric"
    assert loaded.voice_id == "bf_emma"
    assert loaded.show_style == "straight_news"
    assert loaded.idle_format == "music_first"
    assert loaded.llm_api_model == "qwen2.5-7b-instruct"
    assert loaded.music_volume_idle == 0.65
    assert loaded.music_volume_ducked == 0.15


def test_load_and_save_runtime_settings_round_trip_editorial_source_and_ui_fields(tmp_path: Path) -> None:
    settings_path = tmp_path / "station_settings.ini"
    settings_path.write_text(
        "\n".join(
            [
                "[sources]",
                "include_original_posts = true",
                "include_quote_posts = false",
                "include_replies = true",
                "include_reposts = true",
                "",
                "[editorial]",
                "segment_interval_seconds = 75",
                "candidate_lookback_minutes = 120",
                "repeat_cooldown_minutes = 20",
                "max_consecutive_same_source = 3",
                "default_rundown_strategy = discussion_heavy",
                "segment_types = quick_reset, why_it_matters, music_break",
                "",
                "[ui]",
                "theme = obsidian_console",
                "advanced_mode = true",
                "show_console = false",
            ]
        ),
        encoding="utf-8",
    )

    settings, _ = load_runtime_settings(settings_path)

    assert settings.include_original_posts is True
    assert settings.include_quote_posts is False
    assert settings.include_replies is True
    assert settings.include_reposts is True
    assert settings.editorial_segment_interval_seconds == 75
    assert settings.editorial_candidate_lookback_minutes == 120
    assert settings.editorial_repeat_cooldown_minutes == 20
    assert settings.editorial_max_consecutive_same_source == 3
    assert settings.editorial_default_rundown_strategy == "discussion_heavy"
    assert settings.editorial_segment_types == ["quick_reset", "why_it_matters", "music_break"]
    assert settings.ui_theme == "obsidian_console"
    assert settings.ui_advanced_mode is True
    assert settings.ui_show_console is False

    save_runtime_settings(settings_path, settings)
    reloaded, _ = load_runtime_settings(settings_path, include_env_secrets=False)
    assert reloaded.editorial_segment_types == ["quick_reset", "why_it_matters", "music_break"]
    assert reloaded.ui_theme == "obsidian_console"
    assert reloaded.include_replies is True
