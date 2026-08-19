"""api.run — executable entrypoint for the packaged FastAPI sidecar.

``api/app.py`` only builds the app object; something must invoke uvicorn.
The Tauri desktop app spawns this module (bundled by PyInstaller as the
``astra-api`` binary) as its backend process.

Env overrides:
- ``ASTRA_API_PORT``: port to bind (default 8000). Lets the desktop shell
  pick a free port instead of clashing with a dev server.
- ``ASTRA_API_HOST``: bind address (default 0.0.0.0).
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("ASTRA_API_HOST", "0.0.0.0")
    port = int(os.environ.get("ASTRA_API_PORT", "8000"))

    # Import the app object directly (not by dotted string) so the frozen
    # PyInstaller bundle never has to re-import ``api.app`` by name.
    from api.app import app

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("ASTRA_LOG_LEVEL", "info"),
        access_log=os.environ.get("ASTRA_ACCESS_LOG", "0") == "1",
    )


if __name__ == "__main__":
    main()
