"""Static-asset server for the built Next.js UI bundle.

The dashboard is shipped as a static export from ``hutch-ui/`` and copied to
``hutch-py/src/hutch/ui_server/static/`` by ``pnpm --filter hutch-ui build:daemon``.
:func:`bundle_path` returns that location if it exists; the daemon falls
back to the M0 placeholder index when no bundle is present.
"""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def bundle_path() -> Path | None:
    """Return the static UI bundle directory if it exists."""
    if _STATIC_DIR.is_dir() and (_STATIC_DIR / "index.html").exists():
        return _STATIC_DIR
    return None


__all__ = ["bundle_path"]
