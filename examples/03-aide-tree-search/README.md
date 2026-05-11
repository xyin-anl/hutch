# 03 — AIDE tree search

Demonstrates the AIDE adapter end-to-end: takes an AIDE journal (or a
synthetic stand-in with the same shape) and lights up the Phylogeny and
**Tree Search** views.

## What it shows

- `hutch import <path-to-journal>` auto-detects the AIDE format.
- Tree Search view renders the search tree with visit counts, value
  estimates, and a buggy-node indicator (dark red).
- Phylogeny view shows the same lineage as a force-directed graph.
- The Self-Mod Audit and Archive tabs are correctly hidden — AIDE
  doesn't emit those event kinds.

## Running

### Synthetic (recommended for first-run)

```bash
hutch serve --db /tmp/example03.duckdb &
python run_synthetic.py
# visit http://127.0.0.1:7777, click into the run, switch to Tree Search
```

### Real AIDE journal

```bash
git clone https://github.com/WecoAI/aideml
cd aideml
pip install -e .
aide --task "predict survival on titanic" --steps 30
# the journal lands in logs/<id>/journal.json
hutch import logs/<id>/journal.json
```

## Coverage

| Schema concept | Used here |
|---|---|
| Run start / end | ✅ |
| Individual (`experiment_plan`) | ✅ |
| Operator (`tree_expand`) | ✅ |
| TreeExpansion | ✅ |
| Fitness (single objective; `invalid_reason="buggy"` for failed nodes) | ✅ |
