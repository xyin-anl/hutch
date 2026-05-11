# 04 — DGM self-improvement

Demonstrates the DGM adapter end-to-end: takes a DGM run directory (or a
synthetic stand-in with the same shape) and lights up the Phylogeny and
**Self-Mod Audit** views.

## What it shows

- `hutch import <output_dgm>` auto-detects the DGM format.
- Self-Mod Audit shows every parent → child agent edit, the proposal
  text, the overseer verdict (accepted / rejected), and the before/after
  benchmark deltas.
- Cumulative Δ score across accepted modifications.
- Phylogeny shows the agent-version tree.
- The Tree Search and Archive tabs are correctly hidden.

## Running

### Synthetic (recommended for first-run)

```bash
hutch serve --db /tmp/example04.duckdb &
python run_synthetic.py
# visit http://127.0.0.1:7777, click into the run, switch to Self-Mod Audit
```

### Real DGM run

```bash
git clone https://github.com/jennyzzt/dgm
cd dgm
# follow their README to train a few generations on SWE-bench-mini
python DGM_outer.py --num_generations 4
hutch import output_dgm/
```

## Coverage

| Schema concept | Used here |
|---|---|
| Run start / end | ✅ |
| Individual (`agent`) | ✅ |
| Operator (`self_modify`) | ✅ |
| SelfMod (proposal, overseer verdict, score before/after) | ✅ |
| Fitness (`benchmark`, multi-metric: accuracy_score + overall_performance) | ✅ |
