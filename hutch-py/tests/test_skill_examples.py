"""Run each ``hutch-skill/examples/*.py`` against an embedded SDK and validate
that every emitted event is schema-valid.

These tests don't call any LLM — they're a sanity check on our own worked
examples. The real-LLM regression eval lives in :mod:`tests.test_skill_eval`.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

import hutch as h
from hutch.schema import AnyEvent
from hutch.sdk import SDKConfig
from hutch.store import open_db, read_events

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_EXAMPLES_DIR = REPO_ROOT / "hutch-skill" / "examples"


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"skill_examples.{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _all_run_events(db_path: Path) -> list[AnyEvent]:
    conn = open_db(db_path)
    try:
        conn.execute("SELECT DISTINCT run_id FROM events;")
        run_ids = [row[0] for row in conn.fetchall()]
        events: list[AnyEvent] = []
        for run_id in run_ids:
            events.extend(read_events(conn, run_id))
        return events
    finally:
        conn.close()


@pytest.mark.parametrize(
    "filename",
    [
        "01_linear.py",
        "02_evolutionary.py",
        "03_self_improving.py",
        "04_tree_search.py",
        "05_quality_diversity.py",
    ],
)
def test_skill_example_emits_valid_events(filename: str, tmp_path: Path) -> None:
    db_path = tmp_path / f"{Path(filename).stem}.duckdb"
    h.configure(SDKConfig(mode="embedded", db_path=db_path))
    module = _load_module(SKILL_EXAMPLES_DIR / filename)
    module.main()  # type: ignore[attr-defined]

    events = _all_run_events(db_path)
    assert events, f"{filename} produced no events"

    # Schema validation is implicit — read_events round-trips through
    # EVENT_ADAPTER.validate_python, which raises on invalid records. So
    # the assertion is "every event we wrote round-trips".
    counts = Counter(e.event_kind for e in events)
    assert counts["run_start"] >= 1, f"{filename} missing run_start"
    assert counts["run_end"] >= 1, f"{filename} missing run_end"
    assert counts["individual"] >= 1, f"{filename} produced no individuals"


def test_each_example_uses_at_least_one_distinct_operator_kind(tmp_path: Path) -> None:
    """Cross-cutting check: collectively the 5 examples cover the major
    operator kinds we want users to see in the wild."""
    expected_kinds = {
        "01_linear.py": {"refine"},
        "02_evolutionary.py": {"mutate"},  # crossover is probabilistic
        "03_self_improving.py": {"self_modify"},
        "04_tree_search.py": {"tree_expand"},
        "05_quality_diversity.py": {"mutate"},
    }
    for filename, must_include in expected_kinds.items():
        db_path = tmp_path / f"{Path(filename).stem}.duckdb"
        h.configure(SDKConfig(mode="embedded", db_path=db_path))
        module = _load_module(SKILL_EXAMPLES_DIR / filename)
        module.main()  # type: ignore[attr-defined]
        events = _all_run_events(db_path)
        op_kinds = {
            e.payload.kind  # type: ignore[union-attr]
            for e in events
            if e.event_kind == "operator"
        }
        missing = must_include - op_kinds
        assert not missing, f"{filename} did not log {missing}: saw {op_kinds}"
