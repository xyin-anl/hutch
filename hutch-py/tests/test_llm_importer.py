"""End-to-end test for the LLM-assisted importer.

Generates a synthetic foreign format that doesn't match any hand-written
adapter, runs the full pipeline (detect → generate → sandbox-validate →
cache → emit), and asserts the LLM produces an adapter that yields a
non-trivial number of schema-valid events.

Runs only when pytest is invoked with ``--run-llm`` and a provider key is
already present in the environment. The test deliberately does not load
``.env`` so normal local runs cannot accidentally spend provider credits.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

pytestmark = pytest.mark.live_llm


def _require_live_provider() -> None:
    if os.environ.get("OPENAI_API_KEY"):
        pytest.importorskip("openai")
        return
    if os.environ.get("ANTHROPIC_API_KEY"):
        pytest.importorskip("anthropic")
        return
    pytest.skip("OPENAI_API_KEY / ANTHROPIC_API_KEY not set; LLM importer eval is opt-in")


def test_llm_importer_handles_unknown_format(tmp_path: Path) -> None:
    """The LLM-importer should produce ≥80% schema-valid events for the
    synthetic foreign format (full coverage may be lower if the model
    misses some records, which the importer counts honestly)."""
    _require_live_provider()

    from hutch.importer import import_with_llm
    from tests._foreign_format_fixture import make_foreign_run

    fixture = make_foreign_run(tmp_path / "foreign_run", seed=21, num_trials=20)
    cache_dir = tmp_path / "cache"

    result, events = import_with_llm(fixture, cache_dir=cache_dir, use_cache=False)
    consumed = list(events)

    # Sample-set coverage should be high; the model is shown the same
    # records it's about to be evaluated on.
    assert result.sample_total > 0, "no sample events produced"
    assert result.sample_coverage >= 0.8, (
        f"sample coverage too low: {result.sample_coverage:.0%}; "
        f"errors: {result.runtime_errors[:3]}"
    )

    # Full-corpus coverage should also be ≥ 0.8 — the format is uniform
    # so the adapter that worked on the sample should generalize.
    assert result.full_total > 0, "no full-corpus events produced"
    assert result.full_coverage >= 0.8, (
        f"full coverage too low: {result.full_coverage:.0%}; errors: {result.runtime_errors[:3]}"
    )

    # Event mix should include at least one Individual and one Fitness
    # (the records carry both an id and a numeric score).
    kinds = Counter(e.event_kind for e in consumed)
    assert kinds["individual"] >= 1, f"no IndividualEvents emitted; saw {dict(kinds)}"
    assert kinds["fitness"] >= 1, f"no FitnessEvents emitted; saw {dict(kinds)}"

    # The cache file was written.
    cached = list(cache_dir.glob("*.json"))
    assert len(cached) == 1, f"cache should hold one adapter, found {len(cached)}"


def test_llm_importer_uses_cache_on_second_run(tmp_path: Path) -> None:
    """A second invocation against the same fixture should hit the cache
    rather than re-calling the LLM."""
    _require_live_provider()

    from hutch.importer import import_with_llm
    from tests._foreign_format_fixture import make_foreign_run

    fixture = make_foreign_run(tmp_path / "foreign_run", seed=21, num_trials=10)
    cache_dir = tmp_path / "cache"

    first, _ = import_with_llm(fixture, cache_dir=cache_dir, use_cache=False)
    assert first.cache_hit is False

    second, _ = import_with_llm(fixture, cache_dir=cache_dir, use_cache=True)
    assert second.cache_hit is True
    assert second.adapter.fingerprint == first.adapter.fingerprint
