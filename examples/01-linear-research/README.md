# 01 — Linear research loop

A tiny `propose_hypothesis → evaluate → log_claim` loop using the Hutch SDK
directly. Validates that the canonical event model and the dashboard work
correctly even when the lineage is a single chain (fanout 1).

## What it shows

- The full §6 SDK surface (`start_run`, `log_individual`, `log_operator`,
  `log_fitness`, `log_claim`, `log_evidence`, `end_run`) in ~50 lines.
- The schema's permissiveness about evolutionary structure — there are no
  islands, no MAP-Elites grids, and the dashboard still renders correctly.
- The two SDK transports: embedded (writes to a DuckDB file directly) and
  daemon (POSTs to `hutch serve`).

## Running

```bash
# Option A: no daemon, write directly to a DuckDB file
HUTCH_DB_PATH=$PWD/example01.duckdb python run.py

# Option B: against a running daemon
hutch serve --db $PWD/example01.duckdb &
python run.py        # SDK posts to http://127.0.0.1:7777 by default
```

You should see ~27 events emitted (the loop also exercises the
Evidence Graph). Open the dashboard at <http://localhost:7777> and
the run shows up with the "linear" system-kind badge; the Phylogeny
collapses to a vertical chain, Population trajectory is a single
line, Objectives → Best so far shows two staircases (`plausibility`
↑ and `eval_seconds` ↓).

For programmatic access, query the daemon directly:

```bash
curl http://127.0.0.1:7777/runs                # list runs
curl http://127.0.0.1:7777/runs/<run_id>       # run summary
curl http://127.0.0.1:7777/runs/<run_id>/individuals
curl http://127.0.0.1:7777/runs/<run_id>/fitness
```

## Coverage

| Schema concept | Used here |
|---|---|
| Run start / end | ✅ |
| Individual (linear chain, fanout 1) | ✅ |
| Operator (`refine`) | ✅ |
| Fitness (multi-metric) | ✅ |
| Claim + Evidence | ✅ |
| Population / Archive / Objectives | (not used — these are evolutionary; see example 05) |
| Self-modification | (not used — see example 04) |
| Tree expansion | (not used — see example 03) |

## Integration test

[`hutch-py/tests/test_integration.py`][int] runs an abbreviated version
of this script against a real `hutch serve` subprocess and asserts the
daemon's read endpoints return what the SDK wrote.

[int]: ../../hutch-py/tests/test_integration.py
