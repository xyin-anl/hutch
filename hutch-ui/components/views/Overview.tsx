"use client";

import { EmptyState } from "@/components/ui/EmptyState";
import { StatCard } from "@/components/ui/StatCard";
import { formatUsd, sumObservedNumbers } from "@/lib/observed";
import {
  inferSystemKind,
  type FitnessEvent,
  type IndividualEvent,
  type OperatorEvent,
  type RunDetail,
  type ScoreDirection,
  type SystemKind,
} from "@/lib/types";

/**
 * Compose a single direction-aware "best so far" number from a scores
 * dict. We prefer the producer-set ``composite`` field; otherwise we
 * fold per-metric scores using their declared direction:
 *
 * * ``higher`` metrics enter as-is.
 * * ``lower`` metrics enter negated (so larger composite is always better).
 *
 * Metrics not declared (and not heuristically classifiable) are
 * skipped: opting in to a wrong direction is worse than ignoring them.
 */
function composeBestScore(
  scores: Record<string, number>,
  composite: number | null | undefined,
  scoreDirections: Record<string, ScoreDirection>,
): number | null {
  if (composite !== null && composite !== undefined && Number.isFinite(composite)) {
    return composite;
  }
  const contributions: number[] = [];
  for (const [name, value] of Object.entries(scores)) {
    if (!Number.isFinite(value)) continue;
    const dir = scoreDirections[name] ?? guessOverviewDirection(name);
    if (dir === undefined) continue;
    contributions.push(dir === "higher" ? value : -value);
  }
  if (contributions.length === 0) return null;
  return Math.max(...contributions);
}

const _LOWER_HINTS: RegExp[] = [
  /cost/i,
  /time/i,
  /latency/i,
  /loss/i,
  /err/i,
  /\bms\b/i,
  /_ms$/i,
  /_s$/i,
  /seconds?$/i,
  /minutes?$/i,
  /hours?$/i,
  /nrmse/i,
  /rmse/i,
  /regret/i,
  /ppl/i,
  /perplexity/i,
];

function guessOverviewDirection(metric: string): ScoreDirection | undefined {
  if (_LOWER_HINTS.some((re) => re.test(metric))) return "lower";
  // Be conservative: only assume "higher" for the obvious quality words.
  if (/score|accuracy|f1|reward|qd_score|sum_radii|fitness|plausibility|correctness/i.test(metric)) {
    return "higher";
  }
  return undefined;
}

const SYSTEM_BADGE_COLORS: Record<SystemKind, string> = {
  unknown:
    "border-neutral-300 bg-neutral-100 text-neutral-700 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300",
  linear:
    "border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-700 dark:bg-sky-950 dark:text-sky-200",
  evolutionary:
    "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-200",
  "self-improving":
    "border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-700 dark:bg-violet-950 dark:text-violet-200",
  "tree-search":
    "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200",
};

function formatNs(ns: number | null | undefined): string {
  if (!ns) return "—";
  return new Date(ns / 1_000_000).toLocaleString();
}

function formatDurationNs(start: number, end: number): string {
  const ms = (end - start) / 1_000_000;
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  const s = ms / 1000;
  if (s < 90) return `${s.toFixed(1)} s`;
  const min = s / 60;
  if (min < 90) return `${min.toFixed(1)} min`;
  const h = min / 60;
  return `${h.toFixed(1)} h`;
}

export function OverviewView({
  detail,
  individuals,
  operators,
  fitness,
}: {
  detail: RunDetail | undefined;
  individuals: IndividualEvent[];
  operators: OperatorEvent[];
  fitness: FitnessEvent[];
}) {
  if (!detail) {
    return <EmptyState title="No run summary yet" />;
  }

  const systemKind = detail.system_kind ?? inferSystemKind(operators, individuals);
  const badge = SYSTEM_BADGE_COLORS[systemKind];

  const loggedCost = sumObservedNumbers(operators, (o) => o.payload.cost_usd);
  const scoreDirections = detail.score_directions ?? {};
  const compositeScores = fitness
    .map((f) =>
      composeBestScore(
        f.payload.scores ?? {},
        f.payload.composite,
        scoreDirections,
      ),
    )
    .filter((v): v is number => v !== null && Number.isFinite(v));
  const bestComposite =
    compositeScores.length > 0 ? Math.max(...compositeScores) : null;

  const seedCount = individuals.filter((i) => i.payload.is_seed).length;
  const validatedClaims = fitness.filter(
    (f) => f.payload.invalid_reason === null || f.payload.invalid_reason === undefined,
  ).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium ${badge}`}
        >
          {systemKind}
        </span>
        <span className="text-xs text-neutral-500">
          {systemKind === "unknown"
            ? "classification unavailable from logged events"
            : `inferred from operator kinds: ${
                operators.length === 0 ? "—" : sampleOperatorKinds(operators)
              }`}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Events" value={detail.event_count} />
        <StatCard
          label="Individuals"
          value={individuals.length}
          hint={`${seedCount} seed${seedCount === 1 ? "" : "s"}`}
        />
        <StatCard label="Operators" value={operators.length} />
        <StatCard
          label="Fitness samples"
          value={fitness.length}
          hint={`${validatedClaims} valid`}
        />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {bestComposite !== null ? (
          <StatCard
            label="Best composite"
            value={
              Number.isInteger(bestComposite)
                ? bestComposite.toString()
                : bestComposite.toFixed(3)
            }
            hint="derived from logged fitness"
          />
        ) : null}
        {loggedCost.observed ? (
          <StatCard
            label="LLM cost"
            value={formatUsd(loggedCost.total)}
            hint={`sum of ${loggedCost.count} logged operator.cost_usd value${
              loggedCost.count === 1 ? "" : "s"
            }`}
          />
        ) : null}
        <StatCard
          label="Duration"
          value={formatDurationNs(detail.first_timestamp_ns, detail.last_timestamp_ns)}
          hint="first → last event"
        />
      </div>

      <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-600 dark:border-neutral-800 dark:bg-neutral-950 dark:text-neutral-400">
        <h3 className="mb-2 text-xs uppercase tracking-wide text-neutral-500">
          Run timing
        </h3>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs md:grid-cols-3">
          <dt className="text-neutral-500">first event</dt>
          <dd className="font-mono text-neutral-700 md:col-span-2 dark:text-neutral-300">
            {formatNs(detail.first_timestamp_ns)}
          </dd>
          <dt className="text-neutral-500">last event</dt>
          <dd className="font-mono text-neutral-700 md:col-span-2 dark:text-neutral-300">
            {formatNs(detail.last_timestamp_ns)}
          </dd>
          <dt className="text-neutral-500">kinds seen</dt>
          <dd className="font-mono text-neutral-700 md:col-span-2 dark:text-neutral-300">
            {detail.kinds_seen.join(", ")}
          </dd>
        </dl>
      </div>
    </div>
  );
}

function sampleOperatorKinds(operators: OperatorEvent[]): string {
  const counts = new Map<string, number>();
  for (const o of operators) {
    counts.set(o.payload.kind, (counts.get(o.payload.kind) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([k, n]) => `${k}×${n}`)
    .join(", ");
}
