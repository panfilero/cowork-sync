"""System tray icon and menu using pystray."""

import os
import sys
import subprocess
import threading

import pystray
from PIL import Image

from coworksync.logger import LOG_FILE
from coworksync import ui

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")

# When bundled with PyInstaller, assets are extracted to _MEIPASS/coworksync/assets
if getattr(sys, "frozen", False):
    ASSETS_DIR = os.path.join(sys._MEIPASS, "coworksync", "assets")


def _load_icon(name):
    """Load a PNG icon from the assets folder."""
    path = os.path.join(ASSETS_DIR, name)
    return Image.open(path)


class TrayApp:
    """Manages the system tray icon and menu."""

    def __init__(self, engine):
        self.engine = engine
        self._icon = None
        self._icons = {}

    def _get_icon(self, color):
        """Load and cache an icon by color name."""
        if color not in self._icons:
            self._icons[color] = _load_icon(f"icon_{color}.png")
        return self._icons[color]

    def _build_menu(self):
        paused = not self.engine.running
        pause_label = "Resume" if paused else "Pause"

        return pystray.Menu(
            pystray.MenuItem("Status", self._on_status),
            pystray.MenuItem("Sync Now", self._on_sync_now, enabled=self.engine.running),
            pystray.MenuItem("Open Config", self._on_open_config),
            pystray.MenuItem("View Log", self._on_view_log),
            pystray.MenuItem(pause_label, self._on_pause_resume),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._on_exit),
        )

    def _on_status(self, icon, item):
        last = self.engine.last_sync
        last_str = last.strftime("%H:%M:%S") if last else "Never"
        count = self.engine.files_today
        status = self.engine.status
        msg = f"Status: {status}\nLast sync: {last_str}\nFiles synced today: {count}"
        icon.notify(msg, "CoworkSync")

    def _on_sync_now(self, icon, item):
        self.engine.sync_now()

    def _on_open_config(self, icon, item):
        ui.open_window_threaded()

    def _on_view_log(self, icon, item):
        if os.path.exists(LOG_FILE):
            subprocess.Popen(["notepad.exe", LOG_FILE])

    def _on_pause_resume(self, icon, item):
        if self.engine.running:
            self.engine.stop()
        else:
            self.engine.start()
        self.update_icon()

    def _on_exit(self, icon, item):
        self.engine.stop()
        icon.stop()

    def update_icon(self):
        """Update the tray icon based on engine status."""
        if self._icon is None:
            return
        status = self.engine.status
        if status == "error":
            self._icon.icon = self._get_icon("red")
        elif status == "syncing":
            self._icon.icon = self._get_icon("yellow")
        elif status == "running":
            self._icon.icon = self._get_icon("green")
        else:
            self._icon.icon = self._get_icon("red")

    def run(self):
        """Create and run the tray icon (blocking)."""
        self._icon = pystray.Icon(
            "CoworkSync",
            icon=self._get_icon("green"),
            title="CoworkSync",
            menu=self._build_menu(),
        )

        # Periodically update icon color
        def _updater():
            import time
            while self._icon and self._icon.visible:
                try:
                    self.update_icon()
                except Exception:
                    pass
                time.sleep(3)

        updater_thread = threading.Thread(target=_updater, daemon=True)
        updater_thread.start()

        self._icon.run()

    def stop(self):
        """Stop the tray icon."""
        if self._icon:
            self._icon.stop()
