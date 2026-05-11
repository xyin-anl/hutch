# The Hutch — Telemetry Skill for Autoresearch Agents

> **Drop this file into your agent's instruction surface** — `.claude/skills/hutch/`,
> the system prompt of a custom GPT, your Cursor rules, etc. The agent reads
> it and learns to emit canonical events that light up the Hutch dashboard
> at `http://localhost:7777`.
>
> Schema reference (auto-generated from the Pydantic models): `docs/schema.md`.
> If anything below conflicts with that file, `docs/schema.md` wins.

## When this applies

Use this skill **whenever you are running a multi-step search, evolutionary,
self-improvement, tree-search, hypothesis-testing, or quality-diversity
loop** — i.e., any process that produces a sequence of candidate objects
(programs, prompts, hypotheses, theorems, agent versions, …) over time.

If you are doing one-shot reasoning with no candidate objects, this skill
does not apply.

## How to log

Two transports, in order of preference:

1. **Native SDK** (preferred when running inside Python):
   ```python
   import hutch as h
   h.start_run(name="my-search", project="my-project")
   h.log_individual(kind="program", parent_ids=["abc"], ...)
   h.end_run()
   ```

2. **HTTP fallback** when the `hutch` package isn't importable:
   POST a single canonical event (or an NDJSON batch) to the running daemon:
   ```http
   POST http://localhost:7777/events
   Content-Type: application/json

   {
     "run_id": "my-run-id",
     "event_kind": "individual",
     "payload": {"id": "ind-123", "kind": "program", "is_seed": true}
   }
   ```

   Every event has the same envelope: `event_id` (auto-generated UUID if
   omitted), `event_kind` (the discriminator), `run_id`, `timestamp_ns`
   (auto-generated if omitted), optional `stream_id` / `worker_id` /
   `span_id` / `trace_id`, and a typed `payload` keyed by `event_kind`.

Always emit one `run_start` at the beginning and one `run_end` at the end.
Pick a stable `run_id` and reuse it for every event in the same loop.

**Multi-stream / multi-island runs:** when your loop has parallel
workers (one researcher + one engineer agent, multi-island
evolutionary search, multiple MCTS workers, etc), set ``stream_id`` on
**every** event from that worker — both Individuals **and** the
Operators that produced them. The dashboard's swimlane view splits
lanes by ``stream_id``, so without it a multi-island run collapses
into one undifferentiated row. A reasonable default for evolutionary
runs is ``stream_id=f"island-{island_id}"`` so islands map directly to
swimlanes.

**Declare metric directions at run_start.** Pass
``score_directions={"my_metric": "higher" | "lower"}`` to
``h.start_run`` for every metric you'll later log under
``log_fitness(scores=...)``. The Pareto frontier, Best-Composite stat,
and any direction-aware view rely on this; without it the dashboard
falls back to a name-based regex heuristic (``cost`` / ``time`` /
``loss`` / ``nrmse`` → lower; everything else → higher) which will get
custom metric names wrong. Declaring is one line and removes ambiguity::

    h.start_run(
        name="my-search",
        score_directions={
            "accuracy":   "higher",   # ↑ better
            "compile_ms": "lower",    # ↓ better
        },
    )

## What to log

The minimum each event kind MUST carry. Anything not listed is optional.

| `event_kind` | Required payload fields | When to emit |
|---|---|---|
| `run_start` | (envelope only) | Once, at the top of the loop |
| `run_end`   | (envelope only) | Once, at the bottom |
| `individual` | `id`, `kind`, AND (non-empty `parent_ids` OR `is_seed=true`) | Every time you produce a candidate object |
| `operator`   | `id`, `kind` (one of the literals below), `child_id` | Every time a parent → child relation is *caused* by something nameable |
| `fitness`    | `individual_id`, `evaluator_kind`, AND (non-empty `scores` OR `invalid_reason`) | Every time you score a candidate |
| `descriptor` | `individual_id`, `archive_id`, `kind` (`grid`/`cvt`/`aurora`), `coordinates` (preferred) or `cell_id` | When you place a candidate in a behaviour archive (MAP-Elites etc.) |
| `migration`  | `population_id`, `from_island`, `to_island`, `individual_ids` | When you move individuals between islands |
| `self_mod`   | `parent_agent_id`, `child_agent_id` | When the agent edits its own code/prompts/weights |
| `claim`      | `id`, `text` | When you make a falsifiable assertion |
| `evidence`   | `claim_id`, `source_uri`, `stance` (`supports`/`contradicts`/`mentions`) | When you weigh in on a claim |
| `tree_expansion` | `tree_id`, `parent_node`, `child_node` | For MCTS-style tree-search loops |
| `archive_snapshot` | `archive_id`, `coverage` (∈[0,1]), `size` | Periodic snapshots of MAP-Elites coverage |
| `pareto_snapshot` | `population_id`, `front` (non-empty), `objectives` | Periodic snapshots of the Pareto front |
| `steering_command` | `command`, `actor` | Only for write-back from the dashboard; agents normally don't emit these |

### Allowed `kind` values

- **IndividualKind**: `program`, `prompt`, `architecture`, `reward_function`,
  `agent`, `environment`, `theorem`, `proof_state`, `dataset`, `skill`,
  `model_weights`, `paper`, `hypothesis`, `experiment_plan`, `claim`,
  `evidence`, `review`.
- **OperatorKind**: `mutate`, `crossover`, `select`, `refine`, `diversify`,
  `self_modify`, `propose`, `distill`, `migrate`, `meta_mutate`,
  `tree_expand`, `edit_diff`, `evaluate`, `review`.
- **EvaluatorKind**: `deterministic_metric`, `unit_test`, `benchmark`,
  `llm_judge`, `human`, `wet_lab`, `simulator`, `proof_checker`.
- **EvidenceStance**: `supports`, `contradicts`, `mentions`.

If your operator doesn't fit, pick the closest match — most common cases:
- LLM rewriting one program → `refine`.
- LLM combining two parents → `crossover`.
- Random perturbation → `mutate`.
- Filling a new candidate from scratch → `propose`.
- Self-editing → `self_modify`.
- Expanding an MCTS node → `tree_expand`.

## Worked examples

### 1. Linear research loop

```python
import hutch as h

h.start_run(name="hypothesis-refine")
seed = h.log_individual(kind="hypothesis", metadata={"text": "X causes Y"})
h.log_fitness(individual=seed, scores={"plausibility": 0.5})

current = seed
for step in range(5):
    refined = h.log_individual(kind="hypothesis", parent_ids=[current.id])
    h.log_operator(
        kind="refine", parent_ids=[current.id], child_id=refined.id,
        llm_id="gpt-4o", cost_usd=0.012,
    )
    h.log_fitness(individual=refined, scores={"plausibility": 0.55 + step * 0.05})
    current = refined

h.log_claim(text="Refined hypothesis is plausible.", supported_by=[current.id])
h.end_run()
```

### 2. Evolutionary loop (multi-island, OpenEvolve-style)

```python
import hutch as h

h.start_run(name="circle-packing")
pop = h.start_population(name="cp", kind="island", num_islands=3)

# Seed each island
seeds = []
for island_idx in range(3):
    seed = h.log_individual(kind="program", island_id=str(island_idx), generation_index=0)
    h.log_fitness(individual=seed, scores={"sum_radii": evaluate(seed)})
    seeds.append(seed)

# Run a few generations
parents = list(seeds)
for gen in range(1, 5):
    children = []
    for i, parent in enumerate(parents):
        child = h.log_individual(
            kind="program", parent_ids=[parent.id],
            island_id=parent.island_id, generation_index=gen,
        )
        h.log_operator(kind="mutate", parent_ids=[parent.id], child_id=child.id)
        h.log_fitness(individual=child, scores={"sum_radii": evaluate(child)})
        children.append(child)
    parents = children

h.end_run()
```

### 3. Self-improving agent (DGM-style)

```python
import hutch as h

h.start_run(name="dgm-iteration")
parent_agent = "agent-v17"
proposal = "Replace the BFS planner with A*."
score_before = run_swe_bench(parent_agent)

child_agent = "agent-v18"  # apply the diff to disk
score_after = run_swe_bench(child_agent)

h.log_self_modification(
    parent_agent_id=parent_agent,
    child_agent_id=child_agent,
    target_path="src/planner.py",
    proposal=proposal,
    overseer_id="claude-opus-4.7",
    overseer_verdict="accepted",
    benchmark="swe-bench-mini",
    score_before=score_before,
    score_after=score_after,
)
h.end_run()
```

### 4. Tree search (AIDE-style)

```python
import hutch as h

h.start_run(name="aide-search")
root = h.log_individual(kind="experiment_plan", individual_id="root")

frontier = [(root.id, 1)]
for _ in range(20):
    parent_id, depth = frontier.pop(0)
    child = h.log_individual(
        kind="experiment_plan", parent_ids=[parent_id],
        generation_index=depth,
    )
    h.log_operator(kind="tree_expand", parent_ids=[parent_id], child_id=child.id)
    h.log_tree_expansion(
        tree_id="aide", parent_node=parent_id, child_node=child.id,
        visit_count=1, value_estimate=evaluate_node(child),
    )
    h.log_fitness(individual=child, scores={"val_acc": evaluate_node(child)})
    if depth < 4:
        frontier.append((child.id, depth + 1))

h.end_run()
```

### 5. Quality-Diversity / MAP-Elites

```python
import hutch as h

h.start_run(name="map-elites-toy")
archive_id = "me-toy"

for step in range(50):
    parent_id = sample_from_archive() if step > 0 else None
    individual = h.log_individual(
        kind="program", parent_ids=[parent_id] if parent_id else [],
    )
    if parent_id:
        h.log_operator(kind="mutate", parent_ids=[parent_id], child_id=individual.id)
    descriptors, fitness = evaluate_with_descriptors(individual)
    h.log_fitness(individual=individual, scores=fitness)
    h.log_descriptor(
        individual=individual,
        archive_id=archive_id,
        coordinates=descriptors,           # e.g. [0.34, 0.71]
        cell_id=cell_key(descriptors),     # e.g. "(34,71)"
    )

h.end_run()
```

## Steering

The dashboard can issue write-back commands. Vocabulary:
`cancel_individual`, `freeze_island`, `fork_from`, `override_param`,
`pause_run`, `resume_run`, `cancel_self_mod`, `approve_hitl`,
`inject_hint`.

The recommended pattern: register one handler per command kind, then call
`hutch.steering.poll()` once per iteration. `poll()` drains the queue,
dispatches to your handlers, and acks each command with the handler's
return value as the audit-log note. Unhandled commands are auto-acked
with outcome `rejected` so the UI knows they were ignored.

```python
import hutch as h
from hutch import steering

paused = False

@steering.handler("pause_run")
def on_pause(cmd):
    nonlocal paused
    paused = True
    return "paused"

@steering.handler("resume_run")
def on_resume(cmd):
    nonlocal paused
    paused = False
    return "resumed"

@steering.handler("cancel_individual")
def on_cancel(cmd):
    cancelled.add(cmd.target_id)
    return f"will skip {cmd.target_id}"

@steering.handler("inject_hint")
def on_hint(cmd):
    state.next_hint = str(cmd.params.get("text") or "")
    return f"hint length {len(state.next_hint)}"

while True:
    steering.poll()        # drain + dispatch + ack
    if paused:
        time.sleep(0.5)
        continue
    do_one_iteration()
```

`approve_hitl` is the human-in-the-loop case: don't auto-handle it.
Pause your loop until a human clicks Approve/Reject in the Steering
panel. The UI's "approve" action acks the command with outcome
`accepted`, which `steering.poll()` returns to your handler — gate the
next iteration on seeing that outcome.

(Steering is wired in M9; older Hutch versions may no-op `poll()`.)

## Failure modes to avoid

- **Don't emit Individual events without a parent_id when `is_seed=False`** —
  the schema rejects orphans. Either set `is_seed=True` or supply at least
  one `parent_id`.
- **Don't reuse an `individual.id`** — every Individual is a distinct object.
  Re-runs of the same template are still distinct individuals.
- **Don't reference an `individual_id` from a Fitness/Descriptor event before
  emitting that Individual** — the dashboard tolerates out-of-order events
  but downstream consumers may not.
- **Don't lump multiple metrics into one composite without naming them** —
  emit `scores={"acc": …, "compile_ms": …}`, not `composite=0.97`. (You
  can supply `composite` as well, but the per-metric scores are what the
  Population and Pareto views read.)
- **Don't fabricate operator kinds** — pick from the literal list above.
- **Don't silently swallow failed evaluations** — if a candidate fails,
  emit `FitnessEvent(invalid_reason="timeout"|"compile_error"|…)` so the
  dashboard counts the failure honestly.
- **Don't include large blobs (programs, diffs, datasets) inline** — write
  them to disk or object storage and pass a URI in `genome_uri` /
  `diff_uri` / `artifact.uri`.
