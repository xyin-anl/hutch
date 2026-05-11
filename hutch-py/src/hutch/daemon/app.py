"""FastAPI application factory for the Hutch daemon.

For M2 the daemon serves the M0 placeholder index plus the canonical
event-ingest and read endpoints. The UI is wired
in M3; the steering and import endpoints land in M9 and M8 respectively.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from string import Template
from typing import Any, Literal, cast

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from hutch import __version__
from hutch.daemon.broadcaster import RunBroadcaster
from hutch.schema import EVENT_ADAPTER, AnyEvent, SteeringCommandEvent, SteeringCommandPayload
from hutch.schema.types import SteeringActor, SteeringCommandKind
from hutch.steering.store import SteeringStore
from hutch.store import insert_event, open_and_migrate, read_events
from hutch.store.database import DuckConn
from hutch.ui_server import bundle_path

logger = logging.getLogger("hutch.daemon")

DEFAULT_DB_PATH = Path.home() / ".hutch" / "hutch.duckdb"
DEFAULT_MAX_EVENT_BODY_BYTES = 10 * 1024 * 1024
DEFAULT_READ_LIMIT = 5_000

_AUTH_PROTECTED_PREFIXES = ("/events", "/runs", "/steering", "/docs", "/openapi.json")


_INDEX_TEMPLATE = Template("""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>The Hutch</title>
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <style>
      :root { color-scheme: light dark; }
      body {
        margin: 0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #0b0d10;
        color: #e6e8eb;
        display: grid;
        place-items: center;
        min-height: 100vh;
      }
      main { text-align: center; padding: 2rem; max-width: 36rem; }
      h1 { font-size: 3rem; margin: 0 0 0.25rem; letter-spacing: -0.02em; }
      p { color: #9aa1a8; line-height: 1.6; }
      code { background: #1a1d21; padding: 0.15rem 0.4rem; border-radius: 0.25rem; }
      .v { font-variant-numeric: tabular-nums; opacity: 0.6; font-size: 0.85rem; }
    </style>
  </head>
  <body>
    <main>
      <h1>The Hutch.</h1>
      <p>
        Observability, steering, and provenance for autonomous-research agents.
        The daemon is running; the dashboard usually mounts at <code>/</code>.
        The API lives at <code>/healthz</code>, <code>/version</code>,
        <code>/events</code>, and <code>/runs</code>.
      </p>
      <p class="v">hutch $version · schema additive-only post-v0.1.0</p>
    </main>
  </body>
</html>
""")

_INDEX_HTML = _INDEX_TEMPLATE.substitute(version=__version__)


# ---------- response models -------------------------------------------------


class IngestResponse(BaseModel):
    """Returned by ``POST /events``."""

    accepted: int = Field(description="Number of events written.")
    rejected: int = Field(default=0, description="Number of events that failed validation.")
    duplicates: int = Field(default=0, description="Number of already-seen event ids ignored.")


class RunSummary(BaseModel):
    """Aggregate stats per run for the run-list page."""

    run_id: str
    name: str | None = None
    project: str | None = None
    started_at_ns: int | None = None
    ended_at_ns: int | None = None
    status: str | None = None
    event_count: int
    kinds_seen: list[str] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    system_kind: Literal["unknown", "linear", "evolutionary", "self-improving", "tree-search"] = (
        "unknown"
    )


class StreamEventsResponse(BaseModel):
    """Paged stream-event response for high-volume audit views."""

    events: list[dict[str, Any]]
    total: int
    offset: int
    limit: int


def _json_payload_to_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    else:
        parsed = raw
    return parsed if isinstance(parsed, dict) else {}


def _run_system_kind(
    conn: DuckConn,
    run_id: str,
    kinds_seen: list[str] | None = None,
) -> Literal["unknown", "linear", "evolutionary", "self-improving", "tree-search"]:
    return _run_system_kinds_many(conn, {run_id: kinds_seen or []}).get(run_id, "unknown")


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))


def _payload_capabilities(payload: dict[str, Any]) -> dict[str, bool]:
    raw = payload.get("capabilities")
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, bool)}


def _run_explicit_capabilities(conn: DuckConn, run_id: str) -> dict[str, bool]:
    capabilities: dict[str, bool] = {}
    conn.execute(
        """
        SELECT payload
          FROM events
         WHERE run_id = ? AND event_kind = 'run_start'
         ORDER BY timestamp_ns ASC, event_id ASC
         LIMIT 1;
        """,
        [run_id],
    )
    start_row = conn.fetchone()
    if start_row is not None:
        capabilities.update(_payload_capabilities(_json_payload_to_dict(start_row[0])))

    conn.execute(
        """
        SELECT payload
          FROM events
         WHERE run_id = ? AND event_kind = 'run_update'
         ORDER BY timestamp_ns DESC, event_id DESC
         LIMIT 1;
        """,
        [run_id],
    )
    update_row = conn.fetchone()
    if update_row is not None:
        capabilities.update(_payload_capabilities(_json_payload_to_dict(update_row[0])))
    return capabilities


def _run_inferred_capabilities(conn: DuckConn, run_id: str) -> dict[str, bool]:
    return _run_inferred_capabilities_many(conn, [run_id]).get(run_id, {})


def _run_inferred_capabilities_many(
    conn: DuckConn,
    run_ids: list[str],
) -> dict[str, dict[str, bool]]:
    if not run_ids:
        return {}
    placeholders = _placeholders(len(run_ids))
    sql = f"""
        SELECT run_id,
               SUM(
                   CASE
                       WHEN event_kind = 'operator'
                        AND (
                            json_extract_string(payload, '$.cost_usd') IS NOT NULL
                         OR json_extract_string(payload, '$.tokens_in') IS NOT NULL
                         OR json_extract_string(payload, '$.tokens_out') IS NOT NULL
                        )
                       THEN 1 ELSE 0
                   END
               ) AS llm_usage_count,
               SUM(
                   CASE
                       WHEN event_kind = 'stream_event'
                        AND (
                            json_extract_string(payload, '$.label') IN (
                                'cvevolve_message',
                                'cvevolve_tool_call'
                            )
                         OR json_extract_string(payload, '$.metadata.audit_kind') IS NOT NULL
                        )
                       THEN 1 ELSE 0
                   END
               ) AS audit_count
          FROM events
         WHERE run_id IN ({placeholders})
         GROUP BY run_id;
        """  # noqa: S608 - placeholder string is generated from trusted run-id count.
    conn.execute(sql, run_ids)
    out: dict[str, dict[str, bool]] = {}
    for run_id, llm_usage_count, audit_count in conn.fetchall():
        inferred: dict[str, bool] = {}
        if int(llm_usage_count or 0) > 0:
            inferred["llm_usage"] = True
        if int(audit_count or 0) > 0:
            inferred["audit"] = True
        out[str(run_id)] = inferred
    return out


def _run_capabilities(conn: DuckConn, run_id: str) -> dict[str, bool]:
    return _run_capabilities_many(conn, [run_id]).get(run_id, {})


def _run_explicit_capabilities_many(
    conn: DuckConn,
    run_ids: list[str],
) -> dict[str, dict[str, bool]]:
    if not run_ids:
        return {}
    out: dict[str, dict[str, bool]] = {run_id: {} for run_id in run_ids}
    placeholders = _placeholders(len(run_ids))

    start_sql = f"""
        SELECT run_id, payload
          FROM (
              SELECT run_id,
                     payload,
                     ROW_NUMBER() OVER (
                         PARTITION BY run_id
                         ORDER BY timestamp_ns ASC, event_id ASC
                     ) AS rn
                FROM events
               WHERE event_kind = 'run_start'
                 AND run_id IN ({placeholders})
          )
         WHERE rn = 1;
        """  # noqa: S608 - placeholder string is generated from trusted run-id count.
    conn.execute(start_sql, run_ids)
    for row_run_id, payload_raw in conn.fetchall():
        out.setdefault(str(row_run_id), {}).update(
            _payload_capabilities(_json_payload_to_dict(payload_raw))
        )

    update_sql = f"""
        SELECT run_id, payload
          FROM (
              SELECT run_id,
                     payload,
                     ROW_NUMBER() OVER (
                         PARTITION BY run_id
                         ORDER BY timestamp_ns DESC, event_id DESC
                     ) AS rn
                FROM events
               WHERE event_kind = 'run_update'
                 AND run_id IN ({placeholders})
          )
         WHERE rn = 1;
        """  # noqa: S608 - placeholder string is generated from trusted run-id count.
    conn.execute(update_sql, run_ids)
    for row_run_id, payload_raw in conn.fetchall():
        out.setdefault(str(row_run_id), {}).update(
            _payload_capabilities(_json_payload_to_dict(payload_raw))
        )
    return out


def _run_capabilities_many(conn: DuckConn, run_ids: list[str]) -> dict[str, dict[str, bool]]:
    out = _run_explicit_capabilities_many(conn, run_ids)
    inferred = _run_inferred_capabilities_many(conn, run_ids)
    for run_id in run_ids:
        capabilities = out.setdefault(run_id, {})
        for key, value in inferred.get(run_id, {}).items():
            capabilities.setdefault(key, value)
    return out


def _run_system_kinds_many(
    conn: DuckConn,
    kinds_by_run: dict[str, list[str]],
) -> dict[str, Literal["unknown", "linear", "evolutionary", "self-improving", "tree-search"]]:
    out: dict[
        str,
        Literal["unknown", "linear", "evolutionary", "self-improving", "tree-search"],
    ] = {}
    unresolved: set[str] = set()
    for run_id, kinds_seen in kinds_by_run.items():
        kinds = set(kinds_seen or [])
        if "self_mod" in kinds:
            out[run_id] = "self-improving"
        elif "tree_expansion" in kinds:
            out[run_id] = "tree-search"
        elif {"descriptor", "migration", "pareto_snapshot"} & kinds:
            out[run_id] = "evolutionary"
        else:
            unresolved.add(run_id)

    if not unresolved:
        return out

    unresolved_list = sorted(unresolved)
    placeholders = _placeholders(len(unresolved_list))
    adapter_sql = f"""
        SELECT run_id, adapter
          FROM (
              SELECT run_id,
                     json_extract_string(payload, '$.metadata.adapter') AS adapter,
                     ROW_NUMBER() OVER (
                         PARTITION BY run_id
                         ORDER BY timestamp_ns ASC, event_id ASC
                     ) AS rn
                FROM events
               WHERE event_kind = 'run_start'
                 AND run_id IN ({placeholders})
          )
         WHERE rn = 1;
        """  # noqa: S608 - placeholder string is generated from trusted run-id count.
    conn.execute(adapter_sql, unresolved_list)
    for run_id, adapter in conn.fetchall():
        if adapter == "cvevolve":
            out[str(run_id)] = "evolutionary"
            unresolved.discard(str(run_id))

    if not unresolved:
        return out

    unresolved_list = sorted(unresolved)
    placeholders = _placeholders(len(unresolved_list))
    operators_sql = f"""
        SELECT run_id, LIST(DISTINCT json_extract_string(payload, '$.kind'))
          FROM events
         WHERE event_kind = 'operator'
           AND run_id IN ({placeholders})
         GROUP BY run_id;
        """  # noqa: S608 - placeholder string is generated from trusted run-id count.
    conn.execute(operators_sql, unresolved_list)
    op_kinds_by_run: dict[str, set[str]] = {}
    for run_id, values in conn.fetchall():
        op_kinds_by_run[str(run_id)] = {
            str(value) for value in (values or []) if isinstance(value, str) and value
        }

    individuals_sql = f"""
        SELECT run_id,
               COUNT(*),
               SUM(
                   CASE WHEN json_extract_string(payload, '$.is_seed') = 'true'
                        THEN 1 ELSE 0 END
               ),
               SUM(
                   CASE
                       WHEN COALESCE(json_array_length(payload, '$.parent_ids'), 0) > 0
                       THEN 1 ELSE 0
                   END
               ),
               COUNT(DISTINCT NULLIF(json_extract_string(payload, '$.island_id'), ''))
          FROM events
         WHERE event_kind = 'individual'
           AND run_id IN ({placeholders})
         GROUP BY run_id;
        """  # noqa: S608 - placeholder string is generated from trusted run-id count.
    conn.execute(individuals_sql, unresolved_list)
    individual_stats: dict[str, tuple[int, int, int, int]] = {}
    for run_id, individual_count, seed_count, parented_count, island_count in conn.fetchall():
        individual_stats[str(run_id)] = (
            int(individual_count or 0),
            int(seed_count or 0),
            int(parented_count or 0),
            int(island_count or 0),
        )

    for run_id in unresolved:
        op_kinds = op_kinds_by_run.get(run_id, set())
        individual_count, seed_count, parented_count, island_count = individual_stats.get(
            run_id,
            (0, 0, 0, 0),
        )
        if "self_modify" in op_kinds:
            out[run_id] = "self-improving"
        elif "tree_expand" in op_kinds:
            out[run_id] = "tree-search"
        elif op_kinds & {"mutate", "crossover", "migrate", "diversify", "select", "meta_mutate"}:
            out[run_id] = "evolutionary"
        elif island_count >= 2 or seed_count >= 2:
            out[run_id] = "evolutionary"
        elif not op_kinds and parented_count == 0:
            out[run_id] = "unknown"
        elif individual_count == 0 and not op_kinds:
            out[run_id] = "unknown"
        else:
            out[run_id] = "linear"
    return out


def _run_status(conn: DuckConn, run_id: str) -> str | None:
    conn.execute(
        """
        SELECT payload
          FROM events
         WHERE run_id = ? AND event_kind = 'run_end'
         ORDER BY timestamp_ns DESC, event_id DESC
         LIMIT 1;
        """,
        [run_id],
    )
    end_row = conn.fetchone()
    if end_row is not None:
        payload = _json_payload_to_dict(end_row[0])
        status_raw = payload.get("status")
        if isinstance(status_raw, str) and status_raw:
            return status_raw

    conn.execute(
        """
        SELECT payload
          FROM events
         WHERE run_id = ? AND event_kind = 'run_update'
         ORDER BY timestamp_ns DESC, event_id DESC
         LIMIT 1;
        """,
        [run_id],
    )
    update_row = conn.fetchone()
    if update_row is not None:
        payload = _json_payload_to_dict(update_row[0])
        status_raw = payload.get("status")
        if isinstance(status_raw, str) and status_raw:
            return status_raw

    conn.execute("SELECT COUNT(*) FROM events WHERE run_id = ?;", [run_id])
    count_row = conn.fetchone()
    if count_row is None or int(count_row[0]) == 0:
        return None
    return "running"


def _run_exists(conn: DuckConn, run_id: str) -> bool:
    conn.execute("SELECT COUNT(*) FROM events WHERE run_id = ?;", [run_id])
    row = conn.fetchone()
    return row is not None and int(row[0]) > 0


def _event_row_to_json(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        event_id,
        event_kind,
        run_id,
        timestamp_ns,
        stream_id,
        worker_id,
        span_id,
        trace_id,
        payload,
    ) = row
    payload_obj = json.loads(payload) if isinstance(payload, str) else payload
    event = EVENT_ADAPTER.validate_python(
        {
            "event_id": str(event_id),
            "event_kind": event_kind,
            "run_id": run_id,
            "timestamp_ns": int(timestamp_ns),
            "stream_id": stream_id,
            "worker_id": worker_id,
            "span_id": span_id,
            "trace_id": trace_id,
            "payload": payload_obj,
        }
    )
    return cast(dict[str, Any], json.loads(event.model_dump_json()))


# ---------- app construction ------------------------------------------------


def _get_conn(request: Request) -> DuckConn:
    return cast(DuckConn, request.app.state.db_conn)


def _get_db_write_lock(request: Request) -> asyncio.Lock:
    return cast(asyncio.Lock, request.app.state.db_write_lock)


def _get_broadcaster(request: Request) -> RunBroadcaster:
    return cast(RunBroadcaster, request.app.state.broadcaster)


def _get_steering(request: Request) -> SteeringStore:
    return cast(SteeringStore, request.app.state.steering)


def _path_requires_auth(path: str) -> bool:
    return any(
        path == prefix or path.startswith(prefix + "/") for prefix in _AUTH_PROTECTED_PREFIXES
    )


def _auth_token_from_state(app: FastAPI) -> str | None:
    raw = getattr(app.state, "auth_token", None) or os.environ.get("HUTCH_TOKEN")
    if not isinstance(raw, str):
        return None
    token = raw.strip()
    return token or None


def _is_authorized_header(auth_header: str | None, expected_token: str) -> bool:
    if not auth_header:
        return False
    scheme, _, supplied = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        return False
    return secrets.compare_digest(supplied, expected_token)


def _max_event_body_bytes() -> int:
    raw = os.environ.get("HUTCH_MAX_EVENT_BODY_BYTES")
    if raw is None:
        return DEFAULT_MAX_EVENT_BODY_BYTES
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_MAX_EVENT_BODY_BYTES
    return max(1, parsed)


# ---------- steering request models ----------------------------------------


class SteeringIssueRequest(BaseModel):
    """Body of ``POST /steering/{run_id}``."""

    command: SteeringCommandKind
    target_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    actor: SteeringActor = "human"


class SteeringAckRequest(BaseModel):
    """Body of ``POST /steering/{run_id}/{command_id}/ack``."""

    outcome: Literal["accepted", "rejected", "done"]
    note: str | None = None


def create_app(*, db_path: Path | str | None = None, auth_token: str | None = None) -> FastAPI:
    """Build and return the Hutch FastAPI app.

    ``db_path=None`` opens an in-memory DuckDB. Pass an explicit path, or set
    ``HUTCH_DB_PATH`` *before* the daemon's lifespan runs, for persistent
    storage. The env var is resolved lazily inside the lifespan so
    ``hutch serve --db <path>`` works even though the CLI sets the env var
    after :mod:`hutch.daemon.app` is first imported (the package
    ``__init__`` imports it).
    """
    captured_arg: Path | None = Path(db_path) if db_path is not None else None
    captured_auth_token = auth_token

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        target_path = captured_arg
        if target_path is None:
            env_path = os.environ.get("HUTCH_DB_PATH")
            if env_path:
                target_path = Path(env_path)
        if target_path is not None:
            target_path.parent.mkdir(parents=True, exist_ok=True)
        conn = open_and_migrate(target_path)
        app.state.db_conn = conn
        app.state.db_write_lock = asyncio.Lock()
        app.state.db_path = target_path
        if captured_auth_token is not None:
            app.state.auth_token = captured_auth_token
        else:
            app.state.auth_token = os.environ.get("HUTCH_TOKEN")
        app.state.broadcaster = RunBroadcaster()
        app.state.steering = SteeringStore()
        try:
            yield
        finally:
            conn.close()

    app = FastAPI(
        title="The Hutch",
        version=__version__,
        description="Observability, steering, and provenance for autonomous-research agents.",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def require_token_auth(request: Request, call_next: Any) -> Any:
        if request.method == "OPTIONS" or not _path_requires_auth(request.url.path):
            return await call_next(request)
        token = _auth_token_from_state(request.app)
        if token is None:
            return await call_next(request)
        if _is_authorized_header(request.headers.get("authorization"), token):
            return await call_next(request)
        return JSONResponse(
            {"detail": "authentication required"},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # CORS: hutch-ui's `pnpm dev` runs on :7700 and talks to the daemon on
    # :7777. Allow any localhost origin so a developer can run both without
    # extra config. Production deployments behind a reverse proxy already
    # share an origin and don't need this.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------- index / health / version ------------------------------------

    bundle_dir = bundle_path()

    if bundle_dir is None:

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def index() -> HTMLResponse:
            return HTMLResponse(_INDEX_HTML)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/version")
    async def version() -> dict[str, str]:
        return {"version": __version__}

    # ---------- ingest -------------------------------------------------------

    @app.post("/events", response_model=IngestResponse)
    async def ingest_event(
        request: Request,
        conn: DuckConn = Depends(_get_conn),
        write_lock: asyncio.Lock = Depends(_get_db_write_lock),
        broadcaster: RunBroadcaster = Depends(_get_broadcaster),
    ) -> IngestResponse:
        """Accept a single event JSON or an NDJSON batch."""
        max_bytes = _max_event_body_bytes()
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"event body exceeds {max_bytes} bytes",
                    )
            except ValueError:
                pass
        body = await request.body()
        if len(body) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"event body exceeds {max_bytes} bytes",
            )
        events, rejected = _parse_event_body(body)
        if not events and rejected == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="empty body",
            )
        accepted_events: list[AnyEvent] = []
        accepted = 0
        duplicates = 0
        async with write_lock:
            for event in events:
                try:
                    inserted = insert_event(conn, event)
                except Exception as exc:  # duckdb errors are not a single class
                    logger.warning("insert failed: %s", exc)
                    rejected += 1
                    continue
                if not inserted:
                    duplicates += 1
                    continue
                accepted += 1
                accepted_events.append(event)
        for event in accepted_events:
            await broadcaster.publish(event.run_id, event.model_dump_json())
        return IngestResponse(accepted=accepted, rejected=rejected, duplicates=duplicates)

    # ---------- read endpoints ----------------------------------------------

    @app.get("/runs", response_model=list[RunSummary])
    async def list_runs(conn: DuckConn = Depends(_get_conn)) -> list[RunSummary]:
        # Pull immutable run identity from run_start, mutable live status
        # from the newest run_update, and terminal status from run_end.
        conn.execute(
            """
            WITH per_run AS (
                SELECT
                    run_id,
                    COUNT(*) AS event_count,
                    MIN(timestamp_ns) FILTER (WHERE event_kind = 'run_start') AS started_at_ns,
                    MAX(timestamp_ns) FILTER (WHERE event_kind = 'run_end')   AS ended_at_ns,
                    ANY_VALUE(json_extract_string(payload, '$.name'))
                        FILTER (WHERE event_kind = 'run_start') AS name,
                    ANY_VALUE(json_extract_string(payload, '$.project'))
                        FILTER (WHERE event_kind = 'run_start') AS project,
                    LIST(DISTINCT event_kind) AS kinds_seen
                FROM events
                GROUP BY run_id
            ),
            latest_update AS (
                SELECT run_id, status
                FROM (
                    SELECT
                        run_id,
                        json_extract_string(payload, '$.status') AS status,
                        ROW_NUMBER() OVER (
                            PARTITION BY run_id
                            ORDER BY timestamp_ns DESC, event_id DESC
                        ) AS rn
                    FROM events
                    WHERE event_kind = 'run_update'
                )
                WHERE rn = 1
            ),
            latest_end AS (
                SELECT run_id, status
                FROM (
                    SELECT
                        run_id,
                        json_extract_string(payload, '$.status') AS status,
                        ROW_NUMBER() OVER (
                            PARTITION BY run_id
                            ORDER BY timestamp_ns DESC, event_id DESC
                        ) AS rn
                    FROM events
                    WHERE event_kind = 'run_end'
                )
                WHERE rn = 1
            )
            SELECT run_id, event_count, started_at_ns, ended_at_ns,
                   name, project,
                   COALESCE(
                       latest_end.status,
                       latest_update.status,
                       CASE WHEN ended_at_ns IS NULL THEN 'running' ELSE NULL END
                   ) AS status,
                   kinds_seen
              FROM per_run
              LEFT JOIN latest_update USING (run_id)
              LEFT JOIN latest_end USING (run_id)
             ORDER BY COALESCE(started_at_ns, 0) DESC;
            """
        )
        rows = conn.fetchall()
        out: list[RunSummary] = []
        if not rows:
            return out
        run_ids = [str(row[0]) for row in rows]
        kinds_by_run = {str(row[0]): sorted(row[7]) if row[7] else [] for row in rows}
        capabilities_by_run = _run_capabilities_many(conn, run_ids)
        system_kinds_by_run = _run_system_kinds_many(conn, kinds_by_run)

        for (
            run_id,
            event_count,
            started,
            ended,
            name,
            project,
            status_v,
            kinds_seen,
        ) in rows:
            run_id_str = str(run_id)
            kinds = sorted(kinds_seen) if kinds_seen else []
            out.append(
                RunSummary(
                    run_id=run_id_str,
                    name=name if isinstance(name, str) and name else None,
                    project=project if isinstance(project, str) and project else None,
                    started_at_ns=int(started) if started is not None else None,
                    ended_at_ns=int(ended) if ended is not None else None,
                    status=status_v if isinstance(status_v, str) and status_v else None,
                    event_count=int(event_count),
                    kinds_seen=kinds,
                    capabilities=capabilities_by_run.get(run_id_str, {}),
                    system_kind=system_kinds_by_run.get(run_id_str, "unknown"),
                )
            )
        return out

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str, conn: DuckConn = Depends(_get_conn)) -> dict[str, Any]:
        conn.execute(
            """
            SELECT COUNT(*) AS event_count,
                   MIN(timestamp_ns) AS first_timestamp_ns,
                   MAX(timestamp_ns) AS last_timestamp_ns,
                   LIST(DISTINCT event_kind) AS kinds_seen
              FROM events
             WHERE run_id = ?;
            """,
            [run_id],
        )
        row = conn.fetchone()
        if row is None or int(row[0]) == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

        event_count, first_ts, last_ts, kinds_seen = row
        capabilities = _run_capabilities(conn, run_id)
        # Surface the merged run-level score_directions so the UI can apply
        # canonical optimisation direction without re-fetching all events.
        score_directions: dict[str, str] = {}
        run_status: str | None = None
        conn.execute(
            """
            SELECT payload
              FROM events
             WHERE run_id = ? AND event_kind = 'run_start'
             ORDER BY timestamp_ns ASC, event_id ASC
             LIMIT 1;
            """,
            [run_id],
        )
        payload_row = conn.fetchone()
        if payload_row is not None:
            payload = _json_payload_to_dict(payload_row[0])
            raw = payload.get("score_directions")
            if isinstance(raw, dict):
                score_directions = {str(k): str(v) for k, v in raw.items()}

        conn.execute(
            """
            SELECT payload
              FROM events
             WHERE run_id = ? AND event_kind = 'run_update'
             ORDER BY timestamp_ns DESC, event_id DESC
             LIMIT 1;
            """,
            [run_id],
        )
        update_row = conn.fetchone()
        if update_row is not None:
            payload = _json_payload_to_dict(update_row[0])
            raw = payload.get("score_directions")
            if isinstance(raw, dict):
                score_directions.update({str(k): str(v) for k, v in raw.items()})
            status_raw = payload.get("status")
            if isinstance(status_raw, str) and status_raw:
                run_status = status_raw

        conn.execute(
            """
            SELECT payload
              FROM events
             WHERE run_id = ? AND event_kind = 'run_end'
             ORDER BY timestamp_ns DESC, event_id DESC
             LIMIT 1;
            """,
            [run_id],
        )
        end_row = conn.fetchone()
        if end_row is not None:
            payload = _json_payload_to_dict(end_row[0])
            status_raw = payload.get("status")
            if isinstance(status_raw, str) and status_raw:
                run_status = status_raw
        elif run_status is None:
            run_status = "running"

        return {
            "run_id": run_id,
            "event_count": int(event_count),
            "kinds_seen": sorted(kinds_seen) if kinds_seen else [],
            "first_timestamp_ns": int(first_ts),
            "last_timestamp_ns": int(last_ts),
            "status": run_status,
            "score_directions": score_directions,
            "capabilities": capabilities,
            "system_kind": _run_system_kind(conn, run_id, sorted(kinds_seen) if kinds_seen else []),
        }

    @app.get("/runs/{run_id}/events")
    async def get_run_events(
        run_id: str,
        conn: DuckConn = Depends(_get_conn),
        event_kind: str | None = None,
        since_timestamp_ns: int | None = None,
        limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        events = read_events(
            conn,
            run_id,
            event_kind=event_kind,
            since_timestamp_ns=since_timestamp_ns,
            limit=limit,
        )
        if not events and event_kind is None and since_timestamp_ns is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
        return [json.loads(e.model_dump_json()) for e in events]

    @app.get("/runs/{run_id}/stream_events", response_model=StreamEventsResponse)
    async def get_stream_events(
        run_id: str,
        conn: DuckConn = Depends(_get_conn),
        label: str | None = None,
        query: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=2_000),
    ) -> StreamEventsResponse:
        if not _run_exists(conn, run_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

        where_parts = ["run_id = ?", "event_kind = 'stream_event'"]
        params: list[object] = [run_id]
        if label:
            where_parts.append("json_extract_string(payload, '$.label') = ?")
            params.append(label)
        if query:
            like = f"%{query.lower()}%"
            where_parts.append(
                """
                (
                    LOWER(COALESCE(json_extract_string(payload, '$.label'), '')) LIKE ?
                 OR LOWER(COALESCE(json_extract_string(payload, '$.text'), '')) LIKE ?
                 OR LOWER(CAST(payload AS VARCHAR)) LIKE ?
                )
                """
            )
            params.extend([like, like, like])
        where_sql = " AND ".join(where_parts)

        conn.execute(f"SELECT COUNT(*) FROM events WHERE {where_sql};", params)  # noqa: S608
        row = conn.fetchone()
        total = int(row[0] or 0) if row is not None else 0

        conn.execute(
            f"""
            SELECT event_id, event_kind, run_id, timestamp_ns,
                   stream_id, worker_id, span_id, trace_id, payload
              FROM events
             WHERE {where_sql}
             ORDER BY timestamp_ns ASC, event_id ASC
             LIMIT ? OFFSET ?;
            """,  # noqa: S608
            [*params, limit, offset],
        )
        rows = conn.fetchall()
        return StreamEventsResponse(
            events=[_event_row_to_json(row) for row in rows],
            total=total,
            offset=offset,
            limit=limit,
        )

    @app.get("/runs/{run_id}/individuals")
    async def get_individuals(
        run_id: str,
        conn: DuckConn = Depends(_get_conn),
        since_timestamp_ns: int | None = None,
        limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        events = read_events(
            conn,
            run_id,
            event_kind="individual",
            since_timestamp_ns=since_timestamp_ns,
            limit=limit,
        )
        return [json.loads(e.model_dump_json()) for e in events]

    @app.get("/runs/{run_id}/operators")
    async def get_operators(
        run_id: str,
        conn: DuckConn = Depends(_get_conn),
        since_timestamp_ns: int | None = None,
        limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        events = read_events(
            conn,
            run_id,
            event_kind="operator",
            since_timestamp_ns=since_timestamp_ns,
            limit=limit,
        )
        return [json.loads(e.model_dump_json()) for e in events]

    @app.get("/runs/{run_id}/fitness")
    async def get_fitness(
        run_id: str,
        conn: DuckConn = Depends(_get_conn),
        since_timestamp_ns: int | None = None,
        limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        events = read_events(
            conn,
            run_id,
            event_kind="fitness",
            since_timestamp_ns=since_timestamp_ns,
            limit=limit,
        )
        return [json.loads(e.model_dump_json()) for e in events]

    @app.get("/runs/{run_id}/descriptors")
    async def get_descriptors(
        run_id: str,
        conn: DuckConn = Depends(_get_conn),
        since_timestamp_ns: int | None = None,
        limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        events = read_events(
            conn,
            run_id,
            event_kind="descriptor",
            since_timestamp_ns=since_timestamp_ns,
            limit=limit,
        )
        return [json.loads(e.model_dump_json()) for e in events]

    @app.get("/runs/{run_id}/pareto_snapshots")
    async def get_pareto_snapshots(
        run_id: str,
        conn: DuckConn = Depends(_get_conn),
        since_timestamp_ns: int | None = None,
        limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        events = read_events(
            conn,
            run_id,
            event_kind="pareto_snapshot",
            since_timestamp_ns=since_timestamp_ns,
            limit=limit,
        )
        return [json.loads(e.model_dump_json()) for e in events]

    @app.get("/runs/{run_id}/self_mods")
    async def get_self_mods(
        run_id: str,
        conn: DuckConn = Depends(_get_conn),
        since_timestamp_ns: int | None = None,
        limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        events = read_events(
            conn,
            run_id,
            event_kind="self_mod",
            since_timestamp_ns=since_timestamp_ns,
            limit=limit,
        )
        return [json.loads(e.model_dump_json()) for e in events]

    @app.get("/runs/{run_id}/tree_expansions")
    async def get_tree_expansions(
        run_id: str,
        conn: DuckConn = Depends(_get_conn),
        since_timestamp_ns: int | None = None,
        limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        events = read_events(
            conn,
            run_id,
            event_kind="tree_expansion",
            since_timestamp_ns=since_timestamp_ns,
            limit=limit,
        )
        return [json.loads(e.model_dump_json()) for e in events]

    @app.get("/runs/{run_id}/claims")
    async def get_claims(
        run_id: str,
        conn: DuckConn = Depends(_get_conn),
        since_timestamp_ns: int | None = None,
        limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        events = read_events(
            conn,
            run_id,
            event_kind="claim",
            since_timestamp_ns=since_timestamp_ns,
            limit=limit,
        )
        return [json.loads(e.model_dump_json()) for e in events]

    @app.get("/runs/{run_id}/evidence")
    async def get_evidence(
        run_id: str,
        conn: DuckConn = Depends(_get_conn),
        since_timestamp_ns: int | None = None,
        limit: int = Query(default=DEFAULT_READ_LIMIT, ge=1, le=50_000),
    ) -> list[dict[str, Any]]:
        events = read_events(
            conn,
            run_id,
            event_kind="evidence",
            since_timestamp_ns=since_timestamp_ns,
            limit=limit,
        )
        return [json.loads(e.model_dump_json()) for e in events]

    # ---------- live updates -------------------------------------------------

    @app.websocket("/runs/{run_id}/stream")
    async def stream_run(websocket: WebSocket, run_id: str) -> None:
        """Push every new event for *run_id* to the client as JSON text."""
        token = _auth_token_from_state(websocket.app)
        if token is not None:
            auth_header = websocket.headers.get("authorization")
            query_token = websocket.query_params.get("token")
            header_ok = _is_authorized_header(auth_header, token)
            query_ok = query_token is not None and secrets.compare_digest(query_token, token)
            if not header_ok and not query_ok:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
        broadcaster = cast(RunBroadcaster, websocket.app.state.broadcaster)
        await websocket.accept()
        await broadcaster.subscribe(run_id, websocket)
        try:
            while True:
                # We don't expect client messages; this awaits a disconnect.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await broadcaster.unsubscribe(run_id, websocket)

    # ---------- steering ----------------------------------------------------

    async def _persist_steering_event(
        record_dict: dict[str, Any],
        conn: DuckConn,
        write_lock: asyncio.Lock,
        broadcaster: RunBroadcaster,
    ) -> None:
        """Persist a steering record as a canonical ``steering_command`` event.

        We mirror the in-memory queue into the DuckDB event log so the trail
        survives a daemon restart and shows up in audit views.
        """
        run_id = record_dict["run_id"]
        payload = SteeringCommandPayload(
            command=record_dict["command"],
            target_id=record_dict.get("target_id"),
            params=dict(record_dict.get("params") or {}),
            actor=record_dict["actor"],
            metadata={
                "command_id": record_dict["command_id"],
                "status": record_dict["status"],
                "outcome": record_dict.get("outcome"),
                "outcome_note": record_dict.get("outcome_note"),
            },
        )
        event = SteeringCommandEvent(
            run_id=run_id,
            timestamp_ns=(
                record_dict.get("acked_at_ns")
                or record_dict.get("delivered_at_ns")
                or record_dict["created_at_ns"]
            ),
            payload=payload,
        )
        async with write_lock:
            try:
                inserted = insert_event(conn, event)
            except Exception as exc:
                logger.warning("steering event insert failed: %s", exc)
                return
        if not inserted:
            return
        await broadcaster.publish(run_id, event.model_dump_json())

    def _persisted_steering_history(conn: DuckConn, run_id: str) -> list[dict[str, Any]]:
        events = read_events(conn, run_id, event_kind="steering_command", limit=50_000)
        by_command: dict[str, dict[str, Any]] = {}
        for event in events:
            if not isinstance(event, SteeringCommandEvent):
                continue
            payload = event.payload
            metadata = dict(getattr(payload, "metadata", {}) or {})
            command_id = metadata.get("command_id")
            if not isinstance(command_id, str) or not command_id:
                command_id = str(event.event_id)
            record = by_command.setdefault(
                command_id,
                {
                    "command_id": command_id,
                    "run_id": run_id,
                    "command": payload.command,
                    "target_id": payload.target_id,
                    "params": dict(payload.params),
                    "actor": payload.actor,
                    "created_at_ns": event.timestamp_ns,
                    "status": "pending",
                    "delivered_at_ns": None,
                    "acked_at_ns": None,
                    "outcome": None,
                    "outcome_note": None,
                },
            )
            record["command"] = payload.command
            record["target_id"] = payload.target_id
            record["params"] = dict(payload.params)
            record["actor"] = payload.actor
            status_raw = metadata.get("status")
            if isinstance(status_raw, str) and status_raw:
                record["status"] = status_raw
                if status_raw == "delivered":
                    record["delivered_at_ns"] = event.timestamp_ns
                if status_raw == "acked":
                    record["acked_at_ns"] = event.timestamp_ns
            outcome = metadata.get("outcome")
            if isinstance(outcome, str) and outcome:
                record["outcome"] = outcome
            outcome_note = metadata.get("outcome_note")
            if isinstance(outcome_note, str) and outcome_note:
                record["outcome_note"] = outcome_note
        return sorted(by_command.values(), key=lambda item: int(item["created_at_ns"]))

    @app.post("/steering/{run_id}")
    async def issue_steering_command(
        run_id: str,
        body: SteeringIssueRequest,
        store: SteeringStore = Depends(_get_steering),
        conn: DuckConn = Depends(_get_conn),
        write_lock: asyncio.Lock = Depends(_get_db_write_lock),
        broadcaster: RunBroadcaster = Depends(_get_broadcaster),
    ) -> dict[str, Any]:
        if not _run_exists(conn, run_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
        run_status = _run_status(conn, run_id)
        if run_status in {"finished", "failed", "cancelled"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"run is terminal ({run_status}); steering is read-only",
            )
        capabilities = _run_explicit_capabilities(conn, run_id)
        if capabilities.get("steering") is not True:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="run does not advertise steering capability",
            )
        record = await store.issue(
            run_id=run_id,
            command=body.command,
            target_id=body.target_id,
            params=body.params,
            actor=body.actor,
        )
        await _persist_steering_event(record.to_dict(), conn, write_lock, broadcaster)
        return record.to_dict()

    @app.get("/steering/{run_id}/poll")
    async def poll_steering_commands(
        run_id: str,
        store: SteeringStore = Depends(_get_steering),
    ) -> list[dict[str, Any]]:
        delivered = await store.poll(run_id)
        return [r.to_dict() for r in delivered]

    @app.get("/steering/{run_id}")
    async def list_steering_commands(
        run_id: str,
        store: SteeringStore = Depends(_get_steering),
        conn: DuckConn = Depends(_get_conn),
    ) -> list[dict[str, Any]]:
        persisted_history = _persisted_steering_history(conn, run_id)
        records_by_id = {str(record["command_id"]): record for record in persisted_history}
        history = await store.list_history(run_id)
        for record in history:
            payload = record.to_dict()
            records_by_id[str(payload["command_id"])] = payload
        return sorted(records_by_id.values(), key=lambda item: int(item["created_at_ns"]))

    @app.post("/steering/{run_id}/{command_id}/ack")
    async def ack_steering_command(
        run_id: str,
        command_id: str,
        body: SteeringAckRequest,
        store: SteeringStore = Depends(_get_steering),
        conn: DuckConn = Depends(_get_conn),
        write_lock: asyncio.Lock = Depends(_get_db_write_lock),
        broadcaster: RunBroadcaster = Depends(_get_broadcaster),
    ) -> dict[str, Any]:
        record = await store.ack(
            run_id=run_id,
            command_id=command_id,
            outcome=body.outcome,
            note=body.note,
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="steering command not found",
            )
        await _persist_steering_event(record.to_dict(), conn, write_lock, broadcaster)
        return record.to_dict()

    # ---------- static UI bundle (registered last so API routes win) --------
    # When the Next.js bundle exists at ``hutch/ui_server/static`` we serve
    # it from ``/``. The bundle is produced by
    # ``pnpm --filter hutch-ui build:daemon``.

    if bundle_dir is not None:

        @app.get("/run", response_class=HTMLResponse, include_in_schema=False)
        async def run_page() -> FileResponse:
            return FileResponse(bundle_dir / "run" / "index.html")

        app.mount("/", StaticFiles(directory=bundle_dir, html=True), name="ui")

    return app


def _parse_event_body(body: bytes) -> tuple[list[AnyEvent], int]:
    """Parse a request body as either a single event JSON or an NDJSON batch.

    Returns ``(events, rejected_count)``. Lines / records that fail validation
    are counted as rejected, not raised — so a single bad row in a batch
    doesn't poison the whole insert.
    """
    if not body.strip():
        return [], 0
    text = body.decode("utf-8")
    events: list[AnyEvent] = []
    rejected = 0
    # Try a single JSON value first (object or array).
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        records: list[Any]
        records = parsed if isinstance(parsed, list) else [parsed]
        for record in records:
            try:
                events.append(EVENT_ADAPTER.validate_python(record))
            except ValidationError:
                rejected += 1
        return events, rejected
    # Fall back to NDJSON.
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            events.append(EVENT_ADAPTER.validate_python(record))
        except (json.JSONDecodeError, ValidationError):
            rejected += 1
    return events, rejected


# Module-level singleton for ``uvicorn hutch.daemon.app:app``. ``db_path=None``
# triggers the lazy ``HUTCH_DB_PATH`` lookup inside the lifespan so the CLI's
# ``--db`` flag still works.
app = create_app()
