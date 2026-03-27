"""CoworkSync — entry point. Initializes tray, sync engine, and UI."""

import sys

from coworksync.config import load_config, is_configured
from coworksync.sync_engine import SyncEngine
from coworksync.tray import TrayApp
from coworksync.logger import logger
from coworksync import ui


def main():
    logger.info("CoworkSync starting up.")

    # Create sync engine
    engine = SyncEngine()

    # Wire the UI to the engine
    ui.set_engine(engine)

    # Load config and auto-start sync if configured
    cfg = load_config()
    if is_configured(cfg):
        engine.configure(cfg)
        engine.start()
    else:
        logger.info("No config found — open the tray menu to configure.")
        ui.open_window_threaded()

    # Run system tray (blocking — runs the Windows message loop)
    tray = TrayApp(engine)
    try:
        tray.run()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        logger.info("CoworkSync shut down.")


if __name__ == "__main__":
    main()
