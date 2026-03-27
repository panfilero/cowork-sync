# Refactor: Replace Flask UI with CustomTkinter

## Goal
Remove Flask and replace the web-based config UI with a native CustomTkinter window.
The sync engine, tray, config, and logger modules are NOT to be modified.

## Dependencies
- Remove: `flask`
- Add: `customtkinter`
- Update `requirements.txt` accordingly

## Files to Delete
- `coworksync/server.py`
- `coworksync/templates/index.html`
- `coworksync/static/style.css`
- `coworksync/static/app.js`
- `coworksync/templates/` directory
- `coworksync/static/` directory

## Files to Create
- `coworksync/ui.py` — CustomTkinter config window (spec below)

## Files to Modify
- `coworksync/main.py` — remove Flask server startup, wire tray to open CustomTkinter window
- `coworksync/tray.py` — change "Open Config" action from `webbrowser.open()` to calling `ui.open_window()`
- `CoworkSync.spec` — remove `templates` and `static` data bundles, add `--collect-data customtkinter`
- `build.bat` — add `--collect-data customtkinter` flag
- `CLAUDE.md` — update to reflect new architecture (spec below)

## ui.py Specification

Single window, non-resizable. Opens on "Open Config" tray action. If already open, bring to front.

### Fields (match existing config.json keys exactly)
- Source Folder — text entry + Browse button (uses `tkinter.filedialog.askdirectory`)
- Local Folder — text entry + Browse button (same)
- Sync Interval — numeric entry, default 5, min 1, max 60, label "minutes"
- Start with Windows — checkbox, reads/writes registry via existing `config.py` method

### Status Block (read-only, auto-refreshes every 15s via `after()`)
- Status dot label: Running / Syncing / Error / Stopped
- Last sync: relative time string
- Next poll: countdown in minutes
- Files synced today: count

### Buttons
- Save & Start — saves config via `config.py`, calls `sync_engine.start()`
- Stop / Resume — toggles sync engine state

### Activity Log
- Scrollable text box, last 10 log lines
- Reads from logger output
- Refreshes every 15s alongside status block
- Error lines in red, conflict lines in yellow

### Styling
- `customtkinter.set_appearance_mode("System")`
- `customtkinter.set_default_color_theme("blue")`
- Single column layout, compact — target window size ~420×580px

## CLAUDE.md Updates

Replace the Flask references with the following:

- Overview line: change "Flask-based web UI" to "CustomTkinter desktop UI"
- Architecture > Entry point: remove Flask server reference, note that main.py opens CustomTkinter window on demand via tray
- Architecture > remove `server.py` bullet, replace with `ui.py` — CustomTkinter config window, opens via tray "Open Config", auto-refreshes status and log every 15s via `after()` loop
- Architecture > Frontend section: remove entirely
- Build section: note `--collect-data customtkinter` required in PyInstaller build