"""Tests for the QDax repertoire adapter."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from hutch.adapters import detect_format
from hutch.adapters.qdax import detect, import_qdax
from hutch.schema import EVENT_ADAPTER
from tests._qdax_fixture import make_repertoire


@pytest.fixture
def repertoire_dir(tmp_path: Path) -> Path:
    """Directory holding a fresh ``repertoire.json``."""
    target = tmp_path / "qd-toy"
    target.mkdir()
    make_repertoire(target / "repertoire.json")
    return target


def test_detect_dir_with_repertoire_json(repertoire_dir: Path) -> None:
    assert detect(repertoire_dir) is True
    json_path = repertoire_dir / "repertoire.json"
    assert detect(json_path) is True
    # Registry pickup.
    adapter = detect_format(repertoire_dir)
    assert adapter is not None
    assert adapter.name == "qdax"


def test_detect_rejects_unrelated_json(tmp_path: Path) -> None:
    other = tmp_path / "metadata.json"
    other.write_text('{"hello": "world"}', encoding="utf-8")
    assert detect(other) is False


def test_imports_run_envelope_and_archive_snapshot(repertoire_dir: Path) -> None:
    events = list(import_qdax(repertoire_dir))
    assert events
    assert events[0].event_kind == "run_start"
    assert events[-1].event_kind == "run_end"
    snapshots = [e for e in events if e.event_kind == "archive_snapshot"]
    assert len(snapshots) == 1
    payload = snapshots[0].payload
    assert 0 < payload.coverage <= 1.0  # type: ignore[union-attr]
    assert payload.size > 0  # type: ignore[union-attr]


def test_one_individual_per_filled_cell(repertoire_dir: Path) -> None:
    """The synthetic fixture is 8x8=64 cells, ~45% filled — assert counts
    line up: one Individual + Fitness + Descriptor per filled cell, plus
    one Operator per non-seed cell (parents on roughly half of them)."""
    events = list(import_qdax(repertoire_dir))
    counts = Counter(e.event_kind for e in events)
    inds = counts["individual"]
    assert inds > 0
    assert counts["fitness"] == inds
    assert counts["descriptor"] == inds
    # Operators are bounded by the number of non-seed cells.
    seeds = sum(
        1 for e in events if e.event_kind == "individual" and getattr(e.payload, "is_seed", False)
    )
    assert counts["operator"] == inds - seeds


def test_descriptors_carry_dimensions_and_coords(repertoire_dir: Path) -> None:
    events = list(import_qdax(repertoire_dir))
    descriptors = [e for e in events if e.event_kind == "descriptor"]
    assert descriptors
    sample = descriptors[0].payload
    assert sample.archive_id == "qdax-grid"  # type: ignore[union-attr]
    assert sample.kind == "grid"  # type: ignore[union-attr]
    assert sample.dimensions == ["complexity", "speed"]  # type: ignore[union-attr]
    assert len(sample.coordinates) == 2  # type: ignore[union-attr]


def test_every_event_validates_against_canonical_schema(repertoire_dir: Path) -> None:
    """Round-trip every event through ``EVENT_ADAPTER`` to catch schema drift."""
    for ev in import_qdax(repertoire_dir):
        EVENT_ADAPTER.validate_python(ev.model_dump())


def test_explicit_run_id_is_honored(repertoire_dir: Path) -> None:
    events = list(import_qdax(repertoire_dir, run_id="custom-run-id"))
    assert {e.run_id for e in events} == {"custom-run-id"}
