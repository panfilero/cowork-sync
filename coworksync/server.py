"""Flask web server for CoworkSync config UI."""

import os
import socket
import threading

from flask import Flask, jsonify, request, render_template

from coworksync.config import (
    load_config, save_config, validate_source, validate_local,
    warn_local, set_startup, get_startup_enabled,
)
from coworksync.logger import LOG_FILE

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# The sync engine is set externally before starting the server
engine = None


def set_engine(eng):
    global engine
    engine = eng


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    from datetime import datetime
    last_sync = None
    next_poll = None
    if engine and engine.last_sync:
        last_sync = engine.last_sync.isoformat()
    if engine and engine.next_poll:
        remaining = engine.next_poll - datetime.now().timestamp()
        next_poll = max(0, int(remaining))
    return jsonify({
        "status": engine.status if engine else "stopped",
        "last_sync": last_sync,
        "next_poll": next_poll,
        "files_today": engine.files_today if engine else 0,
        "error": engine.error_message if engine else "",
    })


@app.route("/api/config", methods=["GET"])
def api_get_config():
    cfg = load_config()
    cfg["start_with_windows"] = get_startup_enabled()
    return jsonify(cfg)


@app.route("/api/config", methods=["POST"])
def api_save_config():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided."}), 400

    source = data.get("source_folder", "").strip()
    local = data.get("local_folder", "").strip()
    interval = data.get("sync_interval", 5)
    start_win = data.get("start_with_windows", True)

    # Validate
    err = validate_source(source)
    if err:
        return jsonify({"error": err}), 400
    err = validate_local(local)
    if err:
        return jsonify({"error": err}), 400

    try:
        interval = int(interval)
        interval = max(1, min(60, interval))
    except (TypeError, ValueError):
        interval = 5

    cfg = {
        "source_folder": source,
        "local_folder": local,
        "sync_interval": interval,
        "start_with_windows": start_win,
    }
    save_config(cfg)

    # Update startup registry
    import sys
    exe = sys.executable
    if getattr(sys, "frozen", False):
        exe = sys.executable
    set_startup(start_win, exe)

    # Reconfigure engine
    if engine:
        engine.configure(cfg)

    warning = warn_local(local)
    return jsonify({"ok": True, "warning": warning})


@app.route("/api/start", methods=["POST"])
def api_start():
    if engine:
        if engine.running:
            return jsonify({"ok": True, "message": "Already running."})
        engine.start()
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    if engine:
        engine.stop()
    return jsonify({"ok": True})


@app.route("/api/sync-now", methods=["POST"])
def api_sync_now():
    if engine:
        engine.sync_now()
    return jsonify({"ok": True})


@app.route("/api/log")
def api_log():
    if engine and engine.recent_activity:
        return jsonify(engine.recent_activity[:50])
    # Fallback: read from log file
    lines = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()[-50:]
        except OSError:
            pass
    entries = []
    for line in lines:
        line = line.strip()
        if line:
            entries.append({"raw": line})
    return jsonify(entries)


def find_free_port(start=5420):
    """Find a free port starting from the given number."""
    port = start
    while port < start + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1
    return start  # fallback


def start_server(eng, port=5420):
    """Start the Flask server in a background thread. Returns actual port used."""
    set_engine(eng)
    actual_port = find_free_port(port)

    def _run():
        app.run(host="127.0.0.1", port=actual_port, debug=False, use_reloader=False)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return actual_port
