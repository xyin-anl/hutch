"""Generate a small AIDE journal on disk for testing.

AIDE's :class:`Journal` serializes to a JSON object ``{"nodes": [<node>, …]}``
where each node carries an ``id``, an optional nested ``parent`` reference,
``code`` / ``plan`` / ``analysis`` strings, a ``metric`` (numeric or dict),
and a ``ctime`` (epoch seconds).
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def make_aide_journal(target_dir: Path, *, seed: int = 9, expansions: int = 18) -> Path:
    rng = random.Random(seed)
    target_dir.mkdir(parents=True, exist_ok=True)
    journal_path = target_dir / "journal.json"

    base = datetime(2026, 4, 18, 14, 0, 0)
    nodes: list[dict[str, Any]] = []

    root_id = str(uuid.uuid4())
    root_metric = round(rng.uniform(0.4, 0.55), 3)
    root_ctime = (base + timedelta(seconds=1)).timestamp()
    nodes.append(
        _node(
            id=root_id,
            step=0,
            ctime=root_ctime,
            plan="initial draft",
            metric=root_metric,
            is_buggy=False,
            parent_id=None,
        )
    )

    frontier = [(root_id, 0, root_metric)]
    for step in range(1, expansions + 1):
        if not frontier:
            break
        # Pick a parent (prefer high-metric nodes).
        frontier.sort(key=lambda t: -t[2])
        parent_id, _parent_step, parent_metric = frontier[rng.randrange(min(3, len(frontier)))]
        node_id = str(uuid.uuid4())
        is_buggy = rng.random() < 0.18
        if is_buggy:
            metric = None
        else:
            drift = rng.uniform(-0.05, 0.10)
            metric = round(max(0.0, min(1.0, parent_metric + drift)), 3)
        ctime = (base + timedelta(seconds=step * 4)).timestamp()
        plan = rng.choice(
            [
                "Try a deeper MLP head.",
                "Switch the optimizer to AdamW.",
                "Add gradient clipping.",
                "Ensemble two prior solutions.",
                "Lower the learning rate by 5x.",
                "Drop the regularizer.",
            ]
        )
        nodes.append(
            _node(
                id=node_id,
                step=step,
                ctime=ctime,
                plan=plan,
                metric=metric,
                is_buggy=is_buggy,
                parent_id=parent_id,
            )
        )
        if metric is not None:
            frontier.append((node_id, step, metric))

    journal_path.write_text(json.dumps({"nodes": nodes}, indent=2))
    return journal_path


def _node(
    *,
    id: str,
    step: int,
    ctime: float,
    plan: str,
    metric: float | None,
    is_buggy: bool,
    parent_id: str | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": id,
        "step": step,
        "ctime": ctime,
        "code": "# code placeholder",
        "plan": plan,
        "analysis": "" if metric is None else f"reached metric={metric}",
        "exec_time": 0.0 if is_buggy else round(0.1 + step * 0.02, 3),
        "exc_type": "RuntimeError" if is_buggy else None,
        "exc_info": None,
        "is_buggy": is_buggy,
        "metric": metric,
        "parent": {"id": parent_id} if parent_id else None,
    }
    return record
