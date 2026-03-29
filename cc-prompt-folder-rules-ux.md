# Task: Improve Folder Rules UX

The folder rules editor currently requires manually typing subfolder names. Fix this.

---

## Changes to `ui.py`

### 1. Add explanatory label

In `_build_ui()`, right after the "Folder Rules" bold label and before `self._rules_container`, add:

```python
customtkinter.CTkLabel(
    rules_frame,
    text="All folders sync two-way by default. Add exceptions below.",
    text_color="gray",
    font=("", 11),
).pack(anchor="w", padx=10, pady=(0, 5))
```

### 2. Replace free-text path entry with a dropdown

Change `_add_rule_row()` so the path field is a `CTkOptionMenu` populated with actual subfolders from the configured source/local paths, instead of a `CTkEntry` with manual typing.

Add a helper method to scan for subfolders:

```python
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
```

### 3. Rewrite `_add_rule_row()`

Replace the current implementation:

```python
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
```

### 4. Update `_get_folder_rules()` to use `path_var`

```python
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
```

### 5. Update `_load_current_config()` — no changes needed

The existing code already calls `_add_rule_row(path=..., mode=...)` which will hit the `if path:` branch and show a read-only label. This is correct — existing rules display as labels, new rules get the dropdown picker.

---

## What this does NOT change

- Config keys stay the same (`folder_rules` in `config.json`)
- `sync_engine.py` is untouched — the rules format is identical
- The `processing → ignore` rule is still pre-populated and enforced
- The "x" delete button still works on all rows

## Verification

1. Open the UI with valid cloud and local folders configured.
2. Click "+ Add Rule" — confirm you see a dropdown of actual subfolders, not a text entry.
3. Confirm existing rules (like `processing → ignore`) show as labels, not dropdowns.
4. Add a rule, save, reopen — confirm it persists and shows as a label.
5. Confirm the dropdown excludes folders that already have rules.
