"""Tests for the OpenEvolve checkpoint adapter."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from hutch._fixtures.openevolve import make_checkpoint
from hutch.adapters import REGISTRY, detect_format
from hutch.adapters.openevolve import detect, import_openevolve


@pytest.fixture
def checkpoint(tmp_path: Path) -> Path:
    return make_checkpoint(tmp_path / "openevolve_checkpoint")


def test_detect_recognizes_checkpoint(checkpoint: Path) -> None:
    assert detect(checkpoint) is True
    assert detect_format(checkpoint) is REGISTRY[0]


def test_detect_rejects_non_checkpoint(tmp_path: Path) -> None:
    assert detect(tmp_path) is False
    assert detect_format(tmp_path) is None


def test_imports_run_start_and_end(checkpoint: Path) -> None:
    events = list(import_openevolve(checkpoint))
    assert events, "adapter produced no events"
    assert events[0].event_kind == "run_start"
    assert events[-1].event_kind == "run_end"
    # All events share a single run_id derived from the checkpoint path.
    run_ids = {e.run_id for e in events}
    assert len(run_ids) == 1
    assert next(iter(run_ids)).startswith("oe-")


def test_event_kind_counts(checkpoint: Path) -> None:
    """4 islands x 6 programs = 24 individuals, 20 operators (one per non-seed),
    24 fitness samples (every program has metrics), 24 descriptors."""
    events = list(import_openevolve(checkpoint))
    counts = Counter(e.event_kind for e in events)
    assert counts["individual"] == 24
    assert counts["operator"] == 20  # 24 programs - 4 seeds
    assert counts["fitness"] == 24
    assert counts["descriptor"] == 24
    assert counts["run_start"] == 1
    assert counts["run_end"] == 1


def test_seed_individuals_have_no_parents(checkpoint: Path) -> None:
    events = list(import_openevolve(checkpoint))
    seeds = [
        e for e in events if e.event_kind == "individual" and getattr(e.payload, "is_seed", False)
    ]
    assert len(seeds) == 4
    for s in seeds:
        assert s.payload.parent_ids == []  # type: ignore[union-attr]


def test_island_assignment_present(checkpoint: Path) -> None:
    events = list(import_openevolve(checkpoint))
    individuals = [e for e in events if e.event_kind == "individual"]
    islands_seen = {ev.payload.island_id for ev in individuals}  # type: ignore[union-attr]
    assert islands_seen == {"0", "1", "2", "3"}


def test_fitness_scores_round_trip(checkpoint: Path) -> None:
    events = list(import_openevolve(checkpoint))
    fits = [e for e in events if e.event_kind == "fitness"]
    sample = fits[0].payload
    assert "sum_radii" in sample.scores  # type: ignore[union-attr]
    assert "compile_ms" in sample.scores  # type: ignore[union-attr]
    assert sample.composite is not None  # type: ignore[union-attr]


def test_descriptors_have_parsed_coordinates(checkpoint: Path) -> None:
    events = list(import_openevolve(checkpoint))
    descs = [e for e in events if e.event_kind == "descriptor"]
    assert all(len(d.payload.coordinates) == 2 for d in descs)  # type: ignore[union-attr]
    # Cell ids look like "(0.123, 0.456)".
    assert all(
        d.payload.cell_id is not None and d.payload.cell_id.startswith("(")  # type: ignore[union-attr]
        for d in descs
    )


def test_operator_child_id_matches_individual(checkpoint: Path) -> None:
    events = list(import_openevolve(checkpoint))
    individual_ids = {
        e.payload.id  # type: ignore[union-attr]
        for e in events
        if e.event_kind == "individual"
    }
    for op in (e for e in events if e.event_kind == "operator"):
        assert op.payload.child_id in individual_ids  # type: ignore[union-attr]


def test_rejects_directory_without_metadata(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="OpenEvolve checkpoint"):
        list(import_openevolve(tmp_path))
