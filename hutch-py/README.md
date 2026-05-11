# thehutch

[![PyPI](https://img.shields.io/pypi/v/thehutch.svg)](https://pypi.org/p/thehutch)
[![CI](https://github.com/xyin-anl/hutch/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/xyin-anl/hutch/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-xyin--anl.github.io%2Fhutch-blue)](https://xyin-anl.github.io/hutch/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](https://github.com/xyin-anl/hutch/blob/main/LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/thehutch.svg)](https://pypi.org/p/thehutch)

> Observability, steering, and provenance for autonomous-research agents.

`thehutch` is the PyPI distribution for [Hutch](https://github.com/xyin-anl/hutch) —
an observability, steering, and provenance dashboard for autonomous-research
agents. It covers linear "hypothesis → experiment → claim" pipelines as well
as evolutionary, population-based, and self-improving systems
(AlphaEvolve / OpenEvolve / ShinkaEvolve / CVEvolve / DGM / SICA /
AIDE / ASI-ARCH / FunSearch / POET / MAP-Elites).

## Install

```bash
pip install thehutch     # PyPI distribution name; imports as `hutch`
hutch serve               # → http://localhost:7777
```

## Three ways to populate the dashboard

**(a) Import an existing run.** Eleven hand-tuned adapters ship in this
release: OpenEvolve, AIDE, DGM, QDax, ASI-ARCH, FunSearch, CORAL, POET,
CVEvolve, ptychi-evolve, ShinkaEvolve. For anything else, the LLM-assisted
importer asks an LLM to write an adapter on the fly:

```bash
hutch import ./checkpoints/circle_packing       # autodetect (11 adapters)
hutch watch ./checkpoints/live_run              # poll and update live
hutch watch ./cvevolve-run --include-audit      # opt into raw CVEvolve audit logs
hutch import ./novel-format --llm                # LLM-assisted fallback
```

**(b) Instrument a Python loop.**

```python
import hutch as h
h.start_run(name="my-search")
seed = h.log_individual(kind="hypothesis")
h.log_fitness(individual=seed, scores={"plausibility": 0.7})
h.end_run()
```

**(c) Drop the skill into an LLM-driven agent.** See the
[skill](https://github.com/xyin-anl/hutch/tree/main/hutch-skill) — it
makes structured tool calls so any Claude / GPT-4 agent emits canonical
events as it works.

## Steering

The dashboard can be a control surface for runs that declare
`capabilities={"steering": True}`. Those agents poll
`hutch.steering.poll()` between iterations; the UI's Steering tab issues
commands (`pause_run`, `cancel_individual`, `fork_from`, `inject_hint`,
`approve_hitl`, …). Imported/offline runs stay read-only.

## Documentation

- [Concepts](https://github.com/xyin-anl/hutch/blob/main/docs/concepts.md)
- [Schema](https://github.com/xyin-anl/hutch/blob/main/docs/schema.md) (auto-generated)
- [Distribution](https://github.com/xyin-anl/hutch/blob/main/docs/distribution.md)
- [Adapters](https://github.com/xyin-anl/hutch/blob/main/docs/adapters.md)
- [Steering](https://github.com/xyin-anl/hutch/blob/main/docs/steering.md)
- [Security](https://github.com/xyin-anl/hutch/blob/main/docs/security.md)
- [Publication exports](https://github.com/xyin-anl/hutch/blob/main/docs/publication.md)

The schema is **additive-only** between minor releases: new optional
fields and new `kind` enum values are fine; renaming or removing
existing fields is a breaking change.

## License

Apache 2.0.
