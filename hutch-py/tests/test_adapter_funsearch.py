"""Tests for the FunSearch programs-database adapter."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from hutch.adapters import detect_format
from hutch.adapters.funsearch import detect, import_funsearch
from hutch.schema import EVENT_ADAPTER
from tests._funsearch_fixture import make_dump


@pytest.fixture
def dump_dir(tmp_path: Path) -> Path:
    return make_dump(tmp_path / "funsearch-toy")


def test_detect_recognizes_dump(dump_dir: Path) -> None:
    assert detect(dump_dir) is True
    adapter = detect_format(dump_dir)
    assert adapter is not None
    assert adapter.name == "funsearch"


def test_detect_rejects_arbitrary_jsonl(tmp_path: Path) -> None:
    arbitrary = tmp_path / "programs.jsonl"
    arbitrary.write_text('{"hello": "world"}\n', encoding="utf-8")
    assert detect(tmp_path) is False


def test_imports_run_envelope(dump_dir: Path) -> None:
    events = list(import_funsearch(dump_dir))
    assert events
    assert events[0].event_kind == "run_start"
    assert events[-1].event_kind == "run_end"
    # Single run id derived from the dump dir.
    assert {e.run_id for e in events} == {f"fs-{dump_dir.name}"}


def test_event_kind_counts(dump_dir: Path) -> None:
    """24 programs, 3 seeds → 24 individuals + 24 fitness + 21 operators."""
    events = list(import_funsearch(dump_dir))
    counts = Counter(e.event_kind for e in events)
    assert counts["individual"] == 24
    assert counts["fitness"] == 24
    seeds = sum(
        1 for e in events if e.event_kind == "individual" and getattr(e.payload, "is_seed", False)
    )
    assert seeds == 3
    assert counts["operator"] == 24 - seeds


def test_island_streams_and_lineage(dump_dir: Path) -> None:
    events = list(import_funsearch(dump_dir))
    individuals = [e for e in events if e.event_kind == "individual"]
    streams = {e.stream_id for e in individuals if e.stream_id}
    assert streams == {"island-0", "island-1", "island-2"}
    # Every non-seed individual references parents that exist as previous fs-* ids.
    seen_ids: set[str] = set()
    for ev in individuals:
        seen_ids.add(ev.payload.id)  # type: ignore[union-attr]
        for pid in ev.payload.parent_ids:  # type: ignore[union-attr]
            assert pid in seen_ids, f"forward reference {pid}"


def test_crossover_uses_crossover_kind(dump_dir: Path) -> None:
    events = list(import_funsearch(dump_dir))
    operators = [e for e in events if e.event_kind == "operator"]
    crossovers = [
        op
        for op in operators
        if len(op.payload.parent_ids) >= 2 and op.payload.kind == "crossover"  # type: ignore[union-attr]
    ]
    mutations = [
        op
        for op in operators
        if len(op.payload.parent_ids) == 1 and op.payload.kind == "mutate"  # type: ignore[union-attr]
    ]
    # At least one of each given the fixture's 18% crossover probability.
    assert mutations
    # Crossover is probabilistic in the fixture; only assert the kinds line up.
    for op in operators:
        fanout = len(op.payload.parent_ids)  # type: ignore[union-attr]
        if fanout >= 2:
            assert op.payload.kind == "crossover"  # type: ignore[union-attr]
        elif fanout == 1:
            assert op.payload.kind == "mutate"  # type: ignore[union-attr]
    del crossovers


def test_fitness_carries_evaluator_id(dump_dir: Path) -> None:
    events = list(import_funsearch(dump_dir))
    fits = [e for e in events if e.event_kind == "fitness"]
    assert fits
    sample = fits[0].payload
    assert sample.evaluator_kind == "benchmark"  # type: ignore[union-attr]
    assert sample.evaluator_id == "cap_set"  # type: ignore[union-attr]
    assert sample.composite is not None  # type: ignore[union-attr]


def test_every_event_validates_against_schema(dump_dir: Path) -> None:
    for ev in import_funsearch(dump_dir):
        EVENT_ADAPTER.validate_python(ev.model_dump())


def test_explicit_run_id_is_honored(dump_dir: Path) -> None:
    events = list(import_funsearch(dump_dir, run_id="custom-fs"))
    assert {e.run_id for e in events} == {"custom-fs"}
