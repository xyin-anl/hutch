"""Tests for the ptychi-evolve adapter."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from hutch.adapters import detect_format
from hutch.adapters.ptychi_evolve import detect, import_ptychi_evolve
from hutch.schema import EVENT_ADAPTER
from tests._ptychi_evolve_fixture import make_run


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return make_run(tmp_path / "ptychi-toy")


def test_detect_recognizes_run(run_dir: Path) -> None:
    assert detect(run_dir) is True
    adapter = detect_format(run_dir)
    assert adapter is not None
    assert adapter.name == "ptychi_evolve"


def test_detect_rejects_arbitrary_jsonl(tmp_path: Path) -> None:
    arbitrary = tmp_path / "rounds.jsonl"
    arbitrary.write_text('{"hello": "world"}\n', encoding="utf-8")
    assert detect(tmp_path) is False


def test_imports_run_envelope(run_dir: Path) -> None:
    events = list(import_ptychi_evolve(run_dir))
    assert events
    assert events[0].event_kind == "run_start"
    assert events[-1].event_kind == "run_end"


def test_event_kind_counts(run_dir: Path) -> None:
    """5 rounds * 6 individuals = 30 individuals + 30 fitness;
    operators are bounded by non-seed individuals."""
    events = list(import_ptychi_evolve(run_dir))
    counts = Counter(e.event_kind for e in events)
    assert counts["individual"] == 30
    assert counts["fitness"] == 30
    seeds = sum(
        1 for e in events if e.event_kind == "individual" and getattr(e.payload, "is_seed", False)
    )
    assert counts["operator"] == 30 - seeds


def test_metrics_round_trip(run_dir: Path) -> None:
    events = list(import_ptychi_evolve(run_dir))
    fits = [e for e in events if e.event_kind == "fitness"]
    assert fits
    sample = fits[0].payload
    assert "nrmse" in sample.scores  # type: ignore[union-attr]
    assert "time_s" in sample.scores  # type: ignore[union-attr]
    # Composite is the negated nrmse (lower-better → higher-better convention).
    assert sample.composite is not None  # type: ignore[union-attr]
    assert sample.composite == pytest.approx(-sample.scores["nrmse"])  # type: ignore[union-attr]


def test_every_event_validates_against_schema(run_dir: Path) -> None:
    for ev in import_ptychi_evolve(run_dir):
        EVENT_ADAPTER.validate_python(ev.model_dump())


def test_explicit_run_id_is_honored(run_dir: Path) -> None:
    events = list(import_ptychi_evolve(run_dir, run_id="custom-ptychi"))
    assert {e.run_id for e in events} == {"custom-ptychi"}
