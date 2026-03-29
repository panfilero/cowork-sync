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
    """Save config to disk atomically."""
    os.makedirs(APP_DIR, exist_ok=True)
    tmp_path = CONFIG_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, CONFIG_FILE)


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
            winreg.SetValueEx(key, REGISTRY_VALUE, 0, winreg.REG_SZ, f'"{exe_path}" --silent')
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
    """Save sync state to disk atomically."""
    os.makedirs(APP_DIR, exist_ok=True)
    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, STATE_FILE)
