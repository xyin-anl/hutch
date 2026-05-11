"""Generate a small DGM-shaped run on disk for testing.

DGM's on-disk format: each agent version lives at
``output_dgm/<commit_id>/metadata.json`` with ``parent_commit`` pointing at
its parent and one or more benchmark scores. ``dgm_metadata.jsonl`` (at the
run root) holds one record per generation.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def make_dgm_run(target_dir: Path, *, seed: int = 5, generations: int = 4) -> Path:
    rng = random.Random(seed)
    target_dir.mkdir(parents=True, exist_ok=True)
    output_dgm = target_dir / "output_dgm"
    output_dgm.mkdir(exist_ok=True)
    base = datetime(2026, 4, 12, 9, 0, 0)

    archive: list[str] = []
    by_commit: dict[str, dict[str, Any]] = {}
    generation_records: list[dict[str, Any]] = []

    initial = "init-" + rng.randbytes(4).hex()
    initial_score = round(rng.uniform(0.18, 0.25), 3)
    by_commit[initial] = _agent_record(
        commit=initial,
        parent=None,
        generation=0,
        score=initial_score,
        ctime=(base + timedelta(seconds=1)).timestamp(),
        proposal="initial seed agent",
        verdict="accepted",
    )
    archive.append(initial)
    generation_records.append({"generation": 0, "archive": list(archive)})

    parents = [initial]
    for gen in range(1, generations + 1):
        children: list[str] = []
        compiled: list[str] = []
        for parent in parents:
            for branch in range(2):
                commit = f"agent-{gen}-{parent[-4:]}-{branch}-" + rng.randbytes(3).hex()
                parent_score = by_commit[parent].get("overall_performance", 0.0)
                drift = rng.uniform(-0.05, 0.12)
                score = round(max(0.0, min(1.0, parent_score + drift)), 3)
                accepted = score >= parent_score
                ctime = (base + timedelta(seconds=10 * gen + branch)).timestamp()
                by_commit[commit] = _agent_record(
                    commit=commit,
                    parent=parent,
                    generation=gen,
                    score=score,
                    ctime=ctime,
                    proposal=rng.choice(
                        [
                            "Replace BFS with A*",
                            "Cache the tokenizer state",
                            "Add early-exit on identical diffs",
                            "Split the planner into two passes",
                        ]
                    ),
                    verdict="accepted" if accepted else "rejected",
                )
                children.append(commit)
                if branch == 0:
                    compiled.append(commit)
                if accepted:
                    archive.append(commit)
        generation_records.append(
            {
                "generation": gen,
                "selfimprove_entries": [[parent, "edit"] for parent in parents],
                "children": children,
                "children_compiled": compiled,
                "archive": list(archive),
            }
        )
        parents = [c for c in children if c in archive]
        if not parents:
            parents = compiled[:1] or children[:1]

    # Write per-agent metadata.json.
    for commit, record in by_commit.items():
        d = output_dgm / commit
        d.mkdir(exist_ok=True)
        (d / "metadata.json").write_text(json.dumps(record, indent=2))

    # Write the per-generation summary.
    (target_dir / "dgm_metadata.jsonl").write_text(
        "\n".join(json.dumps(rec) for rec in generation_records) + "\n"
    )
    return target_dir


def _agent_record(
    *,
    commit: str,
    parent: str | None,
    generation: int,
    score: float,
    ctime: float,
    proposal: str,
    verdict: str,
) -> dict[str, Any]:
    return {
        "commit_id": commit,
        "parent_commit": parent,
        "generation": generation,
        "ctime": ctime,
        "accuracy_score": score,
        "overall_performance": score,
        "compile_rate": 1.0 if verdict == "accepted" else 0.0,
        "proposal": proposal,
        "overseer_verdict": verdict,
        "overseer_id": "claude-opus-4.7",
        "benchmark": "swe-bench-mini",
        "target_path": "src/coder.py",
        "compiled": True,
    }
