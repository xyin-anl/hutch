import { describe, expect, it } from "vitest";

import {
  bestFitnessByIndividual,
  composeFitnessScore,
  resolveScoreDirection,
} from "@/lib/fitness";
import type { FitnessEvent } from "@/lib/types";

function fitness(
  individualId: string,
  scores: Record<string, number>,
  composite: number | null = null,
): FitnessEvent {
  return {
    event_id: `${individualId}-${Object.keys(scores).join("-")}`,
    event_kind: "fitness",
    run_id: "run-1",
    timestamp_ns: 1,
    payload: {
      individual_id: individualId,
      evaluator_kind: "deterministic_metric",
      scores,
      composite,
      dominates: [],
    },
  };
}

describe("fitness helpers", () => {
  it("prefers declared score directions over name heuristics", () => {
    expect(resolveScoreDirection("loss", { loss: "higher" })).toBe("higher");
    expect(resolveScoreDirection("loss", undefined)).toBe("lower");
  });

  it("uses composite scores when present", () => {
    expect(composeFitnessScore(fitness("i1", { loss: 99 }, 0.42), { loss: "lower" })).toBe(
      0.42,
    );
  });

  it("normalizes lower-is-better metrics so higher comparable scores are better", () => {
    expect(composeFitnessScore(fitness("i1", { loss: 0.2 }), { loss: "lower" })).toBe(
      -0.2,
    );
  });

  it("keeps the best comparable fitness per individual", () => {
    const best = bestFitnessByIndividual(
      [fitness("i1", { loss: 0.5 }), fitness("i1", { loss: 0.1 })],
      { loss: "lower" },
    );
    expect(best.get("i1")).toBe(-0.1);
  });
});
