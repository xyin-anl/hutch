"""Tests for the schema docs generator and the committed copy."""

from __future__ import annotations

from pathlib import Path

from hutch.schema._docgen import render_markdown

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_MD = REPO_ROOT / "docs" / "schema.md"


def test_committed_schema_md_matches_generator() -> None:
    """If you change the schema, regenerate `docs/schema.md`.

    Run::

        python -m hutch.schema._docgen

    from inside ``hutch-py/`` and re-commit the result.
    """
    generated = render_markdown()
    committed = SCHEMA_MD.read_text(encoding="utf-8")
    assert generated == committed, (
        "docs/schema.md is out of sync with the schema. "
        "Run `python -m hutch.schema._docgen` and re-commit."
    )


def test_generated_doc_lists_every_event_kind() -> None:
    """Sanity: every event_kind appears in the generated markdown."""
    from hutch.schema.types import ALL_KINDS

    generated = render_markdown()
    for kind in ALL_KINDS:
        assert f'event_kind = "{kind}"' in generated, f"missing kind {kind}"
