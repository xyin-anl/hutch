"""Synthetic OpenEvolve-style run for example 02.

Generates a small OpenEvolve-shaped checkpoint on disk and imports it into
Hutch through the canonical adapter. Lets you exercise the dashboard with
multi-island, multi-objective evolutionary data without waiting hours for
a real circle-packing run to finish.

For the real OpenEvolve walkthrough (with actual circle-packing programs),
see the OpenEvolve repository at https://github.com/codelion/openevolve and
run::

    hutch import path/to/openevolve_output/checkpoints/checkpoint_100/

against any of their checkpoint directories.

Usage::

    # Embedded mode (no daemon required):
    HUTCH_DB_PATH=/tmp/example02.duckdb python run_synthetic.py

    # Or against a running daemon (recommended for the live dashboard):
    hutch serve --db /tmp/example02.duckdb &
    python run_synthetic.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hutch._fixtures.openevolve import make_checkpoint
from hutch.adapters.openevolve import import_openevolve
from hutch.sdk import SDKConfig, configure
from hutch.sdk._state import state


def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="hutch-example-02-"))
    checkpoint = workdir / "circle_packing_checkpoint"
    print(f"generating synthetic checkpoint at {checkpoint}")
    make_checkpoint(
        checkpoint,
        seed=11,
        num_islands=6,
        programs_per_island=12,
        crossover_probability=0.3,
        objectives=("sum_radii", "compile_ms"),
    )

    cfg = SDKConfig.from_env()
    cfg.strict = True
    configure(cfg)

    transport = state().transport
    count = 0
    for event in import_openevolve(
        checkpoint, run_id="openevolve-circle-packing-demo", project="hutch-examples"
    ):
        transport.send(event)
        count += 1
    print(f"imported {count} events from {checkpoint}")
    print(
        "open the daemon dashboard (default http://127.0.0.1:7777) "
        "and look for the run named 'openevolve-circle-packing-demo'."
    )


if __name__ == "__main__":
    main()
