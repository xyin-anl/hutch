"""SDK configuration and connection-mode resolution.

The SDK supports two transport modes:

* ``daemon``  — POST events to a running ``hutch serve``.
* ``embedded`` — write directly to a local DuckDB file.

Either mode can additionally emit ``research.*`` OpenTelemetry spans by
setting ``otel_endpoint`` (requires the optional ``[otel]`` extra), and
emit OpenLineage ``RunEvent`` JSON by setting ``openlineage_endpoint``
(dep-free).

Resolution order at process start:

1. Explicit :func:`configure` call.
2. ``HUTCH_DAEMON_URL`` env var → daemon mode at that URL.
3. ``HUTCH_DB_PATH`` env var → embedded mode at that path.
4. Default: daemon mode at ``http://127.0.0.1:7777``. The actual transport
   lazily falls back to embedded if the daemon isn't reachable on first
   send (see :mod:`hutch.sdk.transport`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

TransportMode = Literal["daemon", "embedded"]
DEFAULT_DAEMON_URL = "http://127.0.0.1:7777"
DEFAULT_DB_PATH = Path.home() / ".hutch" / "hutch.duckdb"
DEFAULT_FALLBACK_PATH = Path.home() / ".hutch" / "fallback-events.jsonl"


@dataclass(slots=True)
class SDKConfig:
    """Resolved SDK configuration for the current process."""

    mode: TransportMode = "daemon"
    daemon_url: str = DEFAULT_DAEMON_URL
    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)
    fallback_path: Path = field(default_factory=lambda: DEFAULT_FALLBACK_PATH)
    strict: bool = False
    request_timeout_s: float = 5.0
    auto_fallback: bool = True
    auth_token: str | None = None
    # Optional OTel emit path. When set, every
    # canonical event additionally lands as a ``research.*`` OTel span,
    # in addition to the regular daemon / embedded transport. Off by
    # default; activate via ``HUTCH_OTEL_ENDPOINT`` or
    # ``h.configure(SDKConfig(otel_endpoint=…))``. Requires the optional
    # ``[otel]`` extra; without it a one-time warning is logged and the
    # SDK runs without OTel emission.
    otel_endpoint: str | None = None
    otel_service_name: str = "hutch"
    # Optional OpenLineage emit path.
    # When set, lineage-relevant events (run_start / run_end / operator /
    # self_mod) are POSTed as OL ``RunEvent`` JSON to the configured
    # ``/api/v1/lineage`` endpoint. Off by default. Dep-free — no
    # ``openlineage-python`` extra required.
    openlineage_endpoint: str | None = None
    openlineage_namespace: str = "hutch"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> SDKConfig:
        """Build a config from environment variables (defaults to ``os.environ``)."""
        e = env if env is not None else os.environ
        cfg = cls()
        if url := e.get("HUTCH_DAEMON_URL"):
            cfg.mode = "daemon"
            cfg.daemon_url = url
        elif path := e.get("HUTCH_DB_PATH"):
            cfg.mode = "embedded"
            cfg.db_path = Path(path)
        if fb := e.get("HUTCH_FALLBACK_PATH"):
            cfg.fallback_path = Path(fb)
        if e.get("HUTCH_STRICT"):
            cfg.strict = e["HUTCH_STRICT"].lower() not in {"", "0", "false", "no"}
        if to := e.get("HUTCH_TIMEOUT_S"):
            timeout = float(to)
            if timeout <= 0:
                raise ValueError("HUTCH_TIMEOUT_S must be positive")
            cfg.request_timeout_s = timeout
        if token := e.get("HUTCH_TOKEN"):
            cfg.auth_token = token
        if otel := e.get("HUTCH_OTEL_ENDPOINT"):
            cfg.otel_endpoint = otel
        if otel_svc := e.get("HUTCH_OTEL_SERVICE_NAME"):
            cfg.otel_service_name = otel_svc
        if ol := e.get("HUTCH_OPENLINEAGE_ENDPOINT"):
            cfg.openlineage_endpoint = ol
        if ol_ns := e.get("HUTCH_OPENLINEAGE_NAMESPACE"):
            cfg.openlineage_namespace = ol_ns
        return cfg
