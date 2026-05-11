# 02 — OpenEvolve circle packing

Demonstrates the OpenEvolve adapter end-to-end: takes an OpenEvolve
checkpoint (or a synthetic stand-in with the same on-disk format) and
lights up the Phylogeny / Population / Archive / Objectives views with
multi-island, multi-objective data.

## What it shows

- `hutch import <openevolve_checkpoint>` auto-detects the format and emits
  canonical events.
- The Phylogeny view renders multiple islands as separate clusters with
  occasional cross-island edges (crossover events).
- The Population view shows best/median/worst trajectories per generation.
- Fitness coloring on the lineage graph distinguishes the elite individuals.

## Running

### Synthetic (recommended for first-run)

A real OpenEvolve circle-packing run takes hours; the synthetic generator
writes a small checkpoint with the same on-disk shape so you can see the
dashboard immediately.

```bash
hutch serve --db /tmp/example02.duckdb &
python run_synthetic.py
# visit http://127.0.0.1:7777 and click into "openevolve-circle-packing-demo"
```

### Real OpenEvolve checkpoint

```bash
# 1. clone OpenEvolve and run the circle-packing example
git clone https://github.com/codelion/openevolve
cd openevolve
python openevolve-run.py examples/circle_packing/initial_program.py \
  examples/circle_packing/evaluator.py \
  --config examples/circle_packing/config.yaml \
  --iterations 100

# 2. import the checkpoint into Hutch
hutch serve --db /tmp/example02.duckdb &
hutch import openevolve_output/checkpoints/checkpoint_100/
```

## Coverage

| Schema concept | Used here |
|---|---|
| Run start / end | ✅ |
| Individual (multi-island, with parents) | ✅ |
| Operator (`refine`) | ✅ |
| Fitness (multi-objective: `sum_radii`, `compile_ms`) | ✅ |
| Descriptor (MAP-Elites grid coordinates) | ✅ |
| Crossover edges | ✅ (recorded in operator metadata) |

The Archive view + Objectives → Trade-off / Best so far / Distribution
all populate from the descriptor and fitness events emitted here, with
the `sum_radii` ↑ + `compile_ms` ↓ directions declared by the adapter
on `RunStartPayload.score_directions`.
