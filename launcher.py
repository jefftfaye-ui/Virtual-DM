"""Entry point for packaged binary. Starts the server and opens the browser.

Works both as `python launcher.py` and when frozen by PyInstaller.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _wait_and_open(port: int = 8080, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.15)

    import dm_config
    url = "http://localhost:8080/setup" if not dm_config.is_configured() else "http://localhost:8080/ui"
    webbrowser.open(url)


def main() -> None:
    # When frozen, _MEIPASS is the temp dir with bundled files
    if getattr(sys, "frozen", False):
        root = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        os.chdir(root)
        sys.path.insert(0, str(root))

    # Load config before server imports read os.environ
    import dm_config
    dm_config.load()

    # Also load .env if present (dev fallback)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    threading.Thread(target=_wait_and_open, daemon=True).start()

    import uvicorn
    from server import app

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), log_level="warning")


if __name__ == "__main__":
    main()
