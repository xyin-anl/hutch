"""Tests for the ASI-ARCH experiment-dump adapter."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from hutch.adapters import REGISTRY, detect_format
from hutch.adapters.asi_arch import detect, import_asi_arch
from hutch.schema import EVENT_ADAPTER
from tests._asi_arch_fixture import make_dump


@pytest.fixture
def dump_dir(tmp_path: Path) -> Path:
    target = tmp_path / "asi-arch-toy"
    target.mkdir()
    make_dump(target / "experiments.jsonl")
    return target


def test_detect_dir_with_experiments_jsonl(dump_dir: Path) -> None:
    assert detect(dump_dir) is True
    adapter = detect_format(dump_dir)
    assert adapter is not None
    assert adapter.name == "asi_arch"


def test_detect_rejects_unrelated_dir(tmp_path: Path) -> None:
    assert detect(tmp_path) is False
    other = tmp_path / "experiments.jsonl"
    other.write_text('{"foo": "bar"}\n', encoding="utf-8")
    # Missing the characteristic ``index`` and ``parent`` fields.
    assert detect(other.parent) is False


def test_imports_run_envelope(dump_dir: Path) -> None:
    events = list(import_asi_arch(dump_dir))
    assert events
    assert events[0].event_kind == "run_start"
    assert events[-1].event_kind == "run_end"


def test_event_kind_counts(dump_dir: Path) -> None:
    """30 experiments — each gets an Individual + Fitness; 29 of them (all
    except the root) get an Operator. Roughly a third are analyst records,
    which also produce a Review."""
    events = list(import_asi_arch(dump_dir))
    counts = Counter(e.event_kind for e in events)
    assert counts["individual"] == 30
    assert counts["operator"] == 29  # 30 records - 1 root
    assert counts["fitness"] == 30
    assert counts["review"] >= 1
    assert counts["run_start"] == 1
    assert counts["run_end"] == 1


def test_streams_split_per_agent(dump_dir: Path) -> None:
    events = list(import_asi_arch(dump_dir))
    streams = {ev.stream_id for ev in events if ev.stream_id is not None}
    # The fixture rotates through researcher/engineer/analyst.
    assert {"agent-researcher", "agent-engineer", "agent-analyst"}.issubset(streams)


def test_lineage_resolves_parent_indices(dump_dir: Path) -> None:
    events = list(import_asi_arch(dump_dir))
    individuals = [e for e in events if e.event_kind == "individual"]
    seeds = [e for e in individuals if getattr(e.payload, "is_seed", False)]
    assert len(seeds) == 1  # only index=1 (root)
    # Every non-seed payload's parent_ids points at an earlier asi-* id.
    for ev in individuals[1:]:
        parents = ev.payload.parent_ids  # type: ignore[union-attr]
        assert len(parents) == 1
        assert parents[0].startswith("asi-")


def test_every_event_validates_against_schema(dump_dir: Path) -> None:
    for ev in import_asi_arch(dump_dir):
        EVENT_ADAPTER.validate_python(ev.model_dump())


def test_explicit_run_id_is_honored(dump_dir: Path) -> None:
    events = list(import_asi_arch(dump_dir, run_id="custom-asi-run"))
    assert {e.run_id for e in events} == {"custom-asi-run"}


def test_registry_includes_asi_arch() -> None:
    names = {a.name for a in REGISTRY}
    assert "asi_arch" in names
