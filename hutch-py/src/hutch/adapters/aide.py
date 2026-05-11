"""AIDE journal adapter.

Reads the JSON-serialized Journal produced by [AIDE](https://github.com/WecoAI/aideml)
and emits canonical Hutch events. AIDE's :class:`Journal` is a list of
:class:`Node` records; each node has::

    id        : str (UUID)
    step      : int
    ctime     : float (epoch seconds)
    code      : str
    plan      : str | None
    parent    : Node | None              # nested
    children  : set[Node]                # nested
    metric    : MetricValue | float
    is_buggy  : bool
    analysis  : str | None
    exec_time : float
    exc_type  : str | None
    exc_info  : dict | None

Per node the adapter emits:

* :class:`IndividualEvent` (kind=``experiment_plan``).
* :class:`OperatorEvent` (kind=``tree_expand``) when a parent is recorded.
* :class:`TreeExpansionEvent` for the Tree-Search view.
* :class:`FitnessEvent` carrying the metric score (and ``invalid_reason`` if
  ``is_buggy`` is set).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
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
    TreeExpansionEvent,
    TreeExpansionPayload,
)

logger = logging.getLogger("hutch.adapters.aide")


def detect(path: Path) -> bool:
    """An AIDE journal is either a single ``*.json`` file with a ``nodes`` key,
    or a directory containing ``journal.json``."""
    if path.is_file() and path.suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return isinstance(data, dict) and "nodes" in data and isinstance(data["nodes"], list)
    if path.is_dir() and (path / "journal.json").is_file():
        return detect(path / "journal.json")
    return False


def import_aide(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
) -> Iterator[AnyEvent]:
    """Yield canonical events for an AIDE journal."""
    root = Path(path)
    if not detect(root):
        raise ValueError(
            f"{root} doesn't look like an AIDE journal "
            f"(expected a JSON file or a directory containing journal.json)."
        )
    journal_path = root if root.is_file() else root / "journal.json"
    nodes = _load_journal(journal_path)
    if not nodes:
        raise ValueError(f"AIDE journal {journal_path} has no nodes")

    resolved_run_id = run_id or f"aide-{journal_path.parent.name or journal_path.stem}"
    project = project or "aide"
    tree_id = run_id or "aide"

    nodes.sort(key=lambda n: (n.get("step") or 0, n.get("ctime_ns") or 0, n.get("id") or ""))
    started_at = _earliest_ctime_ns(nodes)

    yield RunStartEvent(
        run_id=resolved_run_id,
        timestamp_ns=started_at,
        payload=RunStartPayload(
            name=journal_path.stem,
            project=project,
            started_by="aide-importer",
            config={
                "num_nodes": len(nodes),
                "journal_path": str(journal_path.resolve()),
            },
        ),
    )

    for node in nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str):
            logger.warning("skipping AIDE node with no id: %s", node)
            continue
        ts = int(node.get("ctime_ns") or 0)
        parent_id = node.get("parent_id")
        is_seed = parent_id is None
        score, valid = _score(node)

        yield IndividualEvent(
            run_id=resolved_run_id,
            timestamp_ns=ts,
            payload=IndividualPayload(
                id=node_id,
                kind="experiment_plan",
                parent_ids=[parent_id] if parent_id else [],
                is_seed=is_seed,
                genome_lang="python",
                generation_index=node.get("step"),
                metadata={
                    "plan": node.get("plan"),
                    "analysis": node.get("analysis"),
                    "exec_time": node.get("exec_time"),
                    "exc_type": node.get("exc_type"),
                },
            ),
        )

        if parent_id:
            yield OperatorEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=OperatorPayload(
                    id=f"op-{node_id}",
                    kind="tree_expand",
                    parent_ids=[parent_id],
                    child_id=node_id,
                    metadata={
                        "plan": node.get("plan"),
                        "is_buggy": node.get("is_buggy"),
                    },
                ),
            )
            yield TreeExpansionEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=TreeExpansionPayload(
                    tree_id=tree_id,
                    parent_node=parent_id,
                    child_node=node_id,
                    visit_count=1,
                    value_estimate=score,
                ),
            )

        if score is not None or not valid:
            payload = FitnessPayload(
                individual_id=node_id,
                evaluator_kind="deterministic_metric",
                scores={"metric": score} if score is not None else {},
                invalid_reason=("buggy" if not valid else None),
                composite=score,
            )
            yield FitnessEvent(
                run_id=resolved_run_id,
                timestamp_ns=ts,
                payload=payload,
            )

    last_ts = _latest_ctime_ns(nodes)
    yield RunEndEvent(
        run_id=resolved_run_id,
        timestamp_ns=max(last_ts, started_at + 1),
        payload=RunEndPayload(
            status="finished",
            summary=f"imported {len(nodes)} nodes from {journal_path.name}",
        ),
    )


# ---------- helpers --------------------------------------------------------


def _load_journal(path: Path) -> list[dict[str, Any]]:
    """Return a flat list of node dicts with ``parent_id`` flattened from the
    nested ``parent`` reference AIDE serializes."""
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    nodes_field = raw.get("nodes")
    if not isinstance(nodes_field, list):
        return []
    out: list[dict[str, Any]] = []
    for node in nodes_field:
        if not isinstance(node, dict):
            continue
        flat = dict(node)
        parent = node.get("parent")
        if isinstance(parent, dict) and isinstance(parent.get("id"), str):
            flat["parent_id"] = parent["id"]
        elif isinstance(parent, str):
            flat["parent_id"] = parent
        else:
            flat["parent_id"] = None
        ctime = node.get("ctime")
        if isinstance(ctime, (int, float)):
            flat["ctime_ns"] = int(float(ctime) * 1_000_000_000)
        # Strip the children set; we infer it from the parent links.
        flat.pop("children", None)
        flat.pop("parent", None)
        out.append(flat)
    return out


def _score(node: dict[str, Any]) -> tuple[float | None, bool]:
    """Return ``(score, valid)``. ``valid`` is False if the node is buggy."""
    valid = not bool(node.get("is_buggy"))
    metric = node.get("metric")
    if isinstance(metric, dict):
        metric = metric.get("value")
    if isinstance(metric, (int, float)) and not isinstance(metric, bool):
        return float(metric), valid
    return None, valid


def _earliest_ctime_ns(nodes: list[dict[str, Any]]) -> int:
    candidates = [int(n.get("ctime_ns") or 0) for n in nodes]
    candidates = [c for c in candidates if c > 0]
    return min(candidates) if candidates else 0


def _latest_ctime_ns(nodes: list[dict[str, Any]]) -> int:
    candidates = [int(n.get("ctime_ns") or 0) for n in nodes]
    candidates = [c for c in candidates if c > 0]
    return max(candidates) if candidates else 0
