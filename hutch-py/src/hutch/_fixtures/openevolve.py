"""Generate a small OpenEvolve-shaped checkpoint on disk for testing.

The on-disk format mirrors what OpenEvolve writes (metadata.json + per-program
JSON files under ``programs/``) per the published format. Used by both the
adapter unit tests and the multi-island example.
"""

from __future__ import annotations

import json
import random
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def make_checkpoint(
    target_dir: Path,
    *,
    seed: int = 7,
    num_islands: int = 4,
    programs_per_island: int = 6,
    crossover_probability: float = 0.25,
    objectives: tuple[str, ...] = ("sum_radii", "compile_ms"),
) -> Path:
    """Generate a synthetic OpenEvolve checkpoint at *target_dir* and return it.

    The generated run is small enough for tests but rich enough to exercise
    every event kind the adapter emits: seeds, mutations, crossovers across
    parents, multi-objective metrics, MAP-Elites grid descriptors.
    """
    rng = random.Random(seed)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "programs").mkdir(exist_ok=True)

    base_time = datetime(2026, 4, 1, 12, 0, 0)

    islands_ids: list[list[str]] = [[] for _ in range(num_islands)]
    feature_maps: list[dict[str, str]] = [{} for _ in range(num_islands)]
    archive: list[str] = []
    program_records: list[dict[str, Any]] = []
    iteration = 0

    for island_idx in range(num_islands):
        iteration += 1
        seed_id = _make_id(f"i{island_idx}-seed", iteration)
        islands_ids[island_idx].append(seed_id)
        seed_time = base_time + timedelta(seconds=iteration)
        seed_metrics = _toy_metrics(rng, objectives, base=0.3)
        seed_features = _features(rng)
        feature_maps[island_idx][_cell_key(seed_features)] = seed_id
        program_records.append(
            _program_record(
                pid=seed_id,
                parent_id=None,
                generation=0,
                iteration=iteration,
                timestamp=seed_time,
                metrics=seed_metrics,
                features=seed_features,
                island=island_idx,
                code=f"# island {island_idx} seed",
                changes_description="initial seed",
            )
        )

        # Build subsequent generations on top of the seed (and occasionally cross
        # with another island's program).
        active_parents = [seed_id]
        for gen in range(1, programs_per_island):
            iteration += 1
            child_id = _make_id(f"i{island_idx}-g{gen}", iteration)
            child_time = base_time + timedelta(seconds=iteration)
            primary = rng.choice(active_parents)
            cross = (
                rng.choice(_pick_other_island_ids(islands_ids, island_idx, rng))
                if (
                    rng.random() < crossover_probability
                    and any(_pick_other_island_ids(islands_ids, island_idx, rng))
                )
                else None
            )
            parent_id = primary
            features = _features(rng)
            metrics = _toy_metrics(rng, objectives, base=0.3 + gen * 0.08)
            program_records.append(
                _program_record(
                    pid=child_id,
                    parent_id=parent_id,
                    generation=gen,
                    iteration=iteration,
                    timestamp=child_time,
                    metrics=metrics,
                    features=features,
                    island=island_idx,
                    code=f"# island {island_idx} gen {gen}",
                    changes_description=(
                        f"crossover with {cross}" if cross else f"refined gen {gen}"
                    ),
                    cross_parent=cross,
                )
            )
            islands_ids[island_idx].append(child_id)
            active_parents.append(child_id)
            feature_maps[island_idx][_cell_key(features)] = child_id
            if metrics["sum_radii"] > 0.7:
                archive.append(child_id)

    # Pick best per island and overall.
    island_best: list[str] = []
    for ids in islands_ids:
        best = max(
            ids,
            key=lambda pid: _find_program(program_records, pid)["metrics"]["sum_radii"],
        )
        island_best.append(best)
    best_program_id = max(
        island_best,
        key=lambda pid: _find_program(program_records, pid)["metrics"]["sum_radii"],
    )

    metadata = {
        "islands": islands_ids,
        "island_feature_maps": feature_maps,
        "archive": sorted(set(archive)),
        "best_program_id": best_program_id,
        "island_best_programs": island_best,
        "last_iteration": iteration,
        "feature_stats": {
            "complexity": {"min": 0.0, "max": 1.0},
            "diversity": {"min": 0.0, "max": 1.0},
        },
    }
    (target_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    for record in program_records:
        (target_dir / "programs" / f"{record['id']}.json").write_text(json.dumps(record, indent=2))
    return target_dir


def _make_id(prefix: str, salt: int) -> str:
    """Deterministic, collision-free id keyed on the unique iteration count."""
    h = uuid.uuid5(uuid.NAMESPACE_OID, f"{prefix}|{salt}").hex[:12]
    return f"{prefix}-{h}"


def _toy_metrics(rng: random.Random, objectives: Iterable[str], *, base: float) -> dict[str, float]:
    """Generate toy fitness metrics scaled to roughly [0, 1].

    OpenEvolve runs in the wild use mixed scales (sum_radii in [0, 1],
    compile_ms in [40, 500], …) but for our fixtures we keep everything in
    a comparable range so the dashboard's composite-score fallback
    (``max(scores)`` when no explicit composite is set) doesn't pick up a
    stray millisecond reading.
    """
    out: dict[str, float] = {}
    for name in objectives:
        if name == "sum_radii":
            out[name] = round(min(1.0, max(0.0, base + rng.uniform(-0.1, 0.2))), 4)
        elif name == "compile_ms":
            # Surface as a 0..1 "speed" score where 1 = fast, 0 = slow.
            ms = rng.uniform(40, 250)
            out[name] = round(max(0.0, 1.0 - (ms - 40) / 210), 4)
        else:
            out[name] = round(rng.uniform(0, 1), 4)
    return out


def _features(rng: random.Random) -> tuple[float, float]:
    return (round(rng.uniform(0, 1), 3), round(rng.uniform(0, 1), 3))


def _cell_key(features: tuple[float, float]) -> str:
    return f"({features[0]:.3f}, {features[1]:.3f})"


def _pick_other_island_ids(
    islands_ids: list[list[str]], current: int, rng: random.Random
) -> list[str]:
    others = [ids for idx, ids in enumerate(islands_ids) if idx != current and ids]
    if not others:
        return []
    return rng.choice(others)


def _program_record(
    *,
    pid: str,
    parent_id: str | None,
    generation: int,
    iteration: int,
    timestamp: datetime,
    metrics: dict[str, float],
    features: tuple[float, float],
    island: int,
    code: str,
    changes_description: str,
    cross_parent: str | None = None,
) -> dict[str, Any]:
    return {
        "id": pid,
        "code": code,
        "language": "python",
        "parent_id": parent_id,
        "generation": generation,
        "timestamp": timestamp.isoformat(),
        "iteration_found": iteration,
        "metrics": metrics,
        "complexity": round(0.4 + 0.05 * generation, 3),
        "diversity": features[0],
        "artifacts_json": "{}",
        "embedding": None,
        "changes_description": changes_description,
        "metadata": {"island": island, "cross_parent": cross_parent},
        "prompts": None,
        "_features": features,
    }


def _find_program(records: list[dict[str, Any]], pid: str) -> dict[str, Any]:
    for r in records:
        if r["id"] == pid:
            return r
    raise KeyError(pid)
