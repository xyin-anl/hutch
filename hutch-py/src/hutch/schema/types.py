"""Literal kind enums used across the canonical schema.

These types are *additive*: new values may be appended after v0.1.0; renaming
or removing an existing value is a breaking schema change that requires a
migration.
"""

from __future__ import annotations

from typing import Literal

IndividualKind = Literal[
    "program",
    "prompt",
    "architecture",
    "reward_function",
    "agent",
    "environment",
    "theorem",
    "proof_state",
    "dataset",
    "skill",
    "model_weights",
    "paper",
    "hypothesis",
    "experiment_plan",
    "claim",
    "evidence",
    "review",
]
"""Subtype of an Individual — what kind of object the candidate is."""

OperatorKind = Literal[
    "mutate",
    "crossover",
    "select",
    "refine",
    "diversify",
    "self_modify",
    "propose",
    "distill",
    "migrate",
    "meta_mutate",
    "tree_expand",
    "edit_diff",
    "evaluate",
    "review",
]
"""How an Individual was produced from its parents (or from nothing, for ``propose``)."""

PopulationKind = Literal[
    "linear",
    "island",
    "map_elites",
    "tree",
    "swarm",
    "archive",
]
"""Topology of the population: linear chain, multi-island, MAP-Elites grid, …"""

EvaluatorKind = Literal[
    "deterministic_metric",
    "unit_test",
    "benchmark",
    "llm_judge",
    "human",
    "wet_lab",
    "simulator",
    "proof_checker",
]
"""Source of a Fitness score."""

ArtifactKind = Literal[
    "program",
    "prompt",
    "architecture",
    "theorem",
    "dataset",
    "environment",
    "reward_function",
    "agent",
    "paper",
    "skill",
    "proof",
    "benchmark",
    "repo",
    "ara_package",
]
"""Kind of an externally-stored Artifact (genome, dataset, paper, …)."""

DescriptorArchiveKind = Literal["grid", "cvt", "aurora"]
"""Geometry of a descriptor archive — rectangular grid, CVT cells, or AURORA latent."""

EvidenceStance = Literal["supports", "contradicts", "mentions"]
"""How a piece of Evidence relates to a Claim."""

ScoreDirection = Literal["higher", "lower"]
"""Optimisation direction for a Fitness metric. ``higher`` = higher-is-better
(accuracy, sum_radii, qd_score, …); ``lower`` = lower-is-better (loss,
compile_ms, nrmse, time, regret, …). Declared once per run via
``RunStartPayload.score_directions``; everywhere a metric direction
matters (Pareto frontier, best-composite aggregation, dominance checks)
the canonical schema value wins over name-based heuristics."""

SelfModVerdict = Literal["accepted", "rejected", "pending"]
"""Overseer verdict on a self-modification proposal."""

SteeringActor = Literal["human", "agent", "policy"]
"""Origin of a steering command."""

SteeringCommandKind = Literal[
    "cancel_individual",
    "freeze_island",
    "fork_from",
    "override_param",
    "pause_run",
    "resume_run",
    "cancel_self_mod",
    "approve_hitl",
    "inject_hint",
]
"""Vocabulary of write-back commands the dashboard can issue."""

RunStatus = Literal["running", "finished", "failed", "cancelled"]
"""Terminal status of a run."""

EventKind = Literal[
    "run_start",
    "run_update",
    "run_end",
    "individual",
    "operator",
    "fitness",
    "descriptor",
    "lineage_edge",
    "migration",
    "self_mod",
    "artifact",
    "claim",
    "evidence",
    "review",
    "stream_event",
    "steering_command",
    "pareto_snapshot",
    "tree_expansion",
    "archive_snapshot",
]
"""All canonical event-envelope kinds."""

ALL_KINDS: tuple[str, ...] = (
    "run_start",
    "run_update",
    "run_end",
    "individual",
    "operator",
    "fitness",
    "descriptor",
    "lineage_edge",
    "migration",
    "self_mod",
    "artifact",
    "claim",
    "evidence",
    "review",
    "stream_event",
    "steering_command",
    "pareto_snapshot",
    "tree_expansion",
    "archive_snapshot",
)
"""Runtime tuple mirror of :data:`EventKind` for iteration / fixture generation."""
