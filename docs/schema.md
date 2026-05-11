# Canonical event schema

> **Auto-generated from `hutch-py/src/hutch/schema/`.**
> To regenerate, run `python -m hutch.schema._docgen` from `hutch-py/`.

This page is the field-level reference for every event a Hutch run
can produce. For the higher-level meaning of each field, see
[Concepts](concepts.md).

From v0.1.0 onward, the schema is **additive-only** between minor
releases. New optional fields and new `kind` enum values are fine.
Renaming or removing an existing field is a breaking change and
requires a migration in `hutch-py/src/hutch/store/migrations/`.

## Schema invariants

- Every Individual has at least one `parent_id`, or `is_seed=True`.
- A Fitness event with a non-null `invalid_reason` may have empty
  `scores`. Otherwise `scores` must be non-empty.
- A Pareto-front snapshot must list at least one id.
- If both are supplied, a Descriptor's `coordinates` length must
  match the length of its `dimensions`.
- Archive coverage is in `[0, 1]`.
- `parent_ids` may have any length: 0 for a seed, 1 for a refine or
  mutation, 2 for a crossover, more for an ensemble or distillation.

## Literal kind enums

### `IndividualKind`

`program`, `prompt`, `architecture`, `reward_function`, `agent`, `environment`, `theorem`, `proof_state`, `dataset`, `skill`, `model_weights`, `paper`, `hypothesis`, `experiment_plan`, `claim`, `evidence`, `review`

### `OperatorKind`

`mutate`, `crossover`, `select`, `refine`, `diversify`, `self_modify`, `propose`, `distill`, `migrate`, `meta_mutate`, `tree_expand`, `edit_diff`, `evaluate`, `review`

### `PopulationKind`

`linear`, `island`, `map_elites`, `tree`, `swarm`, `archive`

### `EvaluatorKind`

`deterministic_metric`, `unit_test`, `benchmark`, `llm_judge`, `human`, `wet_lab`, `simulator`, `proof_checker`

### `ArtifactKind`

`program`, `prompt`, `architecture`, `theorem`, `dataset`, `environment`, `reward_function`, `agent`, `paper`, `skill`, `proof`, `benchmark`, `repo`, `ara_package`

### `DescriptorArchiveKind`

`grid`, `cvt`, `aurora`

### `EvidenceStance`

`supports`, `contradicts`, `mentions`

### `SelfModVerdict`

`accepted`, `rejected`, `pending`

### `SteeringActor`

`human`, `agent`, `policy`

### `SteeringCommandKind`

`cancel_individual`, `freeze_island`, `fork_from`, `override_param`, `pause_run`, `resume_run`, `cancel_self_mod`, `approve_hitl`, `inject_hint`

### `RunStatus`

`running`, `finished`, `failed`, `cancelled`

## Event variants

Every event has a fixed envelope plus a typed payload. The envelope:

| field | type | required | description |
|---|---|---|---|
| `event_id` | `UUID` | auto | Unique event identifier (default: random UUIDv4). |
| `event_kind` | `EventKind` | yes | Discriminator: selects the payload type. |
| `run_id` | `str` | yes | Owning run. |
| `timestamp_ns` | `int` | auto | UNIX time in nanoseconds (default: now). |
| `stream_id` | `str?` | no | Swimlane / worker label. |
| `worker_id` | `str?` | no | Concrete worker / process / agent. |
| `span_id` | `str?` | no | OTel span id, if also emitted to OTel. |
| `trace_id` | `str?` | no | OTel trace id, if also emitted to OTel. |

### `event_kind = "run_start"` (`RunStartEvent`)

**Payload:** `RunStartPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `name` | `str | None` | no | None |
| `project` | `str | None` | no | None |
| `started_by` | `str | None` | no | Free-form actor identifier (user, CI job, agent id). |
| `git_commit` | `str | None` | no | None |
| `config` | `dict[str, Any]` | no | {} |
| `capabilities` | `dict[str, bool]` | no | Truthful dashboard capabilities declared by the producer. Common keys include `steering`, `llm_usage`, `live_updates`, and `audit`. Absent keys mean unsupported or not logged, never implicitly true. |
| `score_directions` | `dict[str, Literal['higher', 'lower']]` | no | Per-metric optimisation direction — `higher` (higher is better) or `lower` (lower is better). Used by the dashboard's Pareto frontier, best-composite aggregation, and any other consumer that needs to know which way is up. Declare every metric you log under `FitnessPayload.scores`. Unmatched metrics fall back to a name-based heuristic in the UI. |

### `event_kind = "run_update"` (`RunUpdateEvent`)

**Payload:** `RunUpdatePayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `status` | `Optional[Literal['running', 'finished', 'failed', 'cancelled']]` | no | None |
| `config` | `dict[str, Any]` | no | {} |
| `capabilities` | `dict[str, bool]` | no | {} |
| `score_directions` | `dict[str, Literal['higher', 'lower']]` | no | {} |
| `source_counts` | `dict[str, int]` | no | {} |
| `watcher` | `dict[str, Any]` | no | {} |

### `event_kind = "run_end"` (`RunEndEvent`)

**Payload:** `RunEndPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `status` | `Literal['running', 'finished', 'failed', 'cancelled']` | no | 'finished' |
| `summary` | `str | None` | no | None |

### `event_kind = "individual"` (`IndividualEvent`)

**Payload:** `IndividualPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `id` | `str` | yes | — |
| `kind` | `Literal['program', 'prompt', 'architecture', 'reward_function', 'agent', 'environment', 'theorem', 'proof_state', 'dataset', 'skill', 'model_weights', 'paper', 'hypothesis', 'experiment_plan', 'claim', 'evidence', 'review']` | yes | — |
| `parent_ids` | `list[str]` | no | Zero or more parent Individual ids. Empty iff ``is_seed`` is True. |
| `is_seed` | `bool` | no | False |
| `genome_uri` | `str | None` | no | None |
| `genome_hash` | `str | None` | no | Optional SHA-256 hex digest for ``genome_uri`` content. |
| `genome_lang` | `str | None` | no | None |
| `population_id` | `str | None` | no | None |
| `island_id` | `str | None` | no | None |
| `generation_index` | `int | None` | no | None |

### `event_kind = "operator"` (`OperatorEvent`)

**Payload:** `OperatorPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `id` | `str` | yes | — |
| `kind` | `Literal['mutate', 'crossover', 'select', 'refine', 'diversify', 'self_modify', 'propose', 'distill', 'migrate', 'meta_mutate', 'tree_expand', 'edit_diff', 'evaluate', 'review']` | yes | — |
| `parent_ids` | `list[str]` | no | [] |
| `child_id` | `str` | yes | — |
| `prompt_template` | `str | None` | no | None |
| `llm_id` | `str | None` | no | None |
| `llm_temperature` | `float | None` | no | None |
| `diff` | `str | None` | no | Inline diff text; for large diffs prefer ``diff_uri``. |
| `diff_uri` | `str | None` | no | None |
| `cost_usd` | `float | None` | no | None |
| `tokens_in` | `int | None` | no | None |
| `tokens_out` | `int | None` | no | None |

### `event_kind = "fitness"` (`FitnessEvent`)

**Payload:** `FitnessPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `individual_id` | `str` | yes | — |
| `evaluator_id` | `str | None` | no | None |
| `evaluator_kind` | `Literal['deterministic_metric', 'unit_test', 'benchmark', 'llm_judge', 'human', 'wet_lab', 'simulator', 'proof_checker']` | yes | — |
| `scores` | `dict[str, float]` | no | {} |
| `composite` | `float | None` | no | None |
| `cascade_stage` | `int | None` | no | None |
| `is_pareto_front` | `bool | None` | no | None |
| `dominates` | `list[str]` | no | [] |
| `invalid_reason` | `str | None` | no | If set, this evaluation is considered failed; ``scores`` may be empty. |

### `event_kind = "descriptor"` (`DescriptorEvent`)

**Payload:** `DescriptorPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `individual_id` | `str` | yes | — |
| `archive_id` | `str` | yes | — |
| `kind` | `Literal['grid', 'cvt', 'aurora']` | yes | — |
| `dimensions` | `list[str] | None` | no | None |
| `coordinates` | `list[float]` | no | [] |
| `cell_id` | `str | None` | no | None |
| `is_replaced` | `bool` | no | False |

### `event_kind = "lineage_edge"` (`LineageEdgeEvent`)

**Payload:** `LineageEdgePayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `parent_id` | `str` | yes | — |
| `child_id` | `str` | yes | — |
| `relation` | `str` | no | 'parent' |

### `event_kind = "migration"` (`MigrationEvent`)

**Payload:** `MigrationPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `population_id` | `str` | yes | — |
| `from_island` | `str` | yes | — |
| `to_island` | `str` | yes | — |
| `individual_ids` | `list[str]` | yes | — |
| `trigger` | `str | None` | no | None |

### `event_kind = "self_mod"` (`SelfModEvent`)

**Payload:** `SelfModPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `parent_agent_id` | `str` | yes | — |
| `child_agent_id` | `str` | yes | — |
| `target_path` | `str | None` | no | None |
| `diff_uri` | `str | None` | no | None |
| `proposal` | `str | None` | no | None |
| `overseer_id` | `str | None` | no | None |
| `overseer_verdict` | `Literal['accepted', 'rejected', 'pending']` | no | 'pending' |
| `benchmark` | `str | None` | no | None |
| `score_before` | `float | None` | no | None |
| `score_after` | `float | None` | no | None |

### `event_kind = "artifact"` (`ArtifactEvent`)

**Payload:** `ArtifactPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `id` | `str` | yes | — |
| `kind` | `Literal['program', 'prompt', 'architecture', 'theorem', 'dataset', 'environment', 'reward_function', 'agent', 'paper', 'skill', 'proof', 'benchmark', 'repo', 'ara_package']` | yes | — |
| `uri` | `str` | yes | — |
| `hash` | `str | None` | no | Optional SHA-256 hex digest for ``uri`` content. |
| `format` | `str | None` | no | None |
| `parent_artifact_id` | `str | None` | no | None |
| `ara_layer` | `str | None` | no | Optional ARA-package layer label. |

### `event_kind = "claim"` (`ClaimEvent`)

**Payload:** `ClaimPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `id` | `str` | yes | — |
| `text` | `str` | yes | — |
| `supported_by` | `list[str]` | no | [] |
| `requires_reproduction` | `bool` | no | False |

### `event_kind = "evidence"` (`EvidenceEvent`)

**Payload:** `EvidencePayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `claim_id` | `str` | yes | — |
| `source_uri` | `str` | yes | — |
| `stance` | `Literal['supports', 'contradicts', 'mentions']` | yes | — |
| `confidence` | `float | None` | no | None |
| `source_quality` | `float | None` | no | None |

### `event_kind = "review"` (`ReviewEvent`)

**Payload:** `ReviewPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `target_id` | `str` | yes | — |
| `scorer` | `str` | yes | — |
| `scores` | `dict[str, float]` | no | {} |
| `concerns` | `list[str]` | no | [] |

### `event_kind = "stream_event"` (`StreamEventEvent`)

**Payload:** `StreamEventPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `label` | `str` | yes | — |
| `text` | `str | None` | no | None |

### `event_kind = "steering_command"` (`SteeringCommandEvent`)

**Payload:** `SteeringCommandPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `command` | `Literal['cancel_individual', 'freeze_island', 'fork_from', 'override_param', 'pause_run', 'resume_run', 'cancel_self_mod', 'approve_hitl', 'inject_hint']` | yes | — |
| `target_id` | `str | None` | no | None |
| `params` | `dict[str, Any]` | no | {} |
| `actor` | `Literal['human', 'agent', 'policy']` | yes | — |

### `event_kind = "tree_expansion"` (`TreeExpansionEvent`)

**Payload:** `TreeExpansionPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `tree_id` | `str` | yes | — |
| `parent_node` | `str` | yes | — |
| `child_node` | `str` | yes | — |
| `visit_count` | `int` | no | 0 |
| `value_estimate` | `float | None` | no | None |
| `virtual_loss` | `float | None` | no | None |

### `event_kind = "archive_snapshot"` (`ArchiveSnapshotEvent`)

**Payload:** `ArchiveSnapshotPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `archive_id` | `str` | yes | — |
| `coverage` | `float` | yes | — |
| `qd_score` | `float | None` | no | None |
| `max_fitness` | `float | None` | no | None |
| `size` | `int` | yes | — |
| `snapshot_uri` | `str | None` | no | None |

### `event_kind = "pareto_snapshot"` (`ParetoSnapshotEvent`)

**Payload:** `ParetoSnapshotPayload`

| field | type | required | description |
|---|---|---|---|
| `metadata` | `dict[str, Any]` | no | Free-form extension dictionary. Adapters / SDKs use this for fields the canonical schema does not yet model. |
| `population_id` | `str` | yes | — |
| `front` | `list[str]` | yes | — |
| `objectives` | `list[str]` | yes | — |
| `hypervolume` | `float | None` | no | None |
