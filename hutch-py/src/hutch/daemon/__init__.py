"""Hutch daemon — FastAPI capture + read API.

The full event-ingest and read endpoints land in M2.
For M0 the daemon serves a placeholder index page and a healthcheck.
"""

from __future__ import annotations

from hutch.daemon.app import create_app
from hutch.daemon.server import run_daemon

__all__ = ["create_app", "run_daemon"]
