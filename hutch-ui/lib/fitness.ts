import type { FitnessEvent, ScoreDirection } from "@/lib/types";

const LOWER_HINTS: RegExp[] = [
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

export function resolveScoreDirection(
  metric: string,
  scoreDirections: Record<string, ScoreDirection> | undefined,
): ScoreDirection {
  return (
    scoreDirections?.[metric] ??
    (LOWER_HINTS.some((re) => re.test(metric)) ? "lower" : "higher")
  );
}

export function composeFitnessScore(
  event: FitnessEvent,
  scoreDirections: Record<string, ScoreDirection> | undefined,
): number | null {
  if (event.payload.invalid_reason) return null;
  const composite = event.payload.composite;
  if (composite !== null && composite !== undefined && Number.isFinite(composite)) {
    return composite;
  }
  const contributions = Object.entries(event.payload.scores ?? {})
    .filter(([, value]) => Number.isFinite(value))
    .map(([metric, value]) =>
      resolveScoreDirection(metric, scoreDirections) === "higher" ? value : -value,
    );
  if (contributions.length === 0) return null;
  return Math.max(...contributions);
}

export function bestFitnessByIndividual(
  fitness: FitnessEvent[],
  scoreDirections: Record<string, ScoreDirection> | undefined,
): Map<string, number> {
  const out = new Map<string, number>();
  for (const f of fitness) {
    const comparable = composeFitnessScore(f, scoreDirections);
    if (comparable === null) continue;
    const prev = out.get(f.payload.individual_id);
    if (prev === undefined || comparable > prev) {
      out.set(f.payload.individual_id, comparable);
    }
  }
  return out;
}
