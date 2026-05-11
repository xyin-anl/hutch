"""Synthetic DGM-style self-improvement run for example 04.

Generates a small ``output_dgm/`` tree on disk and imports it via the
canonical adapter. Lights up the dashboard's Self-Mod Audit view without
needing to run the real DGM (which trains agents against SWE-bench and
takes hours).

For the real-DGM walkthrough, clone https://github.com/jennyzzt/dgm and
run a small number of generations, then::

    hutch import path/to/output_dgm/

Usage::

    HUTCH_DB_PATH=/tmp/example04.duckdb python run_synthetic.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hutch._fixtures.dgm import make_dgm_run
from hutch.adapters.dgm import import_dgm
from hutch.sdk import SDKConfig, configure
from hutch.sdk._state import state


def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="hutch-example-04-"))
    run_path = make_dgm_run(workdir, seed=29, generations=5)
    print(f"generated DGM run at {run_path}")

    cfg = SDKConfig.from_env()
    cfg.strict = True
    configure(cfg)

    transport = state().transport
    count = 0
    for event in import_dgm(
        run_path, run_id="dgm-self-improvement-demo", project="hutch-examples"
    ):
        transport.send(event)
        count += 1
    print(f"imported {count} events from {run_path}")


if __name__ == "__main__":
    main()
