#!/usr/bin/env python
"""Run the panel API without connecting to Telegram.

Frontend work only needs the API and the database. Starting the whole bot for that
means a live Telegram session, the plugin tree, the scheduler and the AI stack - slow
to boot and awkward to restart on every change.

This starts the database and the HTTP server, and nothing else. Endpoints backed by
the database work normally; the few that call Telegram (member sync, leaving a chat,
the divorce notification) will fail, and `/health` reports 503 because no client is
connected. That is the expected shape of a frontend dev environment.

Run the real bot (`uv run python -m kmua`) when you need those paths.

Usage:
    uv run python scripts/dev_server.py
    uv run python scripts/dev_server.py --port 8180 --reload-hint
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def serve(host: str, port: int) -> None:
    from kmua.config import app_config

    # Force the panel on: this script exists to serve it, whatever the file says.
    app_config.webapp = True
    app_config.webapp_host = host
    app_config.webapp_port = port

    if not app_config.webapp_allow_origins:
        print(
            "warning: webapp_allow_origins is empty, so requests from the Vite dev "
            "server (a different origin) will be blocked by the browser.\n"
            '         add webapp_allow_origins = ["http://localhost:5173"] to '
            "settings.dev.toml",
            file=sys.stderr,
        )

    import uvicorn

    from kmua.database import db
    from kmua.webapp import create_app

    await db.init_db()

    config = uvicorn.Config(
        create_app(panel_enabled=True),
        host=host,
        port=port,
        log_config=None,
        access_log=True,
        lifespan="on",
    )
    server = uvicorn.Server(config)

    print(f"\n  API   http://{host}:{port}/api")
    print("  Front http://localhost:5173  (run `pnpm dev` in webapp/)")
    print("\n  No Telegram client: /health reports 503 and Telegram-backed")
    print("  endpoints will fail. Everything database-backed works.\n")

    try:
        await server.serve()
    finally:
        await db.close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8180)
    args = parser.parse_args()

    try:
        asyncio.run(serve(args.host, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
