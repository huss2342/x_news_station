"""Simple settings GUI and process launcher for X-News-Station."""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import config
from modules.audio_studio import VoiceGenerator
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
from modules.runtime_settings import RuntimeSettings, apply_runtime_settings, load_runtime_settings, save_runtime_settings
from modules.smoke_test import run_smoke_test
from modules.twitter_setup import (
    delete_saved_twitter_account,
    import_twitter_session,
    list_saved_twitter_accounts,
    load_saved_twitter_account,
    reset_twitter_locks,
)


class LauncherGUI:
    """Tkinter settings editor and process launcher."""

    def __init__(self, settings_path: Path) -> None:
        self.project_root = config.get_project_root()
        self.settings_path = settings_path.resolve()
        self.current_settings, self.notes = load_runtime_settings(
            self.settings_path, include_env_secrets=False
        )
        self.process: subprocess.Popen[str] | None = None
        self.output_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.provider_model_values: list[str] = []
        self.available_filler_topics: list[str] = []
        self.saved_twitter_accounts: list[object] = []

        self.root = tk.Tk()
        self.root.title("X-News-Station Launcher")
        self.root.geometry("1180x900")
        self.root.minsize(1020, 780)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.status_var = tk.StringVar(value="Ready")
        self.voice_status_var = tk.StringVar(value="")
        self.use_mock_var = tk.BooleanVar()
        self.use_music_var = tk.BooleanVar()
        self.anchor_voice_id_var = tk.StringVar()
        self.analyst_voice_id_var = tk.StringVar()
        self.show_style_var = tk.StringVar()
        self.idle_format_var = tk.StringVar()
        self.log_level_var = tk.StringVar()
        self.accounts_var = tk.StringVar()
        self.fetch_interval_var = tk.StringVar()
        self.recap_interval_var = tk.StringVar()
        self.mock_batch_var = tk.StringVar()
        self.filler_enabled_var = tk.BooleanVar()
        self.filler_interval_var = tk.StringVar()
        self.new_filler_topic_var = tk.StringVar()
        self.llm_backend_var = tk.StringVar()
        self.ollama_model_var = tk.StringVar()
        self.ollama_base_url_var = tk.StringVar()
        self.api_base_url_var = tk.StringVar()
        self.api_model_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.api_key_env_var = tk.StringVar()
        self.max_retries_var = tk.StringVar()
        self.backoff_factor_var = tk.StringVar()
        self.music_file_var = tk.StringVar()
        self.log_file_var = tk.StringVar()
        self.music_volume_idle_var = tk.DoubleVar()
        self.music_volume_ducked_var = tk.DoubleVar()
        self.music_volume_idle_label_var = tk.StringVar(value="80%")
        self.music_volume_ducked_label_var = tk.StringVar(value="20%")
        self.twitter_username_var = tk.StringVar()
        self.twitter_cookie_string_var = tk.StringVar()
        self.twitter_auth_token_var = tk.StringVar()
        self.twitter_ct0_var = tk.StringVar()
        self.twitter_account_status_var = tk.StringVar(value="No saved Twitter accounts loaded")

        self.ollama_controls: list[ttk.Widget] = []
        self.api_controls: list[ttk.Widget] = []

        self._build_ui()
        self._load_into_form(self.current_settings)
        self._refresh_voice_status()
        self._refresh_saved_twitter_accounts()

        for note in self.notes:
            self._append_output(f"Settings: {note}")

        self.root.after(150, self._drain_output_queue)

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="X-News-Station Launcher", font=("Segoe UI", 15, "bold")).pack(side="left")
        ttk.Label(header, text=f"Config: {self.settings_path}").pack(side="right")

        notebook = ttk.Notebook(container)
        notebook.pack(fill="x", pady=(0, 8))
        station_tab = ttk.Frame(notebook, padding=10)
        llm_tab = ttk.Frame(notebook, padding=10)
        advanced_tab = ttk.Frame(notebook, padding=10)
        notebook.add(station_tab, text="Station")
        notebook.add(llm_tab, text="LLM")
        notebook.add(advanced_tab, text="Advanced")

        self._build_station_tab(station_tab)
        self._build_llm_tab(llm_tab)
        self._build_advanced_tab(advanced_tab)

        ttk.Label(
            container,
            text="Advanced fields not shown here are preserved from the existing INI when you save.",
        ).pack(anchor="w", pady=(0, 8))

        actions = ttk.Frame(container)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Save Settings", command=self._save_settings).pack(side="left")
        self.start_button = ttk.Button(actions, text="Start Station", command=self._start_station)
        self.start_button.pack(side="left", padx=(8, 0))
        self.stop_button = ttk.Button(actions, text="Stop Station", command=self._stop_station, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Ping Provider", command=self._ping_provider).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Run Health Check", command=self._run_health_check).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Run Smoke Test", command=self._run_smoke_test).pack(side="left", padx=(8, 0))
        ttk.Label(actions, textvariable=self.status_var).pack(side="right")

        self.output = ScrolledText(container, height=22, wrap="word")
        self.output.pack(fill="both", expand=True)
        self.output.configure(state="disabled")

    def _build_station_tab(self, parent: ttk.Frame) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill="x")

        self._add_checkbox(controls, "Use Mock Twitter", self.use_mock_var, 0)
        self._add_checkbox(controls, "Use Music", self.use_music_var, 1)
        self._add_labeled_combobox(controls, "Anchor Voice", self.anchor_voice_id_var, VOICE_OPTIONS, 2, readonly=False)
        self._add_labeled_combobox(controls, "Analyst Voice", self.analyst_voice_id_var, VOICE_OPTIONS, 3, readonly=False)
        self._add_labeled_combobox(
            controls, "Show Style", self.show_style_var, list(SHOW_STYLE_LABELS.keys()), 4
        )
        self._add_labeled_combobox(
            controls, "Idle Format", self.idle_format_var, list(IDLE_FORMAT_LABELS.keys()), 5
        )
        self._add_labeled_combobox(
            controls, "Log Level", self.log_level_var, ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], 6
        )
        self._add_labeled_entry(controls, "Twitter Accounts", self.accounts_var, 7, width=72)
        self._add_labeled_entry(controls, "Fetch Interval (s)", self.fetch_interval_var, 8)
        self._add_labeled_entry(controls, "Recap Interval (s)", self.recap_interval_var, 9)
        self._add_labeled_entry(controls, "Mock Batch Size", self.mock_batch_var, 10)
        ttk.Label(controls, textvariable=self.voice_status_var).grid(row=11, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(controls, text="Preview Voices", command=self._preview_voices).grid(row=12, column=0, sticky="w", pady=(8, 0))

        twitter_frame = ttk.LabelFrame(parent, text="Twitter Setup", padding=10)
        twitter_frame.pack(fill="x", pady=(12, 0))
        ttk.Label(
            twitter_frame,
            text=(
                "Real Twitter mode uses a project-local twscrape account store. "
                "The fields below are used once for session import and are never written to station_settings.ini."
            ),
            wraplength=900,
        ).pack(anchor="w")
        ttk.Label(
            twitter_frame,
            text="You do not need every browser cookie here. auth_token plus ct0 is enough. Full Cookie String is optional if you already copied one.",
            wraplength=900,
        ).pack(anchor="w", pady=(6, 0))

        import_grid = ttk.Frame(twitter_frame)
        import_grid.pack(fill="x", pady=(10, 0))
        self._add_labeled_entry(import_grid, "Twitter Username", self.twitter_username_var, 0, width=48)
        self._add_labeled_entry(import_grid, "Full Cookie String (Optional)", self.twitter_cookie_string_var, 1, width=72)
        self._add_labeled_entry(import_grid, "auth_token", self.twitter_auth_token_var, 2, width=48, show="*")
        self._add_labeled_entry(import_grid, "ct0", self.twitter_ct0_var, 3, width=48, show="*")

        import_actions = ttk.Frame(twitter_frame)
        import_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(import_actions, text="Import Session Cookie", command=self._import_twitter_session).pack(side="left")
        ttk.Button(import_actions, text="Clear Twitter Secrets", command=self._clear_twitter_secret_fields).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(import_actions, text="Show Twitter Setup Steps", command=self._show_twitter_setup).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(twitter_frame, text=f"CLI fallback import format: {TWITTER_ACCOUNT_LINE_FORMAT}").pack(
            anchor="w", pady=(8, 0)
        )

        saved_frame = ttk.LabelFrame(twitter_frame, text="Saved Accounts", padding=10)
        saved_frame.pack(fill="x", pady=(12, 0))
        ttk.Label(
            saved_frame,
            textvariable=self.twitter_account_status_var,
            wraplength=900,
        ).pack(anchor="w", pady=(0, 8))
        saved_list_frame = ttk.Frame(saved_frame)
        saved_list_frame.pack(fill="x")
        self.saved_twitter_listbox = tk.Listbox(saved_list_frame, exportselection=False, height=4)
        self.saved_twitter_listbox.pack(side="left", fill="x", expand=True)
        saved_scrollbar = ttk.Scrollbar(saved_list_frame, orient="vertical", command=self.saved_twitter_listbox.yview)
        saved_scrollbar.pack(side="left", fill="y")
        self.saved_twitter_listbox.configure(yscrollcommand=saved_scrollbar.set)

        saved_actions = ttk.Frame(saved_frame)
        saved_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(saved_actions, text="Refresh Saved Accounts", command=self._refresh_saved_twitter_accounts).pack(side="left")
        ttk.Button(saved_actions, text="Load Selected", command=self._load_selected_twitter_account).pack(side="left", padx=(8, 0))
        ttk.Button(saved_actions, text="Delete Selected", command=self._delete_selected_twitter_account).pack(side="left", padx=(8, 0))
        ttk.Button(saved_actions, text="Reset Locks", command=self._reset_saved_twitter_locks).pack(side="left", padx=(8, 0))

    def _build_llm_tab(self, parent: ttk.Frame) -> None:
        button_row = ttk.Frame(parent)
        button_row.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Button(button_row, text="Use LM Studio Preset", command=self._apply_lm_studio_preset).pack(side="left")
        ttk.Button(button_row, text="Detect LM Studio", command=self._detect_lm_studio).pack(side="left", padx=(8, 0))
        self.refresh_models_button = ttk.Button(button_row, text="Refresh Models", command=self._refresh_models)
        self.refresh_models_button.pack(side="left", padx=(8, 0))

        backend = self._add_labeled_combobox(parent, "LLM Backend", self.llm_backend_var, LLM_BACKEND_OPTIONS, 1)
        backend.bind("<<ComboboxSelected>>", lambda _event: self._update_provider_fields())

        ollama_model = self._add_labeled_combobox(parent, "Ollama Model", self.ollama_model_var, [], 2, width=48, readonly=False)
        ollama_base = self._add_labeled_entry(parent, "Ollama Base URL", self.ollama_base_url_var, 3, width=48)
        api_base = self._add_labeled_entry(parent, "API Base URL", self.api_base_url_var, 4, width=48)
        api_model = self._add_labeled_combobox(parent, "API Model", self.api_model_var, [], 5, width=48, readonly=False)
        api_key = self._add_labeled_entry(parent, "API Key", self.api_key_var, 6, width=48, show="*")
        api_env = self._add_labeled_entry(parent, "API Key Env Var", self.api_key_env_var, 7, width=48)
        self._add_labeled_entry(parent, "Max Retries", self.max_retries_var, 8, width=20)
        self._add_labeled_entry(parent, "Backoff Factor", self.backoff_factor_var, 9, width=20)

        self.ollama_model_combo = ollama_model
        self.api_model_combo = api_model
        self.ollama_controls.extend([ollama_model, ollama_base])
        self.api_controls.extend([api_base, api_model, api_key, api_env])

    def _build_advanced_tab(self, parent: ttk.Frame) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill="x")
        self._add_checkbox(controls, "Enable Filler", self.filler_enabled_var, 0)
        self._add_labeled_entry(controls, "Filler Interval (s)", self.filler_interval_var, 1)
        self._add_labeled_entry(controls, "Music File", self.music_file_var, 2, width=72)
        self._add_labeled_scale(
            controls,
            "Music Volume",
            self.music_volume_idle_var,
            self.music_volume_idle_label_var,
            3,
            command=self._on_music_idle_volume_changed,
        )
        self._add_labeled_scale(
            controls,
            "Speech Duck Level",
            self.music_volume_ducked_var,
            self.music_volume_ducked_label_var,
            4,
            command=self._on_music_ducked_volume_changed,
        )
        self._add_labeled_entry(controls, "Log File", self.log_file_var, 5, width=72)

        filler_frame = ttk.LabelFrame(parent, text="Filler Topics", padding=10)
        filler_frame.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(
            filler_frame,
            text="Select the topics the anchor and analyst can use when the live feed goes quiet.",
        ).pack(anchor="w", pady=(0, 8))

        list_frame = ttk.Frame(filler_frame)
        list_frame.pack(fill="both", expand=True)
        self.filler_topic_listbox = tk.Listbox(list_frame, selectmode="multiple", exportselection=False, height=12)
        self.filler_topic_listbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.filler_topic_listbox.yview)
        scrollbar.pack(side="left", fill="y")
        self.filler_topic_listbox.configure(yscrollcommand=scrollbar.set)

        button_column = ttk.Frame(list_frame)
        button_column.pack(side="left", fill="y", padx=(12, 0))
        ttk.Button(button_column, text="Select All", command=self._select_all_filler_topics).pack(fill="x")
        ttk.Button(button_column, text="Clear Selection", command=self._clear_filler_selection).pack(fill="x", pady=(8, 0))
        ttk.Button(button_column, text="Remove Highlighted", command=self._remove_highlighted_filler_topics).pack(fill="x", pady=(8, 0))

        custom_row = ttk.Frame(filler_frame)
        custom_row.pack(fill="x", pady=(10, 0))
        ttk.Entry(custom_row, textvariable=self.new_filler_topic_var).pack(side="left", fill="x", expand=True)
        ttk.Button(custom_row, text="Add Custom Topic", command=self._add_custom_filler_topic).pack(side="left", padx=(8, 0))

    def _add_checkbox(self, parent: ttk.Frame, label: str, variable: tk.BooleanVar, row: int) -> ttk.Checkbutton:
        widget = ttk.Checkbutton(parent, text=label, variable=variable)
        widget.grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
        return widget

    def _add_labeled_entry(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        row: int,
        width: int = 28,
        show: str | None = None,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        entry = ttk.Entry(parent, textvariable=variable, width=width, show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)
        return entry

    def _add_labeled_combobox(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        values: list[str],
        row: int,
        width: int = 28,
        readonly: bool = True,
    ) -> ttk.Combobox:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, width=width, state="readonly" if readonly else "normal")
        combo.grid(row=row, column=1, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)
        return combo

    def _add_labeled_scale(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.DoubleVar,
        value_label_var: tk.StringVar,
        row: int,
        command: object | None = None,
    ) -> tk.Scale:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        scale = tk.Scale(
            parent,
            from_=0,
            to=100,
            orient="horizontal",
            resolution=1,
            showvalue=False,
            variable=variable,
            command=command,
            length=260,
        )
        scale.grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Label(parent, textvariable=value_label_var, width=6).grid(row=row, column=2, sticky="w", padx=(8, 0))
        parent.columnconfigure(1, weight=1)
        return scale

    def _set_listbox_items(self, items: list[str], selected_items: list[str]) -> None:
        self.available_filler_topics = list(items)
        self.filler_topic_listbox.delete(0, "end")
        for item in self.available_filler_topics:
            self.filler_topic_listbox.insert("end", item)
        selected_lookup = {item for item in selected_items}
        for index, item in enumerate(self.available_filler_topics):
            if item in selected_lookup:
                self.filler_topic_listbox.selection_set(index)

    def _load_filler_topics(self, selected_topics: list[str]) -> None:
        self._set_listbox_items(list(dict.fromkeys([*CURATED_FILLER_TOPICS, *selected_topics])), selected_topics)

    def _get_selected_filler_topics(self) -> list[str]:
        return [self.available_filler_topics[index] for index in self.filler_topic_listbox.curselection()]

    def _select_all_filler_topics(self) -> None:
        self.filler_topic_listbox.selection_set(0, "end")

    def _clear_filler_selection(self) -> None:
        self.filler_topic_listbox.selection_clear(0, "end")

    def _add_custom_filler_topic(self) -> None:
        topic = self.new_filler_topic_var.get().strip()
        if not topic:
            return
        if topic not in self.available_filler_topics:
            self.available_filler_topics.append(topic)
            self.filler_topic_listbox.insert("end", topic)
        self.filler_topic_listbox.selection_set(self.available_filler_topics.index(topic))
        self.new_filler_topic_var.set("")

    def _remove_highlighted_filler_topics(self) -> None:
        selected_indices = list(self.filler_topic_listbox.curselection())
        if not selected_indices:
            return
        selected_topics = self._get_selected_filler_topics()
        remaining = [topic for index, topic in enumerate(self.available_filler_topics) if index not in selected_indices]
        self._set_listbox_items(remaining, [topic for topic in selected_topics if topic in remaining])

    def _selected_saved_twitter_username(self) -> str | None:
        selection = self.saved_twitter_listbox.curselection()
        if not selection:
            return None
        selected_index = selection[0]
        if selected_index >= len(self.saved_twitter_accounts):
            return None
        return str(getattr(self.saved_twitter_accounts[selected_index], "username", ""))

    def _render_saved_twitter_accounts(self, accounts: list[object]) -> None:
        self.saved_twitter_accounts = list(accounts)
        self.saved_twitter_listbox.delete(0, "end")
        if not self.saved_twitter_accounts:
            self.twitter_account_status_var.set("No saved Twitter accounts in accounts.db yet")
            return

        for account in self.saved_twitter_accounts:
            username = str(getattr(account, "username", ""))
            active = "active" if bool(getattr(account, "active", False)) else "inactive"
            has_auth = "auth_token" if bool(getattr(account, "has_auth_token", False)) else "no-auth"
            has_ct0 = "ct0" if bool(getattr(account, "has_ct0", False)) else "no-ct0"
            error_msg = str(getattr(account, "error_msg", ""))
            suffix = f" | {error_msg}" if error_msg else ""
            self.saved_twitter_listbox.insert("end", f"@{username} | {active} | {has_auth} | {has_ct0}{suffix}")

        self.twitter_account_status_var.set(
            f"Loaded {len(self.saved_twitter_accounts)} saved Twitter account(s) from accounts.db"
        )

    def _refresh_saved_twitter_accounts(self) -> None:
        def worker() -> None:
            try:
                accounts = list_saved_twitter_accounts()
                self.output_queue.put(("twitter_accounts", accounts))
                self.output_queue.put(("status", "Saved Twitter accounts refreshed"))
            except Exception as exc:
                self.output_queue.put(("line", f"[twitter] Could not load saved accounts: {exc}"))
                self.output_queue.put(("status", "Saved Twitter account refresh failed"))

        threading.Thread(target=worker, name="twitter-accounts-refresh", daemon=True).start()

    def _load_selected_twitter_account(self) -> None:
        username = self._selected_saved_twitter_username()
        if not username:
            messagebox.showerror("Twitter Account", "Select a saved Twitter account first.", parent=self.root)
            self._set_status("No saved Twitter account selected")
            return

        def worker() -> None:
            try:
                account = load_saved_twitter_account(username)
                self.output_queue.put(("twitter_account_loaded", account))
                self.output_queue.put(("line", f"[twitter] Loaded saved account @{account.username} into the editor fields."))
                self.output_queue.put(("status", "Saved Twitter account loaded"))
            except Exception as exc:
                self.output_queue.put(("line", f"[twitter] Could not load saved account @{username}: {exc}"))
                self.output_queue.put(("status", "Saved Twitter account load failed"))

        threading.Thread(target=worker, name="twitter-account-load", daemon=True).start()

    def _delete_selected_twitter_account(self) -> None:
        username = self._selected_saved_twitter_username()
        if not username:
            messagebox.showerror("Twitter Account", "Select a saved Twitter account first.", parent=self.root)
            self._set_status("No saved Twitter account selected")
            return
        should_delete = messagebox.askyesno(
            "Delete Twitter Account",
            f"Delete saved Twitter account @{username} from the local accounts.db store?",
            parent=self.root,
        )
        if not should_delete:
            return

        def worker() -> None:
            try:
                delete_saved_twitter_account(username)
                accounts = list_saved_twitter_accounts()
                self.output_queue.put(("twitter_accounts", accounts))
                self.output_queue.put(("line", f"[twitter] Deleted saved account @{username}."))
                self.output_queue.put(("status", "Saved Twitter account deleted"))
            except Exception as exc:
                self.output_queue.put(("line", f"[twitter] Could not delete saved account @{username}: {exc}"))
                self.output_queue.put(("status", "Saved Twitter account deletion failed"))

        threading.Thread(target=worker, name="twitter-account-delete", daemon=True).start()

    def _reset_saved_twitter_locks(self) -> None:
        def worker() -> None:
            try:
                reset_twitter_locks()
                accounts = list_saved_twitter_accounts()
                self.output_queue.put(("twitter_accounts", accounts))
                self.output_queue.put(("line", "[twitter] Reset twscrape account locks in accounts.db."))
                self.output_queue.put(("status", "Twitter locks reset"))
            except Exception as exc:
                self.output_queue.put(("line", f"[twitter] Could not reset twscrape locks: {exc}"))
                self.output_queue.put(("status", "Twitter lock reset failed"))

        threading.Thread(target=worker, name="twitter-lock-reset", daemon=True).start()

    def _load_into_form(self, settings: RuntimeSettings) -> None:
        self.use_mock_var.set(settings.use_mock_twitter)
        self.use_music_var.set(settings.use_music)
        self.anchor_voice_id_var.set(settings.anchor_voice_id)
        self.analyst_voice_id_var.set(settings.analyst_voice_id)
        self.show_style_var.set(show_style_label_from_value(settings.show_style))
        self.idle_format_var.set(idle_format_label_from_value(settings.idle_format))
        self.log_level_var.set(settings.log_level)
        self.accounts_var.set(", ".join(settings.twitter_accounts))
        self.fetch_interval_var.set(str(settings.fetch_interval_seconds))
        self.recap_interval_var.set(str(settings.recap_interval_seconds))
        self.mock_batch_var.set(str(settings.mock_tweet_batch_size))
        self.filler_enabled_var.set(settings.filler_enabled)
        self.filler_interval_var.set(str(settings.filler_interval_seconds))
        self._load_filler_topics(settings.filler_topics)
        self.llm_backend_var.set(backend_label_from_settings(settings))
        self.ollama_model_var.set(settings.ollama_model)
        self.ollama_base_url_var.set(settings.ollama_base_url)
        self.api_base_url_var.set(settings.llm_api_base_url)
        self.api_model_var.set(settings.llm_api_model)
        self.api_key_var.set(settings.llm_api_key)
        self.api_key_env_var.set(settings.llm_api_key_env_var)
        self.max_retries_var.set(str(settings.ollama_max_retries))
        self.backoff_factor_var.set(str(settings.ollama_backoff_factor))
        self.music_file_var.set(settings.music_file)
        self.log_file_var.set(settings.log_file)
        self.music_volume_idle_var.set(round(settings.music_volume_idle * 100))
        self.music_volume_ducked_var.set(round(settings.music_volume_ducked * 100))
        self._set_music_volume_labels()

        self.provider_model_values = [settings.llm_api_model] if settings.llm_api_model else []
        self.api_model_combo.configure(values=self.provider_model_values)
        self.ollama_model_combo.configure(values=[settings.ollama_model] if settings.ollama_model else [])
        self._update_provider_fields()

    def _parse_positive_int(self, value: str, label: str) -> int:
        try:
            parsed = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{label} must be a positive integer.") from exc
        if parsed <= 0:
            raise ValueError(f"{label} must be a positive integer.")
        return parsed

    def _parse_positive_float(self, value: str, label: str) -> float:
        try:
            parsed = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"{label} must be a positive number.") from exc
        if parsed <= 0:
            raise ValueError(f"{label} must be a positive number.")
        return parsed

    def _parse_csv(self, value: str, label: str) -> list[str]:
        items = [item.strip() for item in value.split(",") if item.strip()]
        if not items:
            raise ValueError(f"{label} cannot be empty.")
        return items

    def _scale_percent_to_unit(self, value: float) -> float:
        return max(0.0, min(1.0, round(float(value) / 100.0, 2)))

    def _set_music_volume_labels(self) -> None:
        self.music_volume_idle_label_var.set(f"{int(round(self.music_volume_idle_var.get()))}%")
        ducked_value = min(self.music_volume_ducked_var.get(), self.music_volume_idle_var.get())
        if ducked_value != self.music_volume_ducked_var.get():
            self.music_volume_ducked_var.set(ducked_value)
        self.music_volume_ducked_label_var.set(f"{int(round(ducked_value))}%")

    def _on_music_idle_volume_changed(self, _value: object = None) -> None:
        self._set_music_volume_labels()

    def _on_music_ducked_volume_changed(self, _value: object = None) -> None:
        self._set_music_volume_labels()

    def _build_settings_from_form(self) -> RuntimeSettings:
        settings = replace(self.current_settings)
        backend_label = self.llm_backend_var.get().strip() or backend_label_from_settings(settings)
        settings.use_mock_twitter = self.use_mock_var.get()
        settings.use_music = self.use_music_var.get()
        settings.anchor_voice_id = self.anchor_voice_id_var.get().strip() or settings.anchor_voice_id
        settings.analyst_voice_id = self.analyst_voice_id_var.get().strip() or settings.analyst_voice_id
        settings.voice_id = settings.anchor_voice_id
        settings.show_style = show_style_value_from_label(self.show_style_var.get().strip())
        settings.idle_format = idle_format_value_from_label(self.idle_format_var.get().strip())
        settings.log_level = self.log_level_var.get().strip().upper() or settings.log_level
        settings.twitter_accounts = self._parse_csv(self.accounts_var.get(), "Twitter Accounts")
        settings.fetch_interval_seconds = self._parse_positive_int(self.fetch_interval_var.get(), "Fetch Interval")
        settings.recap_interval_seconds = self._parse_positive_int(self.recap_interval_var.get(), "Recap Interval")
        settings.mock_tweet_batch_size = self._parse_positive_int(self.mock_batch_var.get(), "Mock Batch Size")
        settings.filler_enabled = self.filler_enabled_var.get()
        settings.filler_interval_seconds = self._parse_positive_int(self.filler_interval_var.get(), "Filler Interval")
        settings.filler_topics = self._get_selected_filler_topics()
        if not settings.filler_topics:
            raise ValueError("Select at least one filler topic.")

        settings.llm_provider = provider_from_backend_label(backend_label)
        settings.ollama_model = self.ollama_model_var.get().strip() or settings.ollama_model
        settings.ollama_base_url = self.ollama_base_url_var.get().strip() or settings.ollama_base_url
        settings.llm_api_base_url = self.api_base_url_var.get().strip() or settings.llm_api_base_url
        if backend_label == "LM Studio" and not self.api_base_url_var.get().strip():
            settings.llm_api_base_url = LM_STUDIO_DEFAULT_BASE_URL
        settings.llm_api_model = self.api_model_var.get().strip() or settings.llm_api_model
        settings.llm_api_key = self.api_key_var.get().strip()
        settings.llm_api_key_env_var = self.api_key_env_var.get().strip()
        settings.ollama_max_retries = self._parse_positive_int(self.max_retries_var.get(), "Max Retries")
        settings.ollama_backoff_factor = self._parse_positive_float(self.backoff_factor_var.get(), "Backoff Factor")
        settings.music_file = self.music_file_var.get().strip() or settings.music_file
        settings.music_volume_idle = self._scale_percent_to_unit(self.music_volume_idle_var.get())
        settings.music_volume_ducked = min(
            settings.music_volume_idle,
            self._scale_percent_to_unit(self.music_volume_ducked_var.get()),
        )
        settings.log_file = self.log_file_var.get().strip() or settings.log_file
        return settings

    def _save_settings(self) -> bool:
        try:
            settings = self._build_settings_from_form()
            save_runtime_settings(self.settings_path, settings)
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            self._set_status("Settings validation failed")
            return False

        self.current_settings = settings
        self._refresh_voice_status()
        self._append_output(f"Saved settings to {self.settings_path}")
        self._set_status("Settings saved")
        return True

    def _append_output(self, line: str) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", line.rstrip() + "\n")
        self.output.see("end")
        self.output.configure(state="disabled")

    def _refresh_voice_status(self) -> None:
        model_path, voices_path = VoiceGenerator.detect_kokoro_assets()
        if model_path and voices_path:
            self.voice_status_var.set(
                f"High-quality voice pack detected: {model_path.name} + {voices_path.name}"
            )
        else:
            self.voice_status_var.set("High-quality Kokoro assets not detected; system voice fallback will be used")

    def _play_preview_audio(self, audio_path: Path) -> None:
        if os.name == "nt":
            try:
                import winsound

                winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
                return
            except Exception as exc:
                self._append_output(f"Preview playback failed: {exc}")
                return
        self._append_output(f"Preview generated at {audio_path}")

    def _preview_voices(self) -> None:
        try:
            settings = self._build_settings_from_form()
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            self._set_status("Preview blocked by invalid settings")
            return

        def worker() -> None:
            try:
                apply_runtime_settings(settings)
                voice_generator = VoiceGenerator()
                self.output_queue.put(("line", f"[preview] TTS backend: {voice_generator.describe_backend()}"))
                previews = [
                    ("anchor", settings.anchor_voice_id, "Anchor preview. This station now has a cleaner, more natural voice."),
                    ("analyst", settings.analyst_voice_id, "Analyst preview. We can add a second voice to keep the show moving."),
                ]
                for role, voice_id, text in previews:
                    audio_path = voice_generator.generate(text, voice_id)
                    self.output_queue.put(("line", f"[preview] {role.title()} voice {voice_id} -> {audio_path.name}"))
                    self._play_preview_audio(audio_path)
                self.output_queue.put(("line", "[preview] Voice preview finished"))
                self.output_queue.put(("status", "Voice preview finished"))
            except Exception as exc:
                self.output_queue.put(("line", f"[preview] Voice preview failed: {exc}"))
                self.output_queue.put(("status", "Voice preview failed"))

        threading.Thread(target=worker, name="voice-preview", daemon=True).start()
        self._set_status("Previewing voices")

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _set_combobox_state(self, widget: ttk.Combobox, enabled: bool, readonly: bool) -> None:
        widget.configure(state=("readonly" if readonly else "normal") if enabled else "disabled")

    def _update_provider_fields(self) -> None:
        provider = provider_from_backend_label(self.llm_backend_var.get())
        is_ollama = provider == "ollama"
        is_api = provider == "openai_compatible"
        for widget in self.ollama_controls:
            if isinstance(widget, ttk.Combobox):
                self._set_combobox_state(widget, is_ollama, readonly=False)
            else:
                widget.configure(state="normal" if is_ollama else "disabled")
        for widget in self.api_controls:
            if isinstance(widget, ttk.Combobox):
                self._set_combobox_state(widget, is_api, readonly=False)
            else:
                widget.configure(state="normal" if is_api else "disabled")
        self.refresh_models_button.configure(state="normal" if provider != "simple" else "disabled")

    def _apply_lm_studio_preset(self) -> None:
        self.llm_backend_var.set("LM Studio")
        self.api_base_url_var.set(LM_STUDIO_DEFAULT_BASE_URL)
        self.api_key_var.set("")
        if self.api_key_env_var.get().strip() == "OPENAI_API_KEY":
            self.api_key_env_var.set("")
        self._update_provider_fields()
        self._append_output("Applied LM Studio preset (backend=LM Studio, base=http://localhost:1234/v1)")
        self._set_status("LM Studio preset applied")

    def _detect_lm_studio(self) -> None:
        try:
            base_url, models = detect_lm_studio_endpoint()
        except Exception as exc:
            self._append_output(str(exc))
            self._set_status("LM Studio not detected")
            return
        self.llm_backend_var.set("LM Studio")
        self.api_base_url_var.set(base_url)
        self.provider_model_values = models
        self.api_model_combo.configure(values=models)
        if models:
            self.api_model_var.set(models[0])
        self._update_provider_fields()
        self._append_output(f"LM Studio reachable at {base_url}. Models: {', '.join(models[:5]) if models else 'none'}")
        self._set_status("LM Studio detected")

    def _refresh_models(self) -> None:
        provider = provider_from_backend_label(self.llm_backend_var.get())
        try:
            if provider == "ollama":
                models = fetch_ollama_models(self.ollama_base_url_var.get().strip())
                self.ollama_model_combo.configure(values=models)
                if models and not self.ollama_model_var.get().strip():
                    self.ollama_model_var.set(models[0])
            elif provider == "openai_compatible":
                models = fetch_openai_compatible_models(
                    self.api_base_url_var.get().strip(),
                    resolve_api_key(self.api_key_var.get().strip(), self.api_key_env_var.get().strip()),
                )
                self.provider_model_values = models
                self.api_model_combo.configure(values=models)
                if models and not self.api_model_var.get().strip():
                    self.api_model_var.set(models[0])
            else:
                self._append_output("Simple backend selected. No models to refresh.")
                self._set_status("No external models for Simple backend")
                return
        except Exception as exc:
            self._append_output(str(exc))
            self._set_status("Model refresh failed")
            return
        self._append_output(f"Detected models: {', '.join(models[:8]) if models else 'none'}")
        self._set_status("Model list refreshed")

    def _ping_provider(self) -> None:
        provider = provider_from_backend_label(self.llm_backend_var.get())
        try:
            if provider == "ollama":
                models = fetch_ollama_models(self.ollama_base_url_var.get().strip())
                message = f"Ollama reachable. Models: {', '.join(models[:5]) if models else 'none'}"
            elif provider == "openai_compatible":
                models = fetch_openai_compatible_models(
                    self.api_base_url_var.get().strip(),
                    resolve_api_key(self.api_key_var.get().strip(), self.api_key_env_var.get().strip()),
                )
                message = f"OpenAI-compatible endpoint reachable. Models: {', '.join(models[:5]) if models else 'none'}"
            else:
                message = "Simple backend selected. No network provider required."
        except Exception as exc:
            self._append_output(str(exc))
            self._set_status("Provider ping failed")
            return
        self._append_output(message)
        self._set_status("Provider ping succeeded")

    def _run_health_check(self) -> None:
        try:
            settings = self._build_settings_from_form()
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            self._set_status("Health check blocked by invalid settings")
            return
        apply_runtime_settings(settings)
        results = run_health_checks(settings)
        self._append_output("Health check results:")
        self._append_output(render_health_check_report(results))
        if any(result.status == "fail" for result in results):
            self._set_status("Health check found failures")
        elif any(result.status == "warn" for result in results):
            self._set_status("Health check finished with warnings")
        else:
            self._set_status("Health check passed")

    def _run_smoke_test(self) -> None:
        try:
            settings = self._build_settings_from_form()
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            self._set_status("Smoke test blocked by invalid settings")
            return
        apply_runtime_settings(settings)
        results = run_smoke_test(settings)
        self._append_output("Smoke test results:")
        self._append_output(render_health_check_report(results))
        if any(result.status == "fail" for result in results):
            self._set_status("Smoke test found failures")
        elif any(result.status == "warn" for result in results):
            self._set_status("Smoke test finished with warnings")
        else:
            self._set_status("Smoke test passed")

    def _show_twitter_setup(self) -> None:
        self._append_output("Twitter setup:")
        for line in TWITTER_SETUP_LINES:
            self._append_output(line)
        self._set_status("Twitter setup steps shown")

    def _reset_twitter_secret_fields(self) -> None:
        self.twitter_cookie_string_var.set("")
        self.twitter_auth_token_var.set("")
        self.twitter_ct0_var.set("")

    def _clear_twitter_secret_fields(self) -> None:
        self._reset_twitter_secret_fields()
        self._append_output("Cleared Twitter session fields from the launcher.")
        self._set_status("Twitter fields cleared")

    def _import_twitter_session(self) -> None:
        username = self.twitter_username_var.get().strip()
        cookie_string = self.twitter_cookie_string_var.get().strip()
        auth_token = self.twitter_auth_token_var.get().strip()
        ct0 = self.twitter_ct0_var.get().strip()

        def worker() -> None:
            try:
                result = import_twitter_session(
                    username=username,
                    cookie_string=cookie_string,
                    auth_token=auth_token,
                    ct0=ct0,
                )
                account_count = "unknown" if result.account_count is None else str(result.account_count)
                self.output_queue.put(
                    (
                        "line",
                        (
                            f"[twitter] Imported session for @{result.username} into {result.db_path}. "
                            f"Active={result.active}. Saved accounts={account_count}."
                        ),
                    )
                )
                self.output_queue.put(("twitter_accounts", list_saved_twitter_accounts()))
                self.output_queue.put(("status", "Twitter session imported"))
                self.output_queue.put(("clear_twitter_fields", None))
            except Exception as exc:
                self.output_queue.put(("line", f"[twitter] Session import failed: {exc}"))
                self.output_queue.put(("status", "Twitter session import failed"))

        if not username:
            messagebox.showerror("Twitter Session", "Twitter username is required.", parent=self.root)
            self._set_status("Twitter session import failed")
            return

        threading.Thread(target=worker, name="twitter-session-import", daemon=True).start()
        self._set_status("Importing Twitter session")

    def _start_station(self) -> None:
        if self.process and self.process.poll() is None:
            self._set_status("Station is already running")
            return
        if not self._save_settings():
            return
        command = [sys.executable, "-u", "main.py", "--no-gui", "--config", str(self.settings_path)]
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.process = subprocess.Popen(
            command,
            cwd=str(self.project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        threading.Thread(target=self._read_process_output, name="station-output", daemon=True).start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._append_output(f"[launcher] Started station with {' '.join(command)}")
        self._set_status("Station running")

    def _read_process_output(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self.output_queue.put(("line", line.rstrip("\n")))
        self.output_queue.put(("exit", process.wait()))

    def _drain_output_queue(self) -> None:
        while not self.output_queue.empty():
            kind, payload = self.output_queue.get_nowait()
            if kind == "line":
                self._append_output(str(payload))
            elif kind == "status":
                self._set_status(str(payload))
            elif kind == "exit":
                exit_code = int(payload)
                self.process = None
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self._append_output(f"[launcher] Station exited with code {exit_code}")
                self._set_status(f"Station stopped (code {exit_code})")
            elif kind == "clear_twitter_fields":
                self._reset_twitter_secret_fields()
            elif kind == "twitter_accounts":
                self._render_saved_twitter_accounts(list(payload))
            elif kind == "twitter_account_loaded":
                account = payload
                self.twitter_username_var.set(str(getattr(account, "username", "")))
                self.twitter_auth_token_var.set(str(getattr(account, "auth_token", "")))
                self.twitter_ct0_var.set(str(getattr(account, "ct0", "")))
                self.twitter_cookie_string_var.set("")
        self.root.after(150, self._drain_output_queue)

    def _stop_station(self) -> None:
        if self.process is None or self.process.poll() is not None:
            self._set_status("Station is not running")
            return
        self._append_output("[launcher] Stopping station...")
        if os.name == "nt":
            try:
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:
                self.process.terminate()
        else:
            self.process.terminate()
        self.root.after(3000, self._kill_station_if_needed)
        self._set_status("Stopping station")

    def _kill_station_if_needed(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self._append_output("[launcher] Station did not exit in time; terminating process.")
            self.process.kill()

    def _on_close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            should_close = messagebox.askyesno(
                "Stop Station",
                "The station is still running. Stop it and close the launcher?",
                parent=self.root,
            )
            if not should_close:
                return
            self._stop_station()
            self.root.after(400, self.root.destroy)
            return
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def run_gui(settings_path: Path | None = None) -> int:
    """Launch the settings GUI."""
    resolved_path = settings_path or config.get_settings_file()
    return LauncherGUI(resolved_path).run()
