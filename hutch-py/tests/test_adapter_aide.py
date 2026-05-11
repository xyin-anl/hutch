"""Tests for the AIDE adapter."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from hutch._fixtures.aide import make_aide_journal
from hutch.adapters import detect_format
from hutch.adapters.aide import detect, import_aide


@pytest.fixture
def aide_journal(tmp_path: Path) -> Path:
    journal_path = make_aide_journal(tmp_path / "aide_run")
    return journal_path.parent


def test_detect_recognizes_journal(aide_journal: Path) -> None:
    assert detect(aide_journal) is True
    adapter = detect_format(aide_journal)
    assert adapter is not None
    assert adapter.name == "aide"


def test_detect_recognizes_bare_journal_file(aide_journal: Path) -> None:
    assert detect(aide_journal / "journal.json") is True


def test_detect_rejects_unrelated_json(tmp_path: Path) -> None:
    other = tmp_path / "other.json"
    other.write_text('{"nodes": "not-a-list"}')
    assert detect(other) is False


def test_imports_run_envelope_and_nodes(aide_journal: Path) -> None:
    events = list(import_aide(aide_journal))
    assert events[0].event_kind == "run_start"
    assert events[-1].event_kind == "run_end"
    counts = Counter(e.event_kind for e in events)
    assert counts["individual"] >= 1
    # tree_expansion + operator emitted once per non-root node.
    assert counts["tree_expansion"] == counts["individual"] - 1
    assert counts["operator"] == counts["tree_expansion"]
    # Every non-buggy node yields a fitness with metric; buggy nodes still
    # yield a fitness with invalid_reason set.
    assert counts["fitness"] >= counts["individual"] - 1


def test_root_is_seed_others_have_parents(aide_journal: Path) -> None:
    events = list(import_aide(aide_journal))
    individuals = [e for e in events if e.event_kind == "individual"]
    seeds = [e for e in individuals if getattr(e.payload, "is_seed", False)]
    assert len(seeds) == 1
    non_seeds = [e for e in individuals if not getattr(e.payload, "is_seed", False)]
    for ns in non_seeds:
        assert ns.payload.parent_ids  # type: ignore[union-attr]


def test_buggy_nodes_get_invalid_fitness(aide_journal: Path) -> None:
    events = list(import_aide(aide_journal))
    buggy_fits = [
        e
        for e in events
        if e.event_kind == "fitness" and getattr(e.payload, "invalid_reason", None) == "buggy"
    ]
    # At least *some* buggy nodes given the fixture's 18% bug rate.
    assert buggy_fits, "fixture should produce some buggy nodes"


def test_tree_expansion_value_estimate(aide_journal: Path) -> None:
    events = list(import_aide(aide_journal))
    expansions = [e for e in events if e.event_kind == "tree_expansion"]
    assert expansions
    # value_estimate is None for buggy children, set for good ones.
    has_value = [e for e in expansions if getattr(e.payload, "value_estimate", None) is not None]
    assert has_value


def test_rejects_directory_without_journal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="AIDE"):
        list(import_aide(tmp_path / "missing"))
