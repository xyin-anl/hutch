# Adapters

An adapter converts one autoresearch system's on-disk checkpoint into
Hutch's canonical event stream. Eleven ship in this release.

| Adapter | What it reads | Key event kinds emitted |
|---|---|---|
| `openevolve` | OpenEvolve checkpoint dirs (`metadata.json` + `programs/<id>.json`) | individual, operator, fitness, descriptor |
| `aide` | AIDE search-tree journals (`tree.json` or `journal.json`) | individual, operator, fitness, tree_expansion |
| `dgm` | DGM `dgm_metadata.jsonl` plus `output_dgm/<agent_id>/` dirs | individual, self_mod, fitness |
| `qdax` | QDax `repertoire.json` JSON exports | individual, fitness, descriptor, archive_snapshot |
| `asi_arch` | ASI-ARCH MongoDB dumps (`experiments.jsonl`) | individual, operator, fitness, review |
| `funsearch` | FunSearch `programs.jsonl` | individual, operator, fitness |
| `coral` | CORAL multi-agent run dirs (`iterations.jsonl`, heartbeats, memory) | individual, operator, fitness, steering_command, archive_snapshot |
| `poet` | POET `generations.jsonl` (coevolved env-agent pairs) | individual (env + agent), operator, fitness, migration |
| `cvevolve` | CVEvolve session roots or `history/search_history.sqlite` databases | individual, operator, fitness, stream_event |
| `ptychi_evolve` | ptychi-evolve `rounds.jsonl` (X-ray ptychography reconstruction search) | individual, operator, fitness |
| `shinka_evolve` | ShinkaEvolve `candidates.jsonl` plus `meta_mutations.jsonl` | individual (incl. skill for meta-mutations), operator (incl. meta_mutate), fitness |

For anything not in the table, use `hutch import --llm`. It reads a
file or directory of unknown records, asks an LLM to write a
`to_canonical(record)` function, validates the output in a constrained
subprocess, caches the working adapter, and emits canonical events. The
trust boundary is documented in [security.md](security.md#llm-importer).

## CLI

```bash
hutch import ./checkpoint                 # auto-detect format from the registry
hutch watch ./checkpoint                  # keep polling and update the dashboard live
hutch import --watch ./checkpoint         # same live mode through the import command
hutch import ./checkpoint --format aide   # force a specific adapter
hutch import ./cvevolve-run/history/search_history.sqlite --format cvevolve
hutch watch ./cvevolve-run --format cvevolve --include-audit
hutch import ./novel-format --llm         # fall back to the LLM-assisted importer
```

Auto-detection runs each registered adapter's `detect(path)` in order
and picks the first match.

## Writing a new adapter

Each adapter at `hutch-py/src/hutch/adapters/<system>.py` exposes:

```python
def detect(path: Path) -> bool:
    """Cheap probe. Return True for paths this adapter can handle."""

def import_<system>(
    path: str | Path,
    *,
    run_id: str | None = None,
    project: str | None = None,
    finalize: bool = True,
) -> Iterator[AnyEvent]:
    """Yield canonical events. Skip what you can't recover rather than
    fabricating fields. When finalize=False, suppress run_end for watch mode."""

def is_complete(path: Path) -> bool | None:
    """Return True for explicit completion, False for still active, or None
    when the format has no explicit terminal marker."""
```

Then add an entry to `REGISTRY` in
`hutch-py/src/hutch/adapters/__init__.py`:

```python
Adapter(
    name="myformat",
    detect=myformat.detect,
    importer=myformat.import_myformat,
    is_complete=myformat.is_complete,
    completion_policy="explicit",  # or "idle"
),
```

A test under `hutch-py/tests/test_adapter_<system>.py` should:

1. Generate a small synthetic fixture in a temp dir.
2. Assert that event-kind counts match the fixture.
3. Round-trip every emitted event through
   `EVENT_ADAPTER.validate_python()` to catch schema drift.
4. Verify `detect()` accepts the fixture and rejects an unrelated dir.
5. Verify `finalize=False` suppresses `run_end` and registry-derived event
   IDs are stable across repeated imports.

## Permissive by default

All adapters render gracefully on partial data. If the source format
does not carry generation indices or descriptor dimensions, the adapter
omits the optional fields rather than guessing. The dashboard's views
tolerate holes in the data: the Phylogeny falls back to a chain when
there are no crossovers, the Archive tab is hidden when there are no
descriptors, and so on.

## Per-adapter notes

### OpenEvolve

Reads the published checkpoint format: a `metadata.json` listing islands
and feature maps, and one `programs/<program_id>.json` per individual.
OpenEvolve does not preserve the original mutation or crossover label,
so operators are emitted as `kind="refine"` (the safest canonical fit).
Cell-key strings like `"(34, 71)"` are parsed into descriptor
coordinates with a regex; if parsing fails, the cell-key string is
preserved as `cell_id`.

### AIDE

AIDE's search-tree dumps are nested JSON. The adapter reads the journal
file directly and emits one `IndividualEvent` (`kind="experiment_plan"`)
per node, plus a `TreeExpansionEvent` carrying visit counts and value
estimates. Buggy or non-runnable nodes get a `FitnessEvent` with
`invalid_reason` populated, so the dashboard counts the failure
honestly.

### DGM

DGM keeps a JSONL log of agent generations and on-disk diffs of each
self-modification. The adapter pairs the parent and child agents into a
`SelfModEvent` carrying the overseer verdict and the
benchmark-score-before / benchmark-score-after pair. The Self-Mod Audit
view is the primary surface for these.

### QDax

The adapter accepts a JSON export of a QDax `Repertoire` rather than a
live JAX object, so it can stay free of a JAX or NumPy dependency.
Two-line conversion from a live repertoire:

```python
import json
json.dump({
    "centroids":   r.centroids.tolist(),
    "fitnesses":   r.fitnesses.tolist(),
    "descriptors": r.descriptors.tolist(),
    "metadata":    {"descriptor_dims": [...], "objective_name": "fitness"},
}, open("repertoire.json", "w"))
```

The adapter emits one `IndividualEvent` plus `FitnessEvent` plus
`DescriptorEvent` per filled cell, plus one `ArchiveSnapshotEvent` per
run summarizing coverage, qd_score, and max_fitness.

### ASI-ARCH

ASI-ARCH stores experiment records in MongoDB. The adapter reads the
natural `mongoexport` output: a JSONL file with one record per line, or
a single JSON file containing an array. Records carry an `index` (a
stable integer id) and a `parent` index (`0` or `null` means root). The
agent role (`researcher`, `engineer`, or `analyst`) lands as the
envelope's `stream_id`, so the Operator-trace swimlane lays the events
out per role. The analyst's free-form `analysis` text becomes a
`ReviewEvent`.

### FunSearch

A JSONL dump of one program record per line:
`{id, code, score, parents, island_id, generation, evaluator}`.
Mutation versus crossover is inferred from the length of the `parents`
array (1 means mutate, 2 or more means crossover). Island assignment
becomes the envelope's `stream_id`, so the Operator-trace swimlane lays
events out per island. The `evaluator` field becomes the canonical
`evaluator_id`, so the dashboard can filter per benchmark (cap-set,
online bin packing, etc.).

### CORAL

Multi-agent runs map naturally onto Hutch's structural pieces:

- **Agents become streams.** Every CORAL agent (Researcher, Engineer,
  Analyst, etc.) gets its own `stream_id` swimlane.
- **Heartbeats become `steering_command` events.** CORAL's intervention
  mechanism mirrors directly onto Hutch's command vocabulary
  (`pause_run`, `cancel_individual`, `inject_hint`, etc.), so the
  Steering panel and audit trail surface them.
- **Shared memory becomes `archive_snapshot` events.** Periodic
  snapshots of the cross-agent memory show up in the Archive view's
  coverage curve.

Format: `iterations.jsonl`, optionally accompanied by
`heartbeats.jsonl` and `memory_snapshots.jsonl`.

### POET

Coevolution of environments and agents. Each generation records
`environments`, `pairs` (env-agent evaluations), and `transfers`
(agents moving between envs). The adapter emits each environment as an
`IndividualEvent(kind="environment")`, each agent as
`IndividualEvent(kind="agent")` (disjoint id spaces), the pair score as
a `FitnessEvent` with `evaluator_id = env_id` so the dashboard can
filter agent fitness per environment, and transfers as
`MigrationEvent(trigger="poet_transfer")`. Agents inherit
`island_id = env_id`, so the Phylogeny groups by environment.

### CVEvolve

CVEvolve supports both one-shot import and live polling. The adapter
accepts either a session root containing `history/search_history.sqlite`
or a direct path to that SQLite file. Detection requires the expected
CVEvolve history tables (`metric_definitions`, `rounds`, `candidates`,
`metrics`, `evaluation_metrics`, and `session_state`), so unrelated
SQLite files are ignored. In watch mode, completion is explicit:
`hutch watch <session>` exits when `session_state.phase = "completed"`.

Candidates become `IndividualEvent(kind="program")` records with code
referenced by `file://` URI when the candidate artifact exists. Baseline
candidates are seeds; non-baseline CVEvolve actions become operators:
`generate` maps to `propose`, `tune` maps to `refine`, one-parent
`evolve` maps to `mutate`, and crossover strategy or multi-parent
`evolve` maps to `crossover`. Metrics and holdout-test metrics become
`FitnessEvent` records. CVEvolve `minimize` metric definitions are
declared as Hutch `lower` score directions and their composites are
negated, keeping the dashboard's higher-is-better aggregate convention.
Candidate failures are retained as `stream_event` audit rows. Message
and tool-call audit databases are intentionally left out of the default
adapter to avoid flooding the event store. Use `--include-audit` with
`hutch import`, `hutch import --watch`, or `hutch watch` to import
`history/messages.sqlite` and legacy `history/tool_calls.sqlite` as
`cvevolve_message` / `cvevolve_tool_call` stream events. The dashboard
shows those rows in the CVEvolve Audit tab when present. Audit event text
is capped by `--audit-max-text-chars` (default `8000`; `0` disables
truncation).

When audit import is enabled the adapter declares the `audit` run
capability so the dashboard can show the CVEvolve Audit tab. Watch mode
declares `live_updates`; offline adapter imports do not declare
`steering`.

### ptychi-evolve

A JSONL-per-round dump of an X-ray ptychography reconstruction search.
Each round contains a population of candidate reconstruction algorithms
with `{nrmse, time_s}` metrics. Both metrics are lower-better, so the
adapter sets the canonical `composite` to `-nrmse` to keep the
dashboard's higher-is-better axis pointing the right way.

### ShinkaEvolve

Two JSONL files: `candidates.jsonl` (the program or prompt search) and
`meta_mutations.jsonl` (the search procedure itself, evolved via
`meta_mutate`). Meta-mutations land as `IndividualEvent(kind="skill")`
plus `OperatorEvent(kind="meta_mutate")`. That is the schema's intended
shape for "the procedure searching for the procedure."

## Beyond this release

One additional system would be a natural fit, **AlphaEvolve**, but it
is closed-source with no public checkpoint format to target. Until that
changes, `hutch import --llm` covers the long tail.
