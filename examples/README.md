# The Hutch examples

Seven runnable end-to-end demos covering the system kinds Hutch models.
Each subdirectory has its own README explaining what the example shows
and how to run it.

| Directory | Demonstrates | Entry point |
|---|---|---|
| [`01-linear-research`](01-linear-research)             | A 5-step `propose → evaluate → claim` loop using the SDK directly. Produces a vertical Phylogeny chain, `linear` system-kind badge, two-objective Pareto trade-off (plausibility ↑ × eval_seconds ↓), and a populated Evidence Graph. | `run.py` |
| [`02-openevolve-circle-packing`](02-openevolve-circle-packing) | Multi-island, multi-objective evolutionary search via the `openevolve` adapter. Lights up Phylogeny / Population / Archive / Objectives / Operator-trace. | `run_synthetic.py` |
| [`03-aide-tree-search`](03-aide-tree-search)           | AIDE-style MCTS tree search via the `aide` adapter. Lights up the Tree Search view with visit counts and value estimates. | `run_synthetic.py` |
| [`04-dgm-self-improvement`](04-dgm-self-improvement)   | DGM-style agent self-modification via the `dgm` adapter. Lights up the Self-Mod Audit table with overseer verdicts and score deltas. | `run_synthetic.py` |
| [`05-map-elites-toy`](05-map-elites-toy)               | Quality-Diversity / MAP-Elites loop using the SDK directly. Lights up the Archive heatmap with descriptor coordinates + cell coverage. | `run.py` |
| [`06-evolutionary-operators`](06-evolutionary-operators) | Explicit `mutate` / `crossover` / `select` operator cadence on a multi-island synthetic loop. Drives the Operators tab's per-kind breakdown + cadence chart. | `run.py` |
| [`07-steering-demo`](07-steering-demo)                 | Live steering write-back: a long-running loop that polls the steering channel and obeys `pause_run` / `cancel_individual` / `inject_hint` / `fork_from` issued from the dashboard. | `run.py` |

## Running any example

Each example accepts the SDK's standard transport selection. With a
running daemon (recommended for the live dashboard):

```bash
hutch serve --db /tmp/hutch.duckdb &
HUTCH_DAEMON_URL=http://127.0.0.1:7777 python examples/01-linear-research/run.py
```

…or write directly to a DuckDB file in embedded mode:

```bash
HUTCH_DB_PATH=/tmp/hutch.duckdb python examples/01-linear-research/run.py
```

Examples 02–04 use the `hutch._fixtures` helpers (shipped with the
wheel) to build a synthetic on-disk dump in the shape each adapter
expects; examples 01 / 05 / 06 / 07 use the SDK directly. The
system-kind badge shown on each run's Overview is auto-inferred from
the operator kinds that landed in DuckDB.
