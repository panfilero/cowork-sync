# Task: Phase 3 — Per-Subfolder Sync Rules

**Use a feature branch:** `git checkout -b feature/folder-rules`

This is the largest change in the project. Each subfolder within the synced root gets an independent sync mode. Read this entire prompt before starting.

---

## Overview

### Sync Modes

| Mode | Behavior |
|------|----------|
| `two-way` | Current behavior. Last-write-wins. (Default for all folders.) |
| `source-to-local` | Cloud (source) is authority. Local changes are overwritten/deleted. |
| `local-to-source` | Local is authority. Cloud changes are overwritten/deleted. |
| `ignore` | Excluded from sync entirely. Not scanned, not watched. |

### Config Schema

Add `folder_rules` to `config.json`:

```json
{
  "source_folder": "...",
  "local_folder": "...",
  "sync_interval": 5,
  "start_with_windows": true,
  "folder_rules": [
    {"path": "processing", "mode": "ignore"},
    {"path": "archive", "mode": "source-to-local"},
    {"path": "exports", "mode": "local-to-source"}
  ]
}
```

Rules use relative paths from the sync root. The deepest (most specific) matching rule wins. Unmatched paths default to `two-way`.

---

## File-by-File Implementation

### 1. `config.py`

**Add `folder_rules` to `DEFAULT_CONFIG`:**

```python
DEFAULT_CONFIG = {
    "source_folder": "",
    "local_folder": "",
    "sync_interval": 5,
    "start_with_windows": True,
    "folder_rules": [{"path": "processing", "mode": "ignore"}],
}
```

**Migration:** The existing `load_config()` already merges loaded config with `DEFAULT_CONFIG` via `{**DEFAULT_CONFIG, **cfg}`. This means old configs without `folder_rules` will automatically get the default. No extra migration code needed.

---

### 2. `sync_engine.py` — Exclusion System Refactor

This is the core of the change. There are **6 locations** that currently use `_is_excluded()` or `EXCLUDED_FOLDERS`. Each needs different treatment.

#### 2a. Split `_is_excluded()` into two functions

The current `_is_excluded()` checks both folder rules AND file-level exclusions (system files, temp files). These need to be separated because folder rules are now mode-based, but file exclusions are unconditional.

**Keep** `_is_excluded_file()` for file-level checks (unchanged logic):

```python
EXCLUDED_FILES = {"thumbs.db", "desktop.ini", ".ds_store", "coworksync.log", "sync.ffs_db"}
EXCLUDED_EXTENSIONS = {".tmp", ".ffs_db", ".ffs_lock", ".coworksync.tmp"}

def _is_excluded_file(rel_path):
    """Check if a file should be excluded from sync (system files, temp files)."""
    name = os.path.basename(rel_path).lower()
    if name in EXCLUDED_FILES:
        return True
    _, ext = os.path.splitext(name)
    if ext in EXCLUDED_EXTENSIONS:
        return True
    return False
```

**Remove** `EXCLUDED_FOLDERS` entirely. The `processing` exclusion now lives in `folder_rules`.

**Remove** the old `_is_excluded()` function.

#### 2b. Add `get_mode()` to `SyncEngine`

```python
def get_mode(self, rel_path):
    """Return the sync mode for a given relative path.
    Matches the deepest (most specific) rule. Default: two-way."""
    rel_normalized = rel_path.replace("\\", "/").lower().rstrip("/")
    best_match = ("", "two-way")
    for rule in self._folder_rules:
        prefix = rule["path"].replace("\\", "/").lower().rstrip("/")
        if rel_normalized == prefix or rel_normalized.startswith(prefix + "/"):
            if len(prefix) > len(best_match[0]):
                best_match = (prefix, rule["mode"])
    return best_match[1]
```

#### 2c. Load rules in `configure()`

Add to the `configure()` method:

```python
self._folder_rules = cfg.get("folder_rules", [{"path": "processing", "mode": "ignore"}])
```

Also initialize `self._folder_rules` in `__init__()`:

```python
self._folder_rules = [{"path": "processing", "mode": "ignore"}]
```

#### 2d. Update all 6 call sites

Here's every location that uses `_is_excluded()` or `EXCLUDED_FOLDERS`, and what to do with each:

---

**Site 1: `_SyncHandler._handle()` — watchdog event entry point**

Current:
```python
def _handle(self, event, action):
    if event.is_directory and action != "deleted":
        return
    src_path = event.src_path
    rel = os.path.relpath(src_path, self.watch_root)
    if _is_excluded(rel):
        return
    dst_path = os.path.join(self.other_root, rel)
    self.engine._debounced_sync_file(src_path, dst_path, rel, action)
```

New:
```python
def _handle(self, event, action):
    if event.is_directory and action != "deleted":
        return
    src_path = event.src_path
    rel = os.path.relpath(src_path, self.watch_root)
    if _is_excluded_file(rel):
        return
    mode = self.engine.get_mode(rel)
    if mode == "ignore":
        return
    dst_path = os.path.join(self.other_root, rel)
    self.engine._debounced_sync_file(src_path, dst_path, rel, action, self.side_name, mode)
```

Key change: pass `side_name` and `mode` through to `_debounced_sync_file`.

---

**Site 2: `_SyncHandler.on_moved()` — move event handling**

Current code calls `_is_excluded()` on both old and new paths. Replace with:

```python
def on_moved(self, event):
    old_rel = os.path.relpath(event.src_path, self.watch_root)
    new_rel = os.path.relpath(event.dest_path, self.watch_root)
    if not _is_excluded_file(old_rel):
        old_mode = self.engine.get_mode(old_rel)
        if old_mode != "ignore":
            old_dst = os.path.join(self.other_root, old_rel)
            self.engine._debounced_sync_file(event.src_path, old_dst, old_rel, "deleted", self.side_name, old_mode)
    if not _is_excluded_file(new_rel):
        new_mode = self.engine.get_mode(new_rel)
        if new_mode != "ignore":
            new_dst = os.path.join(self.other_root, new_rel)
            self.engine._debounced_sync_file(event.dest_path, new_dst, new_rel, "created", self.side_name, new_mode)
```

---

**Site 3: `_debounced_sync_file()` — pass through side_name and mode**

Update signature and forward:

```python
def _debounced_sync_file(self, src_path, dst_path, rel_path, action, side_name, mode):
    """Debounce file events — wait 2s after last event before acting."""
    key = rel_path
    with self._lock:
        if key in self._debounce_timers:
            self._debounce_timers[key].cancel()
        timer = threading.Timer(
            2.0,
            self._handle_event,
            args=(src_path, dst_path, rel_path, action, side_name, mode),
        )
        self._debounce_timers[key] = timer
        timer.start()
```

---

**Site 4: `_handle_event()` — watchdog event processing**

Update signature:

```python
def _handle_event(self, src_path, dst_path, rel_path, action, side_name, mode):
```

Replace the `_is_excluded` check at the top:

```python
# Old:
if _is_excluded(rel_path):
    return

# New:
if _is_excluded_file(rel_path):
    return
if mode == "ignore":
    return
```

Add mode-based direction gating **after** the suppression check, **before** the action logic:

```python
# Mode-based direction gating
# If source-to-local: only act on events from the source side
# If local-to-source: only act on events from the local side
if mode == "source-to-local" and side_name == "local":
    logger.debug("SKIP   %s  (mode=source-to-local, event from local side — ignored)", rel_path)
    return
if mode == "local-to-source" and side_name == "source":
    logger.debug("SKIP   %s  (mode=local-to-source, event from source side — ignored)", rel_path)
    return
```

The rest of `_handle_event` (delete, copy, suppression, mtime guard) stays the same. For one-way modes, the direction gating above ensures we only process events from the authoritative side — the copy/delete logic itself doesn't need to change because `src_path` and `dst_path` are already set correctly by the `_SyncHandler`.

---

**Site 5: `_full_sync()` — poll-based sync loop**

Replace the `_is_excluded` check:

```python
# Old:
if _is_excluded(rel):
    continue

# New:
if _is_excluded_file(rel):
    continue
mode = self.get_mode(rel)
if mode == "ignore":
    continue
```

Then update the three main branches to be mode-aware:

**Branch: both exist (`in_src and in_dst`)**

```python
if in_src and in_dst:
    src_mtime = source_files[rel]["mtime"]
    dst_mtime = local_files[rel]["mtime"]
    diff = src_mtime - dst_mtime

    if mode == "two-way":
        # Existing logic: _mtimes_equal check, then last-write-wins
        # KEEP ALL EXISTING CODE IN THIS BRANCH UNCHANGED
        ...

    elif mode == "source-to-local":
        # Source is authority — always copy source to local (skip if mtimes match)
        if _mtimes_equal(src_mtime, dst_mtime):
            logger.debug("SKIP   %s  (source-to-local, mtimes equal)", rel)
            current_files[rel] = source_files[rel]
        else:
            copy_file(src_path, dst_path)
            logger.info("COPY   %s  (source-to-local, source is authority)", rel)
            self._add_activity("Copied", os.path.basename(rel), "→ L")
            self._increment_files_today()
            actions_taken += 1
            current_files[rel] = source_files[rel]

    elif mode == "local-to-source":
        # Local is authority — always copy local to source (skip if mtimes match)
        if _mtimes_equal(src_mtime, dst_mtime):
            logger.debug("SKIP   %s  (local-to-source, mtimes equal)", rel)
            current_files[rel] = local_files[rel]
        else:
            copy_file(dst_path, src_path)
            logger.info("COPY   %s  (local-to-source, local is authority)", rel)
            self._add_activity("Copied", os.path.basename(rel), "→ S")
            self._increment_files_today()
            actions_taken += 1
            current_files[rel] = local_files[rel]
```

**Branch: only in source (`in_src and not in_dst`)**

```python
elif in_src and not in_dst:
    if mode == "two-way":
        # KEEP EXISTING LOGIC UNCHANGED (in_state check, first_run guard, etc.)
        ...

    elif mode == "source-to-local":
        # Source is authority — always copy to local
        copy_file(src_path, dst_path)
        logger.info("COPY   %s  (source-to-local, new in source)", rel)
        self._add_activity("Copied", os.path.basename(rel), "→ L")
        self._increment_files_today()
        actions_taken += 1
        current_files[rel] = source_files[rel]

    elif mode == "local-to-source":
        # Local is authority — file missing from local means delete from source
        pending_deletes.append((src_path, rel, "local-to-source, not in local"))
```

**Branch: only in local (`not in_src and in_dst`)**

```python
elif not in_src and in_dst:
    if mode == "two-way":
        # KEEP EXISTING LOGIC UNCHANGED (in_state check, first_run guard, etc.)
        ...

    elif mode == "source-to-local":
        # Source is authority — file missing from source means delete from local
        pending_deletes.append((dst_path, rel, "source-to-local, not in source"))

    elif mode == "local-to-source":
        # Local is authority — always copy to source
        copy_file(dst_path, src_path)
        logger.info("COPY   %s  (local-to-source, new in local)", rel)
        self._add_activity("Copied", os.path.basename(rel), "→ S")
        self._increment_files_today()
        actions_taken += 1
        current_files[rel] = local_files[rel]
```

**Important notes on the one-way delete logic:**

- One-way mode deletions (file missing from authority side) go into `pending_deletes` — they ARE subject to the mass deletion threshold. This is critical because a VFS disconnect in `source-to-local` mode would make everything "missing from source" and try to delete all local files.
- One-way mode deletions do NOT check `in_state` or `first_run`. The authority side is the single source of truth — if a file isn't there, it shouldn't exist on the other side, regardless of state history.

---

**Site 6: `_scan_folder()` — directory walk**

Current code filters directories using `EXCLUDED_FOLDERS`:

```python
dirnames[:] = [d for d in dirnames if d.lower() not in EXCLUDED_FOLDERS]
```

Replace with mode-based filtering. The engine needs to skip `ignore`-mode directories during scanning:

```python
def _scan_folder(self, root):
    """Walk a folder tree and return {rel_path: {mtime, size}}."""
    result = {}
    if not os.path.isdir(root):
        return result
    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out ignored directories in-place
        rel_dir = os.path.relpath(dirpath, root)
        dirnames[:] = [
            d for d in dirnames
            if self.get_mode(os.path.join(rel_dir, d) if rel_dir != "." else d) != "ignore"
        ]
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root)
            if _is_excluded_file(rel):
                continue
            # Don't need to check mode here — parent dir filtering handles ignore,
            # and we need to scan files in one-way folders to know what to sync
            try:
                st = os.stat(full)
                result[rel] = {"mtime": st.st_mtime, "size": st.st_size}
            except OSError:
                pass
    return result
```

---

### 3. `ui.py` — Folder Rules Editor

Add a "Folder Rules" section between the Sync Interval / Start with Windows area and the Status block.

**Window size:** Change geometry from `"420x580"` to `"420x700"` to accommodate the new section.

#### UI Layout

```
┌─────────────────────────────────────────┐
│  Folder Rules                           │
│  ┌─────────────────────────────────────┐│
│  │ processing     [ignore      ▼]  [x] ││
│  │ archive        [source→local▼]  [x] ││
│  │ exports        [local→source▼]  [x] ││
│  └─────────────────────────────────────┘│
│  [ + Add Rule ]                         │
└─────────────────────────────────────────┘
```

#### Implementation

In `_build_ui()`, after the startup checkbox and before the status frame, add:

```python
# --- Folder Rules ---
rules_frame = customtkinter.CTkFrame(self)
rules_frame.pack(fill="x", padx=15, pady=5)

customtkinter.CTkLabel(rules_frame, text="Folder Rules", font=("", 13, "bold")).pack(anchor="w", padx=10, pady=(10, 5))

self._rules_container = customtkinter.CTkScrollableFrame(rules_frame, height=100)
self._rules_container.pack(fill="x", padx=10, pady=(0, 5))

self._rule_rows = []  # list of {frame, path_entry, mode_menu, mode_var}

customtkinter.CTkButton(
    rules_frame, text="+ Add Rule", width=100,
    command=self._add_rule_row
).pack(anchor="w", padx=10, pady=(0, 10))
```

**Add helper methods:**

```python
MODE_OPTIONS = ["two-way", "source-to-local", "local-to-source", "ignore"]

def _add_rule_row(self, path="", mode="ignore"):
    """Add a folder rule row to the rules editor."""
    row_frame = customtkinter.CTkFrame(self._rules_container, fg_color="transparent")
    row_frame.pack(fill="x", pady=2)

    path_entry = customtkinter.CTkEntry(row_frame, width=160, placeholder_text="subfolder path")
    path_entry.pack(side="left", padx=(0, 5))
    if path:
        path_entry.insert(0, path)

    mode_var = customtkinter.StringVar(value=mode)
    mode_menu = customtkinter.CTkOptionMenu(row_frame, variable=mode_var, values=self.MODE_OPTIONS, width=140)
    mode_menu.pack(side="left", padx=(0, 5))

    delete_btn = customtkinter.CTkButton(
        row_frame, text="x", width=30,
        command=lambda: self._remove_rule_row(row_frame)
    )
    delete_btn.pack(side="left")

    row_data = {"frame": row_frame, "path_entry": path_entry, "mode_menu": mode_menu, "mode_var": mode_var}
    self._rule_rows.append(row_data)

def _remove_rule_row(self, frame):
    """Remove a folder rule row."""
    self._rule_rows = [r for r in self._rule_rows if r["frame"] != frame]
    frame.destroy()

def _get_folder_rules(self):
    """Collect folder rules from the UI rows."""
    rules = []
    for row in self._rule_rows:
        path = row["path_entry"].get().strip().replace("\\", "/").strip("/")
        mode = row["mode_var"].get()
        if path:  # skip empty paths
            rules.append({"path": path, "mode": mode})
    # Ensure processing/ignore is always present
    has_processing = any(r["path"].lower() == "processing" and r["mode"] == "ignore" for r in rules)
    if not has_processing:
        rules.insert(0, {"path": "processing", "mode": "ignore"})
    return rules
```

**Load rules in `_load_current_config()`:**

Add after the existing config loading:

```python
# Load folder rules
rules = cfg.get("folder_rules", [{"path": "processing", "mode": "ignore"}])
for rule in rules:
    self._add_rule_row(path=rule.get("path", ""), mode=rule.get("mode", "ignore"))
```

**Save rules in `_on_save()`:**

Add `folder_rules` to the config dict that gets saved:

```python
cfg = {
    "source_folder": source,
    "local_folder": local,
    "sync_interval": interval,
    "start_with_windows": self.startup_var.get(),
    "folder_rules": self._get_folder_rules(),
}
```

---

### 4. `CLAUDE.md` — Update Documentation

Update the following sections:

**Key Design Decisions — replace the "Excluded paths" bullet:**

```
- **Per-subfolder sync rules:** Each subfolder can have an independent mode: `two-way` (default), `source-to-local`, `local-to-source`, or `ignore`. Rules are configured in `folder_rules` in `config.json`. The deepest matching rule wins. `processing/` defaults to `ignore`.
- **File-level exclusions:** `thumbs.db`, `desktop.ini`, `.ds_store`, `*.tmp`, `*.ffs_db`, `*.ffs_lock`, `*.coworksync.tmp` are always excluded regardless of folder rules.
```

**Architecture — update `sync_engine.py` description to mention:**

```
Contains `get_mode(rel_path)` for per-subfolder rule lookup. Watchdog events carry `side_name` and `mode` through the debounce chain to enforce one-way rules.
```

---

## Decision Logic Summary

This table shows what happens for each mode × scenario combination. Use it to verify correctness.

| Scenario | two-way | source-to-local | local-to-source |
|----------|---------|-----------------|-----------------|
| Both exist, mtimes equal | Skip | Skip | Skip |
| Both exist, source newer | Copy source→local | Copy source→local | Copy local→source |
| Both exist, local newer | Copy local→source | Copy source→local | Copy local→source |
| Only in source, not in state | Copy to local | Copy to local | Delete from source* |
| Only in source, in state | Delete from source | Copy to local | Delete from source* |
| Only in local, not in state | Copy to source | Delete from local* | Copy to source |
| Only in local, in state | Delete from local | Delete from local* | Copy to source |
| Watchdog event from source side | Process normally | Process normally | Ignore |
| Watchdog event from local side | Process normally | Ignore | Process normally |

*These deletions go through `pending_deletes` and are subject to the mass deletion threshold.

**Key difference from two-way:** One-way modes don't check `in_state` for deletions. If the authority side doesn't have a file, it gets deleted from the other side unconditionally (subject to mass delete threshold and first_run guard).

**Exception:** The `first_run` guard still applies to one-way deletions. On first run with empty state, we copy everything and delete nothing, regardless of mode.

---

## Verification

1. `git checkout -b feature/folder-rules` before starting.
2. After all changes, run `python coworksync/main.py --verbose`.
3. Test with default config (no folder_rules) — behavior should be identical to before (all two-way).
4. Add a rule `{"path": "test-readonly", "mode": "source-to-local"}`. Create a file in the local `test-readonly` folder. Confirm it gets deleted on next poll (source is authority, file not in source).
5. Add a rule `{"path": "test-ignore", "mode": "ignore"}`. Create files in `test-ignore` on both sides. Confirm they are never synced.
6. Open the UI. Confirm folder rules are displayed and editable. Add/remove rules, save, reload — confirm persistence.
7. Confirm `processing` folder is still ignored (now via rules instead of hardcoded `EXCLUDED_FOLDERS`).
8. Merge to main when verified: `git checkout main && git merge feature/folder-rules`
