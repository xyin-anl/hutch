# 05 — MAP-Elites (toy)

A small MAP-Elites loop on a toy 2D fitness landscape, exercising the full
quality-diversity surface of Hutch's schema:

- `IndividualEvent` — every sample gets one
- `OperatorEvent` (`mutate`) — every non-seed has a parent operator
- `FitnessEvent` — single objective, scaled to [0, 1]
- `DescriptorEvent` — 2D coordinates placed into a 16×16 grid

The Archive view in the dashboard reads `descriptor` events and renders the
grid with cells colored by best composite fitness.

## Running

```bash
# Embedded mode:
HUTCH_DB_PATH=/tmp/example05.duckdb python run.py

# Or with a live daemon:
hutch serve --db /tmp/example05.duckdb &
python run.py
```

Open <http://localhost:7777>, click into the run, and switch to the **Archive**
tab.

## What you should see

- A 16×16 grid with around 100–125 cells filled (out of 256), depending on
  the random seed. Coverage ≈ 49%.
- Yellow patches near the centre-right of the grid (the smooth bowl peaks
  near `(0.6, 0.6)` in descriptor space).
- Hover any filled cell to see the individual id and its exact fitness.
- The Phylogeny view shows a flat sea of seeds with mutation chains
  branching off them.

## Compared to example 02

Example 02 (OpenEvolve) uses the *adapter* path — events are imported from
an existing checkpoint. Example 05 uses the *SDK* path directly: `h.start_run`,
`h.log_individual`, `h.log_descriptor`. Both produce the same canonical
events and feed the same dashboard.

For the **skill** path (LLM-driven loop following `SKILL.md`), see
`hutch-skill/tests/test_skill_eval.py`.
