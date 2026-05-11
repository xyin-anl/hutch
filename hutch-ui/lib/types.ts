/**
 * Canonical Hutch event schema in TypeScript.
 *
 * Hand-mirrored from `hutch-py/src/hutch/schema/`. The single source of truth
 * is the Pydantic models on the Python side; if you edit this file, run
 * `python -m hutch.schema._docgen` to confirm `docs/schema.md` still matches.
 *
 * v0.1.x keeps the schema additive-only. Both sides should eventually be
 * regenerated from a shared JSON schema.
 */

// ---------------- literal-kind enums ----------------

export type IndividualKind =
  | "program"
  | "prompt"
  | "architecture"
  | "reward_function"
  | "agent"
  | "environment"
  | "theorem"
  | "proof_state"
  | "dataset"
  | "skill"
  | "model_weights"
  | "paper"
  | "hypothesis"
  | "experiment_plan"
  | "claim"
  | "evidence"
  | "review";

export type OperatorKind =
  | "mutate"
  | "crossover"
  | "select"
  | "refine"
  | "diversify"
  | "self_modify"
  | "propose"
  | "distill"
  | "migrate"
  | "meta_mutate"
  | "tree_expand"
  | "edit_diff"
  | "evaluate"
  | "review";

export type EvaluatorKind =
  | "deterministic_metric"
  | "unit_test"
  | "benchmark"
  | "llm_judge"
  | "human"
  | "wet_lab"
  | "simulator"
  | "proof_checker";

export type DescriptorArchiveKind = "grid" | "cvt" | "aurora";
export type EvidenceStance = "supports" | "contradicts" | "mentions";
export type RunStatus = "running" | "finished" | "failed" | "cancelled";

export type EventKind =
  | "run_start"
  | "run_end"
  | "individual"
  | "operator"
  | "fitness"
  | "descriptor"
  | "lineage_edge"
  | "migration"
  | "self_mod"
  | "artifact"
  | "claim"
  | "evidence"
  | "review"
  | "stream_event"
  | "steering_command"
  | "pareto_snapshot"
  | "tree_expansion"
  | "archive_snapshot";

// ---------------- payloads ----------------

export interface BasePayload {
  metadata?: Record<string, unknown>;
}

export interface RunStartPayload extends BasePayload {
  name?: string | null;
  project?: string | null;
  started_by?: string | null;
  git_commit?: string | null;
  config?: Record<string, unknown>;
  score_directions?: Record<string, ScoreDirection>;
}

export interface RunEndPayload extends BasePayload {
  status: RunStatus;
  summary?: string | null;
}

export interface IndividualPayload extends BasePayload {
  id: string;
  kind: IndividualKind;
  parent_ids: string[];
  is_seed: boolean;
  genome_uri?: string | null;
  genome_hash?: string | null;
  genome_lang?: string | null;
  population_id?: string | null;
  island_id?: string | null;
  generation_index?: number | null;
}

export interface OperatorPayload extends BasePayload {
  id: string;
  kind: OperatorKind;
  parent_ids: string[];
  child_id: string;
  prompt_template?: string | null;
  llm_id?: string | null;
  llm_temperature?: number | null;
  diff?: string | null;
  diff_uri?: string | null;
  cost_usd?: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
}

export interface FitnessPayload extends BasePayload {
  individual_id: string;
  evaluator_id?: string | null;
  evaluator_kind: EvaluatorKind;
  scores: Record<string, number>;
  composite?: number | null;
  cascade_stage?: number | null;
  is_pareto_front?: boolean | null;
  dominates: string[];
  invalid_reason?: string | null;
}

export interface ClaimPayload extends BasePayload {
  id: string;
  text: string;
  supported_by: string[];
  requires_reproduction: boolean;
}

export interface DescriptorPayload extends BasePayload {
  individual_id: string;
  archive_id: string;
  kind: DescriptorArchiveKind;
  dimensions?: string[] | null;
  coordinates: number[];
  cell_id?: string | null;
  is_replaced: boolean;
}

export interface ParetoSnapshotPayload extends BasePayload {
  population_id: string;
  front: string[];
  objectives: string[];
  hypervolume?: number | null;
}

export type SelfModVerdict = "accepted" | "rejected" | "pending";

export interface SelfModPayload extends BasePayload {
  parent_agent_id: string;
  child_agent_id: string;
  target_path?: string | null;
  diff_uri?: string | null;
  proposal?: string | null;
  overseer_id?: string | null;
  overseer_verdict: SelfModVerdict;
  benchmark?: string | null;
  score_before?: number | null;
  score_after?: number | null;
}

export interface TreeExpansionPayload extends BasePayload {
  tree_id: string;
  parent_node: string;
  child_node: string;
  visit_count: number;
  value_estimate?: number | null;
  virtual_loss?: number | null;
}

export interface EvidencePayload extends BasePayload {
  claim_id: string;
  source_uri: string;
  stance: EvidenceStance;
  confidence?: number | null;
  source_quality?: number | null;
}

export type SteeringActor = "human" | "agent" | "policy";

export type SteeringCommandKind =
  | "cancel_individual"
  | "freeze_island"
  | "fork_from"
  | "override_param"
  | "pause_run"
  | "resume_run"
  | "cancel_self_mod"
  | "approve_hitl"
  | "inject_hint";

export interface SteeringCommandPayload extends BasePayload {
  command: SteeringCommandKind;
  target_id?: string | null;
  params?: Record<string, unknown>;
  actor: SteeringActor;
}

// ---------------- envelopes ----------------

interface EnvelopeBase {
  event_id: string;
  run_id: string;
  timestamp_ns: number;
  stream_id?: string | null;
  worker_id?: string | null;
  span_id?: string | null;
  trace_id?: string | null;
}

export interface RunStartEvent extends EnvelopeBase {
  event_kind: "run_start";
  payload: RunStartPayload;
}
export interface RunEndEvent extends EnvelopeBase {
  event_kind: "run_end";
  payload: RunEndPayload;
}
export interface IndividualEvent extends EnvelopeBase {
  event_kind: "individual";
  payload: IndividualPayload;
}
export interface OperatorEvent extends EnvelopeBase {
  event_kind: "operator";
  payload: OperatorPayload;
}
export interface FitnessEvent extends EnvelopeBase {
  event_kind: "fitness";
  payload: FitnessPayload;
}
export interface ClaimEvent extends EnvelopeBase {
  event_kind: "claim";
  payload: ClaimPayload;
}
export interface EvidenceEvent extends EnvelopeBase {
  event_kind: "evidence";
  payload: EvidencePayload;
}
export interface SteeringCommandEvent extends EnvelopeBase {
  event_kind: "steering_command";
  payload: SteeringCommandPayload;
}
export interface DescriptorEvent extends EnvelopeBase {
  event_kind: "descriptor";
  payload: DescriptorPayload;
}
export interface ParetoSnapshotEvent extends EnvelopeBase {
  event_kind: "pareto_snapshot";
  payload: ParetoSnapshotPayload;
}
export interface SelfModEvent extends EnvelopeBase {
  event_kind: "self_mod";
  payload: SelfModPayload;
}
export interface TreeExpansionEvent extends EnvelopeBase {
  event_kind: "tree_expansion";
  payload: TreeExpansionPayload;
}

// Catch-all for events the views don't deeply inspect yet.
export interface GenericEvent extends EnvelopeBase {
  event_kind: Exclude<
    EventKind,
    | "run_start"
    | "run_end"
    | "individual"
    | "operator"
    | "fitness"
    | "claim"
    | "evidence"
    | "descriptor"
    | "pareto_snapshot"
    | "self_mod"
    | "tree_expansion"
    | "steering_command"
  >;
  payload: BasePayload & Record<string, unknown>;
}

export type HutchEvent =
  | RunStartEvent
  | RunEndEvent
  | IndividualEvent
  | OperatorEvent
  | FitnessEvent
  | ClaimEvent
  | EvidenceEvent
  | DescriptorEvent
  | ParetoSnapshotEvent
  | SelfModEvent
  | TreeExpansionEvent
  | SteeringCommandEvent
  | GenericEvent;

// ---------------- daemon DTOs ----------------

export interface RunSummary {
  run_id: string;
  name?: string | null;
  project?: string | null;
  started_at_ns?: number | null;
  ended_at_ns?: number | null;
  status?: string | null;
  event_count: number;
  kinds_seen?: EventKind[];
}

export type ScoreDirection = "higher" | "lower";

export interface RunDetail {
  run_id: string;
  event_count: number;
  kinds_seen: EventKind[];
  first_timestamp_ns: number;
  last_timestamp_ns: number;
  /**
   * Per-metric optimisation direction declared by the producer at
   * ``run_start``. The Pareto / Best Composite / Population views
   * prefer this over name-based heuristics; metrics not listed here
   * fall back to the heuristic.
   */
  score_directions?: Record<string, ScoreDirection>;
}

// ---------------- helpers ----------------

/** Inferred system family from the operator + individual events in a run. */
export type SystemKind =
  | "linear"
  | "evolutionary"
  | "self-improving"
  | "tree-search";

export function inferSystemKind(
  operators: OperatorEvent[],
  individuals: IndividualEvent[] = [],
): SystemKind {
  const opKinds = new Set(operators.map((o) => o.payload.kind));
  if (opKinds.has("self_modify")) return "self-improving";
  if (opKinds.has("tree_expand")) return "tree-search";
  if (
    opKinds.has("mutate") ||
    opKinds.has("crossover") ||
    opKinds.has("migrate")
  ) {
    return "evolutionary";
  }
  // Population structure also signals evolutionary: multiple islands, OR more
  // than one seed (parallel chains), are not what a linear run looks like.
  const islandIds = new Set(
    individuals
      .map((i) => i.payload.island_id)
      .filter((v): v is string => typeof v === "string"),
  );
  if (islandIds.size >= 2) return "evolutionary";
  const seeds = individuals.filter((i) => i.payload.is_seed).length;
  if (seeds >= 2) return "evolutionary";
  return "linear";
}
