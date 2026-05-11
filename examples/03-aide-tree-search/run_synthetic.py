"""Synthetic AIDE-style tree-search run for example 03.

Generates a small AIDE journal on disk and imports it via the canonical
adapter so the dashboard's Tree-Search view lights up without needing to
run actual ML experiments.

For the real-AIDE walkthrough, run `aide` from
https://github.com/WecoAI/aideml on a toy task and import the resulting
``logs/<id>/journal.json`` with::

    hutch import logs/<id>/

Usage::

    HUTCH_DB_PATH=/tmp/example03.duckdb python run_synthetic.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hutch._fixtures.aide import make_aide_journal
from hutch.adapters.aide import import_aide
from hutch.sdk import SDKConfig, configure
from hutch.sdk._state import state


def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="hutch-example-03-"))
    journal_path = make_aide_journal(workdir, seed=23, expansions=28)
    print(f"generated AIDE journal at {journal_path}")

    cfg = SDKConfig.from_env()
    cfg.strict = True
    configure(cfg)

    transport = state().transport
    count = 0
    for event in import_aide(
        journal_path, run_id="aide-tree-search-demo", project="hutch-examples"
    ):
        transport.send(event)
        count += 1
    print(f"imported {count} events from {journal_path}")


if __name__ == "__main__":
    main()
