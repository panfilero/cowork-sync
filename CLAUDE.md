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

# Run silently (used by Windows auto-start, no UI on launch)
python coworksync/main.py --silent
```

There is no test suite. Testing is done manually by running the application.

## Architecture

**Entry point:** `coworksync/main.py` — creates SyncEngine, wires the UI engine reference, loads config, and runs the system tray (blocking). Opens the CustomTkinter config window on demand via tray or automatically on first run.

**Core modules:**
- `sync_engine.py` — Two-way sync using watchdog (real-time file events, debounced 2s) + fallback polling (default every 5 min). Conflict resolution is last-write-wins. Status states: `stopped` → `running` → `syncing` / `error`. Contains sync-loop suppression logic (see Key Design Decisions). Contains `get_mode(rel_path)` for per-subfolder rule lookup. Watchdog events carry `side_name` and `mode` through the debounce chain to enforce one-way rules.
- `config.py` — JSON config at `%APPDATA%\CoworkSync\config.json`, state DB at `state.json`, Windows registry integration for startup.
- `ui.py` — CustomTkinter config window, opens via tray "Open Config". Singleton pattern (brings to front if already open). Auto-refreshes status and activity log every 15s via `after()` loop. Folder rules editor: existing rules display as read-only labels; "+ Add Rule" shows a dropdown of actual subfolders scanned from both configured paths (2 levels deep), excluding folders already assigned a rule.
- `tray.py` — pystray system tray icon with color-coded status (green=running, yellow=syncing, red=error). Updates every 3s.
- `logger.py` — Rotating file logger (5MB, 2 backups) at `%APPDATA%\CoworkSync\coworksync.log`. Exposes `enable_verbose()` to switch to DEBUG level.

**Build:** PyInstaller via `CoworkSync.spec` — windowed mode, single file, bundles assets and customtkinter data (`collect_data_files`). `generate_icons.py` creates 64×64 PNG and ICO tray icons before build.

## Key Design Decisions

- **Dual sync:** Watchdog + polling for reliability across virtual file systems (Google Drive VFS).
- **Direct deletion:** Uses `os.remove()`/`shutil.rmtree()` (never recycle bin) so cloud clients register changes.
- **Per-subfolder sync rules:** Each subfolder can have an independent mode: `two-way` (default), `source-to-local`, `local-to-source`, or `ignore`. Rules are configured in `folder_rules` in `config.json`. The deepest matching rule wins. `processing/` defaults to `ignore`.
- **File-level exclusions:** `thumbs.db`, `desktop.ini`, `.ds_store`, `*.tmp`, `*.ffs_db`, `*.ffs_lock`, `*.coworksync.tmp` are always excluded regardless of folder rules.
- **FAT32 tolerance:** 2-second mtime comparison tolerance for cross-filesystem compatibility.
- **No external database:** Simple JSON files for all persistent state.
- **All copies go through `copy_file()`:** Uses `CopyFileExW` (not `shutil.copy2`) so minifilter drivers like Google Drive register the write. `shutil.copy2` is only the non-Windows fallback inside that function.
- **Sync-loop suppression:** `SyncEngine._suppressed` is a `{abs_dst_path: monotonic_timestamp}` dict. Before every watchdog-triggered copy, the destination path is added to the dict. When the other watcher fires for that same path (the echo event), `_handle_event` checks `_is_suppressed(src_path)` and skips with `SKIP (suppressed)` logged. Window is 5 seconds. Entries are pruned lazily on each `_suppress()` call.
- **Watchdog mtime guard:** `_handle_event` stats both sides before copying. If `|src_mtime - dst_mtime| ≤ 2.0s`, the copy is skipped. This catches Google Drive post-ingest timestamp touches.
- **Immediate state update after watchdog copy:** After each `_handle_event` copy, `_update_state_for_file` writes the new mtime into `state.json` under `_lock`. This prevents the next poll cycle from seeing a mismatch and re-copying.
- **Mass deletion threshold:** Poll-based deletions are collected into a pending list and checked against a threshold (>10 files AND >50% of known files) before execution. If triggered, status is set to `error`, the state DB is NOT updated (preserving the pre-disconnect view), and no files are deleted. "Force Sync (bypass safety)" in the tray menu bypasses the threshold for manual recovery. Watchdog deletions are NOT gated by this threshold.
- **Atomic writes:** `save_state()` and `save_config()` write to a `.tmp` file (flushed and fsynced) then rename via `os.replace()` for crash safety. Both files are in `%APPDATA%\CoworkSync\`, always on the same volume.
- **Atomic copy:** `copy_file()` writes to `<dst>.coworksync.tmp` then renames to the final destination via `os.replace()`. Prevents partial files from being treated as valid if the app crashes mid-copy. The `_suppress(dst_path)` call still uses the final `dst` path, not the tmp path.
- **DST mtime tolerance:** `_mtimes_equal()` treats files as identical if their mtime diff is within 2s (FAT32) or within 2s of exactly 3600s (DST shift). Used in both watchdog and poll comparisons.
- **First-run conservative mode:** When the state DB is empty, all files are copied and no deletions are performed, regardless of which side a file exists on.

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
