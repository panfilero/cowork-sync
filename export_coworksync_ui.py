import os
from datetime import datetime

OUTPUT = "exported_coworksync_ui.md"

# Files to include — UI window, system tray, icon generation
INCLUDE_FILES = [
    # Config window (CustomTkinter)
    "coworksync/ui.py",

    # System tray icon & menu (pystray)
    "coworksync/tray.py",

    # Icon asset generation (PIL)
    "coworksync/generate_icons.py",
]

# Directories to exclude from tree display
EXCLUDE_DIRS = {
    ".git", "venv", ".vscode", ".idea", ".claude",
    "dist", "__pycache__", ".pytest_cache", "build",
}

# Files to exclude from tree display
EXCLUDE_FILES = {
    "export_coworksync_core.py",
    "export_coworksync_ui.py",
    "exported_coworksync_core.md",
    "exported_coworksync_ui.md",
    ".gitignore",
}


def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ext_to_lang(filepath):
    ext_map = {
        ".py": "python",
        ".md": "markdown",
        ".txt": "text",
        ".bat": "bat",
        ".json": "json",
        ".spec": "python",
        ".cfg": "ini",
        ".ini": "ini",
        ".toml": "toml",
    }
    _, ext = os.path.splitext(filepath)
    return ext_map.get(ext.lower(), "")


def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "<binary or unreadable file>"


def generate_tree(base="."):
    tree_lines = []
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        level = root.replace(base, "").count(os.sep)
        indent = "    " * level
        folder = os.path.basename(root) or "."
        tree_lines.append(f"{indent}{folder}/")
        file_indent = "    " * (level + 1)
        for f in sorted(files):
            if f not in EXCLUDE_FILES:
                tree_lines.append(f"{file_indent}{f}")
    return "\n".join(tree_lines)


with open(OUTPUT, "w", encoding="utf-8") as out:
    out.write("# CoworkSync — UI Export\n\n")
    out.write(f"**Exported:** {get_timestamp()} (local)  \n")
    out.write("**Stack:** Python + CustomTkinter + pystray + Pillow (Windows)  \n")
    out.write("**Scope:** Config window, system tray icon/menu, icon asset generation  \n")
    out.write("**Excludes:** Sync engine, config/state management, logger, entry point  \n\n")
    out.write("---\n\n")

    # Project tree
    out.write("## Project Structure\n\n")
    out.write("```\n")
    out.write(generate_tree())
    out.write("\n```\n\n")
    out.write("---\n\n")

    # File contents
    out.write("## Source Files\n\n")

    for filepath in INCLUDE_FILES:
        if not os.path.exists(filepath):
            continue
        lang = ext_to_lang(filepath)
        content = read_file(filepath)
        out.write(f"### `{filepath}`\n\n")
        out.write(f"```{lang}\n")
        out.write(content)
        if not content.endswith("\n"):
            out.write("\n")
        out.write("```\n\n")
        out.write("---\n\n")

print(f"Export complete -> {OUTPUT}")
