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
```

There is no test suite. Testing is done manually by running the application.

## Architecture

**Entry point:** `coworksync/main.py` — creates SyncEngine, wires the UI engine reference, loads config, and runs the system tray (blocking). Opens the CustomTkinter config window on demand via tray or automatically on first run.

**Core modules:**
- `sync_engine.py` — Two-way sync using watchdog (real-time file events, debounced 2s) + fallback polling (default every 5 min). Conflict resolution is last-write-wins. Status states: `stopped` → `running` → `syncing` / `error`.
- `config.py` — JSON config at `%APPDATA%\CoworkSync\config.json`, state DB at `state.json`, Windows registry integration for startup.
- `ui.py` — CustomTkinter config window, opens via tray "Open Config". Singleton pattern (brings to front if already open). Auto-refreshes status and activity log every 15s via `after()` loop.
- `tray.py` — pystray system tray icon with color-coded status (green=running, yellow=syncing, red=error). Updates every 3s.
- `logger.py` — Rotating file logger (5MB, 2 backups) at `%APPDATA%\CoworkSync\coworksync.log`.

**Build:** PyInstaller via `CoworkSync.spec` — windowed mode, single file, bundles assets and customtkinter data (`collect_data_files`). `generate_icons.py` creates 64×64 PNG and ICO tray icons before build.

## Key Design Decisions

- **Dual sync:** Watchdog + polling for reliability across virtual file systems (Google Drive VFS).
- **Direct deletion:** Uses `os.remove()`/`shutil.rmtree()` (never recycle bin) so cloud clients register changes.
- **Excluded paths:** `processing/` folder, `thumbs.db`, `desktop.ini`, `.ds_store`, `*.tmp`, `*.ffs_db`, `*.ffs_lock`.
- **FAT32 tolerance:** 2-second mtime comparison tolerance for cross-filesystem compatibility.
- **No external database:** Simple JSON files for all persistent state.
