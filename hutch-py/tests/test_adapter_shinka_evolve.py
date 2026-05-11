"""Tests for the ShinkaEvolve adapter."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from hutch.adapters import detect_format
from hutch.adapters.shinka_evolve import detect, import_shinka_evolve
from hutch.schema import EVENT_ADAPTER
from tests._shinka_evolve_fixture import make_run


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return make_run(tmp_path / "shinka-toy")


def test_detect_recognizes_run(run_dir: Path) -> None:
    assert detect(run_dir) is True
    adapter = detect_format(run_dir)
    assert adapter is not None
    assert adapter.name == "shinka_evolve"


def test_detect_rejects_arbitrary_jsonl(tmp_path: Path) -> None:
    arbitrary = tmp_path / "candidates.jsonl"
    arbitrary.write_text('{"hello": "world"}\n', encoding="utf-8")
    assert detect(tmp_path) is False


def test_imports_run_envelope(run_dir: Path) -> None:
    events = list(import_shinka_evolve(run_dir))
    assert events
    assert events[0].event_kind == "run_start"
    assert events[-1].event_kind == "run_end"


def test_event_kind_distribution(run_dir: Path) -> None:
    """20 candidates / 4 generations = 5 per gen * 4 = 20 individuals,
    plus 2 meta-mutations (1 seed + 1 op)."""
    events = list(import_shinka_evolve(run_dir))
    counts = Counter(e.event_kind for e in events)
    # 20 candidates + 2 meta-mutations
    assert counts["individual"] == 22
    # 20 candidate fitness samples, no fitness for meta-mutations
    assert counts["fitness"] == 20
    # Operators: 1 meta-mutate + (20 - 5) candidate operators = 16
    assert counts["operator"] == 16


def test_meta_mutate_operator_emitted(run_dir: Path) -> None:
    events = list(import_shinka_evolve(run_dir))
    operators = [e for e in events if e.event_kind == "operator"]
    meta_ops = [op for op in operators if op.payload.kind == "meta_mutate"]  # type: ignore[union-attr]
    assert len(meta_ops) == 1
    assert meta_ops[0].payload.parent_ids == ["meta-0"]  # type: ignore[union-attr]
    assert meta_ops[0].payload.child_id == "meta-1"  # type: ignore[union-attr]


def test_individual_kinds_split_program_vs_prompt(run_dir: Path) -> None:
    events = list(import_shinka_evolve(run_dir))
    individuals = [e for e in events if e.event_kind == "individual"]
    kinds = {e.payload.kind for e in individuals}  # type: ignore[union-attr]
    # Skill kind = the meta-mutation entities; program/prompt = the candidates.
    assert "skill" in kinds
    # The probabilistic fixture biases toward "program".
    assert "program" in kinds


def test_crossover_uses_crossover_operator_kind(run_dir: Path) -> None:
    events = list(import_shinka_evolve(run_dir))
    operators = [e for e in events if e.event_kind == "operator"]
    for op in operators:
        if op.payload.kind == "crossover":  # type: ignore[union-attr]
            assert len(op.payload.parent_ids) >= 2  # type: ignore[union-attr]


def test_every_event_validates_against_schema(run_dir: Path) -> None:
    for ev in import_shinka_evolve(run_dir):
        EVENT_ADAPTER.validate_python(ev.model_dump())


def test_explicit_run_id_is_honored(run_dir: Path) -> None:
    events = list(import_shinka_evolve(run_dir, run_id="custom-shinka"))
    assert {e.run_id for e in events} == {"custom-shinka"}
