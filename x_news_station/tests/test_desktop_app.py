"""Minimal GUI smoke tests for the PySide6 desktop app."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from desktop_app import DesktopApp
from modules.healthcheck import HealthCheckResult
from modules.runtime_settings import create_settings_file, load_runtime_settings


def _build_window(qtbot, tmp_path: Path) -> DesktopApp:
    settings_path = tmp_path / "station_settings.ini"
    create_settings_file(settings_path, overwrite=True)
    window = DesktopApp(settings_path)
    qtbot.addWidget(window)
    return window


def test_desktop_app_renders_navigation_and_console(qtbot, tmp_path: Path) -> None:
    window = _build_window(qtbot, tmp_path)
    window.show()
    qtbot.wait(50)

    assert window.nav_list.count() == 7
    assert window.page_stack.count() == 7
    assert window.console_dock.isHidden() is False
    assert window.windowTitle() == "X-News-Station Control Room"


def test_desktop_app_save_round_trip_new_fields(qtbot, tmp_path: Path) -> None:
    settings_path = tmp_path / "station_settings.ini"
    create_settings_file(settings_path, overwrite=True)
    window = DesktopApp(settings_path)
    qtbot.addWidget(window)

    window.accounts_edit.setText("user_a, user_b")
    window.include_replies_checkbox.setChecked(True)
    window.editorial_strategy_combo.setCurrentText("Discussion Heavy")
    window.theme_combo.setCurrentText("Obsidian Console")
    window.console_visible_checkbox.setChecked(False)

    assert window._save_settings() is True
    reloaded, _ = load_runtime_settings(settings_path, include_env_secrets=False)
    assert reloaded.twitter_accounts == ["user_a", "user_b"]
    assert reloaded.include_replies is True
    assert reloaded.editorial_default_rundown_strategy == "discussion_heavy"
    assert reloaded.ui_theme == "obsidian_console"
    assert reloaded.ui_show_console is False


def test_handle_health_report_updates_cards_and_report_view(qtbot, tmp_path: Path) -> None:
    window = _build_window(qtbot, tmp_path)
    results = [
        HealthCheckResult("LLM", "pass", "Provider reachable"),
        HealthCheckResult("Twitter", "warn", "Using mock mode"),
    ]

    window._handle_health_report(results, "LLM: PASS\nTwitter: WARN")

    assert "LLM: PASS" in window.health_report_view.toPlainText()
    assert window.health_result_cards["LLM"].value_label.text() == "PASS"
    assert window.health_result_cards["Twitter"].value_label.text() == "WARN"
