# The Hutch

[![PyPI](https://img.shields.io/pypi/v/thehutch.svg)](https://pypi.org/p/thehutch)
[![CI](https://github.com/xyin-anl/hutch/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/xyin-anl/hutch/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-xyin--anl.github.io%2Fhutch-blue)](https://xyin-anl.github.io/hutch/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/thehutch.svg)](https://pypi.org/p/thehutch)

> Observability, steering, and provenance for autonomous-research agents.

**The Hutch** is an observability, steering, and provenance dashboard for
autonomous-research agents — covering linear "hypothesis → experiment →
claim" pipelines as well as evolutionary, population-based, and
self-improving systems (AlphaEvolve / OpenEvolve / ShinkaEvolve /
CVEvolve / DGM / SICA / AIDE / ASI-ARCH / FunSearch / POET /
MAP-Elites).

## Status

**v0.1.1 alpha** — schema marked unstable until v1.0.0. The canonical
event schema is **additive-only** from v0.1.0 onward: new optional
fields and new `kind` enum values are fine in any minor release, but
renaming or removing existing fields is a breaking change that requires
a migration. We follow [SemVer](https://semver.org/) on the public
Python API and CLI.

The dashboard, daemon, and SDK are usable today. Eleven hand-tuned
adapters ship in v0.1.1 (OpenEvolve, AIDE, DGM, QDax, ASI-ARCH,
FunSearch, CORAL, POET, CVEvolve, ptychi-evolve, ShinkaEvolve); the
LLM-assisted importer is the long-tail fallback for anything else.

## Quick start

```bash
pip install thehutch     # PyPI distribution name; imports as `hutch`
hutch serve               # → http://localhost:7777
```

That's enough to host the dashboard. To populate it:

**(a) Import an existing run.**

```bash
hutch import ./checkpoints/circle_packing       # autodetect (11 adapters)
hutch watch ./checkpoints/live_run              # poll and update live
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

**(c) Drop the skill into an LLM-driven agent.** Add
`hutch-skill/SKILL.md` to your agent's instruction surface
(`.claude/skills/hutch/`, custom GPT system prompt, Cursor rules, etc.)
and the agent will emit canonical events as it works.

## Design

Hutch collapses every autoresearch system to five abstractions:

| Abstraction | Linear case | Evolutionary case | Self-improvement case |
|---|---|---|---|
| **Individual** | Current hypothesis | A program in the population | The current agent codebase |
| **Operator**   | `refine` / `propose` | `mutate` / `crossover` | `self_modify` |
| **Fitness**    | Validation accuracy | `(sum_radii, compile_ms)` | SWE-Bench score |
| **Lineage**    | A chain | A tree or graph | A tree of agent versions |
| **Archive** *(optional)* | None | MAP-Elites grid | DGM agent archive |

Three distribution layers, all normalizing into the same canonical
event store:

1. **LLM-assisted importer** — `hutch import <path>` against any foreign
   artifact.
2. **Skill-driven SDK** — drop `SKILL.md` into your agent; it makes
   structured tool calls.
3. **Native SDK / OTel** — `import hutch; h.log_individual(...)`
   directly.

**Documentation:** <https://xyin-anl.github.io/hutch/> — concepts, schema, adapters,
steering, integrations, security. See also [`CHANGELOG.md`](CHANGELOG.md).

## Adapters

| Adapter | Reads |
|---|---|
| `openevolve`     | OpenEvolve checkpoint dirs |
| `aide`           | AIDE search-tree journals |
| `dgm`            | DGM agent-archive logs |
| `qdax`           | QDax `Repertoire` JSON exports |
| `asi_arch`       | ASI-ARCH MongoDB dumps |
| `funsearch`      | FunSearch programs.jsonl |
| `coral`          | CORAL multi-agent runs (heartbeats → steering, memory → archive) |
| `poet`           | POET coevolution dumps (environments + agents) |
| `cvevolve`       | CVEvolve session roots or `history/search_history.sqlite`; optional `--include-audit` reads `messages.sqlite` / `tool_calls.sqlite` |
| `ptychi_evolve`  | ptychi-evolve rounds (X-ray ptychography) |
| `shinka_evolve`  | ShinkaEvolve candidates + meta-mutations |
| LLM-assisted     | Anything else (`hutch import --llm <path>`) |

## Steering

The dashboard can be a *control surface* for runs that declare
`capabilities={"steering": True}`. Those agents poll
`hutch.steering.poll()` between iterations; the UI's Steering tab issues
commands (`pause_run`, `cancel_individual`, `fork_from`, `inject_hint`,
`approve_hitl`, …). Imported/offline runs stay read-only. See
[`docs/steering.md`](docs/steering.md).

## Examples

| Path | What it shows |
|---|---|
| [`examples/01-linear-research`](examples/01-linear-research) | Smallest end-to-end loop + Evidence Graph |
| [`examples/02-openevolve-circle-packing`](examples/02-openevolve-circle-packing) | Multi-island evolutionary, MAP-Elites grid |
| [`examples/03-aide-tree-search`](examples/03-aide-tree-search) | AIDE-style tree search |
| [`examples/04-dgm-self-improvement`](examples/04-dgm-self-improvement) | Self-modifying agent with overseer audit |
| [`examples/05-map-elites-toy`](examples/05-map-elites-toy) | Quality-diversity / MAP-Elites |
| [`examples/06-evolutionary-operators`](examples/06-evolutionary-operators) | Mutate / crossover / select cadence |
| [`examples/07-steering-demo`](examples/07-steering-demo) | Live steering: pause / cancel / fork |

## Repository layout

```
hutch-py/      # Python: SDK, daemon, CLI, importer, adapters
hutch-ui/      # Next.js 15 + TypeScript + Tailwind dashboard
hutch-skill/   # The distributable SKILL.md + worked examples
examples/     # End-to-end runnable demos
docs/         # Concepts, schema, distribution, adapters, steering
```

## Contributing

The project is designed so a community member can add a new adapter or
a new view in a couple of hours; PRs welcome.

## License

Apache 2.0. See [LICENSE](LICENSE).
