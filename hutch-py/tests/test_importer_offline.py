"""Offline tests for the LLM-assisted importer — exercise the bits that
don't actually call out to a model.

The end-to-end LLM eval lives in :mod:`tests.test_llm_importer`.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from hutch.importer import (
    detect_structure,
    execute_adapter,
    fingerprint_for,
)
from hutch.importer.cache import CachedAdapter, load, store
from hutch.importer.generate import build_user_prompt
from tests._foreign_format_fixture import make_foreign_run


def test_detect_structure_finds_records_and_metadata(tmp_path: Path) -> None:
    fixture = make_foreign_run(tmp_path / "run", seed=3, num_trials=6)
    sample = detect_structure(fixture)
    assert sample.sample_records, "should sample at least one record"
    assert sample.metadata is not None
    assert sample.readme is not None
    assert any("trials/" in p or "trial-" in p for p in sample.file_listing)


def test_detect_structure_accepts_single_json_file(tmp_path: Path) -> None:
    f = tmp_path / "file.json"
    f.write_text('{"id":"i1","score":1.0}', encoding="utf-8")
    sample = detect_structure(f)
    assert sample.sample_records == [{"id": "i1", "score": 1.0}]
    assert sample.file_listing == ["file.json"]


def test_prompt_redacts_common_secret_fields(tmp_path: Path) -> None:
    f = tmp_path / "records.jsonl"
    f.write_text('{"id":"i1","api_key":"sk-secret"}\n', encoding="utf-8")
    sample = detect_structure(f)
    prompt = build_user_prompt(sample)
    assert "sk-secret" not in prompt
    assert "[REDACTED]" in prompt


def test_execute_adapter_round_trip() -> None:
    code = textwrap.dedent(
        """
        def to_canonical(record):
            return [
                {
                    "run_id": record["run"],
                    "event_kind": "individual",
                    "payload": {
                        "id": record["id"],
                        "kind": "program",
                        "is_seed": True,
                        "parent_ids": [],
                    },
                }
            ]
        """
    )
    payload = execute_adapter(code, [{"run": "r1", "id": "i1"}, {"run": "r1", "id": "i2"}])
    assert payload["error"] is None
    assert len(payload["results"]) == 2
    for events in payload["results"]:
        assert isinstance(events, list)
        assert events[0]["event_kind"] == "individual"


def test_execute_adapter_handles_runtime_error() -> None:
    code = textwrap.dedent(
        """
        def to_canonical(record):
            return [{"event_kind": "individual", "run_id": "r", "payload": record["missing"]}]
        """
    )
    payload = execute_adapter(code, [{"id": "i"}])
    assert payload["error"] is None
    # The single record errored, so we got back a per-record sentinel.
    assert isinstance(payload["results"][0], dict)
    assert "_error" in payload["results"][0]


def test_execute_adapter_rejects_bad_code() -> None:
    payload = execute_adapter("def not_to_canonical(): pass", [{"id": "x"}])
    assert payload["error"] == "to_canonical not defined"


def test_execute_adapter_rejects_imports_and_open() -> None:
    import_payload = execute_adapter(
        "import os\ndef to_canonical(record): return []", [{"id": "x"}]
    )
    assert "forbidden syntax" in str(import_payload["error"])

    open_payload = execute_adapter(
        "def to_canonical(record):\n    return open('/etc/passwd').read()",
        [{"id": "x"}],
    )
    assert "forbidden name: open" in str(open_payload["error"])


def test_fingerprint_changes_with_prompt() -> None:
    a = fingerprint_for("system A", "user A")
    b = fingerprint_for("system A", "user B")
    c = fingerprint_for("system A", "user A")
    assert a != b
    assert a == c


def test_cache_round_trip(tmp_path: Path) -> None:
    rec = CachedAdapter(
        fingerprint="abc123",
        adapter_code="def to_canonical(r): return []",
        notes="empty adapter",
        coverage=0.0,
        sample_size=0,
        valid_events=0,
        total_events=0,
        created_at_ns=1,
        path="/tmp/run",
        provider="openai",
        model="gpt-4o",
    )
    p = store(rec, root=tmp_path)
    assert p.exists()
    back = load("abc123", root=tmp_path)
    assert back is not None
    assert back.adapter_code == rec.adapter_code
    assert load("missing", root=tmp_path) is None
