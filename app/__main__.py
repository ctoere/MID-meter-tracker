"""python -m app — start the local server and open a browser."""

from __future__ import annotations

import threading
import webbrowser

import uvicorn

from .config import get_config
from .server import app


def main() -> None:
    cfg = get_config()
    url = f"http://{cfg.host}:{cfg.port}/"

    if not cfg.register_path.exists():
        raise SystemExit(
            f"No register at {cfg.register_path}\n"
            f"Run the one-time migration first:  python -m migrate.migrate_tracker"
        )

    print(f"Zeres MID Register — {cfg.register_path}")
    print(f"  {url}")
    if cfg.open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()
