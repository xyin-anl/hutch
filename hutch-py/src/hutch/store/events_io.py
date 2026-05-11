"""Read / write canonical events against the DuckDB ``events`` table.

This is the bridge layer between :mod:`hutch.schema` and DuckDB. The
SDK's transports, the daemon's ingest / read endpoints, and the
exporters all go through these helpers — the ``events`` table is the
single source of truth.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from hutch.schema import EVENT_ADAPTER, AnyEvent
from hutch.store.database import DuckConn

INSERT_EVENT_SQL = """
INSERT INTO events (
    event_id, event_kind, run_id, timestamp_ns,
    stream_id, worker_id, span_id, trace_id, payload
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

SELECT_EVENTS_BASE_SQL = """
SELECT event_id, event_kind, run_id, timestamp_ns,
       stream_id, worker_id, span_id, trace_id, payload
  FROM events
 WHERE run_id = ?
"""

ORDER_EVENTS_SQL = " ORDER BY timestamp_ns ASC, event_id ASC"


def insert_event(conn: DuckConn, event: AnyEvent) -> bool:
    """Persist a single event to the raw events log.

    Returns ``True`` when the event was inserted and ``False`` when an event
    with the same ``event_id`` was already present. Hutch ingestion is
    intentionally idempotent because daemon delivery is at-least-once.
    """
    payload_json = event.payload.model_dump_json()
    try:
        conn.execute(
            INSERT_EVENT_SQL,
            [
                str(event.event_id),
                event.event_kind,
                event.run_id,
                event.timestamp_ns,
                event.stream_id,
                event.worker_id,
                event.span_id,
                event.trace_id,
                payload_json,
            ],
        )
    except Exception as exc:
        if _is_duplicate_event_error(exc):
            return False
        raise
    return True


def _is_duplicate_event_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "constraint" in message
        and "duplicate" in message
        and ("event_id" in message or "primary key" in message)
    )


def insert_events(conn: DuckConn, events: Iterable[AnyEvent]) -> int:
    """Persist a batch of events. Returns the count actually inserted."""
    count = 0
    for event in events:
        if insert_event(conn, event):
            count += 1
    return count


def read_events(
    conn: DuckConn,
    run_id: str,
    *,
    event_kind: str | None = None,
    since_timestamp_ns: int | None = None,
    limit: int | None = None,
) -> list[AnyEvent]:
    """Read events for a run, in (timestamp, event_id) order."""
    sql = SELECT_EVENTS_BASE_SQL
    params: list[object] = [run_id]
    if event_kind is not None:
        sql += " AND event_kind = ?"
        params.append(event_kind)
    if since_timestamp_ns is not None:
        sql += " AND timestamp_ns > ?"
        params.append(since_timestamp_ns)
    sql += ORDER_EVENTS_SQL
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    sql += ";"
    conn.execute(sql, params)
    rows = conn.fetchall()
    out: list[AnyEvent] = []
    for row in rows:
        (
            event_id,
            event_kind,
            run_id_,
            timestamp_ns,
            stream_id,
            worker_id,
            span_id,
            trace_id,
            payload,
        ) = row
        # DuckDB returns JSON columns as strings; payload may already be parsed
        # depending on driver build, so accept either.
        if isinstance(payload, str):
            payload_obj = json.loads(payload)
        else:
            payload_obj = payload
        record = {
            "event_id": str(event_id),
            "event_kind": event_kind,
            "run_id": run_id_,
            "timestamp_ns": int(timestamp_ns),
            "stream_id": stream_id,
            "worker_id": worker_id,
            "span_id": span_id,
            "trace_id": trace_id,
            "payload": payload_obj,
        }
        out.append(EVENT_ADAPTER.validate_python(record))
    return out
