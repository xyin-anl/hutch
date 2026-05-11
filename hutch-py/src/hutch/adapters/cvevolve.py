"""CVEvolve session adapter.

CVEvolve stores its search history in ``history/search_history.sqlite`` under
each session root. This adapter reads that SQLite database directly and emits
Hutch's canonical evolutionary-search events:

* candidates become program Individuals;
* candidate actions become Operators (propose/refine/mutate/crossover);
* ranking metrics and holdout-test metrics become Fitness events;
* candidate failures become StreamEvent audit rows.

High-volume message/tool-call logs are ignored by default. Pass
``include_audit=True`` to import them as opt-in StreamEvent rows for audit
inspection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import urllib.parse
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hutch.schema import (
    AnyEvent,
    FitnessEvent,
    FitnessPayload,
    IndividualEvent,
    IndividualPayload,
    OperatorEvent,
    OperatorPayload,
    RunEndEvent,
    RunEndPayload,
    RunStartEvent,
    RunStartPayload,
    RunUpdateEvent,
    RunUpdatePayload,
    StreamEventEvent,
    StreamEventPayload,
)
from hutch.schema.types import OperatorKind, RunStatus, ScoreDirection

logger = logging.getLogger("hutch.adapters.cvevolve")

_DB_RELATIVE = Path("history") / "search_history.sqlite"
_MESSAGES_DB_RELATIVE = Path("history") / "messages.sqlite"
_TOOL_CALLS_DB_RELATIVE = Path("history") / "tool_calls.sqlite"
_REQUIRED_TABLES = frozenset(
    {
        "metric_definitions",
        "rounds",
        "candidates",
        "metrics",
        "evaluation_metrics",
        "session_state",
    }
)
_OPTIONAL_TABLES = frozenset({"holdout_test_metrics", "candidate_failures"})


@dataclass(frozen=True, slots=True)
class _Source:
    input_path: Path
    session_root: Path
    db_path: Path
    workspace_root: Path
    messages_db_path: Path
    tool_calls_db_path: Path


def detect(path: Path) -> bool:
    """Return ``True`` when *path* looks like a CVEvolve session or DB."""
    source = _resolve_source(path)
    if source is None or not source.db_path.is_file():
        return False
    try:
        with _connect_readonly(source.db_path) as conn:
            tables = _table_names(conn)
    except sqlite3.Error:
        return False
    return _REQUIRED_TABLES.issubset(tables)


def is_complete(path: Path) -> bool | None:
    """Return CVEvolve's explicit completion state when the DB is readable."""
    source = _resolve_source(path)
    if source is None or not source.db_path.is_file():
        return None
    try:
        with _connect_readonly(source.db_path) as conn:
            tables = _table_names(conn)
            if not _REQUIRED_TABLES.issubset(tables):
                return None
            state = _session_state(conn)
    except sqlite3.Error:
        return False
    if state is None:
        return False
    return state.get("phase") == "completed"


def import_cvevolve(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
    finalize: bool = True,
    include_audit: bool = False,
    audit_max_text_chars: int = 8000,
) -> Iterator[AnyEvent]:
    """Yield canonical events for a CVEvolve session root or history DB."""
    if audit_max_text_chars < 0:
        raise ValueError("audit_max_text_chars must be zero or greater")
    source = _resolve_source(Path(path))
    if source is None or not source.db_path.is_file():
        raise ValueError(f"{path} is not a CVEvolve session root or search_history.sqlite file")

    try:
        conn = _connect_readonly(source.db_path)
    except sqlite3.Error as exc:
        msg = f"Could not open CVEvolve history database {source.db_path}: {exc}"
        raise ValueError(msg) from exc

    with conn:
        tables = _table_names(conn)
        if not _REQUIRED_TABLES.issubset(tables):
            missing = ", ".join(sorted(_REQUIRED_TABLES - tables))
            raise ValueError(f"{source.db_path} is missing CVEvolve tables: {missing}")

        metric_directions = _metric_directions(conn)
        candidates = _candidate_rows(conn)
        metrics_by_candidate = _metrics_by_candidate(conn)
        holdout_rows = _holdout_rows(conn) if "holdout_test_metrics" in tables else []
        failure_rows = _failure_rows(conn) if "candidate_failures" in tables else []
        audit_message_rows = _message_audit_rows(source) if include_audit else []
        audit_tool_call_rows = _tool_call_audit_rows(source) if include_audit else []
        state = _session_state(conn)

        started_at = _earliest_timestamp(
            candidates,
            [m for rows in metrics_by_candidate.values() for m in rows],
            holdout_rows,
            failure_rows,
            audit_message_rows,
            audit_tool_call_rows,
            [state] if state else [],
        )
        resolved_run_id = run_id or _derive_run_id(source.session_root)
        started_by = "cvevolve-importer"
        session_name = source.session_root.name or "cvevolve-session"

        yield RunStartEvent(
            run_id=resolved_run_id,
            timestamp_ns=started_at,
            payload=RunStartPayload(
                name=session_name,
                project=project or "cvevolve",
                started_by=started_by,
                config=_run_config(
                    source,
                    conn,
                    candidates,
                    holdout_rows,
                    failure_rows,
                    include_audit=include_audit,
                    audit_message_count=len(audit_message_rows),
                    audit_tool_call_count=len(audit_tool_call_rows),
                    audit_max_text_chars=audit_max_text_chars,
                ),
                capabilities={"audit": True} if include_audit else {},
                score_directions=metric_directions,
            ),
        )

        emitted_timestamps = [started_at]
        total_operators = 0
        total_fitness = 0
        source_counts = {
            "candidates": len(candidates),
            "metrics": sum(len(rows) for rows in metrics_by_candidate.values()),
            "holdout_test_metrics": len(holdout_rows),
            "candidate_failures": len(failure_rows),
            "audit_messages": len(audit_message_rows),
            "audit_tool_calls": len(audit_tool_call_rows),
        }

        for index, candidate in enumerate(candidates, start=1):
            candidate_id = str(candidate["candidate_id"])
            parents = _loads_str_list(candidate["parent_ids_json"])
            ts = _timestamp_for(candidate, started_at, index)
            emitted_timestamps.append(ts)
            metadata = _candidate_metadata(candidate, source)

            yield IndividualEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                worker_id=_worker_id_for(candidate),
                payload=IndividualPayload(
                    id=candidate_id,
                    kind="program",
                    parent_ids=parents,
                    is_seed=len(parents) == 0,
                    genome_uri=_candidate_code_uri(candidate, source.workspace_root),
                    genome_lang=_candidate_genome_lang(candidate),
                    generation_index=_int_or_none(candidate["round_index"]),
                    metadata=metadata,
                ),
            )

            op_kind = _operator_kind_for(
                action=str(candidate["action"]),
                parent_ids=parents,
                metadata=metadata,
            )
            if op_kind is not None:
                yield OperatorEvent(
                    run_id=resolved_run_id,
                    timestamp_ns=ts,
                    worker_id=_worker_id_for(candidate),
                    payload=OperatorPayload(
                        id=f"op-{candidate_id}",
                        kind=op_kind,
                        parent_ids=parents,
                        child_id=candidate_id,
                        metadata=_operator_metadata(candidate, metadata),
                    ),
                )
                total_operators += 1

            for metric_index, metric in enumerate(
                metrics_by_candidate.get(candidate_id, []),
                start=1,
            ):
                metric_ts = _timestamp_for(metric, ts, metric_index)
                emitted_timestamps.append(metric_ts)
                event = _fitness_event_for_metric(
                    resolved_run_id,
                    metric,
                    metric_directions,
                    timestamp_ns=metric_ts,
                )
                if event is not None:
                    yield event
                    total_fitness += 1

        post_candidate_base = max(emitted_timestamps) if emitted_timestamps else started_at

        for index, holdout in enumerate(holdout_rows, start=1):
            ts = _timestamp_for(holdout, post_candidate_base, index)
            emitted_timestamps.append(ts)
            event = _fitness_event_for_holdout(
                resolved_run_id,
                holdout,
                metric_directions,
                timestamp_ns=ts,
            )
            if event is not None:
                yield event
                total_fitness += 1

        failure_base = max(emitted_timestamps) if emitted_timestamps else post_candidate_base
        for index, failure in enumerate(failure_rows, start=1):
            ts = _timestamp_for(failure, failure_base, index)
            emitted_timestamps.append(ts)
            yield StreamEventEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=StreamEventPayload(
                    label="candidate_failure",
                    text=_str_or_none(failure["error_message"]),
                    metadata={
                        "round_index": failure["round_index"],
                        "action": failure["action"],
                        "candidate_name": failure["candidate_name"],
                        "code_file_path": failure["code_file_path"],
                        "parent_ids": _loads_str_list(failure["parent_ids_json"]),
                        "notes": failure["notes"],
                        "settings": _loads_dict(failure["settings_json"]),
                        "source_metadata": _loads_dict(failure["metadata_json"]),
                        "source_table": "candidate_failures",
                        "source_id": failure["id"],
                    },
                ),
            )

        audit_base = max(emitted_timestamps) if emitted_timestamps else failure_base
        audit_events = _audit_stream_events(
            run_id=resolved_run_id,
            message_rows=audit_message_rows,
            tool_call_rows=audit_tool_call_rows,
            timestamp_base=audit_base,
            max_text_chars=audit_max_text_chars,
        )
        for audit_event in audit_events:
            emitted_timestamps.append(audit_event.timestamp_ns)
            yield audit_event

        if finalize:
            last_ts = max(emitted_timestamps) if emitted_timestamps else started_at
            final_status = _run_status_for(state)
            timestamp_ns = max(last_ts + 1, started_at + 1)
            if final_status == "finished":
                yield RunEndEvent(
                    run_id=resolved_run_id,
                    timestamp_ns=timestamp_ns,
                    payload=RunEndPayload(
                        status=final_status,
                        summary=(
                            f"imported {len(candidates)} CVEvolve candidates, "
                            f"{total_operators} operators, and {total_fitness} fitness events "
                            f"from {session_name}"
                        ),
                        metadata={
                            "stop_reason": state.get("stop_reason") if state else "",
                            "phase": state.get("phase") if state else None,
                            "status": state.get("status") if state else None,
                        },
                    ),
                )
            else:
                yield RunUpdateEvent(
                    run_id=resolved_run_id,
                    timestamp_ns=timestamp_ns,
                    payload=RunUpdatePayload(
                        status=final_status,
                        config={
                            "source_path": str(source.input_path.resolve()),
                            "session_root": str(source.session_root.resolve()),
                            "db_path": str(source.db_path.resolve()),
                        },
                        capabilities={"audit": True} if include_audit else {},
                        score_directions=metric_directions,
                        source_counts=source_counts,
                        watcher={
                            "adapter": "cvevolve",
                            "completion_policy": "explicit",
                        },
                        metadata={
                            "source_key": _active_run_update_source_key(state, source_counts),
                            "phase": state.get("phase") if state else None,
                            "status": state.get("status") if state else None,
                            "current_round_index": state.get("current_round_index")
                            if state
                            else None,
                            "current_action": state.get("current_action") if state else None,
                            "current_reason": state.get("current_reason") if state else None,
                        },
                    ),
                )


# ---------- SQLite helpers -------------------------------------------------


def _resolve_source(path: Path) -> _Source | None:
    input_path = path
    if path.is_dir():
        session_root = path
        db_path = path / _DB_RELATIVE
    elif path.is_file():
        db_path = path
        session_root = path.parent.parent if path.parent.name == "history" else path.parent
    else:
        return None
    return _Source(
        input_path=input_path,
        session_root=session_root,
        db_path=db_path,
        workspace_root=session_root / "workspace",
        messages_db_path=session_root / _MESSAGES_DB_RELATIVE,
        tool_calls_db_path=session_root / _TOOL_CALLS_DB_RELATIVE,
    )


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = "file:" + urllib.parse.quote(str(db_path.resolve()), safe="/:") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=1.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type IN ('table', 'view')
        """
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _count_table(conn: sqlite3.Connection, table_name: str) -> int:
    if table_name not in _REQUIRED_TABLES and table_name not in _OPTIONAL_TABLES:
        return 0
    try:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()  # noqa: S608
    except sqlite3.Error:
        return 0
    return int(row["count"]) if row is not None else 0


def _metric_directions(conn: sqlite3.Connection) -> dict[str, ScoreDirection]:
    rows = conn.execute(
        """
        SELECT name, direction
        FROM metric_definitions
        ORDER BY is_primary DESC, created_at ASC, name ASC
        """
    ).fetchall()
    out: dict[str, ScoreDirection] = {}
    for row in rows:
        name = str(row["name"])
        direction = str(row["direction"])
        out[name] = "lower" if direction == "minimize" else "higher"
    return out


def _candidate_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT
            candidate_id,
            round_index,
            action,
            candidate_name,
            description,
            code_path,
            code_file_path,
            lineage_id,
            lineage_parent_ids_json,
            parent_ids_json,
            notes,
            metadata_json,
            created_at
        FROM candidates
        ORDER BY round_index ASC, created_at ASC, candidate_id ASC
        """
    ).fetchall()
    return list(rows)


def _metrics_by_candidate(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    rows = conn.execute(
        """
        SELECT
            id,
            candidate_id,
            round_index,
            metric_name,
            value,
            is_primary,
            notes,
            settings_json,
            created_at
        FROM metrics
        WHERE candidate_id IS NOT NULL AND candidate_id != ''
        ORDER BY candidate_id ASC, id ASC
        """
    ).fetchall()
    out: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        out.setdefault(str(row["candidate_id"]), []).append(row)
    return out


def _holdout_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT
            id,
            candidate_id,
            round_index,
            metric_name,
            value,
            notes,
            settings_json,
            created_at
        FROM holdout_test_metrics
        WHERE candidate_id IS NOT NULL AND candidate_id != ''
        ORDER BY id ASC
        """
    ).fetchall()
    return list(rows)


def _failure_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT
            id,
            round_index,
            action,
            candidate_name,
            code_file_path,
            parent_ids_json,
            error_message,
            notes,
            settings_json,
            metadata_json,
            created_at
        FROM candidate_failures
        ORDER BY id ASC
        """
    ).fetchall()
    return list(rows)


def _message_audit_rows(source: _Source) -> list[sqlite3.Row]:
    if not source.messages_db_path.is_file():
        return []
    return _audit_table_rows(
        source.messages_db_path,
        table_name="message_events",
        columns={
            "id": "rowid AS id",
            "created_at": "NULL AS created_at",
            "round_index": "NULL AS round_index",
            "worker_index": "0 AS worker_index",
            "message_type": "'message' AS message_type",
            "content": "'' AS content",
            "metadata_json": "'{}' AS metadata_json",
        },
    )


def _tool_call_audit_rows(source: _Source) -> list[sqlite3.Row]:
    if not source.tool_calls_db_path.is_file():
        return []
    return _audit_table_rows(
        source.tool_calls_db_path,
        table_name="tool_calls",
        columns={
            "id": "rowid AS id",
            "created_at": "NULL AS created_at",
            "tool_name": "'tool' AS tool_name",
            "arguments_json": "'{}' AS arguments_json",
        },
    )


def _audit_table_rows(
    db_path: Path,
    *,
    table_name: str,
    columns: Mapping[str, str],
) -> list[sqlite3.Row]:
    try:
        with _connect_readonly(db_path) as conn:
            if table_name not in _table_names(conn):
                return []
            available = _column_names(conn, table_name)
            select_exprs = [
                column if column in available else fallback for column, fallback in columns.items()
            ]
            order_by = "id" if "id" in available else "rowid"
            rows = conn.execute(
                f"SELECT {', '.join(select_exprs)} FROM {table_name} ORDER BY {order_by} ASC"  # noqa: S608
            ).fetchall()
    except sqlite3.Error as exc:
        if _is_locked_error(exc):
            raise
        logger.warning("skipping unreadable CVEvolve audit database %s: %s", db_path, exc)
        return []
    return list(rows)


def _session_state(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            phase,
            status,
            current_round_index,
            current_action,
            current_reason,
            preparation_summary,
            stop_reason,
            updated_at
        FROM session_state
        WHERE singleton_id = 1
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row is not None else None


# ---------- event-building helpers ----------------------------------------


def _derive_run_id(session_root: Path) -> str:
    name = session_root.name or f"session-{uuid.uuid4().hex[:12]}"
    return f"cvevolve-{name}"


def _run_config(
    source: _Source,
    conn: sqlite3.Connection,
    candidates: Sequence[sqlite3.Row],
    holdout_rows: Sequence[sqlite3.Row],
    failure_rows: Sequence[sqlite3.Row],
    *,
    include_audit: bool,
    audit_message_count: int,
    audit_tool_call_count: int,
    audit_max_text_chars: int,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "source_path": str(source.input_path.resolve()),
        "session_root": str(source.session_root.resolve()),
        "db_path": str(source.db_path.resolve()),
        "workspace_root": str(source.workspace_root.resolve()),
        "candidate_count": len(candidates),
        "metric_count": _count_table(conn, "metrics"),
        "evaluation_metric_count": _count_table(conn, "evaluation_metrics"),
        "holdout_test_metric_count": len(holdout_rows),
        "candidate_failure_count": len(failure_rows),
        "audit_available": {
            "messages_sqlite": source.messages_db_path.is_file(),
            "tool_calls_sqlite": source.tool_calls_db_path.is_file(),
        },
        "audit_included": include_audit,
    }
    if include_audit:
        config["audit_message_count"] = audit_message_count
        config["audit_tool_call_count"] = audit_tool_call_count
        config["audit_max_text_chars"] = audit_max_text_chars
    snapshot = source.session_root / "config.snapshot.yaml"
    if snapshot.is_file():
        config["config_snapshot_path"] = str(snapshot.resolve())
        config["config_snapshot_summary"] = _config_snapshot_summary(snapshot)
    mlflow_run = source.session_root / "mlflow_run.json"
    if mlflow_run.is_file():
        payload = _load_json_file(mlflow_run)
        if payload:
            config["mlflow_run"] = payload
    return config


def _config_snapshot_summary(path: Path) -> dict[str, Any]:
    """Tiny dependency-free YAML summary for common scalar CVEvolve fields."""
    summary: dict[str, Any] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return summary
    current_section: str | None = None
    wanted_sections = {"model", "workspace", "metric", "tracking"}
    wanted_keys = {
        "name",
        "model_name",
        "temperature",
        "root_dir",
        "data_dir",
        "name_hint",
        "direction_hint",
        "target_value",
        "enabled",
        "mlflow_experiment_name",
    }
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and ":" in line:
            key, _, value = line.partition(":")
            current_section = key.strip()
            if current_section == "name" and value.strip():
                summary["name"] = value.strip()
            continue
        if current_section not in wanted_sections or ":" not in line:
            continue
        key, _, value = line.strip().partition(":")
        if key not in wanted_keys:
            continue
        section = summary.setdefault(current_section, {})
        if isinstance(section, dict):
            section[key] = value.strip() or None
    return summary


def _candidate_metadata(candidate: Any, source: _Source) -> dict[str, Any]:
    raw_metadata = _loads_dict(candidate["metadata_json"])
    settings = raw_metadata.get("settings")
    analysis = raw_metadata.get("analysis")
    lineage_parent_ids = _loads_str_list(candidate["lineage_parent_ids_json"])
    return {
        "candidate_name": candidate["candidate_name"],
        "description": candidate["description"],
        "action": candidate["action"],
        "round_index": candidate["round_index"],
        "lineage_id": candidate["lineage_id"],
        "lineage_parent_ids": lineage_parent_ids,
        "code_path": candidate["code_path"],
        "code_file_path": candidate["code_file_path"],
        "absolute_code_file_path": _candidate_code_abs_path(candidate, source.workspace_root),
        "notes": candidate["notes"],
        "settings": settings if isinstance(settings, dict) else {},
        "analysis": analysis if isinstance(analysis, dict) else {},
        "cvevolve_metadata": raw_metadata,
    }


def _operator_metadata(candidate: Any, metadata: Mapping[str, Any]) -> dict[str, Any]:
    analysis = metadata.get("analysis")
    analysis_summary = None
    if isinstance(analysis, dict):
        raw_summary = analysis.get("summary")
        analysis_summary = raw_summary if isinstance(raw_summary, str) else None
    return {
        "cvevolve_action": candidate["action"],
        "evolve_strategy": metadata.get("cvevolve_metadata", {}).get("evolve_strategy")
        if isinstance(metadata.get("cvevolve_metadata"), dict)
        else None,
        "round_index": candidate["round_index"],
        "candidate_name": candidate["candidate_name"],
        "lineage_id": candidate["lineage_id"],
        "lineage_parent_ids": metadata.get("lineage_parent_ids", []),
        "analysis_summary": analysis_summary,
    }


def _operator_kind_for(
    *,
    action: str,
    parent_ids: Sequence[str],
    metadata: Mapping[str, Any],
) -> OperatorKind | None:
    normalized = action.strip().lower()
    if normalized == "baseline":
        return None
    if normalized == "generate" and not parent_ids:
        return "propose"
    if normalized == "tune":
        return "refine"
    if normalized == "evolve":
        raw_metadata = metadata.get("cvevolve_metadata")
        strategy = ""
        if isinstance(raw_metadata, dict):
            raw_strategy = raw_metadata.get("evolve_strategy")
            strategy = raw_strategy if isinstance(raw_strategy, str) else ""
        if strategy == "crossover" or len(parent_ids) >= 2:
            return "crossover"
        if len(parent_ids) == 1:
            return "mutate"
        return "refine"
    return "refine"


def _fitness_event_for_metric(
    run_id: str,
    metric: Any,
    metric_directions: Mapping[str, ScoreDirection],
    *,
    timestamp_ns: int,
) -> FitnessEvent | None:
    candidate_id = _str_or_none(metric["candidate_id"])
    metric_name = _str_or_none(metric["metric_name"])
    if candidate_id is None or metric_name is None:
        return None
    value = _float_or_none(metric["value"])
    if value is None:
        return None
    is_primary = int(metric["is_primary"] or 0) == 1
    return FitnessEvent(
        run_id=run_id,
        timestamp_ns=timestamp_ns,
        payload=FitnessPayload(
            individual_id=candidate_id,
            evaluator_id="cvevolve-primary" if is_primary else "cvevolve-metric",
            evaluator_kind="deterministic_metric",
            scores={metric_name: value},
            composite=_composite_for(metric_name, value, metric_directions),
            metadata={
                "round_index": metric["round_index"],
                "is_primary": is_primary,
                "notes": metric["notes"],
                "settings": _loads_dict(metric["settings_json"]),
                "source_table": "metrics",
                "source_id": metric["id"],
            },
        ),
    )


def _fitness_event_for_holdout(
    run_id: str,
    metric: Any,
    metric_directions: Mapping[str, ScoreDirection],
    *,
    timestamp_ns: int,
) -> FitnessEvent | None:
    candidate_id = _str_or_none(metric["candidate_id"])
    metric_name = _str_or_none(metric["metric_name"])
    if candidate_id is None or metric_name is None:
        return None
    value = _float_or_none(metric["value"])
    scores = {metric_name: value} if value is not None else {}
    return FitnessEvent(
        run_id=run_id,
        timestamp_ns=timestamp_ns,
        payload=FitnessPayload(
            individual_id=candidate_id,
            evaluator_id="cvevolve-holdout",
            evaluator_kind="deterministic_metric",
            scores=scores,
            composite=(
                _composite_for(metric_name, value, metric_directions) if value is not None else None
            ),
            invalid_reason=None if value is not None else str(metric["notes"] or "holdout failed"),
            metadata={
                "round_index": metric["round_index"],
                "notes": metric["notes"],
                "settings": _loads_dict(metric["settings_json"]),
                "source_table": "holdout_test_metrics",
                "source_id": metric["id"],
            },
        ),
    )


def _audit_stream_events(
    *,
    run_id: str,
    message_rows: Sequence[Any],
    tool_call_rows: Sequence[Any],
    timestamp_base: int,
    max_text_chars: int,
) -> list[StreamEventEvent]:
    events: list[StreamEventEvent] = []
    for index, row in enumerate(message_rows, start=1):
        text, truncated, char_count = _limited_text(row["content"], max_text_chars)
        worker_index = _int_or_none(row["worker_index"])
        worker_id = f"worker_{worker_index}" if worker_index is not None else None
        events.append(
            StreamEventEvent(
                run_id=run_id,
                timestamp_ns=_timestamp_for(row, timestamp_base, index),
                stream_id="cvevolve-audit",
                worker_id=worker_id,
                payload=StreamEventPayload(
                    label="cvevolve_message",
                    text=text,
                    metadata={
                        "audit_kind": "message",
                        "message_type": row["message_type"],
                        "round_index": row["round_index"],
                        "worker_index": worker_index,
                        "content_chars": char_count,
                        "truncated": truncated,
                        "message_metadata": _loads_dict(row["metadata_json"]),
                        "source_table": "messages.message_events",
                        "source_id": row["id"],
                        "source_file": "history/messages.sqlite",
                    },
                ),
            )
        )

    offset = len(events)
    for index, row in enumerate(tool_call_rows, start=1):
        tool_name = str(row["tool_name"] or "tool")
        raw_arguments = str(row["arguments_json"] or "{}")
        text, truncated, char_count = _limited_text(
            f"{tool_name} {raw_arguments}",
            max_text_chars,
        )
        events.append(
            StreamEventEvent(
                run_id=run_id,
                timestamp_ns=_timestamp_for(row, timestamp_base, offset + index),
                stream_id="cvevolve-audit",
                payload=StreamEventPayload(
                    label="cvevolve_tool_call",
                    text=text,
                    metadata={
                        "audit_kind": "tool_call",
                        "tool_name": tool_name,
                        "arguments": _loads_json_value(raw_arguments),
                        "argument_chars": char_count,
                        "truncated": truncated,
                        "source_table": "tool_calls.tool_calls",
                        "source_id": row["id"],
                        "source_file": "history/tool_calls.sqlite",
                    },
                ),
            )
        )

    return sorted(
        events,
        key=lambda event: (
            event.timestamp_ns,
            str(event.payload.metadata.get("source_table", "")),
            str(event.payload.metadata.get("source_id", "")),
        ),
    )


def _composite_for(
    metric_name: str,
    value: float,
    metric_directions: Mapping[str, ScoreDirection],
) -> float:
    return -value if metric_directions.get(metric_name) == "lower" else value


def _run_status_for(state: Mapping[str, Any] | None) -> RunStatus:
    if state is None:
        return "finished"
    if state.get("phase") == "completed":
        return "finished"
    return "running"


def _active_run_update_source_key(
    state: Mapping[str, Any] | None,
    source_counts: Mapping[str, int],
) -> str:
    signature = {
        "phase": state.get("phase") if state else None,
        "status": state.get("status") if state else None,
        "current_round_index": state.get("current_round_index") if state else None,
        "current_action": state.get("current_action") if state else None,
        "updated_at": state.get("updated_at") if state else None,
        "source_counts": dict(sorted(source_counts.items())),
    }
    digest = hashlib.sha256(
        json.dumps(signature, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    return f"run_update:active:{digest}"


# ---------- scalar / JSON / timestamp helpers -----------------------------


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _loads_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _loads_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item is not None]


def _loads_json_value(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _limited_text(value: Any, max_chars: int) -> tuple[str, bool, int]:
    text = "" if value is None else str(value)
    char_count = len(text)
    if max_chars > 0 and char_count > max_chars:
        return text[:max_chars], True, char_count
    return text, False, char_count


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_ns(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1_000_000_000)


def _timestamp_for(row: Any, fallback_base: int, offset: int) -> int:
    for key in ("created_at", "updated_at"):
        ts = _parse_iso_ns(_row_get(row, key))
        if ts is not None:
            return ts
    return fallback_base + offset


def _earliest_timestamp(*row_groups: Sequence[Any]) -> int:
    candidates: list[int] = []
    for group in row_groups:
        for row in group:
            for key in ("created_at", "updated_at"):
                ts = _parse_iso_ns(_row_get(row, key))
                if ts is not None:
                    candidates.append(ts)
    if candidates:
        return min(candidates)
    return time.time_ns()


def _row_get(row: Any, key: str) -> Any:
    if hasattr(row, "get"):
        return row.get(key)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _is_locked_error(exc: sqlite3.Error) -> bool:
    text = str(exc).lower()
    return "database is locked" in text or "database is busy" in text or "locked" in text


def _candidate_code_abs_path(candidate: Any, workspace_root: Path) -> str | None:
    code_path = _str_or_none(candidate["code_file_path"])
    if code_path is None:
        return None
    raw = Path(code_path)
    resolved = raw if raw.is_absolute() else workspace_root / raw
    return str(resolved.resolve()) if resolved.exists() else None


def _candidate_code_uri(candidate: Any, workspace_root: Path) -> str | None:
    abs_path = _candidate_code_abs_path(candidate, workspace_root)
    if abs_path is None:
        return None
    return Path(abs_path).as_uri()


def _candidate_genome_lang(candidate: Any) -> str | None:
    code_path = _str_or_none(candidate["code_file_path"])
    if code_path is None:
        return None
    suffix = Path(code_path).suffix.lower()
    if suffix == ".py":
        return "python"
    return None


def _worker_id_for(candidate: Any) -> str | None:
    code_path = _str_or_none(candidate["code_path"])
    if code_path is None:
        return None
    for part in Path(code_path).parts:
        if part.startswith("worker_"):
            return part
    return None
