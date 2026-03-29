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
EXCLUDED_EXTENSIONS = {".tmp", ".ffs_db", ".ffs_lock", ".coworksync.tmp"}

MASS_DELETE_THRESHOLD = 10
MASS_DELETE_PERCENTAGE = 0.5  # 50% of known files

FAT32_TOLERANCE = 2.0
DST_TOLERANCE = 3600.0


def _mtimes_equal(mtime_a, mtime_b):
    """Check if two mtimes are effectively equal (FAT32 + DST tolerance)."""
    diff = abs(mtime_a - mtime_b)
    return diff <= FAT32_TOLERANCE or abs(diff - DST_TOLERANCE) <= FAT32_TOLERANCE


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
    """Copy via temp file + atomic rename. Uses CopyFileExW on Windows
    so minifilter drivers (e.g. Google Drive) register the operation."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp_dst = dst + ".coworksync.tmp"

    if sys.platform == "win32":
        logger.debug("copy_file: CopyFileExW %s -> %s (tmp)", src, tmp_dst)
        ok = ctypes.windll.kernel32.CopyFileExW(
            ctypes.c_wchar_p(src),
            ctypes.c_wchar_p(tmp_dst),
            None,
            None,
            ctypes.c_bool(False),
            0,
        )
        if not ok:
            err = ctypes.GetLastError()
            try:
                os.remove(tmp_dst)
            except OSError:
                pass
            raise OSError(err, ctypes.FormatError(err), src)
    else:
        logger.debug("copy_file: shutil.copy2 %s -> %s (tmp)", src, tmp_dst)
        shutil.copy2(src, tmp_dst)

    os.replace(tmp_dst, dst)
    logger.debug("copy_file: rename succeeded %s", dst)


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

    def force_sync(self):
        """Run a full sync with mass deletion threshold disabled."""
        if not self.running:
            return
        logger.warning("Force sync triggered — mass deletion threshold disabled.")
        self._add_activity("Force sync", "threshold bypassed", "")
        try:
            self._force_sync_active = True
            self._full_sync()
        finally:
            self._force_sync_active = False

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
                            if _mtimes_equal(src_mtime, dst_mtime):
                                logger.debug(
                                    "SKIP   %s  (watchdog mtime equal via _mtimes_equal:"
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
            first_run = len(known_files) == 0
            if first_run:
                logger.info("First run detected — all files will be copied (no deletions). State DB is empty.")
            current_files = {}

            source_files = self._scan_folder(self.source)
            local_files = self._scan_folder(self.local)

            all_rel_paths = set(source_files.keys()) | set(local_files.keys()) | set(known_files.keys())
            pending_deletes = []  # list of (path_to_delete, rel_path, reason)

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
                        if _mtimes_equal(src_mtime, dst_mtime):
                            # Within FAT32 or DST tolerance, treat as equal
                            logger.debug(
                                "SKIP   %s  (mtime equal via _mtimes_equal: src=%.3f dst=%.3f diff=%.3f)",
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
                        if in_state and not first_run:
                            # Was known, now gone from local → deleted locally
                            logger.debug(
                                "DEL←S  %s  (in_state=True, missing from local → delete source)",
                                rel,
                            )
                            pending_deletes.append((src_path, rel, "removed from local"))
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
                        if in_state and not first_run:
                            # Was known, now gone from source → deleted at source
                            logger.debug(
                                "DEL←L  %s  (in_state=True, missing from source → delete local)",
                                rel,
                            )
                            pending_deletes.append((dst_path, rel, "removed from source"))
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

            # Check mass deletion threshold before executing any deletes
            if pending_deletes and not getattr(self, '_force_sync_active', False):
                num_deletes = len(pending_deletes)
                num_known = len(known_files)
                if num_known > 0 and num_deletes > MASS_DELETE_THRESHOLD and num_deletes > num_known * MASS_DELETE_PERCENTAGE:
                    logger.error(
                        "Mass deletion blocked: %d files would be deleted out of %d known "
                        "(threshold: %d / %.0f%%). Possible VFS disconnect.",
                        num_deletes, num_known, MASS_DELETE_THRESHOLD, MASS_DELETE_PERCENTAGE * 100,
                    )
                    self.status = "error"
                    self.error_message = (
                        f"Mass deletion blocked: {num_deletes} files would be deleted. "
                        "Check your cloud drive connection."
                    )
                    self._add_activity("Mass delete blocked", f"{num_deletes} files", "")
                    # Do NOT update state DB — preserve pre-disconnect state
                    self.syncing = False
                    return

            # Safe to execute deletions
            for path_to_delete, rel, reason in pending_deletes:
                try:
                    delete_path(path_to_delete)
                    logger.info("DELETE %s  (%s)", rel, reason)
                    self._add_activity("Deleted", os.path.basename(rel), "x")
                    self._increment_files_today()
                    actions_taken += 1
                except Exception as e:
                    logger.error("DELETE %s  error: %s", rel, e)
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
