"""CustomTkinter config window for CoworkSync."""

import sys
import threading
from datetime import datetime
from tkinter import filedialog

import customtkinter

from coworksync.config import (
    load_config, save_config, validate_source, validate_local,
    warn_local, set_startup, get_startup_enabled, save_state,
)
from coworksync.logger import LOG_FILE

customtkinter.set_appearance_mode("System")
customtkinter.set_default_color_theme("blue")

# Singleton window reference
_window = None
_engine = None


def set_engine(engine):
    """Set the sync engine reference."""
    global _engine
    _engine = engine


def open_window():
    """Open the config window. If already open, bring to front."""
    global _window
    if _window is not None and _window.winfo_exists():
        _window.lift()
        _window.focus_force()
        return
    _window = ConfigWindow()
    _window.mainloop()


def open_window_threaded():
    """Open the config window from a non-main thread."""
    threading.Thread(target=open_window, daemon=True).start()


class ConfigWindow(customtkinter.CTk):
    """Main configuration window."""

    def __init__(self):
        super().__init__()

        self.title("CoworkSync")
        self.geometry("420x580")
        self.resizable(False, True)

        self._build_ui()
        self._load_current_config()
        self._refresh_status()

    def _build_ui(self):
        self._main_scroll = customtkinter.CTkScrollableFrame(self)
        self._main_scroll.pack(fill="both", expand=True, padx=0, pady=0)

        # --- Folder config ---
        config_frame = customtkinter.CTkFrame(self._main_scroll)
        config_frame.pack(fill="x", padx=15, pady=(15, 5))

        customtkinter.CTkLabel(config_frame, text="Cloud Folder").pack(anchor="w", padx=10, pady=(10, 0))
        source_row = customtkinter.CTkFrame(config_frame, fg_color="transparent")
        source_row.pack(fill="x", padx=10, pady=(2, 5))
        self.source_entry = customtkinter.CTkEntry(source_row, width=290)
        self.source_entry.pack(side="left", fill="x", expand=True)
        customtkinter.CTkButton(source_row, text="Browse", width=70, command=self._browse_source).pack(side="right", padx=(5, 0))

        customtkinter.CTkLabel(config_frame, text="Claude Cowork Folder").pack(anchor="w", padx=10, pady=(5, 0))
        local_row = customtkinter.CTkFrame(config_frame, fg_color="transparent")
        local_row.pack(fill="x", padx=10, pady=(2, 5))
        self.local_entry = customtkinter.CTkEntry(local_row, width=290)
        self.local_entry.pack(side="left", fill="x", expand=True)
        customtkinter.CTkButton(local_row, text="Browse", width=70, command=self._browse_local).pack(side="right", padx=(5, 0))

        customtkinter.CTkLabel(
            config_frame,
            text="Changing paths will stop sync. You must restart manually.",
            text_color="gray",
            font=("", 11),
        ).pack(anchor="w", padx=10, pady=(0, 8))

        customtkinter.CTkLabel(config_frame, text="Sync Interval (minutes)").pack(anchor="w", padx=10, pady=(5, 0))
        self.interval_entry = customtkinter.CTkEntry(config_frame, width=80)
        self.interval_entry.pack(anchor="w", padx=10, pady=(2, 5))

        self.startup_var = customtkinter.BooleanVar()
        self.startup_check = customtkinter.CTkCheckBox(config_frame, text="Start with Windows", variable=self.startup_var)
        self.startup_check.pack(anchor="w", padx=10, pady=(5, 10))

        # --- Folder Rules ---
        rules_frame = customtkinter.CTkFrame(self._main_scroll)
        rules_frame.pack(fill="x", padx=15, pady=5)

        customtkinter.CTkLabel(rules_frame, text="Folder Rules", font=("", 13, "bold")).pack(anchor="w", padx=10, pady=(10, 5))

        customtkinter.CTkLabel(
            rules_frame,
            text="All folders sync two-way by default. Add exceptions below.",
            text_color="gray",
            font=("", 11),
        ).pack(anchor="w", padx=10, pady=(0, 5))

        self._rules_container = customtkinter.CTkScrollableFrame(rules_frame, height=100)
        self._rules_container.pack(fill="x", padx=10, pady=(0, 5))

        self._rule_rows = []  # list of {frame, path_var, mode_menu, mode_var}

        customtkinter.CTkButton(
            rules_frame, text="+ Add Rule", width=100,
            command=self._add_rule_row
        ).pack(anchor="w", padx=10, pady=(0, 10))

        # --- Status block ---
        status_frame = customtkinter.CTkFrame(self._main_scroll)
        status_frame.pack(fill="x", padx=15, pady=5)

        customtkinter.CTkLabel(status_frame, text="Status", font=("", 13, "bold")).pack(anchor="w", padx=10, pady=(10, 5))

        self.status_label = customtkinter.CTkLabel(status_frame, text="Status: Stopped")
        self.status_label.pack(anchor="w", padx=10)
        self.last_sync_label = customtkinter.CTkLabel(status_frame, text="Last sync: Never")
        self.last_sync_label.pack(anchor="w", padx=10)
        self.next_poll_label = customtkinter.CTkLabel(status_frame, text="Next poll: —")
        self.next_poll_label.pack(anchor="w", padx=10)
        self.files_label = customtkinter.CTkLabel(status_frame, text="Files synced today: 0")
        self.files_label.pack(anchor="w", padx=10, pady=(0, 10))

        # --- Buttons ---
        btn_frame = customtkinter.CTkFrame(self._main_scroll, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=5)

        self.save_btn = customtkinter.CTkButton(btn_frame, text="Save", command=self._on_save)
        self.save_btn.pack(side="left", expand=True, padx=(0, 5))

        self.toggle_btn = customtkinter.CTkButton(btn_frame, text="Stop", command=self._on_toggle)
        self.toggle_btn.pack(side="left", expand=True, padx=(5, 5))

        self.sync_now_btn = customtkinter.CTkButton(btn_frame, text="Sync Now", command=self._on_sync_now, state="disabled")
        self.sync_now_btn.pack(side="left", expand=True, padx=(5, 0))

        # --- Error/warning label ---
        self.message_label = customtkinter.CTkLabel(self._main_scroll, text="", text_color="red")
        self.message_label.pack(fill="x", padx=15)

        # --- Activity log ---
        log_frame = customtkinter.CTkFrame(self._main_scroll)
        log_frame.pack(fill="both", expand=True, padx=15, pady=(5, 15))

        customtkinter.CTkLabel(log_frame, text="Activity Log", font=("", 13, "bold")).pack(anchor="w", padx=10, pady=(10, 5))

        self.log_text = customtkinter.CTkTextbox(log_frame, height=120, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _load_current_config(self):
        cfg = load_config()
        self._saved_source = cfg.get("source_folder", "")
        self._saved_local = cfg.get("local_folder", "")
        self.source_entry.insert(0, self._saved_source)
        self.local_entry.insert(0, self._saved_local)
        self.interval_entry.insert(0, str(cfg.get("sync_interval", 5)))
        self.startup_var.set(get_startup_enabled())

        # Load folder rules
        rules = cfg.get("folder_rules", [{"path": "processing", "mode": "ignore"}])
        for rule in rules:
            self._add_rule_row(path=rule.get("path", ""), mode=rule.get("mode", "ignore"))

    MODE_OPTIONS = ["two-way", "source-to-local", "local-to-source", "ignore"]

    def _get_available_subfolders(self):
        """Scan both configured folders and return a sorted list of subfolder relative paths."""
        import os
        subfolders = set()
        for root_path in [self.source_entry.get().strip(), self.local_entry.get().strip()]:
            if root_path and os.path.isdir(root_path):
                for entry in os.scandir(root_path):
                    if entry.is_dir() and not entry.name.startswith("."):
                        subfolders.add(entry.name)
                        # Also scan one level deeper for nested folders
                        try:
                            for sub_entry in os.scandir(entry.path):
                                if sub_entry.is_dir() and not sub_entry.name.startswith("."):
                                    subfolders.add(f"{entry.name}/{sub_entry.name}")
                        except OSError:
                            pass
        # Remove any folders that already have rules
        existing_paths = {row["path_var"].get().lower() for row in self._rule_rows if "path_var" in row}
        available = sorted(subfolders - existing_paths)
        return available if available else ["(no folders found)"]

    def _add_rule_row(self, path="", mode="ignore"):
        """Add a folder rule row to the rules editor."""
        row_frame = customtkinter.CTkFrame(self._rules_container, fg_color="transparent")
        row_frame.pack(fill="x", pady=2)

        path_var = customtkinter.StringVar(value=path)

        if path:
            # Existing rule — show as a read-only label (already configured)
            path_label = customtkinter.CTkLabel(row_frame, text=path, width=160, anchor="w")
            path_label.pack(side="left", padx=(0, 5))
        else:
            # New rule — show dropdown of available subfolders
            available = self._get_available_subfolders()
            path_menu = customtkinter.CTkOptionMenu(row_frame, variable=path_var, values=available, width=160)
            path_menu.pack(side="left", padx=(0, 5))
            if available and available[0] != "(no folders found)":
                path_var.set(available[0])

        mode_var = customtkinter.StringVar(value=mode)
        mode_menu = customtkinter.CTkOptionMenu(row_frame, variable=mode_var, values=self.MODE_OPTIONS, width=140)
        mode_menu.pack(side="left", padx=(0, 5))

        delete_btn = customtkinter.CTkButton(
            row_frame, text="x", width=30,
            command=lambda: self._remove_rule_row(row_frame)
        )
        delete_btn.pack(side="left")

        row_data = {
            "frame": row_frame,
            "path_var": path_var,
            "mode_menu": mode_menu,
            "mode_var": mode_var,
        }
        self._rule_rows.append(row_data)

    def _remove_rule_row(self, frame):
        """Remove a folder rule row."""
        self._rule_rows = [r for r in self._rule_rows if r["frame"] != frame]
        frame.destroy()

    def _get_folder_rules(self):
        """Collect folder rules from the UI rows."""
        rules = []
        for row in self._rule_rows:
            path = row["path_var"].get().strip().replace("\\", "/").strip("/")
            mode = row["mode_var"].get()
            if path and path != "(no folders found)":
                rules.append({"path": path, "mode": mode})
        # Ensure processing/ignore is always present
        has_processing = any(r["path"].lower() == "processing" and r["mode"] == "ignore" for r in rules)
        if not has_processing:
            rules.insert(0, {"path": "processing", "mode": "ignore"})
        return rules

    def _browse_source(self):
        path = filedialog.askdirectory(title="Select Cloud Folder")
        if path:
            self.source_entry.delete(0, "end")
            self.source_entry.insert(0, path)
            self._on_path_changed()

    def _browse_local(self):
        path = filedialog.askdirectory(title="Select Claude Cowork Folder")
        if path:
            self.local_entry.delete(0, "end")
            self.local_entry.insert(0, path)
            self._on_path_changed()

    def _on_path_changed(self):
        """Stop sync and clear state when either folder path is changed."""
        new_source = self.source_entry.get().strip()
        new_local = self.local_entry.get().strip()
        if new_source == self._saved_source and new_local == self._saved_local:
            return
        if _engine and _engine.running:
            _engine.stop()
        save_state({})
        self._update_status_display()

    def _on_save(self):
        source = self.source_entry.get().strip()
        local = self.local_entry.get().strip()

        err = validate_source(source)
        if err:
            self.message_label.configure(text=err, text_color="red")
            return
        err = validate_local(local)
        if err:
            self.message_label.configure(text=err, text_color="red")
            return

        try:
            interval = int(self.interval_entry.get())
            interval = max(1, min(60, interval))
        except (TypeError, ValueError):
            interval = 5

        cfg = {
            "source_folder": source,
            "local_folder": local,
            "sync_interval": interval,
            "start_with_windows": self.startup_var.get(),
            "folder_rules": self._get_folder_rules(),
        }
        save_config(cfg)

        exe = sys.executable
        set_startup(self.startup_var.get(), exe)

        self._saved_source = source
        self._saved_local = local

        if _engine:
            _engine.configure(cfg)

        warning = warn_local(local)
        if warning:
            self.message_label.configure(text=warning, text_color="orange")
        else:
            self.message_label.configure(text="Config saved.", text_color="green")

    def _on_toggle(self):
        if not _engine:
            return
        if _engine.running:
            _engine.stop()
        else:
            _engine.start()
        self._update_status_display()

    def _on_sync_now(self):
        if _engine:
            _engine.sync_now()
        self._update_status_display()

    def _refresh_status(self):
        """Auto-refresh status and log every 15 seconds."""
        self._update_status_display()
        self._update_log()
        self.after(15000, self._refresh_status)

    def _update_status_display(self):
        if not _engine:
            return

        status = _engine.status.capitalize()
        color = {"Running": "green", "Syncing": "orange", "Error": "red", "Stopped": "gray"}.get(status, "gray")
        self.status_label.configure(text=f"Status: {status}", text_color=color)

        if _engine.last_sync:
            delta = datetime.now() - _engine.last_sync
            secs = int(delta.total_seconds())
            if secs < 60:
                rel = f"{secs}s ago"
            elif secs < 3600:
                rel = f"{secs // 60}m ago"
            else:
                rel = _engine.last_sync.strftime("%H:%M:%S")
            self.last_sync_label.configure(text=f"Last sync: {rel}")
        else:
            self.last_sync_label.configure(text="Last sync: Never")

        if _engine.next_poll:
            remaining = _engine.next_poll - datetime.now().timestamp()
            mins = max(0, int(remaining) // 60)
            self.next_poll_label.configure(text=f"Next poll: {mins}m")
        else:
            self.next_poll_label.configure(text="Next poll: —")

        self.files_label.configure(text=f"Files synced today: {_engine.files_today}")

        if _engine.running:
            self.toggle_btn.configure(text="Stop")
            self.sync_now_btn.configure(state="normal")
        else:
            self.toggle_btn.configure(text="Resume")
            self.sync_now_btn.configure(state="disabled")

    def _update_log(self):
        if not _engine:
            return

        lines = []
        for entry in _engine.recent_activity[:10]:
            direction = entry.get("direction", "")
            line = f"[{entry['time']}] {entry['action']}  {entry['file']}"
            if direction:
                line += f"  {direction}"
            lines.append(line)

        if not lines:
            # Fallback: read from log file
            try:
                import os
                if os.path.exists(LOG_FILE):
                    with open(LOG_FILE, "r", encoding="utf-8") as f:
                        raw = f.readlines()[-10:]
                    lines = [l.strip() for l in raw if l.strip()]
            except OSError:
                pass

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")

        for line in lines:
            tag = None
            if "Error" in line or "ERROR" in line:
                tag = "error"
            elif "Conflict" in line or "CONFLICT" in line:
                tag = "conflict"
            self.log_text.insert("end", line + "\n")

        self.log_text.configure(state="disabled")
