"""uvicorn launcher for the Hutch daemon.

Kept separate from :mod:`hutch.daemon.app` so test code can import the
FastAPI app factory without booting a server.
"""

from __future__ import annotations

import os
from ipaddress import ip_address
from pathlib import Path

import uvicorn

from hutch.daemon.app import DEFAULT_DB_PATH


def run_daemon(
    host: str = "127.0.0.1",
    port: int = 7777,
    *,
    db_path: Path | str | None = None,
    reload: bool = False,
    unsafe_no_auth: bool = False,
) -> None:
    """Run the Hutch daemon under uvicorn (blocking call).

    Resolution for ``db_path``:

    1. Explicit argument.
    2. ``HUTCH_DB_PATH`` environment variable.
    3. The default at ``~/.hutch/hutch.duckdb``.
    """
    if db_path is None:
        db_path = os.environ.get("HUTCH_DB_PATH") or DEFAULT_DB_PATH
    if not _is_loopback_host(host) and not os.environ.get("HUTCH_TOKEN") and not unsafe_no_auth:
        raise RuntimeError(
            "refusing to bind Hutch daemon to a non-loopback host without HUTCH_TOKEN. "
            "Set HUTCH_TOKEN or pass --unsafe-no-auth for trusted local networks only."
        )
    # The lifespan opens the connection — pass the path through the env so
    # uvicorn's reloader-spawned worker reads the same value.
    os.environ["HUTCH_DB_PATH"] = str(db_path)
    uvicorn.run(
        "hutch.daemon.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def _is_loopback_host(host: str) -> bool:
    """Return True for host values that bind only to loopback interfaces."""
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False
