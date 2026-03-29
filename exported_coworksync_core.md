# CoworkSync — Core Engine Export

**Exported:** 2026-03-29 16:15:38 (local)  
**Stack:** Python + watchdog + pystray + CustomTkinter (Windows)  
**Scope:** Sync engine, config/state, logger, entry point, build config  
**Excludes:** UI window, tray icon, icon generation  

---

## Project Structure

```
./
    CLAUDE.md
    CoworkSync-Spec.md
    CoworkSync.spec
    REFACTOR.md
    build.bat
    requirements.txt
    coworksync/
        __init__.py
        config.py
        generate_icons.py
        logger.py
        main.py
        sync_engine.py
        tray.py
        ui.py
        assets/
            icon_green.ico
            icon_green.png
            icon_red.ico
            icon_red.png
            icon_yellow.ico
            icon_yellow.png
```

---

## Source Files

### `CLAUDE.md`

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CoworkSync is a Windows-only background service that maintains two-way file synchronization between a cloud-synced folder (Google Drive, Dropbox, etc.) and a local Cowork workspace folder. It runs as a system tray application with a CustomTkinter desktop UI for configuration.

## Build & Run

```bash
# Install dependencies
pip install -r requirements.txt

# Build single-file executable (generates icons first, then runs PyInstaller)
build.bat

# Run the built executable
dist/CoworkSync.exe

# Run from source (for development)
python coworksync/main.py

# Run with debug-level logging (every mtime comparison, copy call, suppression hit)
python coworksync/main.py --verbose
```

There is no test suite. Testing is done manually by running the application.

## Architecture

**Entry point:** `coworksync/main.py` — creates SyncEngine, wires the UI engine reference, loads config, and runs the system tray (blocking). Opens the CustomTkinter config window on demand via tray or automatically on first run.

**Core modules:**
- `sync_engine.py` — Two-way sync using watchdog (real-time file events, debounced 2s) + fallback polling (default every 5 min). Conflict resolution is last-write-wins. Status states: `stopped` → `running` → `syncing` / `error`. Contains sync-loop suppression logic (see Key Design Decisions).
- `config.py` — JSON config at `%APPDATA%\CoworkSync\config.json`, state DB at `state.json`, Windows registry integration for startup.
- `ui.py` — CustomTkinter config window, opens via tray "Open Config". Singleton pattern (brings to front if already open). Auto-refreshes status and activity log every 15s via `after()` loop.
- `tray.py` — pystray system tray icon with color-coded status (green=running, yellow=syncing, red=error). Updates every 3s.
- `logger.py` — Rotating file logger (5MB, 2 backups) at `%APPDATA%\CoworkSync\coworksync.log`. Exposes `enable_verbose()` to switch to DEBUG level.

**Build:** PyInstaller via `CoworkSync.spec` — windowed mode, single file, bundles assets and customtkinter data (`collect_data_files`). `generate_icons.py` creates 64×64 PNG and ICO tray icons before build.

## Key Design Decisions

- **Dual sync:** Watchdog + polling for reliability across virtual file systems (Google Drive VFS).
- **Direct deletion:** Uses `os.remove()`/`shutil.rmtree()` (never recycle bin) so cloud clients register changes.
- **Excluded paths:** `processing/` folder, `thumbs.db`, `desktop.ini`, `.ds_store`, `*.tmp`, `*.ffs_db`, `*.ffs_lock`.
- **FAT32 tolerance:** 2-second mtime comparison tolerance for cross-filesystem compatibility.
- **No external database:** Simple JSON files for all persistent state.
- **All copies go through `copy_file()`:** Uses `CopyFileExW` (not `shutil.copy2`) so minifilter drivers like Google Drive register the write. `shutil.copy2` is only the non-Windows fallback inside that function.
- **Sync-loop suppression:** `SyncEngine._suppressed` is a `{abs_dst_path: monotonic_timestamp}` dict. Before every watchdog-triggered copy, the destination path is added to the dict. When the other watcher fires for that same path (the echo event), `_handle_event` checks `_is_suppressed(src_path)` and skips with `SKIP (suppressed)` logged. Window is 5 seconds. Entries are pruned lazily on each `_suppress()` call.
- **Watchdog mtime guard:** `_handle_event` stats both sides before copying. If `|src_mtime - dst_mtime| ≤ 2.0s`, the copy is skipped. This catches Google Drive post-ingest timestamp touches.
- **Immediate state update after watchdog copy:** After each `_handle_event` copy, `_update_state_for_file` writes the new mtime into `state.json` under `_lock`. This prevents the next poll cycle from seeing a mismatch and re-copying.

## Known Issues / Active Investigation

- **Poll not syncing after initial full sync (under investigation):** Suspected cause is Google Drive modifying file timestamps after ingestion, causing the 2s mtime tolerance to mask real differences. Run with `--verbose` and look for `SKIP` lines with near-zero diffs to confirm.

## Logging Reference

Log is at `%APPDATA%\CoworkSync\coworksync.log`.

| Log prefix | Meaning |
|---|---|
| `COPY` | File copied (poll or watchdog) |
| `DELETE` | File or directory deleted |
| `SKIP (suppressed)` | Watchdog echo event suppressed — working correctly |
| `SKIP` (DEBUG) | Poll or watchdog skipped due to matching mtimes |
| `COPY→L` / `COPY→S` (DEBUG) | Poll decision with exact mtime values |
| `DEL←S` / `DEL←L` (DEBUG) | Poll deletion decision |
| `copy_file: CopyFileExW` (DEBUG) | Low-level copy call and success/failure |
```

---

### `requirements.txt`

```text
watchdog
pystray
Pillow
schedule
customtkinter
pyinstaller
```

---

### `build.bat`

```bat
@echo off
echo Generating icons...
python coworksync/generate_icons.py
if errorlevel 1 (
    echo Icon generation failed!
    pause
    exit /b 1
)
echo.
echo Building CoworkSync...
pyinstaller --clean CoworkSync.spec
echo.
echo Done. Output: dist\CoworkSync.exe
pause
```

---

### `CoworkSync.spec`

```python
# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

datas = []
datas += collect_data_files('customtkinter')

a = Analysis(
    ['coworksync/main.py'],
    pathex=[],
    binaries=[],
    datas=datas + [
        ('coworksync/assets', 'coworksync/assets'),
    ],
    hiddenimports=[
        'watchdog.observers.winapi',
        'pystray._win32',
        'PIL._tkinter_finder',
        'customtkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CoworkSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='coworksync/assets/icon_green.ico',
)
```

---

### `coworksync/main.py`

```python
"""CoworkSync — entry point. Initializes tray, sync engine, and UI."""

import sys

from coworksync.config import load_config, is_configured
from coworksync.sync_engine import SyncEngine
from coworksync.tray import TrayApp
from coworksync.logger import logger, enable_verbose
from coworksync import ui


def main_ui_only():
    """Open just the CustomTkinter config window, bypassing the tray."""
    engine = SyncEngine()
    ui.set_engine(engine)
    cfg = load_config()
    if is_configured(cfg):
        engine.configure(cfg)
        engine.start()
    ui.open_window()
    engine.stop()


def main():
    if "--verbose" in sys.argv:
        enable_verbose()
        logger.debug("Verbose/debug logging enabled.")
    logger.info("CoworkSync starting up.")

    # Create sync engine
    engine = SyncEngine()

    # Wire the UI to the engine
    ui.set_engine(engine)

    # Load config and auto-start sync if configured
    cfg = load_config()
    if is_configured(cfg):
        engine.configure(cfg)
        engine.start()
    else:
        logger.info("No config found — open the tray menu to configure.")
        ui.open_window_threaded()

    # Run system tray (blocking — runs the Windows message loop)
    tray = TrayApp(engine)
    try:
        tray.run()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        logger.info("CoworkSync shut down.")


if __name__ == "__main__":
    if "--ui-only" in sys.argv:
        main_ui_only()
    else:
        main()
```

---

### `coworksync/sync_engine.py`

```python
"""Core sync logic — watchdog observer, debounced events, fallback polling, state DB."""

import os
import sys
import shutil
import ctypes
import time
import threading
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from coworksync.config import load_config, load_state, save_state
from coworksync.logger import logger

# --- Exclusions ---

EXCLUDED_FOLDERS = {"processing"}
EXCLUDED_FILES = {"thumbs.db", "desktop.ini", ".ds_store", "coworksync.log", "sync.ffs_db"}
EXCLUDED_EXTENSIONS = {".tmp", ".ffs_db", ".ffs_lock"}


def _is_excluded(rel_path):
    """Check if a relative path should be excluded from sync."""
    parts = rel_path.replace("\\", "/").split("/")
    for part in parts:
        if part.lower() in EXCLUDED_FOLDERS:
            return True
    name = os.path.basename(rel_path).lower()
    if name in EXCLUDED_FILES:
        return True
    _, ext = os.path.splitext(name)
    if ext in EXCLUDED_EXTENSIONS:
        return True
    return False


def _rel(path, root):
    """Get relative path from root."""
    return os.path.relpath(path, root)


# --- File operations ---

def delete_path(path):
    """Delete a file or directory. Never use recycle bin."""
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.isfile(path):
        os.remove(path)


def copy_file(src, dst):
    """Copy a file via Win32 CopyFileExW so minifilter drivers (e.g. Google Drive)
    register the operation. Falls back to shutil.copy2 on non-Windows."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if sys.platform == "win32":
        logger.debug("copy_file: CopyFileExW %s -> %s", src, dst)
        ok = ctypes.windll.kernel32.CopyFileExW(
            ctypes.c_wchar_p(src),
            ctypes.c_wchar_p(dst),
            None,   # progress callback
            None,   # callback data
            ctypes.c_bool(False),  # cancel flag
            0,      # flags
        )
        if not ok:
            err = ctypes.GetLastError()
            raise OSError(err, ctypes.FormatError(err), src)
        logger.debug("copy_file: CopyFileExW succeeded %s", dst)
    else:
        logger.debug("copy_file: shutil.copy2 %s -> %s", src, dst)
        shutil.copy2(src, dst)
        logger.debug("copy_file: shutil.copy2 succeeded %s", dst)


# --- Sync Engine ---

class SyncEngine:
    """Two-way folder sync engine with watchdog + polling."""

    def __init__(self):
        self.source = ""
        self.local = ""
        self.interval = 5  # minutes
        self.running = False
        self.syncing = False
        self.observer = None
        self.poll_timer = None
        self.last_sync = None
        self.next_poll = None
        self.files_today = 0
        self._files_today_date = None
        self._lock = threading.Lock()
        self._debounce_timers = {}
        self._suppressed = {}  # {abs_dst_path: monotonic_timestamp} — echo-event suppression
        self._stop_event = threading.Event()
        self.status = "stopped"  # stopped | running | syncing | error
        self.error_message = ""
        self.recent_activity = []  # list of dicts: {time, action, file, direction}

    def _add_activity(self, action, filename, direction=""):
        """Record a recent activity entry."""
        entry = {
            "time": datetime.now().strftime("%H:%M"),
            "action": action,
            "file": filename,
            "direction": direction,
        }
        self.recent_activity.insert(0, entry)
        self.recent_activity = self.recent_activity[:50]

    def _increment_files_today(self):
        today = datetime.now().date()
        if self._files_today_date != today:
            self.files_today = 0
            self._files_today_date = today
        self.files_today += 1

    def configure(self, cfg):
        """Apply config values. Restarts poll timer if interval changed while running."""
        self.source = cfg.get("source_folder", "")
        self.local = cfg.get("local_folder", "")
        new_interval = cfg.get("sync_interval", 5)
        interval_changed = new_interval != self.interval
        self.interval = new_interval
        if self.running and interval_changed:
            if self.poll_timer:
                self.poll_timer.cancel()
                self.poll_timer = None
            self._schedule_poll()
            logger.info("Sync interval updated to %d min — poll rescheduled.", self.interval)

    def start(self):
        """Start the sync engine."""
        if self.running:
            return
        cfg = load_config()
        self.configure(cfg)
        if not self.source or not self.local:
            self.status = "error"
            self.error_message = "Source and local folders must be configured."
            return

        self._stop_event.clear()
        self.running = True
        self.status = "running"
        self.error_message = ""
        logger.info("Sync engine started: %s <-> %s", self.source, self.local)

        # Initial full sync
        try:
            self._full_sync()
        except Exception as e:
            logger.error("Initial sync failed: %s", e)
            self.status = "error"
            self.error_message = str(e)

        # Start watchdog
        self._start_watcher()
        # Start polling
        self._schedule_poll()

    def stop(self):
        """Stop the sync engine."""
        self.running = False
        self._stop_event.set()
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5)
            self.observer = None
        if self.poll_timer:
            self.poll_timer.cancel()
            self.poll_timer = None
        # Cancel all debounce timers
        for timer in self._debounce_timers.values():
            timer.cancel()
        self._debounce_timers.clear()
        self._suppressed.clear()
        self.status = "stopped"
        self.next_poll = None
        logger.info("Sync engine stopped.")

    def sync_now(self):
        """Trigger an immediate full sync."""
        if not self.running:
            return
        logger.info("Manual sync triggered.")
        self._add_activity("Manual sync", "triggered", "")
        threading.Thread(target=self._full_sync, daemon=True).start()

    # --- Sync-loop suppression ---

    _SUPPRESS_WINDOW = 5.0  # seconds

    def _suppress(self, dst_path):
        """Record that we just wrote dst_path so the echo watchdog event is ignored."""
        with self._lock:
            now = time.monotonic()
            # Prune entries older than 2× the window to keep the dict bounded
            expired = [p for p, ts in self._suppressed.items()
                       if now - ts > self._SUPPRESS_WINDOW * 2]
            for p in expired:
                del self._suppressed[p]
            self._suppressed[dst_path] = now

    def _is_suppressed(self, path):
        """Return True (and log) if this path is within the suppression window."""
        with self._lock:
            ts = self._suppressed.get(path)
            if ts is None:
                return False
            age = time.monotonic() - ts
            if age <= self._SUPPRESS_WINDOW:
                return True
            # Expired — remove it
            del self._suppressed[path]
            return False

    def _update_state_for_file(self, rel_path, written_path):
        """Immediately persist one file's mtime/size into the state DB.

        Called after every watchdog-triggered copy so the next poll cycle sees
        matching mtimes and does not re-copy the same file.
        """
        try:
            st = os.stat(written_path)
            with self._lock:
                state = load_state()
                state.setdefault("files", {})[rel_path] = {
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                }
                save_state(state)
        except Exception as e:
            logger.debug("State update skipped for %s: %s", rel_path, e)

    # --- Watchdog ---

    def _start_watcher(self):
        """Start watchdog observers on both folders."""
        self.observer = Observer()
        src_handler = _SyncHandler(self, self.source, self.local, "source")
        dst_handler = _SyncHandler(self, self.local, self.source, "local")
        try:
            self.observer.schedule(src_handler, self.source, recursive=True)
            self.observer.schedule(dst_handler, self.local, recursive=True)
            self.observer.start()
        except Exception as e:
            logger.error("Failed to start watcher: %s", e)
            self.status = "error"
            self.error_message = f"Watcher error: {e}"

    def _debounced_sync_file(self, src_path, dst_path, rel_path, action):
        """Debounce file events — wait 2s after last event before acting."""
        key = rel_path
        with self._lock:
            if key in self._debounce_timers:
                self._debounce_timers[key].cancel()
            timer = threading.Timer(
                2.0,
                self._handle_event,
                args=(src_path, dst_path, rel_path, action),
            )
            self._debounce_timers[key] = timer
            timer.start()

    def _handle_event(self, src_path, dst_path, rel_path, action):
        """Process a single file event after debounce."""
        with self._lock:
            self._debounce_timers.pop(rel_path, None)

        if _is_excluded(rel_path):
            return

        # Guard 1 — suppression: we wrote this file ourselves; ignore the echo event
        if action in ("created", "modified") and self._is_suppressed(src_path):
            logger.info("SKIP (suppressed)  %s", rel_path)
            return

        try:
            if action == "deleted":
                if os.path.exists(dst_path):
                    delete_path(dst_path)
                    logger.info("DELETE  %s", rel_path)
                    self._add_activity("Deleted", os.path.basename(rel_path), "x")
                    self._increment_files_today()
            elif action in ("created", "modified"):
                if os.path.exists(src_path) and os.path.isfile(src_path):
                    # Guard 2 — mtime tolerance: skip if both sides are already in sync
                    if os.path.exists(dst_path):
                        try:
                            src_mtime = os.stat(src_path).st_mtime
                            dst_mtime = os.stat(dst_path).st_mtime
                            if abs(src_mtime - dst_mtime) <= 2.0:
                                logger.debug(
                                    "SKIP   %s  (watchdog mtime equal:"
                                    " src=%.3f dst=%.3f diff=%.3f)",
                                    rel_path, src_mtime, dst_mtime,
                                    src_mtime - dst_mtime,
                                )
                                return
                        except OSError:
                            pass  # stat failed — proceed with copy

                    # Guard 3 — add dst to suppression BEFORE writing so the
                    # echo event is already covered when the OS notifies the
                    # other watcher (which can fire before copy_file returns).
                    self._suppress(dst_path)
                    copy_file(src_path, dst_path)
                    logger.info("COPY   %s", rel_path)
                    direction = "\u2192 L" if "source" in src_path else "\u2192 S"
                    self._add_activity("Copied", os.path.basename(rel_path), direction)
                    self._increment_files_today()
                    # Update state immediately so the next poll sees matching mtimes
                    self._update_state_for_file(rel_path, dst_path)
        except Exception as e:
            logger.error("EVENT  %s error: %s", rel_path, e)
            self._add_activity("Error", os.path.basename(rel_path), str(e))

    # --- Polling ---

    def _schedule_poll(self):
        """Schedule the next poll cycle."""
        if not self.running or self._stop_event.is_set():
            return
        self.next_poll = datetime.now().timestamp() + self.interval * 60
        self.poll_timer = threading.Timer(self.interval * 60, self._poll_cycle)
        self.poll_timer.daemon = True
        self.poll_timer.start()

    def _poll_cycle(self):
        """Run a poll-based full sync, then reschedule."""
        if not self.running:
            return
        try:
            self._full_sync()
        except Exception as e:
            logger.error("Poll sync failed: %s", e)
            self._add_activity("Error", "Poll sync", str(e))
        self._schedule_poll()

    # --- Full sync ---

    def _full_sync(self):
        """Walk both trees and sync differences."""
        self.syncing = True
        prev_status = self.status
        self.status = "syncing"
        actions_taken = 0

        try:
            state = load_state()
            known_files = state.get("files", {})
            current_files = {}

            source_files = self._scan_folder(self.source)
            local_files = self._scan_folder(self.local)

            all_rel_paths = set(source_files.keys()) | set(local_files.keys()) | set(known_files.keys())

            for rel in all_rel_paths:
                if _is_excluded(rel):
                    continue

                src_path = os.path.join(self.source, rel)
                dst_path = os.path.join(self.local, rel)
                in_src = rel in source_files
                in_dst = rel in local_files
                in_state = rel in known_files

                try:
                    if in_src and in_dst:
                        # Both exist — sync newer
                        src_mtime = source_files[rel]["mtime"]
                        dst_mtime = local_files[rel]["mtime"]
                        diff = src_mtime - dst_mtime
                        if abs(diff) <= 2.0:
                            # Within FAT32 tolerance, treat as equal
                            logger.debug(
                                "SKIP   %s  (mtime equal: src=%.3f dst=%.3f diff=%.3f)",
                                rel, src_mtime, dst_mtime, diff,
                            )
                            current_files[rel] = source_files[rel]
                        elif src_mtime > dst_mtime:
                            logger.debug(
                                "COPY→L %s  (source newer: src=%.3f dst=%.3f diff=+%.3f)",
                                rel, src_mtime, dst_mtime, diff,
                            )
                            copy_file(src_path, dst_path)
                            logger.info("COPY   %s  (source newer)", rel)
                            self._add_activity("Copied", os.path.basename(rel), "\u2192 L")
                            self._increment_files_today()
                            actions_taken += 1
                            current_files[rel] = source_files[rel]
                        else:
                            logger.debug(
                                "COPY→S %s  (local newer: src=%.3f dst=%.3f diff=%.3f)",
                                rel, src_mtime, dst_mtime, diff,
                            )
                            copy_file(dst_path, src_path)
                            logger.info("COPY   %s  (local newer)", rel)
                            self._add_activity("Copied", os.path.basename(rel), "\u2192 S")
                            self._increment_files_today()
                            actions_taken += 1
                            current_files[rel] = local_files[rel]

                    elif in_src and not in_dst:
                        if in_state:
                            # Was known, now gone from local → deleted locally
                            logger.debug(
                                "DEL←S  %s  (in_state=True, missing from local → delete source)",
                                rel,
                            )
                            delete_path(src_path)
                            logger.info("DELETE %s  (removed from local)", rel)
                            self._add_activity("Deleted", os.path.basename(rel), "x")
                            self._increment_files_today()
                            actions_taken += 1
                        else:
                            # New in source → copy to local
                            logger.debug(
                                "COPY→L %s  (not in_state, only in source → copy to local)",
                                rel,
                            )
                            copy_file(src_path, dst_path)
                            logger.info("COPY   %s  (new in source)", rel)
                            self._add_activity("Copied", os.path.basename(rel), "\u2192 L")
                            self._increment_files_today()
                            actions_taken += 1
                            current_files[rel] = source_files[rel]

                    elif not in_src and in_dst:
                        if in_state:
                            # Was known, now gone from source → deleted at source
                            logger.debug(
                                "DEL←L  %s  (in_state=True, missing from source → delete local)",
                                rel,
                            )
                            delete_path(dst_path)
                            logger.info("DELETE %s  (removed from source)", rel)
                            self._add_activity("Deleted", os.path.basename(rel), "x")
                            self._increment_files_today()
                            actions_taken += 1
                        else:
                            # New in local → copy to source
                            logger.debug(
                                "COPY→S %s  (not in_state, only in local → copy to source)",
                                rel,
                            )
                            copy_file(dst_path, src_path)
                            logger.info("COPY   %s  (new in local)", rel)
                            self._add_activity("Copied", os.path.basename(rel), "\u2192 S")
                            self._increment_files_today()
                            actions_taken += 1
                            current_files[rel] = local_files[rel]

                    # else: not in src, not in dst — already gone, clean up state
                except Exception as e:
                    logger.error("SYNC   %s  error: %s", rel, e)
                    self._add_activity("Error", os.path.basename(rel), str(e))

            # Save state
            state["last_sync"] = datetime.now().isoformat()
            state["files"] = current_files
            save_state(state)
            self.last_sync = datetime.now()

            if actions_taken > 0:
                logger.info("POLL   synced %d file(s)", actions_taken)
                self._add_activity("Poll", f"{actions_taken} file(s) synced", "")

        except Exception as e:
            logger.error("Full sync error: %s", e)
            self.status = "error"
            self.error_message = str(e)
            self._add_activity("Error", "Full sync", str(e))
            return
        finally:
            self.syncing = False

        if self.running:
            self.status = "running"

    def _scan_folder(self, root):
        """Walk a folder tree and return {rel_path: {mtime, size}}."""
        result = {}
        if not os.path.isdir(root):
            return result
        for dirpath, dirnames, filenames in os.walk(root):
            # Filter out excluded directories in-place
            dirnames[:] = [d for d in dirnames if d.lower() not in EXCLUDED_FOLDERS]
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, root)
                if _is_excluded(rel):
                    continue
                try:
                    st = os.stat(full)
                    result[rel] = {"mtime": st.st_mtime, "size": st.st_size}
                except OSError:
                    pass
        return result


class _SyncHandler(FileSystemEventHandler):
    """Watchdog handler that debounces and forwards events to SyncEngine."""

    def __init__(self, engine, watch_root, other_root, side_name):
        super().__init__()
        self.engine = engine
        self.watch_root = watch_root
        self.other_root = other_root
        self.side_name = side_name

    def _handle(self, event, action):
        if event.is_directory and action != "deleted":
            return
        src_path = event.src_path
        rel = os.path.relpath(src_path, self.watch_root)
        if _is_excluded(rel):
            return
        dst_path = os.path.join(self.other_root, rel)
        self.engine._debounced_sync_file(src_path, dst_path, rel, action)

    def on_created(self, event):
        self._handle(event, "created")

    def on_modified(self, event):
        self._handle(event, "modified")

    def on_deleted(self, event):
        self._handle(event, "deleted")

    def on_moved(self, event):
        # Treat as delete old + create new
        old_rel = os.path.relpath(event.src_path, self.watch_root)
        new_rel = os.path.relpath(event.dest_path, self.watch_root)
        if not _is_excluded(old_rel):
            old_dst = os.path.join(self.other_root, old_rel)
            self.engine._debounced_sync_file(event.src_path, old_dst, old_rel, "deleted")
        if not _is_excluded(new_rel):
            new_dst = os.path.join(self.other_root, new_rel)
            self.engine._debounced_sync_file(event.dest_path, new_dst, new_rel, "created")
```

---

### `coworksync/config.py`

```python
"""Config read/write and path validation."""

import os
import json
import winreg

APP_DIR = os.path.join(os.environ.get("APPDATA", ""), "CoworkSync")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
STATE_FILE = os.path.join(APP_DIR, "state.json")

REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_VALUE = "CoworkSync"

DEFAULT_CONFIG = {
    "source_folder": "",
    "local_folder": "",
    "sync_interval": 5,
    "start_with_windows": True,
}


def load_config():
    """Load config from disk, returning defaults if not found."""
    os.makedirs(APP_DIR, exist_ok=True)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Merge with defaults for any missing keys
            merged = {**DEFAULT_CONFIG, **cfg}
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    """Save config to disk."""
    os.makedirs(APP_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def is_configured(cfg):
    """Check if both folders are set."""
    return bool(cfg.get("source_folder")) and bool(cfg.get("local_folder"))


def validate_source(path):
    """Validate source folder exists."""
    if not path:
        return "Source folder is required."
    if not os.path.isdir(path):
        return "Source folder does not exist."
    return None


def validate_local(path):
    """Validate local folder exists. Warn if outside C:\\Users\\."""
    if not path:
        return "Local folder is required."
    if not os.path.isdir(path):
        return "Local folder does not exist."
    return None


def warn_local(path):
    """Return warning if path is outside user directory."""
    if path and not path.lower().startswith("c:\\users\\"):
        return "Warning: path is outside C:\\Users\\ — Cowork may not be able to access it."
    return None


def set_startup(enabled, exe_path=None):
    """Add or remove the Windows startup registry key."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_SET_VALUE
        )
        if enabled:
            if exe_path is None:
                import sys
                exe_path = sys.executable
            winreg.SetValueEx(key, REGISTRY_VALUE, 0, winreg.REG_SZ, exe_path)
        else:
            try:
                winreg.DeleteValue(key, REGISTRY_VALUE)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except OSError:
        pass


def get_startup_enabled():
    """Check if startup registry key exists."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REGISTRY_KEY, 0, winreg.KEY_READ
        )
        winreg.QueryValueEx(key, REGISTRY_VALUE)
        winreg.CloseKey(key)
        return True
    except (FileNotFoundError, OSError):
        return False


# --- State database ---

def load_state():
    """Load sync state from disk."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_sync": None, "files": {}}


def save_state(state):
    """Save sync state to disk."""
    os.makedirs(APP_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
```

---

### `coworksync/logger.py`

```python
"""Logging setup with rotating file handler."""

import os
import logging
from logging.handlers import RotatingFileHandler

APP_DIR = os.path.join(os.environ.get("APPDATA", ""), "CoworkSync")
LOG_FILE = os.path.join(APP_DIR, "coworksync.log")


def enable_verbose():
    """Switch the logger to DEBUG level (call before setup_logger if possible,
    or after — it will update the existing logger in place)."""
    logging.getLogger("coworksync").setLevel(logging.DEBUG)


def setup_logger():
    """Configure and return the application logger."""
    os.makedirs(APP_DIR, exist_ok=True)

    logger = logging.getLogger("coworksync")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=2,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


logger = setup_logger()
```

---

