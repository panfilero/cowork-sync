"""CoworkSync — entry point. Initializes tray, web server, and sync engine."""

import sys
import threading

from coworksync.config import load_config, is_configured
from coworksync.sync_engine import SyncEngine
from coworksync.server import start_server
from coworksync.tray import TrayApp
from coworksync.logger import logger


def main():
    logger.info("CoworkSync starting up.")

    # Create sync engine
    engine = SyncEngine()

    # Start Flask web server
    port = start_server(engine, port=5420)
    logger.info("Web UI available at http://localhost:%d", port)

    # Load config and auto-start sync if configured
    cfg = load_config()
    if is_configured(cfg):
        engine.configure(cfg)
        engine.start()
    else:
        logger.info("No config found — open the web UI to configure.")
        # Open browser on first run
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    # Run system tray (blocking — runs the Windows message loop)
    tray = TrayApp(engine, port=port)
    try:
        tray.run()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        logger.info("CoworkSync shut down.")


if __name__ == "__main__":
    main()
