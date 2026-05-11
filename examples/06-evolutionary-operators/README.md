# 06 — Evolutionary operators (mutate / crossover / select)

A small evolutionary loop that exercises the three classic genetic operators
explicitly so the dashboard can color-code them.

## What it shows

- Each operator kind (`mutate`, `crossover`, `select`) appears in
  Operator-trace with its own color.
- Crossover children have **two** parents in their `parent_ids`, so the
  Phylogeny view renders dashed cross-edges between the parents.
- Overview's system-kind inference picks up `evolutionary` from these
  operator labels (alongside the multi-island indicator already present).

## Why this example exists

Most evolutionary frameworks that ship publicly (OpenEvolve / AlphaEvolve /
ptychi-evolve) don't preserve the original mutation-vs-crossover label in
their on-disk checkpoints — every parent→child edge ends up tagged
generically. That's why our OpenEvolve adapter conservatively emits
`refine` for every operator.

When you instrument your own loop (or have an LLM agent follow
`hutch-skill/SKILL.md`), you get to record the correct labels, and the
dashboard surfaces them.

## Running

```bash
HUTCH_DB_PATH=/tmp/example06.duckdb python run.py
hutch serve --db /tmp/example06.duckdb
# open http://127.0.0.1:7777, click into the run, switch to Operator-trace
```

## Coverage

| Schema concept | Used here |
|---|---|
| Run start / end | ✅ |
| Individual (multi-island, with 1 or 2 parents) | ✅ |
| Operator (`mutate` / `crossover` / `select`) | ✅ |
| Fitness | ✅ |
| Population | ✅ multi-island |
