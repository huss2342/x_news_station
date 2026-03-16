"""PySide6 desktop app for X-News-Station."""

from __future__ import annotations

import json
import logging
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import config
from modules.audio_studio import VoiceGenerator
from modules.editorial_planner import EditorialRundownPlanner
from modules.healthcheck import (
    CURATED_FILLER_TOPICS,
    IDLE_FORMAT_LABELS,
    LLM_BACKEND_OPTIONS,
    LM_STUDIO_DEFAULT_BASE_URL,
    SHOW_STYLE_LABELS,
    TWITTER_ACCOUNT_LINE_FORMAT,
    TWITTER_SETUP_LINES,
    VOICE_OPTIONS,
    backend_label_from_settings,
    detect_lm_studio_endpoint,
    fetch_ollama_models,
    fetch_openai_compatible_models,
    idle_format_label_from_value,
    idle_format_value_from_label,
    provider_from_backend_label,
    render_health_check_report,
    resolve_api_key,
    run_health_checks,
    show_style_label_from_value,
    show_style_value_from_label,
)
from modules.news_fetcher import PreviewTweet, get_monitor
from modules.json_storage import read_json_file, write_json_file
from modules.runtime_settings import RuntimeSettings, apply_runtime_settings, load_runtime_settings, save_runtime_settings
from modules.smoke_test import run_smoke_test
from modules.twitter_setup import (
    delete_saved_twitter_account,
    get_twitter_db_path,
    import_twitter_session,
    list_saved_twitter_accounts,
    load_saved_twitter_account,
    reset_twitter_locks,
)

try:
    from PySide6.QtCore import QProcess, Qt, QTimer, QObject, QUrl, Signal
    from PySide6.QtGui import QAction, QDesktopServices, QFont, QTextCursor
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QDockWidget,
        QDoubleSpinBox,
        QFileDialog,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSlider,
        QSpinBox,
        QSplitter,
        QStackedWidget,
        QToolBar,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for the desktop app. Install requirements and relaunch.") from exc


UI_THEME_OPTIONS = {
    "Broadcast Warm": "broadcast_warm",
    "Obsidian Console": "obsidian_console",
    "Day Shift": "day_shift",
}
UI_THEME_LABELS = {value: label for label, value in UI_THEME_OPTIONS.items()}
EDITORIAL_STRATEGY_OPTIONS = {
    "Editorial": "editorial",
    "Freshness First": "freshness_first",
    "Discussion Heavy": "discussion_heavy",
}
EDITORIAL_STRATEGY_LABELS = {value: label for label, value in EDITORIAL_STRATEGY_OPTIONS.items()}


class DesktopSignals(QObject):
    """Cross-thread signals for desktop actions."""

    append_output = Signal(str)
    set_status = Signal(str)
    health_report = Signal(list, str)
    twitter_accounts = Signal(list)
    twitter_account_loaded = Signal(object)
    model_list = Signal(str, list)
    voice_preview_finished = Signal()
    refresh_dashboard = Signal()


class StatusCard(QFrame):
    """Compact readiness/status card."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.value_label = QLabel("Unknown")
        self.value_label.setObjectName("cardValue")
        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        self.detail_label.setObjectName("cardDetail")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def update_state(self, status: str, message: str) -> None:
        palette = {
            "pass": "#2d9c63",
            "warn": "#cf8b2d",
            "fail": "#d25a4b",
            "idle": "#6d717b",
        }
        self.value_label.setText(status.upper())
        self.value_label.setStyleSheet(f"color: {palette.get(status, palette['idle'])};")
        self.detail_label.setText(message)


class DesktopApp(QMainWindow):
    """Main Qt launcher and broadcast dashboard."""

    def __init__(self, settings_path: Path) -> None:
        super().__init__()
        self.project_root = config.get_project_root()
        self.settings_path = settings_path.resolve()
        self.current_settings, self.notes = load_runtime_settings(self.settings_path, include_env_secrets=False)
        self.signals = DesktopSignals()
        self.process: QProcess | None = None
        self.output_lines: list[str] = []
        self.available_filler_topics: list[str] = []
        self.saved_twitter_accounts: list[object] = []
        self.health_result_cards: dict[str, StatusCard] = {}
        self.advanced_widgets: list[QWidget] = []
        self.last_rundown_payload: dict[str, Any] = {}

        self.setWindowTitle("X-News-Station Control Room")
        self.resize(1540, 980)
        self.setMinimumSize(1240, 820)

        self._build_ui()
        self._connect_signals()
        self._load_into_form(self.current_settings)
        self._refresh_voice_status()
        self._refresh_saved_twitter_accounts()
        self._refresh_rundown_state()
        for note in self.notes:
            self._append_output(f"Settings: {note}")
        self._apply_theme(self.current_settings.ui_theme)
        self._set_advanced_mode(self.current_settings.ui_advanced_mode)
        self.console_dock.setVisible(self.current_settings.ui_show_console)
        self._refresh_dashboard_preview()

        self.rundown_timer = QTimer(self)
        self.rundown_timer.setInterval(2000)
        self.rundown_timer.timeout.connect(self._refresh_rundown_state)
        self.rundown_timer.start()

    def _connect_signals(self) -> None:
        self.signals.append_output.connect(self._append_output)
        self.signals.set_status.connect(self.status_badge.setText)
        self.signals.health_report.connect(self._handle_health_report)
        self.signals.twitter_accounts.connect(self._render_saved_twitter_accounts)
        self.signals.twitter_account_loaded.connect(self._handle_loaded_twitter_account)
        self.signals.model_list.connect(self._handle_model_list)
        self.signals.voice_preview_finished.connect(self._refresh_voice_status)
        self.signals.refresh_dashboard.connect(self._refresh_dashboard_preview)

    def _build_ui(self) -> None:
        self._build_actions()
        self._build_console_dock()
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("headerBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 14, 18, 14)
        header_layout.setSpacing(12)

        title_stack = QVBoxLayout()
        title_label = QLabel("X-News-Station Control Room")
        title_label.setObjectName("appTitle")
        subtitle_label = QLabel("Broadcast desk, editorial queue, and live diagnostics")
        subtitle_label.setObjectName("appSubtitle")
        title_stack.addWidget(title_label)
        title_stack.addWidget(subtitle_label)
        header_layout.addLayout(title_stack)
        header_layout.addStretch(1)

        self.advanced_toggle = QCheckBox("Advanced Mode")
        self.advanced_toggle.toggled.connect(self._set_advanced_mode)
        header_layout.addWidget(self.advanced_toggle)

        self.status_badge = QLabel("Ready")
        self.status_badge.setObjectName("statusBadge")
        header_layout.addWidget(self.status_badge)
        root_layout.addWidget(header)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navRail")
        self.nav_list.setFixedWidth(220)
        for page_name in [
            "Dashboard",
            "Show",
            "Sources",
            "Voices & Audio",
            "AI & Editorial",
            "Diagnostics",
            "Setup & Credentials",
        ]:
            QListWidgetItem(page_name, self.nav_list)

        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(QWidget())
        self.page_stack.addWidget(QWidget())
        self.page_stack.addWidget(QWidget())
        self.page_stack.addWidget(QWidget())
        self.page_stack.addWidget(QWidget())
        self.page_stack.addWidget(QWidget())
        self.page_stack.addWidget(QWidget())
        self.nav_list.currentRowChanged.connect(self.page_stack.setCurrentIndex)

        self.inspector_panel = QFrame()
        self.inspector_panel.setObjectName("inspectorPanel")
        self.inspector_panel.setFixedWidth(260)
        self.inspector_layout = QVBoxLayout(self.inspector_panel)
        self.inspector_layout.setContentsMargins(18, 18, 18, 18)
        self.inspector_layout.setSpacing(14)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.nav_list)

        center_widget = QWidget()
        center_layout = QHBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self.page_stack, 1)
        center_layout.addWidget(self.inspector_panel)
        splitter.addWidget(center_widget)
        splitter.setStretchFactor(1, 1)
        root_layout.addWidget(splitter, 1)

        self.setCentralWidget(root)
        self._build_pages()
        self.nav_list.setCurrentRow(0)

    def _build_actions(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.setObjectName("mainToolbar")
        self.addToolBar(toolbar)

        save_action = QAction("Save Settings", self)
        save_action.triggered.connect(self._save_settings)
        toolbar.addAction(save_action)

        self.start_action = QAction("Start Station", self)
        self.start_action.triggered.connect(self._start_station)
        toolbar.addAction(self.start_action)

        self.stop_action = QAction("Stop Station", self)
        self.stop_action.triggered.connect(self._stop_station)
        self.stop_action.setEnabled(False)
        toolbar.addAction(self.stop_action)

        health_action = QAction("Run Health Check", self)
        health_action.triggered.connect(self._run_health_check)
        toolbar.addAction(health_action)

        smoke_action = QAction("Run Smoke Test", self)
        smoke_action.triggered.connect(self._run_smoke_test)
        toolbar.addAction(smoke_action)

        refetch_action = QAction("Refetch Stories", self)
        refetch_action.triggered.connect(self._refetch_stories)
        toolbar.addAction(refetch_action)

        ping_action = QAction("Ping Provider", self)
        ping_action.triggered.connect(self._ping_provider)
        toolbar.addAction(ping_action)

        preview_action = QAction("Preview Voices", self)
        preview_action.triggered.connect(self._preview_voices)
        toolbar.addAction(preview_action)

    def _build_console_dock(self) -> None:
        self.console_dock = QDockWidget("Diagnostics Console", self)
        self.console_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        dock_root = QWidget()
        dock_layout = QVBoxLayout(dock_root)
        dock_layout.setContentsMargins(10, 10, 10, 10)
        dock_layout.setSpacing(8)

        controls = QHBoxLayout()
        self.console_filter = QLineEdit()
        self.console_filter.setPlaceholderText("Filter visible log lines")
        self.console_filter.textChanged.connect(self._refresh_console_view)
        controls.addWidget(self.console_filter, 1)

        self.console_pause = QCheckBox("Pause Autoscroll")
        controls.addWidget(self.console_pause)

        clear_button = QPushButton("Clear View")
        clear_button.clicked.connect(self._clear_console_view)
        controls.addWidget(clear_button)

        copy_button = QPushButton("Copy Visible")
        copy_button.clicked.connect(self._copy_console_view)
        controls.addWidget(copy_button)

        open_log_button = QPushButton("Open Log File")
        open_log_button.clicked.connect(self._open_log_file)
        controls.addWidget(open_log_button)
        dock_layout.addLayout(controls)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.console.document().setDefaultFont(QFont("Consolas", 10))
        dock_layout.addWidget(self.console, 1)
        self.console_dock.setWidget(dock_root)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.console_dock)

    def _register_advanced_widget(self, widget: QWidget) -> QWidget:
        self.advanced_widgets.append(widget)
        return widget

    def _build_page_shell(self, page: QWidget, title: str, subtitle: str) -> QVBoxLayout:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return layout

    def _build_group(self, title: str, advanced: bool = False) -> tuple[QGroupBox, QGridLayout]:
        group = QGroupBox(title)
        layout = QGridLayout(group)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)
        layout.setColumnStretch(1, 1)
        if advanced:
            self._register_advanced_widget(group)
        return group, layout

    def _add_grid_row(self, layout: QGridLayout, row: int, label: str, widget: QWidget) -> None:
        title = QLabel(label)
        title.setObjectName("fieldLabel")
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(title, row, 0)
        layout.addWidget(widget, row, 1)

    def _make_combo(self, values: list[str], editable: bool = False) -> QComboBox:
        combo = QComboBox()
        combo.addItems(values)
        combo.setEditable(editable)
        combo.setInsertPolicy(QComboBox.NoInsert)
        return combo

    def _build_slider_row(self, tooltip: str) -> tuple[QWidget, QSlider, QLabel]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setSingleStep(1)
        slider.setPageStep(5)
        value_label = QLabel("0%")
        value_label.setMinimumWidth(44)
        layout.addWidget(slider, 1)
        layout.addWidget(value_label)
        row.setToolTip(tooltip)
        return row, slider, value_label

    def _set_selectable_items(
        self,
        list_widget: QListWidget,
        items: list[str],
        selected_items: list[str],
        labels: dict[str, str] | None = None,
    ) -> None:
        selected_lookup = set(selected_items)
        list_widget.clear()
        for value in items:
            item = QListWidgetItem((labels or {}).get(value, value))
            item.setData(Qt.UserRole, value)
            list_widget.addItem(item)
            if value in selected_lookup:
                item.setSelected(True)

    def _selected_list_values(self, list_widget: QListWidget) -> list[str]:
        values: list[str] = []
        for item in list_widget.selectedItems():
            values.append(str(item.data(Qt.UserRole) or item.text()))
        return values

    def _parse_positive_int(self, value: int, label: str) -> int:
        if int(value) <= 0:
            raise ValueError(f"{label} must be a positive integer.")
        return int(value)

    def _parse_positive_float(self, value: float, label: str) -> float:
        if float(value) <= 0:
            raise ValueError(f"{label} must be a positive number.")
        return float(value)

    def _parse_csv(self, value: str, label: str) -> list[str]:
        items = [item.strip() for item in value.split(",") if item.strip()]
        if not items:
            raise ValueError(f"{label} cannot be empty.")
        return items

    def _slider_percent_to_unit(self, slider: QSlider) -> float:
        return max(0.0, min(1.0, round(slider.value() / 100.0, 2)))

    def _update_volume_labels(self) -> None:
        idle_value = self.music_volume_idle_slider.value()
        ducked_value = min(self.music_volume_ducked_slider.value(), idle_value)
        if ducked_value != self.music_volume_ducked_slider.value():
            self.music_volume_ducked_slider.setValue(ducked_value)
        self.music_volume_idle_value.setText(f"{idle_value}%")
        self.music_volume_ducked_value.setText(f"{ducked_value}%")

    def _build_pages(self) -> None:
        self._build_dashboard_page(self.page_stack.widget(0))
        self._build_show_page(self.page_stack.widget(1))
        self._build_sources_page(self.page_stack.widget(2))
        self._build_audio_page(self.page_stack.widget(3))
        self._build_ai_page(self.page_stack.widget(4))
        self._build_diagnostics_page(self.page_stack.widget(5))
        self._build_setup_page(self.page_stack.widget(6))
        self._build_inspector()

    def _build_dashboard_page(self, page: QWidget) -> None:
        layout = self._build_page_shell(
            page,
            "Dashboard",
            "Monitor live readiness, see what is on air, and inspect the next editorial segments before they play.",
        )

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        for card_name in ("LLM", "Twitter", "Audio", "Music"):
            card = StatusCard(card_name)
            card.update_state("idle", "Not checked yet")
            cards_row.addWidget(card, 1)
            self.health_result_cards[card_name] = card
        layout.addLayout(cards_row)

        content_row = QHBoxLayout()
        content_row.setSpacing(14)

        now_group = QGroupBox("Now Playing")
        now_layout = QVBoxLayout(now_group)
        now_layout.setContentsMargins(14, 14, 14, 14)
        now_layout.setSpacing(8)
        self.station_state_value = QLabel("Idle")
        self.station_state_value.setObjectName("panelValue")
        self.now_playing_title = QLabel("Waiting for the first segment")
        self.now_playing_title.setObjectName("nowPlayingTitle")
        self.now_playing_body = QLabel(
            "When the engine starts, the editorial planner will publish the current segment and the next queue here."
        )
        self.now_playing_body.setWordWrap(True)
        self.now_playing_body.setObjectName("nowPlayingBody")
        self.candidate_pool_value = QLabel("Candidate pool: 0 stories")
        self.candidate_pool_value.setObjectName("mutedLabel")
        now_layout.addWidget(self.station_state_value)
        now_layout.addWidget(self.now_playing_title)
        now_layout.addWidget(self.now_playing_body)
        now_layout.addWidget(self.candidate_pool_value)
        content_row.addWidget(now_group, 1)

        queue_group = QGroupBox("Upcoming Rundown")
        queue_layout = QVBoxLayout(queue_group)
        queue_layout.setContentsMargins(14, 14, 14, 14)
        queue_layout.setSpacing(8)
        self.rundown_preview_list = QListWidget()
        self.rundown_preview_list.setSelectionMode(QAbstractItemView.NoSelection)
        queue_layout.addWidget(self.rundown_preview_list)
        content_row.addWidget(queue_group, 1)
        layout.addLayout(content_row)

        self.dashboard_summary = QLabel("")
        self.dashboard_summary.setObjectName("mutedLabel")
        self.dashboard_summary.setWordWrap(True)
        layout.addWidget(self.dashboard_summary)

    def _build_show_page(self, page: QWidget) -> None:
        layout = self._build_page_shell(
            page,
            "Show",
            "Shape the station format, timing, and headline flow without editing raw INI fields by hand.",
        )

        basics_group, basics = self._build_group("Station Basics")
        self.use_mock_checkbox = QCheckBox("Use Mock Twitter")
        self.use_music_checkbox = QCheckBox("Enable Background Music")
        basics.addWidget(self.use_mock_checkbox, 0, 0, 1, 2)
        basics.addWidget(self.use_music_checkbox, 1, 0, 1, 2)

        self.show_style_combo = self._make_combo(list(SHOW_STYLE_LABELS.keys()))
        self.idle_format_combo = self._make_combo(list(IDLE_FORMAT_LABELS.keys()))
        self.accounts_edit = QLineEdit()
        self.accounts_edit.setPlaceholderText("elonmusk, sama, karpathy")
        self.mock_batch_spin = QSpinBox()
        self.mock_batch_spin.setRange(1, 500)

        self._add_grid_row(basics, 2, "Show Style", self.show_style_combo)
        self._add_grid_row(basics, 3, "Idle Format", self.idle_format_combo)
        self._add_grid_row(basics, 4, "Twitter Accounts", self.accounts_edit)
        self._add_grid_row(basics, 5, "Mock Tweet Batch Size", self.mock_batch_spin)
        self._register_advanced_widget(self.mock_batch_spin)
        layout.addWidget(basics_group)

        timing_group, timing = self._build_group("Broadcast Timing")
        self.fetch_interval_spin = QSpinBox()
        self.fetch_interval_spin.setRange(5, 86400)
        self.recap_interval_spin = QSpinBox()
        self.recap_interval_spin.setRange(30, 86400)
        self.filler_enabled_checkbox = QCheckBox("Enable AI Filler Segments")
        self.filler_interval_spin = QSpinBox()
        self.filler_interval_spin.setRange(30, 86400)

        self._add_grid_row(timing, 0, "Fetch Interval (s)", self.fetch_interval_spin)
        self._add_grid_row(timing, 1, "Recap Interval (s)", self.recap_interval_spin)
        timing.addWidget(self.filler_enabled_checkbox, 2, 0, 1, 2)
        self._add_grid_row(timing, 3, "Filler Interval (s)", self.filler_interval_spin)
        layout.addWidget(timing_group)

        filler_group = QGroupBox("Filler and Discussion Topics")
        filler_layout = QVBoxLayout(filler_group)
        filler_layout.setContentsMargins(14, 14, 14, 14)
        filler_layout.setSpacing(8)
        self.filler_topic_list = QListWidget()
        self.filler_topic_list.setSelectionMode(QAbstractItemView.MultiSelection)
        filler_buttons = QHBoxLayout()
        select_all_filler = QPushButton("Select All")
        select_all_filler.clicked.connect(
            lambda: [self.filler_topic_list.item(index).setSelected(True) for index in range(self.filler_topic_list.count())]
        )
        clear_filler = QPushButton("Clear")
        clear_filler.clicked.connect(self.filler_topic_list.clearSelection)
        remove_filler = QPushButton("Remove Highlighted")
        remove_filler.clicked.connect(self._remove_highlighted_filler_topics)
        filler_buttons.addWidget(select_all_filler)
        filler_buttons.addWidget(clear_filler)
        filler_buttons.addWidget(remove_filler)
        filler_buttons.addStretch(1)

        custom_topic_row = QWidget()
        custom_topic_layout = QHBoxLayout(custom_topic_row)
        custom_topic_layout.setContentsMargins(0, 0, 0, 0)
        custom_topic_layout.setSpacing(8)
        self.new_filler_topic_edit = QLineEdit()
        self.new_filler_topic_edit.setPlaceholderText("Add a custom filler topic")
        add_topic_button = QPushButton("Add Topic")
        add_topic_button.clicked.connect(self._add_custom_filler_topic)
        custom_topic_layout.addWidget(self.new_filler_topic_edit, 1)
        custom_topic_layout.addWidget(add_topic_button)
        filler_layout.addWidget(self.filler_topic_list)
        filler_layout.addLayout(filler_buttons)
        filler_layout.addWidget(custom_topic_row)
        layout.addWidget(filler_group)

        summary_group = QGroupBox("Format Notes")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(14, 14, 14, 14)
        self.show_notes = QLabel("")
        self.show_notes.setWordWrap(True)
        self.show_notes.setObjectName("mutedLabel")
        summary_layout.addWidget(self.show_notes)
        layout.addWidget(summary_group)

    def _build_sources_page(self, page: QWidget) -> None:
        layout = self._build_page_shell(
            page,
            "Sources",
            "Choose which post types enter the editorial pool and manage project-local Twitter sessions safely.",
        )
        post_group, post_grid = self._build_group("Editorial Source Mix")
        source_help = QLabel(
            "These filters directly affect whether fetched posts are eligible to air. If posts are coming back from X but nothing plays, this is one of the first places to check."
        )
        source_help.setWordWrap(True)
        source_help.setObjectName("mutedLabel")
        post_grid.addWidget(source_help, 0, 0, 1, 2)
        self.include_original_checkbox = QCheckBox("Include Original Posts")
        self.include_quote_checkbox = QCheckBox("Include Quote Posts")
        self.include_replies_checkbox = QCheckBox("Include Replies")
        self.include_reposts_checkbox = QCheckBox("Include Reposts")
        post_grid.addWidget(self.include_original_checkbox, 1, 0, 1, 2)
        post_grid.addWidget(self.include_quote_checkbox, 2, 0, 1, 2)
        post_grid.addWidget(self.include_replies_checkbox, 3, 0, 1, 2)
        post_grid.addWidget(self.include_reposts_checkbox, 4, 0, 1, 2)
        self._register_advanced_widget(self.include_replies_checkbox)
        self._register_advanced_widget(self.include_reposts_checkbox)
        layout.addWidget(post_group)

        cache_group = QGroupBox("Seen Story Cache")
        cache_layout = QVBoxLayout(cache_group)
        cache_layout.setContentsMargins(14, 14, 14, 14)
        cache_layout.setSpacing(8)
        self.seen_cache_label = QLabel("")
        self.seen_cache_label.setWordWrap(True)
        self.seen_cache_label.setObjectName("mutedLabel")
        cache_buttons = QHBoxLayout()
        for label, handler in (
            ("Refetch Stories", self._refetch_stories),
            ("Reset Seen Cache", self._reset_seen_cache),
            ("Open Seen IDs", self._open_seen_ids_file),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            cache_buttons.addWidget(button)
        cache_buttons.addStretch(1)
        cache_layout.addWidget(self.seen_cache_label)
        cache_layout.addLayout(cache_buttons)
        layout.addWidget(cache_group)

    def _build_audio_page(self, page: QWidget) -> None:
        layout = self._build_page_shell(
            page,
            "Voices & Audio",
            "Tune the broadcast voices and the background music bed without leaving the control room.",
        )

        voices_group, voices_grid = self._build_group("Voice Desk")
        self.anchor_voice_combo = self._make_combo(VOICE_OPTIONS, editable=True)
        self.analyst_voice_combo = self._make_combo(VOICE_OPTIONS, editable=True)
        self._add_grid_row(voices_grid, 0, "Anchor Voice", self.anchor_voice_combo)
        self._add_grid_row(voices_grid, 1, "Analyst Voice", self.analyst_voice_combo)
        preview_button = QPushButton("Preview Voices")
        preview_button.clicked.connect(self._preview_voices)
        voices_grid.addWidget(preview_button, 2, 1, alignment=Qt.AlignLeft)
        self.voice_status_label = QLabel("")
        self.voice_status_label.setObjectName("mutedLabel")
        self.voice_status_label.setWordWrap(True)
        voices_grid.addWidget(self.voice_status_label, 3, 0, 1, 2)
        layout.addWidget(voices_group)

        music_group, music_grid = self._build_group("Music Bed and Playback")
        music_file_row = QWidget()
        music_file_layout = QHBoxLayout(music_file_row)
        music_file_layout.setContentsMargins(0, 0, 0, 0)
        music_file_layout.setSpacing(8)
        self.music_file_edit = QLineEdit()
        self.music_file_edit.setPlaceholderText("assets/music/background.mp3")
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self._browse_music_file)
        music_file_layout.addWidget(self.music_file_edit, 1)
        music_file_layout.addWidget(browse_button)
        self._add_grid_row(music_grid, 0, "Music File", music_file_row)

        idle_row, self.music_volume_idle_slider, self.music_volume_idle_value = self._build_slider_row("Music Volume")
        ducked_row, self.music_volume_ducked_slider, self.music_volume_ducked_value = self._build_slider_row(
            "Speech Duck Level"
        )
        self.music_volume_idle_slider.valueChanged.connect(self._update_volume_labels)
        self.music_volume_ducked_slider.valueChanged.connect(self._update_volume_labels)
        self._add_grid_row(music_grid, 1, "Music Volume", idle_row)
        self._add_grid_row(music_grid, 2, "Speech Duck Level", ducked_row)
        layout.addWidget(music_group)

    def _build_ai_page(self, page: QWidget) -> None:
        layout = self._build_page_shell(
            page,
            "AI & Editorial",
            "Set the model backend, editorial pacing, and the segment types the planner can choose from when the feed quiets down.",
        )

        provider_group, provider_grid = self._build_group("Provider")
        provider_actions = QWidget()
        provider_actions_layout = QHBoxLayout(provider_actions)
        provider_actions_layout.setContentsMargins(0, 0, 0, 0)
        provider_actions_layout.setSpacing(8)
        for label, handler in (
            ("Use LM Studio Preset", self._apply_lm_studio_preset),
            ("Detect LM Studio", self._detect_lm_studio),
            ("Refresh Models", self._refresh_models),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            provider_actions_layout.addWidget(button)
            if label == "Refresh Models":
                self.refresh_models_button = button
        provider_actions_layout.addStretch(1)
        provider_grid.addWidget(provider_actions, 0, 0, 1, 2)

        self.llm_backend_combo = self._make_combo(LLM_BACKEND_OPTIONS)
        self.llm_backend_combo.currentTextChanged.connect(self._update_provider_fields)
        self.ollama_model_combo = self._make_combo([], editable=True)
        self.ollama_base_url_edit = QLineEdit()
        self.api_base_url_edit = QLineEdit()
        self.api_model_combo = self._make_combo([], editable=True)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_env_edit = QLineEdit()
        self.max_retries_spin = QSpinBox()
        self.max_retries_spin.setRange(1, 100)
        self.backoff_factor_spin = QDoubleSpinBox()
        self.backoff_factor_spin.setRange(0.1, 30.0)
        self.backoff_factor_spin.setDecimals(2)
        self.backoff_factor_spin.setSingleStep(0.1)

        self._add_grid_row(provider_grid, 1, "LLM Backend", self.llm_backend_combo)
        self._add_grid_row(provider_grid, 2, "Ollama Model", self.ollama_model_combo)
        self._add_grid_row(provider_grid, 3, "Ollama Base URL", self.ollama_base_url_edit)
        self._add_grid_row(provider_grid, 4, "API Base URL", self.api_base_url_edit)
        self._add_grid_row(provider_grid, 5, "API Model", self.api_model_combo)
        self._add_grid_row(provider_grid, 6, "API Key", self.api_key_edit)
        self._add_grid_row(provider_grid, 7, "API Key Env Var", self.api_key_env_edit)
        self._add_grid_row(provider_grid, 8, "Max Retries", self.max_retries_spin)
        self._add_grid_row(provider_grid, 9, "Backoff Factor", self.backoff_factor_spin)
        self._register_advanced_widget(self.api_key_env_edit)
        self._register_advanced_widget(self.max_retries_spin)
        self._register_advanced_widget(self.backoff_factor_spin)
        layout.addWidget(provider_group)

        editorial_group, editorial_grid = self._build_group("Editorial Planner")
        self.editorial_strategy_combo = self._make_combo(list(EDITORIAL_STRATEGY_OPTIONS.keys()))
        self.segment_interval_spin = QSpinBox()
        self.segment_interval_spin.setRange(15, 3600)
        self.candidate_lookback_spin = QSpinBox()
        self.candidate_lookback_spin.setRange(5, 1440)
        self.repeat_cooldown_spin = QSpinBox()
        self.repeat_cooldown_spin.setRange(1, 1440)
        self.max_same_source_spin = QSpinBox()
        self.max_same_source_spin.setRange(1, 20)
        self._add_grid_row(editorial_grid, 0, "Rundown Strategy", self.editorial_strategy_combo)
        self._add_grid_row(editorial_grid, 1, "Segment Interval (s)", self.segment_interval_spin)
        self._add_grid_row(editorial_grid, 2, "Candidate Lookback (min)", self.candidate_lookback_spin)
        self._add_grid_row(editorial_grid, 3, "Repeat Cooldown (min)", self.repeat_cooldown_spin)
        self._add_grid_row(editorial_grid, 4, "Max Consecutive Same Source", self.max_same_source_spin)
        layout.addWidget(editorial_group)

        segment_group = QGroupBox("Allowed Segment Types")
        segment_layout = QVBoxLayout(segment_group)
        segment_layout.setContentsMargins(14, 14, 14, 14)
        self.segment_type_list = QListWidget()
        self.segment_type_list.setSelectionMode(QAbstractItemView.MultiSelection)
        segment_buttons = QHBoxLayout()
        select_all_segments = QPushButton("Select All")
        select_all_segments.clicked.connect(
            lambda: [self.segment_type_list.item(index).setSelected(True) for index in range(self.segment_type_list.count())]
        )
        reset_segments = QPushButton("Reset Defaults")
        reset_segments.clicked.connect(
            lambda: self._set_selectable_items(
                self.segment_type_list,
                list(config.EDITORIAL_SEGMENT_TYPE_LABELS),
                list(config.EDITORIAL_SEGMENT_TYPES),
                config.EDITORIAL_SEGMENT_TYPE_LABELS,
            )
        )
        segment_buttons.addWidget(select_all_segments)
        segment_buttons.addWidget(reset_segments)
        segment_buttons.addStretch(1)
        segment_layout.addWidget(self.segment_type_list)
        segment_layout.addLayout(segment_buttons)
        layout.addWidget(segment_group)

    def _build_diagnostics_page(self, page: QWidget) -> None:
        layout = self._build_page_shell(
            page,
            "Diagnostics",
            "Keep the terminal visible, inspect the current runtime paths, and open the generated files that drive the dashboard.",
        )

        logging_group, logging_grid = self._build_group("Logging")
        self.log_level_combo = self._make_combo(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_file_edit = QLineEdit()
        self._add_grid_row(logging_grid, 0, "Log Level", self.log_level_combo)
        self._add_grid_row(logging_grid, 1, "Log File", self.log_file_edit)
        layout.addWidget(logging_group)

        paths_group = QGroupBox("Runtime Paths")
        paths_layout = QVBoxLayout(paths_group)
        paths_layout.setContentsMargins(14, 14, 14, 14)
        paths_layout.setSpacing(6)
        self.paths_summary = QLabel("")
        self.paths_summary.setWordWrap(True)
        self.paths_summary.setObjectName("mutedLabel")
        paths_layout.addWidget(self.paths_summary)
        layout.addWidget(paths_group)

        report_group = QGroupBox("Latest Health or Smoke Report")
        report_layout = QVBoxLayout(report_group)
        report_layout.setContentsMargins(14, 14, 14, 14)
        self.health_report_view = QPlainTextEdit()
        self.health_report_view.setReadOnly(True)
        report_layout.addWidget(self.health_report_view)
        layout.addWidget(report_group, 1)

        diagnostics_actions = QHBoxLayout()
        for label, handler in (
            ("Open Log File", self._open_log_file),
            ("Open Accounts DB Folder", self._open_accounts_folder),
            ("Open Rundown State", self._open_rundown_state_file),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            diagnostics_actions.addWidget(button)
        diagnostics_actions.addStretch(1)
        layout.addLayout(diagnostics_actions)

    def _build_setup_page(self, page: QWidget) -> None:
        layout = self._build_page_shell(
            page,
            "Setup & Credentials",
            "One-time Twitter session import and saved account management. Run these steps during initial setup, not during daily operation.",
        )

        import_group, import_grid = self._build_group("Twitter Session Import")
        self.twitter_username_edit = QLineEdit()
        self.twitter_cookie_string_edit = QLineEdit()
        self.twitter_cookie_string_edit.setPlaceholderText("Optional: paste a full cookie string if you already have one")
        self.twitter_auth_token_edit = QLineEdit()
        self.twitter_auth_token_edit.setEchoMode(QLineEdit.Password)
        self.twitter_ct0_edit = QLineEdit()
        self.twitter_ct0_edit.setEchoMode(QLineEdit.Password)
        self._add_grid_row(import_grid, 0, "Twitter Username", self.twitter_username_edit)
        self._add_grid_row(import_grid, 1, "Full Cookie String (Optional)", self.twitter_cookie_string_edit)
        self._add_grid_row(import_grid, 2, "auth_token", self.twitter_auth_token_edit)
        self._add_grid_row(import_grid, 3, "ct0", self.twitter_ct0_edit)
        self._register_advanced_widget(self.twitter_cookie_string_edit)

        import_actions = QWidget()
        import_actions_layout = QHBoxLayout(import_actions)
        import_actions_layout.setContentsMargins(0, 0, 0, 0)
        import_actions_layout.setSpacing(8)
        for label, handler in (
            ("Import Session Cookie", self._import_twitter_session),
            ("Clear Secret Fields", self._clear_twitter_secret_fields),
            ("Show Setup Steps", self._show_twitter_setup),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            import_actions_layout.addWidget(button)
        import_actions_layout.addStretch(1)
        import_grid.addWidget(import_actions, 4, 0, 1, 2)
        layout.addWidget(import_group)

        saved_group = QGroupBox("Saved Accounts")
        saved_layout = QVBoxLayout(saved_group)
        saved_layout.setContentsMargins(14, 14, 14, 14)
        saved_layout.setSpacing(10)
        self.twitter_account_status = QLabel("No saved Twitter accounts loaded")
        self.twitter_account_status.setObjectName("mutedLabel")
        self.twitter_account_status.setWordWrap(True)
        self.saved_twitter_list = QListWidget()
        self.saved_twitter_list.setSelectionMode(QAbstractItemView.SingleSelection)
        saved_buttons = QHBoxLayout()
        for label, handler in (
            ("Refresh Saved Accounts", self._refresh_saved_twitter_accounts),
            ("Load Selected", self._load_selected_twitter_account),
            ("Delete Selected", self._delete_selected_twitter_account),
            ("Reset Locks", self._reset_saved_twitter_locks),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            saved_buttons.addWidget(button)
        saved_layout.addWidget(self.twitter_account_status)
        saved_layout.addWidget(self.saved_twitter_list)
        saved_layout.addLayout(saved_buttons)
        layout.addWidget(saved_group)

    def _build_inspector(self) -> None:
        title = QLabel("Control Panel")
        title.setObjectName("pageTitle")
        self.inspector_layout.addWidget(title)

        summary_group = QGroupBox("Station Snapshot")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(14, 14, 14, 14)
        summary_layout.setSpacing(6)
        self.config_path_label = QLabel(str(self.settings_path))
        self.config_path_label.setWordWrap(True)
        self.config_path_label.setObjectName("mutedLabel")
        self.provider_summary = QLabel("")
        self.provider_summary.setWordWrap(True)
        self.provider_summary.setObjectName("mutedLabel")
        self.sources_summary = QLabel("")
        self.sources_summary.setWordWrap(True)
        self.sources_summary.setObjectName("mutedLabel")
        self.runtime_summary = QLabel("")
        self.runtime_summary.setWordWrap(True)
        self.runtime_summary.setObjectName("mutedLabel")
        summary_layout.addWidget(QLabel("Config File"))
        summary_layout.addWidget(self.config_path_label)
        summary_layout.addWidget(QLabel("Provider"))
        summary_layout.addWidget(self.provider_summary)
        summary_layout.addWidget(QLabel("Source Mix"))
        summary_layout.addWidget(self.sources_summary)
        summary_layout.addWidget(QLabel("Runtime"))
        summary_layout.addWidget(self.runtime_summary)
        self.inspector_layout.addWidget(summary_group)

        ui_group = QGroupBox("Desktop Preferences")
        ui_layout = QGridLayout(ui_group)
        ui_layout.setContentsMargins(14, 14, 14, 14)
        ui_layout.setHorizontalSpacing(10)
        ui_layout.setVerticalSpacing(10)
        ui_layout.setColumnStretch(1, 1)
        self.theme_combo = self._make_combo(list(UI_THEME_OPTIONS.keys()))
        self.theme_combo.currentTextChanged.connect(lambda _label: self._apply_theme(self._selected_theme_value()))
        self.console_visible_checkbox = QCheckBox("Show Embedded Console")
        self.console_visible_checkbox.toggled.connect(self.console_dock.setVisible)
        self._add_grid_row(ui_layout, 0, "Theme", self.theme_combo)
        ui_layout.addWidget(self.console_visible_checkbox, 1, 0, 1, 2)
        self.inspector_layout.addWidget(ui_group)

        self.inspector_layout.addStretch(1)

    def _selected_theme_value(self) -> str:
        return UI_THEME_OPTIONS.get(self.theme_combo.currentText(), "broadcast_warm")

    def _set_advanced_mode(self, enabled: bool) -> None:
        for widget in self.advanced_widgets:
            widget.setVisible(bool(enabled))
        self.current_settings.ui_advanced_mode = bool(enabled)

    def _apply_theme(self, theme: str) -> None:
        style_map = {
            "broadcast_warm": """
                QWidget { background: #15110f; color: #f1e8dc; font-family: 'Segoe UI', 'Noto Sans', 'DejaVu Sans'; }
                QMainWindow { background: #15110f; }
                #headerBar, QToolBar#mainToolbar { background: #211815; border-bottom: 1px solid #43312a; }
                #appTitle { font-size: 24px; font-weight: 700; color: #fff6ed; }
                #appSubtitle, QLabel#mutedLabel, #pageSubtitle { color: #c4b4a6; }
                #pageTitle { font-size: 20px; font-weight: 700; color: #fff2e8; }
                #navRail { background: #1c1512; border-right: 1px solid #3c2b25; padding: 8px; }
                #navRail::item { padding: 12px 14px; margin: 3px 0; border-radius: 10px; }
                #navRail::item:selected { background: #7b3f24; color: #fff7ee; }
                #inspectorPanel, QDockWidget { background: #191310; border-left: 1px solid #3c2b25; }
                QGroupBox, #statusCard { background: #1e1714; border: 1px solid #46352d; border-radius: 14px; margin-top: 10px; }
                QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #ffbe86; }
                QLabel#cardTitle { color: #ffbe86; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; }
                QLabel#cardValue, QLabel#panelValue { font-size: 20px; font-weight: 700; color: #fff8f1; }
                QLabel#cardDetail, QLabel#nowPlayingBody, QLabel#mutedLabel { color: #c9b7aa; }
                QLabel#nowPlayingTitle { font-size: 18px; font-weight: 700; color: #fff3ea; }
                QLabel#statusBadge { background: #7b2619; color: #fff3ec; padding: 6px 12px; border-radius: 12px; font-weight: 700; }
                QPushButton { background: #7f4124; border: 1px solid #9c613d; padding: 8px 12px; border-radius: 10px; }
                QPushButton:hover { background: #99512d; }
                QPushButton:disabled { background: #3c2a24; color: #907e73; border-color: #4a3931; }
                QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox { background: #140f0d; border: 1px solid #4e3c34; border-radius: 8px; padding: 6px; }
            """,
            "obsidian_console": """
                QWidget { background: #0f1418; color: #dde7ee; font-family: 'Segoe UI', 'Noto Sans', 'DejaVu Sans'; }
                QMainWindow { background: #0f1418; }
                #headerBar, QToolBar#mainToolbar { background: #152028; border-bottom: 1px solid #243641; }
                #appTitle { font-size: 24px; font-weight: 700; color: #f5fbff; }
                #appSubtitle, QLabel#mutedLabel, #pageSubtitle { color: #98aab6; }
                #pageTitle { font-size: 20px; font-weight: 700; color: #f0f8fe; }
                #navRail { background: #121a20; border-right: 1px solid #22313c; padding: 8px; }
                #navRail::item { padding: 12px 14px; margin: 3px 0; border-radius: 10px; }
                #navRail::item:selected { background: #19495a; color: #f5fbff; }
                #inspectorPanel, QDockWidget { background: #121a20; border-left: 1px solid #22313c; }
                QGroupBox, #statusCard { background: #162128; border: 1px solid #2a3b46; border-radius: 14px; margin-top: 10px; }
                QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #7fc9e8; }
                QLabel#cardTitle { color: #7fc9e8; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; }
                QLabel#cardValue, QLabel#panelValue { font-size: 20px; font-weight: 700; color: #f5fbff; }
                QLabel#statusBadge { background: #1d566a; color: #effaff; padding: 6px 12px; border-radius: 12px; font-weight: 700; }
                QPushButton { background: #1d566a; border: 1px solid #2f7087; padding: 8px 12px; border-radius: 10px; }
                QPushButton:hover { background: #24687e; }
                QPushButton:disabled { background: #26353d; color: #71838f; border-color: #31424d; }
                QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox { background: #0d1317; border: 1px solid #334753; border-radius: 8px; padding: 6px; }
            """,
            "day_shift": """
                QWidget { background: #f4efe9; color: #2b261f; font-family: 'Segoe UI', 'Noto Sans', 'DejaVu Sans'; }
                QMainWindow { background: #f4efe9; }
                #headerBar, QToolBar#mainToolbar { background: #efe3d2; border-bottom: 1px solid #cfbfa8; }
                #appTitle { font-size: 24px; font-weight: 700; color: #2b261f; }
                #appSubtitle, QLabel#mutedLabel, #pageSubtitle { color: #63594e; }
                #pageTitle { font-size: 20px; font-weight: 700; color: #29251f; }
                #navRail { background: #ece3d8; border-right: 1px solid #cfbfa8; padding: 8px; color: #2b261f; }
                #navRail::item { padding: 12px 14px; margin: 3px 0; border-radius: 10px; }
                #navRail::item:selected { background: #c76630; color: #fffaf5; }
                #inspectorPanel, QDockWidget { background: #ede4d9; border-left: 1px solid #cfbfa8; }
                QGroupBox, #statusCard { background: #fbf7f2; border: 1px solid #d9c7b2; border-radius: 14px; margin-top: 10px; }
                QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #9c4a20; }
                QLabel#cardTitle { color: #9c4a20; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; }
                QLabel#cardValue, QLabel#panelValue { font-size: 20px; font-weight: 700; color: #2a251f; }
                QLabel#statusBadge { background: #c76630; color: #fffaf5; padding: 6px 12px; border-radius: 12px; font-weight: 700; }
                QPushButton { background: #c76630; border: 1px solid #da7f4f; color: #fff9f4; padding: 8px 12px; border-radius: 10px; }
                QPushButton:hover { background: #d47440; }
                QPushButton:disabled { background: #d8ccc0; color: #8a7d70; border-color: #d0c2b4; }
                QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox { background: #fffdfb; border: 1px solid #d8c7b3; border-radius: 8px; padding: 6px; color: #2b261f; }
            """,
        }
        self.setStyleSheet(style_map.get(theme, style_map["broadcast_warm"]))

    def _build_settings_from_form(self) -> RuntimeSettings:
        settings = replace(self.current_settings)
        backend_label = self.llm_backend_combo.currentText().strip() or backend_label_from_settings(settings)

        settings.use_mock_twitter = self.use_mock_checkbox.isChecked()
        settings.use_music = self.use_music_checkbox.isChecked()
        settings.anchor_voice_id = self.anchor_voice_combo.currentText().strip() or settings.anchor_voice_id
        settings.analyst_voice_id = self.analyst_voice_combo.currentText().strip() or settings.analyst_voice_id
        settings.voice_id = settings.anchor_voice_id
        settings.show_style = show_style_value_from_label(self.show_style_combo.currentText().strip())
        settings.idle_format = idle_format_value_from_label(self.idle_format_combo.currentText().strip())
        settings.log_level = self.log_level_combo.currentText().strip().upper() or settings.log_level

        settings.twitter_accounts = self._parse_csv(self.accounts_edit.text(), "Twitter Accounts")
        settings.fetch_interval_seconds = self._parse_positive_int(self.fetch_interval_spin.value(), "Fetch Interval")
        settings.recap_interval_seconds = self._parse_positive_int(self.recap_interval_spin.value(), "Recap Interval")
        settings.mock_tweet_batch_size = self._parse_positive_int(self.mock_batch_spin.value(), "Mock Batch Size")
        settings.filler_enabled = self.filler_enabled_checkbox.isChecked()
        settings.filler_interval_seconds = self._parse_positive_int(
            self.filler_interval_spin.value(),
            "Filler Interval",
        )

        settings.include_original_posts = self.include_original_checkbox.isChecked()
        settings.include_quote_posts = self.include_quote_checkbox.isChecked()
        settings.include_replies = self.include_replies_checkbox.isChecked()
        settings.include_reposts = self.include_reposts_checkbox.isChecked()

        filler_topics = self._selected_list_values(self.filler_topic_list)
        if settings.filler_enabled and not filler_topics:
            raise ValueError("Select at least one filler topic when filler is enabled.")
        settings.filler_topics = filler_topics or list(settings.filler_topics)

        segment_types = self._selected_list_values(self.segment_type_list)
        if not segment_types:
            raise ValueError("Select at least one editorial segment type.")
        settings.editorial_segment_types = segment_types
        settings.editorial_segment_interval_seconds = self._parse_positive_int(
            self.segment_interval_spin.value(),
            "Segment Interval",
        )
        settings.editorial_candidate_lookback_minutes = self._parse_positive_int(
            self.candidate_lookback_spin.value(),
            "Candidate Lookback",
        )
        settings.editorial_repeat_cooldown_minutes = self._parse_positive_int(
            self.repeat_cooldown_spin.value(),
            "Repeat Cooldown",
        )
        settings.editorial_max_consecutive_same_source = self._parse_positive_int(
            self.max_same_source_spin.value(),
            "Max Consecutive Same Source",
        )
        settings.editorial_default_rundown_strategy = EDITORIAL_STRATEGY_OPTIONS.get(
            self.editorial_strategy_combo.currentText(),
            settings.editorial_default_rundown_strategy,
        )

        settings.llm_provider = provider_from_backend_label(backend_label)
        settings.ollama_model = self.ollama_model_combo.currentText().strip() or settings.ollama_model
        settings.ollama_base_url = self.ollama_base_url_edit.text().strip() or settings.ollama_base_url
        settings.llm_api_base_url = self.api_base_url_edit.text().strip() or settings.llm_api_base_url
        if backend_label == "LM Studio" and not self.api_base_url_edit.text().strip():
            settings.llm_api_base_url = LM_STUDIO_DEFAULT_BASE_URL
        settings.llm_api_model = self.api_model_combo.currentText().strip() or settings.llm_api_model
        settings.llm_api_key = self.api_key_edit.text().strip()
        settings.llm_api_key_env_var = self.api_key_env_edit.text().strip()
        settings.ollama_max_retries = self._parse_positive_int(self.max_retries_spin.value(), "Max Retries")
        settings.ollama_backoff_factor = self._parse_positive_float(
            self.backoff_factor_spin.value(),
            "Backoff Factor",
        )

        settings.music_file = self.music_file_edit.text().strip() or settings.music_file
        settings.music_volume_idle = self._slider_percent_to_unit(self.music_volume_idle_slider)
        settings.music_volume_ducked = min(
            settings.music_volume_idle,
            self._slider_percent_to_unit(self.music_volume_ducked_slider),
        )
        settings.log_file = self.log_file_edit.text().strip() or settings.log_file
        settings.ui_theme = self._selected_theme_value()
        settings.ui_advanced_mode = self.advanced_toggle.isChecked()
        settings.ui_show_console = self.console_visible_checkbox.isChecked()
        return settings

    def _save_settings(self) -> bool:
        try:
            settings = self._build_settings_from_form()
            save_runtime_settings(self.settings_path, settings)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            self.status_badge.setText("Settings validation failed")
            return False

        self.current_settings = settings
        self._refresh_voice_status()
        self._refresh_dashboard_preview()
        self.console_dock.setVisible(settings.ui_show_console)
        self._append_output(f"Saved settings to {self.settings_path}")
        self.status_badge.setText("Settings saved")
        return True

    def _load_into_form(self, settings: RuntimeSettings) -> None:
        self.use_mock_checkbox.setChecked(settings.use_mock_twitter)
        self.use_music_checkbox.setChecked(settings.use_music)
        self.anchor_voice_combo.setCurrentText(settings.anchor_voice_id)
        self.analyst_voice_combo.setCurrentText(settings.analyst_voice_id)
        self.show_style_combo.setCurrentText(show_style_label_from_value(settings.show_style))
        self.idle_format_combo.setCurrentText(idle_format_label_from_value(settings.idle_format))
        self.log_level_combo.setCurrentText(settings.log_level)
        self.accounts_edit.setText(", ".join(settings.twitter_accounts))
        self.fetch_interval_spin.setValue(settings.fetch_interval_seconds)
        self.recap_interval_spin.setValue(settings.recap_interval_seconds)
        self.mock_batch_spin.setValue(settings.mock_tweet_batch_size)
        self.filler_enabled_checkbox.setChecked(settings.filler_enabled)
        self.filler_interval_spin.setValue(settings.filler_interval_seconds)

        self.include_original_checkbox.setChecked(settings.include_original_posts)
        self.include_quote_checkbox.setChecked(settings.include_quote_posts)
        self.include_replies_checkbox.setChecked(settings.include_replies)
        self.include_reposts_checkbox.setChecked(settings.include_reposts)

        filler_items = list(dict.fromkeys([*CURATED_FILLER_TOPICS, *settings.filler_topics]))
        self._set_selectable_items(self.filler_topic_list, filler_items, settings.filler_topics)

        self.llm_backend_combo.setCurrentText(backend_label_from_settings(settings))
        self.ollama_model_combo.clear()
        self.ollama_model_combo.addItems([settings.ollama_model] if settings.ollama_model else [])
        self.ollama_model_combo.setCurrentText(settings.ollama_model)
        self.ollama_base_url_edit.setText(settings.ollama_base_url)
        self.api_base_url_edit.setText(settings.llm_api_base_url)
        self.api_model_combo.clear()
        self.api_model_combo.addItems([settings.llm_api_model] if settings.llm_api_model else [])
        self.api_model_combo.setCurrentText(settings.llm_api_model)
        self.api_key_edit.setText(settings.llm_api_key)
        self.api_key_env_edit.setText(settings.llm_api_key_env_var)
        self.max_retries_spin.setValue(settings.ollama_max_retries)
        self.backoff_factor_spin.setValue(settings.ollama_backoff_factor)

        self.editorial_strategy_combo.setCurrentText(
            EDITORIAL_STRATEGY_LABELS.get(settings.editorial_default_rundown_strategy, "Editorial")
        )
        self.segment_interval_spin.setValue(settings.editorial_segment_interval_seconds)
        self.candidate_lookback_spin.setValue(settings.editorial_candidate_lookback_minutes)
        self.repeat_cooldown_spin.setValue(settings.editorial_repeat_cooldown_minutes)
        self.max_same_source_spin.setValue(settings.editorial_max_consecutive_same_source)
        self._set_selectable_items(
            self.segment_type_list,
            list(config.EDITORIAL_SEGMENT_TYPE_LABELS),
            settings.editorial_segment_types,
            config.EDITORIAL_SEGMENT_TYPE_LABELS,
        )

        self.music_file_edit.setText(settings.music_file)
        self.log_file_edit.setText(settings.log_file)
        self.music_volume_idle_slider.setValue(round(settings.music_volume_idle * 100))
        self.music_volume_ducked_slider.setValue(round(settings.music_volume_ducked * 100))
        self._update_volume_labels()

        self.theme_combo.setCurrentText(UI_THEME_LABELS.get(settings.ui_theme, "Broadcast Warm"))
        self.console_visible_checkbox.setChecked(settings.ui_show_console)
        self.advanced_toggle.setChecked(settings.ui_advanced_mode)
        self._update_provider_fields()
        self._refresh_dashboard_preview()

    def _append_output(self, line: str) -> None:
        self.output_lines.append(str(line).rstrip())
        self._refresh_console_view()

    def _refresh_voice_status(self) -> None:
        model_path, voices_path = VoiceGenerator.detect_kokoro_assets()
        if model_path and voices_path:
            self.voice_status_label.setText(
                f"High-quality Kokoro pack detected: {model_path.name} + {voices_path.name}"
            )
        else:
            self.voice_status_label.setText("Kokoro assets not detected. The station will fall back to the system voice path.")

    def _browse_music_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Music",
            str(self.project_root),
            "Audio Files (*.mp3 *.wav *.ogg);;All Files (*)",
        )
        if selected:
            relative = Path(selected)
            try:
                relative = relative.relative_to(self.project_root)
            except ValueError:
                pass
            self.music_file_edit.setText(str(relative))

    def _play_preview_audio(self, audio_path: Path) -> None:
        if sys.platform.startswith("win"):
            try:
                import winsound

                winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
                return
            except Exception as exc:  # pragma: no cover - best effort preview
                self._append_output(f"[preview] Playback failed: {exc}")
        self._append_output(f"[preview] Preview generated at {audio_path}")

    def _preview_voices(self) -> None:
        try:
            settings = self._build_settings_from_form()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            self.status_badge.setText("Preview blocked by invalid settings")
            return

        def worker() -> None:
            try:
                apply_runtime_settings(settings)
                voice_generator = VoiceGenerator()
                self.signals.append_output.emit(f"[preview] TTS backend: {voice_generator.describe_backend()}")
                previews = [
                    ("Anchor", settings.anchor_voice_id, "Anchor preview. This station now sounds sharper and less repetitive."),
                    ("Analyst", settings.analyst_voice_id, "Analyst preview. A second voice helps the idle segments feel like a real show."),
                ]
                for role, voice_id, text in previews:
                    audio_path = voice_generator.generate(text, voice_id)
                    self.signals.append_output.emit(f"[preview] {role} voice {voice_id} -> {audio_path.name}")
                    self._play_preview_audio(audio_path)
                self.signals.set_status.emit("Voice preview finished")
                self.signals.voice_preview_finished.emit()
            except Exception as exc:
                self.signals.append_output.emit(f"[preview] Voice preview failed: {exc}")
                self.signals.set_status.emit("Voice preview failed")

        threading.Thread(target=worker, name="desktop-voice-preview", daemon=True).start()
        self.status_badge.setText("Previewing voices")

    def _selected_saved_twitter_username(self) -> str | None:
        item = self.saved_twitter_list.currentItem()
        if item is None:
            return None
        username = item.data(Qt.UserRole)
        return str(username) if username else None

    def _render_saved_twitter_accounts(self, accounts: list[object]) -> None:
        self.saved_twitter_accounts = list(accounts)
        self.saved_twitter_list.clear()
        if not self.saved_twitter_accounts:
            self.twitter_account_status.setText("No saved Twitter accounts in accounts.db yet")
            return

        for account in self.saved_twitter_accounts:
            username = str(getattr(account, "username", ""))
            active = "active" if bool(getattr(account, "active", False)) else "inactive"
            has_auth = "auth_token" if bool(getattr(account, "has_auth_token", False)) else "no-auth"
            has_ct0 = "ct0" if bool(getattr(account, "has_ct0", False)) else "no-ct0"
            error_msg = str(getattr(account, "error_msg", "") or "")
            suffix = f" | {error_msg}" if error_msg else ""
            item = QListWidgetItem(f"@{username} | {active} | {has_auth} | {has_ct0}{suffix}")
            item.setData(Qt.UserRole, username)
            self.saved_twitter_list.addItem(item)

        self.twitter_account_status.setText(
            f"Loaded {len(self.saved_twitter_accounts)} saved Twitter account(s) from accounts.db"
        )

    def _refresh_saved_twitter_accounts(self) -> None:
        def worker() -> None:
            try:
                accounts = list_saved_twitter_accounts()
                self.signals.twitter_accounts.emit(accounts)
                self.signals.set_status.emit("Saved Twitter accounts refreshed")
            except Exception as exc:
                self.signals.append_output.emit(f"[twitter] Could not load saved accounts: {exc}")
                self.signals.set_status.emit("Saved Twitter account refresh failed")

        threading.Thread(target=worker, name="desktop-twitter-refresh", daemon=True).start()

    def _load_selected_twitter_account(self) -> None:
        username = self._selected_saved_twitter_username()
        if not username:
            QMessageBox.warning(self, "Twitter Account", "Select a saved Twitter account first.")
            self.status_badge.setText("No saved Twitter account selected")
            return

        def worker() -> None:
            try:
                account = load_saved_twitter_account(username)
                self.signals.twitter_account_loaded.emit(account)
                self.signals.append_output.emit(f"[twitter] Loaded saved account @{account.username} into the editor fields.")
                self.signals.set_status.emit("Saved Twitter account loaded")
            except Exception as exc:
                self.signals.append_output.emit(f"[twitter] Could not load saved account @{username}: {exc}")
                self.signals.set_status.emit("Saved Twitter account load failed")

        threading.Thread(target=worker, name="desktop-twitter-load", daemon=True).start()

    def _delete_selected_twitter_account(self) -> None:
        username = self._selected_saved_twitter_username()
        if not username:
            QMessageBox.warning(self, "Twitter Account", "Select a saved Twitter account first.")
            self.status_badge.setText("No saved Twitter account selected")
            return
        if QMessageBox.question(
            self,
            "Delete Twitter Account",
            f"Delete saved Twitter account @{username} from the local accounts.db store?",
        ) != QMessageBox.Yes:
            return

        def worker() -> None:
            try:
                delete_saved_twitter_account(username)
                accounts = list_saved_twitter_accounts()
                self.signals.twitter_accounts.emit(accounts)
                self.signals.append_output.emit(f"[twitter] Deleted saved account @{username}.")
                self.signals.set_status.emit("Saved Twitter account deleted")
            except Exception as exc:
                self.signals.append_output.emit(f"[twitter] Could not delete saved account @{username}: {exc}")
                self.signals.set_status.emit("Saved Twitter account deletion failed")

        threading.Thread(target=worker, name="desktop-twitter-delete", daemon=True).start()

    def _reset_saved_twitter_locks(self) -> None:
        def worker() -> None:
            try:
                reset_twitter_locks()
                self.signals.twitter_accounts.emit(list_saved_twitter_accounts())
                self.signals.append_output.emit("[twitter] Reset twscrape account locks in accounts.db.")
                self.signals.set_status.emit("Twitter locks reset")
            except Exception as exc:
                self.signals.append_output.emit(f"[twitter] Could not reset twscrape locks: {exc}")
                self.signals.set_status.emit("Twitter lock reset failed")

        threading.Thread(target=worker, name="desktop-twitter-reset", daemon=True).start()

    def _handle_loaded_twitter_account(self, account: object) -> None:
        self.twitter_username_edit.setText(str(getattr(account, "username", "")))
        self.twitter_auth_token_edit.setText(str(getattr(account, "auth_token", "")))
        self.twitter_ct0_edit.setText(str(getattr(account, "ct0", "")))
        self.twitter_cookie_string_edit.setText("")

    def _show_twitter_setup(self) -> None:
        self._append_output("Twitter setup:")
        for line in TWITTER_SETUP_LINES:
            self._append_output(line)
        self.status_badge.setText("Twitter setup steps shown")

    def _reset_twitter_secret_fields(self) -> None:
        self.twitter_cookie_string_edit.clear()
        self.twitter_auth_token_edit.clear()
        self.twitter_ct0_edit.clear()

    def _clear_twitter_secret_fields(self) -> None:
        self._reset_twitter_secret_fields()
        self._append_output("Cleared Twitter session fields from the desktop control room.")
        self.status_badge.setText("Twitter fields cleared")

    def _import_twitter_session(self) -> None:
        username = self.twitter_username_edit.text().strip()
        cookie_string = self.twitter_cookie_string_edit.text().strip()
        auth_token = self.twitter_auth_token_edit.text().strip()
        ct0 = self.twitter_ct0_edit.text().strip()
        if not username:
            QMessageBox.warning(self, "Twitter Session", "Twitter username is required.")
            self.status_badge.setText("Twitter session import failed")
            return

        def worker() -> None:
            try:
                result = import_twitter_session(
                    username=username,
                    cookie_string=cookie_string,
                    auth_token=auth_token,
                    ct0=ct0,
                )
                account_count = "unknown" if result.account_count is None else str(result.account_count)
                self.signals.append_output.emit(
                    f"[twitter] Imported session for @{result.username} into {result.db_path}. "
                    f"Active={result.active}. Saved accounts={account_count}."
                )
                self.signals.twitter_accounts.emit(list_saved_twitter_accounts())
                self.signals.set_status.emit("Twitter session imported")
            except Exception as exc:
                self.signals.append_output.emit(f"[twitter] Session import failed: {exc}")
                self.signals.set_status.emit("Twitter session import failed")

        threading.Thread(target=worker, name="desktop-twitter-import", daemon=True).start()
        self.status_badge.setText("Importing Twitter session")

    def _add_custom_filler_topic(self) -> None:
        topic = self.new_filler_topic_edit.text().strip()
        if not topic:
            return
        items = [self.filler_topic_list.item(index).data(Qt.UserRole) for index in range(self.filler_topic_list.count())]
        if topic not in items:
            item = QListWidgetItem(topic)
            item.setData(Qt.UserRole, topic)
            self.filler_topic_list.addItem(item)
        for index in range(self.filler_topic_list.count()):
            current = self.filler_topic_list.item(index)
            if current.data(Qt.UserRole) == topic:
                current.setSelected(True)
                break
        self.new_filler_topic_edit.clear()

    def _remove_highlighted_filler_topics(self) -> None:
        for item in list(self.filler_topic_list.selectedItems()):
            self.filler_topic_list.takeItem(self.filler_topic_list.row(item))

    def _refresh_dashboard_preview(self) -> None:
        settings = self.current_settings
        provider_label = backend_label_from_settings(settings)
        source_flags = []
        if settings.include_original_posts:
            source_flags.append("original")
        if settings.include_quote_posts:
            source_flags.append("quote")
        if settings.include_replies:
            source_flags.append("reply")
        if settings.include_reposts:
            source_flags.append("repost")
        source_summary = ", ".join(source_flags) if source_flags else "none"
        seen_count = self._load_seen_count()
        self.dashboard_summary.setText(
            f"{provider_label} backend, {len(settings.twitter_accounts)} tracked account(s), "
            f"{settings.show_style} show style, {settings.editorial_default_rundown_strategy} rundown."
        )
        self.show_notes.setText(
            f"Headline checks run every {settings.fetch_interval_seconds}s. Recaps every {settings.recap_interval_seconds}s. "
            f"Idle segments are {settings.idle_format} with filler every {settings.filler_interval_seconds}s."
        )
        self.provider_summary.setText(
            f"{provider_label} | model {settings.llm_api_model if settings.llm_provider == 'openai_compatible' else settings.ollama_model}"
        )
        self.sources_summary.setText(f"Source mix: {source_summary} | seen cache: {seen_count} story id(s)")
        self.runtime_summary.setText(
            f"Theme {settings.ui_theme}. Console {'on' if settings.ui_show_console else 'off'}. "
            f"Advanced {'on' if settings.ui_advanced_mode else 'off'}."
        )
        self.paths_summary.setText(
            f"Config: {self.settings_path}\n"
            f"Log: {self.project_root / settings.log_file}\n"
            f"Accounts DB: {get_twitter_db_path()}\n"
            f"Rundown State: {config.get_rundown_state_file()}"
        )
        if hasattr(self, "seen_cache_label"):
            self.seen_cache_label.setText(
                f"The station currently remembers {seen_count} already-aired tweet id(s) in {config.get_seen_ids_file()}. "
                "If every fetched post shows as already seen, reset this cache to allow rebroadcast."
            )

    def _load_seen_count(self) -> int:
        payload = read_json_file(config.get_seen_ids_file(), dict, logging.getLogger(__name__))
        if isinstance(payload, dict):
            raw_ids = payload.get("seen_ids", [])
            if isinstance(raw_ids, list):
                return len(raw_ids)
        return 0

    def _refresh_rundown_state(self) -> None:
        payload = read_json_file(config.get_rundown_state_file(), dict, logging.getLogger(__name__))
        if not isinstance(payload, dict):
            payload = {}
        self.last_rundown_payload = payload
        state = str(payload.get("state", "IDLE")).title()
        self.station_state_value.setText(state)
        self.candidate_pool_value.setText(f"Candidate pool: {payload.get('candidate_count', 0)} stories")

        current_item = payload.get("current_item") or {}
        segment_type = str(current_item.get("segment_type", "")).replace("_", " ").title()
        stories = current_item.get("stories") or []
        if segment_type:
            headline = stories[0]["text"] if stories else "Editorial segment in progress"
            self.now_playing_title.setText(segment_type)
            self.now_playing_body.setText(headline)
        else:
            self.now_playing_title.setText("Waiting for the first segment")
            self.now_playing_body.setText("Start the engine to see the live editorial rundown.")

        self.rundown_preview_list.clear()
        for item in payload.get("preview", []) or []:
            label = str(item.get("segment_type", "segment")).replace("_", " ").title()
            stories = item.get("stories") or []
            detail = stories[0]["text"] if stories else str(item.get("reason", ""))
            self.rundown_preview_list.addItem(f"{label}: {detail}")

    def _handle_health_report(self, results: list[Any], report: str) -> None:
        self.health_report_view.setPlainText(report)
        for result in results:
            card = self.health_result_cards.get(str(getattr(result, "name", "")))
            if card is not None:
                card.update_state(str(getattr(result, "status", "idle")), str(getattr(result, "message", "")))
        if any(getattr(result, "status", "") == "fail" for result in results):
            self.status_badge.setText("Health check found failures")
        elif any(getattr(result, "status", "") == "warn" for result in results):
            self.status_badge.setText("Health check finished with warnings")
        else:
            self.status_badge.setText("Health check passed")

    def _handle_model_list(self, provider: str, models: list[str]) -> None:
        if provider == "ollama":
            self.ollama_model_combo.clear()
            self.ollama_model_combo.addItems(models)
            if models and not self.ollama_model_combo.currentText().strip():
                self.ollama_model_combo.setCurrentText(models[0])
        else:
            self.api_model_combo.clear()
            self.api_model_combo.addItems(models)
            if models and not self.api_model_combo.currentText().strip():
                self.api_model_combo.setCurrentText(models[0])
        self._append_output(f"Detected models: {', '.join(models[:8]) if models else 'none'}")
        self.status_badge.setText("Model list refreshed")

    def _update_provider_fields(self) -> None:
        provider = provider_from_backend_label(self.llm_backend_combo.currentText())
        is_ollama = provider == "ollama"
        is_api = provider == "openai_compatible"
        for widget in (self.ollama_model_combo, self.ollama_base_url_edit):
            widget.setEnabled(is_ollama)
        for widget in (self.api_base_url_edit, self.api_model_combo, self.api_key_edit, self.api_key_env_edit):
            widget.setEnabled(is_api)
        self.refresh_models_button.setEnabled(provider != "simple")

    def _apply_lm_studio_preset(self) -> None:
        self.llm_backend_combo.setCurrentText("LM Studio")
        self.api_base_url_edit.setText(LM_STUDIO_DEFAULT_BASE_URL)
        self.api_key_edit.clear()
        if self.api_key_env_edit.text().strip() == "OPENAI_API_KEY":
            self.api_key_env_edit.clear()
        self._update_provider_fields()
        self._append_output("Applied LM Studio preset (backend=LM Studio, base=http://localhost:1234/v1)")
        self.status_badge.setText("LM Studio preset applied")

    def _detect_lm_studio(self) -> None:
        try:
            base_url, models = detect_lm_studio_endpoint()
        except Exception as exc:
            self._append_output(str(exc))
            self.status_badge.setText("LM Studio not detected")
            return
        self.llm_backend_combo.setCurrentText("LM Studio")
        self.api_base_url_edit.setText(base_url)
        self._handle_model_list("openai_compatible", models)
        if models:
            self.api_model_combo.setCurrentText(models[0])
        self._append_output(f"LM Studio reachable at {base_url}. Models: {', '.join(models[:5]) if models else 'none'}")
        self.status_badge.setText("LM Studio detected")

    def _refresh_models(self) -> None:
        provider = provider_from_backend_label(self.llm_backend_combo.currentText())
        try:
            if provider == "ollama":
                models = fetch_ollama_models(self.ollama_base_url_edit.text().strip())
            elif provider == "openai_compatible":
                models = fetch_openai_compatible_models(
                    self.api_base_url_edit.text().strip(),
                    resolve_api_key(self.api_key_edit.text().strip(), self.api_key_env_edit.text().strip()),
                )
            else:
                self._append_output("Simple backend selected. No models to refresh.")
                self.status_badge.setText("No external models for Simple backend")
                return
        except Exception as exc:
            self._append_output(str(exc))
            self.status_badge.setText("Model refresh failed")
            return
        self._handle_model_list(provider, models)

    def _ping_provider(self) -> None:
        provider = provider_from_backend_label(self.llm_backend_combo.currentText())
        try:
            if provider == "ollama":
                models = fetch_ollama_models(self.ollama_base_url_edit.text().strip())
                message = f"Ollama reachable. Models: {', '.join(models[:5]) if models else 'none'}"
            elif provider == "openai_compatible":
                models = fetch_openai_compatible_models(
                    self.api_base_url_edit.text().strip(),
                    resolve_api_key(self.api_key_edit.text().strip(), self.api_key_env_edit.text().strip()),
                )
                message = f"OpenAI-compatible endpoint reachable. Models: {', '.join(models[:5]) if models else 'none'}"
            else:
                message = "Simple backend selected. No network provider required."
        except Exception as exc:
            self._append_output(str(exc))
            self.status_badge.setText("Provider ping failed")
            return
        self._append_output(message)
        self.status_badge.setText("Provider ping succeeded")

    def _run_health_check(self) -> None:
        try:
            settings = self._build_settings_from_form()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            self.status_badge.setText("Health check blocked by invalid settings")
            return

        def worker() -> None:
            apply_runtime_settings(settings)
            results = run_health_checks(settings)
            report = render_health_check_report(results)
            self.signals.append_output.emit("Health check results:")
            self.signals.append_output.emit(report)
            self.signals.health_report.emit(results, report)

        threading.Thread(target=worker, name="desktop-health-check", daemon=True).start()
        self.status_badge.setText("Running health check")

    def _run_smoke_test(self) -> None:
        try:
            settings = self._build_settings_from_form()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            self.status_badge.setText("Smoke test blocked by invalid settings")
            return

        def worker() -> None:
            apply_runtime_settings(settings)
            results = run_smoke_test(settings)
            report = render_health_check_report(results)
            self.signals.append_output.emit("Smoke test results:")
            self.signals.append_output.emit(report)
            self.signals.health_report.emit(results, report)

        threading.Thread(target=worker, name="desktop-smoke-test", daemon=True).start()
        self.status_badge.setText("Running smoke test")

    def _refetch_stories(self) -> None:
        try:
            settings = self._build_settings_from_form()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            self.status_badge.setText("Refetch blocked by invalid settings")
            return

        def render_preview_line(preview: PreviewTweet) -> str:
            tweet = preview.tweet
            state = "already seen" if preview.already_seen else "new"
            details: list[str] = [tweet.source_type, state]
            if tweet.quoted_username:
                details.append(f"quotes @{tweet.quoted_username}")
            if tweet.article_title:
                details.append(f"article {tweet.article_title}")
            elif tweet.article_url:
                details.append(f"link {tweet.article_url}")
            snippet = " ".join(tweet.text.split())[:180]
            return f"[refetch] @{tweet.username} | {' | '.join(details)} | {snippet}"

        def worker() -> None:
            try:
                apply_runtime_settings(settings)
                monitor = get_monitor(use_mock=settings.use_mock_twitter)
                if hasattr(monitor, "preview_latest"):
                    preview_items, diagnostics = monitor.preview_latest(settings.twitter_accounts, include_seen=True)
                else:
                    preview_items = [PreviewTweet(tweet=tweet, already_seen=False) for tweet in monitor.fetch_latest(settings.twitter_accounts)]
                    diagnostics = []

                self.signals.append_output.emit("[refetch] Manual story preview:")
                for stat in diagnostics:
                    self.signals.append_output.emit(
                        f"[refetch] @{stat.username} raw={stat.raw_count} new={stat.queued_count} "
                        f"already_seen={stat.seen_skipped_count} filtered_by_source={stat.filtered_source_count}"
                    )

                if not preview_items:
                    self.signals.append_output.emit(
                        "[refetch] No latest stories were returned. If the account has posts, they may already be in seen_ids or filtered by source type."
                    )
                else:
                    for item in preview_items[:8]:
                        self.signals.append_output.emit(render_preview_line(item))
                self.signals.refresh_dashboard.emit()
                self.signals.set_status.emit("Story refetch finished")
            except Exception as exc:
                self.signals.append_output.emit(f"[refetch] Story refetch failed: {exc}")
                self.signals.set_status.emit("Story refetch failed")

        threading.Thread(target=worker, name="desktop-refetch-stories", daemon=True).start()
        self.status_badge.setText("Refetching stories")

    def _reset_seen_cache(self) -> None:
        if QMessageBox.question(
            self,
            "Reset Seen Cache",
            "Clear the seen story cache so previously aired posts can be queued again?",
        ) != QMessageBox.Yes:
            return

        success = write_json_file(config.get_seen_ids_file(), {"seen_ids": []}, logging.getLogger(__name__))
        if not success:
            QMessageBox.warning(self, "Seen Cache", "Could not reset the seen story cache.")
            self.status_badge.setText("Seen cache reset failed")
            return
        self._append_output(f"[sources] Reset seen story cache at {config.get_seen_ids_file()}")
        self._refresh_dashboard_preview()
        self.status_badge.setText("Seen cache reset")

    def _open_seen_ids_file(self) -> None:
        self._open_path(config.get_seen_ids_file(), "Seen IDs")

    def _start_station(self) -> None:
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            self.status_badge.setText("Station is already running")
            return
        if not self._save_settings():
            return

        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        self.process.setArguments(["-u", "main.py", "--no-gui", "--config", str(self.settings_path)])
        self.process.setWorkingDirectory(str(self.project_root))
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_process_output)
        self.process.finished.connect(self._handle_process_finished)
        self.process.start()

        self.start_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self._append_output(f"[launcher] Started station with {sys.executable} -u main.py --no-gui --config {self.settings_path}")
        self.status_badge.setText("Station running")

    def _on_process_output(self) -> None:
        if self.process is None:
            return
        payload = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in payload.splitlines():
            self._append_output(line)

    def _handle_process_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._append_output(f"[launcher] Station exited with code {exit_code}")
        self.status_badge.setText(f"Station stopped (code {exit_code})")
        self.start_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.process = None

    def _stop_station(self) -> None:
        if self.process is None or self.process.state() == QProcess.NotRunning:
            self.status_badge.setText("Station is not running")
            return
        self._append_output("[launcher] Stopping station...")
        self.process.terminate()
        QTimer.singleShot(3000, self._kill_station_if_needed)
        self.status_badge.setText("Stopping station")

    def _kill_station_if_needed(self) -> None:
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            self._append_output("[launcher] Station did not exit in time; killing process.")
            self.process.kill()

    def _open_path(self, path: Path, title: str) -> None:
        target = path.resolve()
        if not target.exists():
            QMessageBox.warning(self, title, f"Path does not exist: {target}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _open_accounts_folder(self) -> None:
        self._open_path(get_twitter_db_path().parent, "Accounts DB Folder")

    def _open_rundown_state_file(self) -> None:
        self._open_path(config.get_rundown_state_file(), "Rundown State")

    def closeEvent(self, event) -> None:  # pragma: no cover - UI interaction
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            should_close = QMessageBox.question(
                self,
                "Stop Station",
                "The station is still running. Stop it and close the control room?",
            )
            if should_close != QMessageBox.Yes:
                event.ignore()
                return
            self._stop_station()
        event.accept()

    def _refresh_console_view(self) -> None:
        needle = self.console_filter.text().strip().lower()
        visible_lines = [line for line in self.output_lines if not needle or needle in line.lower()]
        self.console.setPlainText("\n".join(visible_lines))
        if not self.console_pause.isChecked():
            cursor = self.console.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.console.setTextCursor(cursor)

    def _clear_console_view(self) -> None:
        self.output_lines = []
        self.console.clear()

    def _copy_console_view(self) -> None:
        QApplication.clipboard().setText(self.console.toPlainText())
        self.status_badge.setText("Copied visible console output")

    def _open_log_file(self) -> None:
        path = self.project_root / self.current_settings.log_file
        if not path.exists():
            QMessageBox.warning(self, "Log File", f"Log file does not exist: {path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))


def run_gui(settings_path: Path | None = None) -> int:
    """Run the desktop control room."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("X-News-Station")
    window = DesktopApp(settings_path or config.get_settings_file())
    window.show()
    return app.exec()


def run_desktop_app(settings_path: Path | None = None) -> int:
    """Compatibility alias used by the main entrypoint."""
    return run_gui(settings_path)
