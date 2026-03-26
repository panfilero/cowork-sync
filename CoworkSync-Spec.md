# CoworkSync — Product Specification
**Version:** 1.0
**Purpose:** Build specification for Claude Code
**Stack:** Python, PyInstaller

---

## Overview

CoworkSync is a lightweight Windows background service that keeps a cloud-synced folder (Google Drive, Dropbox, OneDrive, or any local folder) in sync with a local Cowork workspace folder. It replaces the manual FreeFileSync + RealTimeSync + Windows Task Scheduler setup with a single silent tool.

---

## Problem Statement

Claude Cowork requires files to exist in a real local folder. Cloud storage clients like Google Drive Desktop use a virtual file system (VFS) that Cowork cannot access. Users must currently configure three separate tools (FreeFileSync, RealTimeSync, Windows Task Scheduler) to bridge this gap. This spec describes a single tool that replaces all three.

---

## Core Requirements

### Sync Behavior

- Two-way sync between a source folder (cloud-synced) and a destination folder (local Cowork workspace)
- File system watcher for instant detection of changes (using `watchdog`)
- Fallback polling every 5 minutes in case file system events are not fired reliably (common with virtual drives like Google Drive Desktop)
- On new file in source → copy to destination
- On new file in destination → copy to source
- On file modified in either → copy newer version to the other side
- On file deleted in either → delete from the other side
- Deletions must use the standard `os.remove()` / `shutil.rmtree()` method — NOT Windows Recycle Bin — to ensure Google Drive Desktop registers the deletion correctly
- Exclude `processing\` folder from sync entirely — never copy or delete anything in this folder
- Exclude standard system files: `thumbs.db`, `desktop.ini`, `.DS_Store`, `*.tmp`
- Use a database file (simple JSON) to track sync state and detect moved files between polls

### Conflict Resolution

- Last-write-wins based on file modification timestamp
- If timestamps are within 2 seconds of each other, treat as equal (FAT32 tolerance)
- Log conflicts to `coworksync.log` but do not prompt the user

### System Tray

- App runs silently in the Windows system tray
- Tray icon shows current status:
  - Green: running, no errors
  - Yellow: syncing in progress
  - Red: error state
- Right-click tray icon menu:
  - **Status** — shows last sync time and file count
  - **Sync Now** — triggers immediate manual sync
  - **Open Config** — opens the config window
  - **View Log** — opens `coworksync.log` in Notepad
  - **Pause / Resume** — pause sync without exiting
  - **Exit** — stop the service and exit

### Config Window

Simple UI with minimal options. Opens on first run and via tray menu.

Fields:
- **Source folder** — path to cloud-synced folder (Browse button)
- **Local folder** — path to local Cowork workspace (Browse button)
- **Sync interval** — fallback poll interval in minutes (default: 5, range: 1–60)
- **Save** button
- **Start / Stop** toggle

Config saved to `%APPDATA%\CoworkSync\config.json`.

### Startup

- App registers itself to run on Windows login via registry key: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- Checkbox in config window: **Start with Windows** (default: on)
- On startup, if config exists, begin syncing immediately with no UI shown

### Logging

- Log file: `%APPDATA%\CoworkSync\coworksync.log`
- Log entries: timestamp, event type (copy, delete, conflict, error, poll), file path
- Rotate log at 5MB, keep last 2 rotations
- Do not log empty poll cycles (inbox was empty) — only log when action was taken

---

## Technical Specification

### Dependencies

```
watchdog        # File system event monitoring
pystray         # System tray icon and menu
Pillow          # Required by pystray for icon rendering
tkinter         # Config UI (included in standard Python)
schedule        # Fallback polling timer
pyinstaller     # Build to .exe
```

### File Structure

```
coworksync/
    main.py             <- Entry point, initializes tray and sync engine
    sync_engine.py      <- Core sync logic, watcher, poller
    config.py           <- Config read/write, path validation
    tray.py             <- System tray icon and menu
    ui.py               <- Config window (tkinter)
    logger.py           <- Logging setup and rotation
    assets/
        icon_green.png
        icon_yellow.png
        icon_red.png
    build.bat           <- PyInstaller build script
```

### Key Logic — sync_engine.py

```python
# On startup:
# 1. Load config
# 2. Run initial full comparison sync
# 3. Start watchdog observer on both folders
# 4. Start fallback poll timer (default 5 min)

# On file event (watchdog):
# - Debounce: wait 2 seconds after last event before acting (prevents partial file copies)
# - Determine direction based on which folder the event came from
# - Copy or delete on the other side

# On poll cycle:
# - Walk both folder trees
# - Compare file lists and modification times
# - Sync any differences found
# - Update state database

# Exclusions (never sync these):
EXCLUDED_FOLDERS = ['processing']
EXCLUDED_FILES = ['thumbs.db', 'desktop.ini', '.DS_Store', 'coworksync.log', 'sync.ffs_db']
EXCLUDED_EXTENSIONS = ['.tmp', '.ffs_db', '.ffs_lock']
```

### Deletion Method

```python
# Always use os.remove() for files and shutil.rmtree() for folders
# Never use send2trash or winshell recycle bin methods
# This ensures Google Drive Desktop registers the deletion correctly
import os
import shutil

def delete_file(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)
```

### State Database

Simple JSON file at `%APPDATA%\CoworkSync\state.json`:

```json
{
  "last_sync": "2026-03-26T12:00:00",
  "files": {
    "relative/path/to/file.pdf": {
      "mtime": 1234567890.0,
      "size": 12345
    }
  }
}
```

Used to detect moves and avoid redundant copies on poll cycles.

### Build Script — build.bat

```bat
pyinstaller --onefile --windowed --name CoworkSync ^
  --icon assets/icon_green.ico ^
  --add-data "assets;assets" ^
  main.py
```

Output: `dist\CoworkSync.exe` — single file, no installer required.

---

## Frontend UI Specification

### Stack

Replace tkinter with a **Flask** local web UI. The tray icon's **Open Config** menu item opens the UI in the user's default browser at `http://localhost:5420`.

Add to dependencies:
```
flask       # Local web server for config UI
```

### Single Page UI

One screen handles everything — configuration, status, and controls.

#### Layout

```
┌─────────────────────────────────────────┐
│  CoworkSync                    v1.0     │
│  ─────────────────────────────────────  │
│                                         │
│  Source Folder                          │
│  [H:\My Drive\Project Folder   ] [📁]  │
│                                         │
│  Local Folder                           │
│  [C:\Users\Username\Project    ] [📁]  │
│                                         │
│  Sync Interval    [5] minutes           │
│                                         │
│  ☑ Start with Windows                   │
│                                         │
│  ─────────────────────────────────────  │
│                                         │
│  Status      ● Running                  │
│  Last sync   2 minutes ago              │
│  Next poll   3 minutes                  │
│  Synced today  12 files                 │
│                                         │
│  [  Save & Start  ]  [  Stop  ]         │
│                                         │
│  ─────────────────────────────────────  │
│  Recent Activity                        │
│  12:04  Copied   invoice_jan.pdf  →  C  │
│  12:04  Deleted  old_report.pdf   ×     │
│  11:59  Poll     no changes             │
│                                         │
└─────────────────────────────────────────┘
```

#### Elements

**Source Folder field**
- Text input, full path
- Browse button opens Windows folder picker via `tkinter.filedialog` (still used only for this — no other tkinter dependency)
- Validates path exists on Save, shows inline error if not

**Local Folder field**
- Same as above
- Validates path exists and is inside `C:\Users\` (Cowork requirement)
- Shows warning if path is outside user directory

**Sync Interval**
- Number input, default 5, min 1, max 60
- Label: "minutes"

**Start with Windows checkbox**
- Checked by default
- Writes/removes registry key on change

**Status block**
- Status dot: green (running), yellow (syncing), red (error), gray (stopped)
- Last sync: relative time ("2 minutes ago", "just now")
- Next poll: countdown in minutes
- Synced today: file count, resets at midnight

**Save & Start button**
- Saves config to `%APPDATA%\CoworkSync\config.json`
- Starts sync engine if not running
- Shows inline success confirmation

**Stop button**
- Pauses sync engine
- Button label changes to **Resume** when stopped

**Recent Activity log**
- Last 10 log entries
- Shows: time, action (Copied / Deleted / Conflict / Error / Poll), filename, direction arrow
- Auto-refreshes every 15 seconds via JavaScript `setInterval`
- Errors shown in red, conflicts in yellow, normal actions in default color

### Flask Routes

```python
GET  /              # Serve the UI
GET  /api/status    # Returns JSON: status, last_sync, next_poll, files_today
GET  /api/config    # Returns current config JSON
POST /api/config    # Save new config
POST /api/start     # Start sync engine
POST /api/stop      # Stop sync engine
POST /api/sync-now  # Trigger immediate sync
GET  /api/log       # Returns last 50 log lines as JSON
```

### Design

- Clean, minimal — single column, plenty of whitespace
- Font: system font stack (`-apple-system, Segoe UI, sans-serif`)
- Colors: white background, dark text, blue accent for buttons, standard green/yellow/red for status
- No external CSS frameworks — vanilla CSS only, keep it lightweight
- No JavaScript frameworks — vanilla JS only
- Total page weight under 50KB

### File Structure Addition

```
coworksync/
    server.py           <- Flask app, routes, serves UI
    templates/
        index.html      <- Single page UI
    static/
        style.css
        app.js          <- Status polling, form handling
```

### Port

Use port `5420`. If port is already in use, increment until a free port is found and update the tray menu link accordingly.

---

## Out of Scope

- macOS or Linux support (Windows only for now)
- Google Drive API integration — relies on Google Drive Desktop being installed
- Dropbox API integration — relies on Dropbox client being installed
- Any UI beyond the config window and tray menu
- Versioning or file history
- Encryption
- Multiple folder pairs (v1 supports one pair only)

---

## Success Criteria

- App installs by running a single `.exe` file
- User configures two folder paths and clicks Save
- Files placed in source folder appear in destination folder within 10 seconds
- Files deleted from destination folder are deleted from source folder and reflected in Google Drive web within 30 seconds
- App survives reboot and resumes syncing automatically
- App uses less than 50MB RAM at idle
- No visible UI after initial setup — runs silently in system tray

---

## Known Issues to Handle

- Google Drive Desktop VFS does not fire reliable file system change notifications — mitigated by 5 minute fallback poll
- Google Drive Desktop does not register Recycle Bin deletions — mitigated by using `os.remove()` directly
- Partial file copies (file still being written when watcher fires) — mitigated by 2 second debounce on watcher events
- First run on a machine with existing files in both folders — mitigated by initial full comparison sync before starting watcher
