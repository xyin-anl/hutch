"""Tests for the DGM adapter."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from hutch._fixtures.dgm import make_dgm_run
from hutch.adapters import detect_format
from hutch.adapters.dgm import detect, import_dgm


@pytest.fixture
def dgm_run(tmp_path: Path) -> Path:
    return make_dgm_run(tmp_path / "dgm_run")


def test_detect_recognizes_dgm_run(dgm_run: Path) -> None:
    assert detect(dgm_run) is True
    # Detected by the registry.
    adapter = detect_format(dgm_run)
    assert adapter is not None
    assert adapter.name == "dgm"
    # Make sure it doesn't pick up a random empty dir.
    assert detect_format(dgm_run.parent / "empty") is None


def test_detect_rejects_arbitrary_directory(tmp_path: Path) -> None:
    assert detect(tmp_path) is False


def test_imports_run_envelope_and_agents(dgm_run: Path) -> None:
    events = list(import_dgm(dgm_run))
    assert events
    assert events[0].event_kind == "run_start"
    assert events[-1].event_kind == "run_end"
    counts = Counter(e.event_kind for e in events)
    # 1 seed + 4 generations × (2 parents max × 2 children) bounded above; the
    # exact count depends on the rng but the ratios hold.
    assert counts["individual"] >= 5
    assert counts["self_mod"] == counts["individual"] - 1  # one per non-seed
    assert counts["operator"] == counts["self_mod"]
    assert counts["fitness"] == counts["individual"]  # every agent has a score


def test_self_mod_carries_before_after_scores(dgm_run: Path) -> None:
    events = list(import_dgm(dgm_run))
    self_mods = [e for e in events if e.event_kind == "self_mod"]
    assert self_mods
    for sm in self_mods:
        # parent score is set for every non-seed once we've walked the chain.
        assert sm.payload.parent_agent_id  # type: ignore[union-attr]
        assert sm.payload.child_agent_id  # type: ignore[union-attr]
        assert sm.payload.score_after is not None  # type: ignore[union-attr]


def test_seed_agent_has_no_parents(dgm_run: Path) -> None:
    events = list(import_dgm(dgm_run))
    seeds = [
        e for e in events if e.event_kind == "individual" and getattr(e.payload, "is_seed", False)
    ]
    assert len(seeds) == 1
    assert seeds[0].payload.parent_ids == []  # type: ignore[union-attr]


def test_overseer_verdict_normalized(dgm_run: Path) -> None:
    events = list(import_dgm(dgm_run))
    verdicts = {
        e.payload.overseer_verdict  # type: ignore[union-attr]
        for e in events
        if e.event_kind == "self_mod"
    }
    assert verdicts.issubset({"accepted", "rejected", "pending"})


def test_rejects_non_dgm_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DGM"):
        list(import_dgm(tmp_path / "nope"))
