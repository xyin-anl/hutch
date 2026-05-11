"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyState } from "@/components/ui/EmptyState";
import { composeFitnessScore } from "@/lib/fitness";
import type { FitnessEvent, IndividualEvent, ScoreDirection } from "@/lib/types";

interface GenerationStats {
  generation: number;
  best: number;
  median: number;
  worst: number;
  count: number;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1]! + sorted[mid]!) / 2
    : sorted[mid]!;
}

function buildGenerationStats(
  individuals: IndividualEvent[],
  fitness: FitnessEvent[],
  scoreDirections: Record<string, ScoreDirection> | undefined,
): GenerationStats[] {
  const indexById = new Map<string, number | null>();
  for (const ind of individuals) {
    indexById.set(ind.payload.id, ind.payload.generation_index ?? null);
  }
  const haveExplicit = individuals.some(
    (i) => i.payload.generation_index !== null && i.payload.generation_index !== undefined,
  );
  // Bucket fitness events: by generation_index if set on the individual, else
  // by their position in timestamp order.
  const buckets = new Map<number, number[]>();
  fitness
    .slice()
    .sort((a, b) => a.timestamp_ns - b.timestamp_ns)
    .forEach((f, i) => {
      const v = composeFitnessScore(f, scoreDirections);
      if (v === null) return;
      const gen = haveExplicit
        ? (indexById.get(f.payload.individual_id) ?? null) ?? -1
        : i;
      const arr = buckets.get(gen) ?? [];
      arr.push(v);
      buckets.set(gen, arr);
    });
  return Array.from(buckets.entries())
    .filter(([gen]) => gen !== -1)
    .sort((a, b) => a[0] - b[0])
    .map(([gen, vals]) => ({
      generation: gen,
      best: Math.max(...vals),
      median: median(vals),
      worst: Math.min(...vals),
      count: vals.length,
    }));
}

export function PopulationView({
  individuals,
  fitness,
  scoreDirections,
}: {
  individuals: IndividualEvent[];
  fitness: FitnessEvent[];
  scoreDirections?: Record<string, ScoreDirection>;
}) {
  if (fitness.length === 0) {
    return (
      <EmptyState
        title="No fitness events yet"
        detail="Call h.log_fitness(...) to populate this view."
      />
    );
  }

  const stats = buildGenerationStats(individuals, fitness, scoreDirections);
  if (stats.length === 0) {
    return (
      <EmptyState
        title="No valid fitness samples"
        detail="Every fitness event has an invalid_reason set or no scores."
      />
    );
  }

  const haveExplicitGen = individuals.some(
    (i) => i.payload.generation_index !== null && i.payload.generation_index !== undefined,
  );
  const xLabel = haveExplicitGen ? "Generation" : "Fitness sample (timestamp order)";
  const singleSampleGenerations = stats.every((s) => s.count === 1);

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
        <h3 className="text-sm font-medium text-neutral-800 dark:text-neutral-200">
          {singleSampleGenerations
            ? "Fitness by generation"
            : "Best / median / worst per generation"}
        </h3>
        <p className="text-xs text-neutral-500">
          {singleSampleGenerations ? (
            <>
              Each generation has one valid fitness sample, so the chart shows
              the scored candidate trajectory.
            </>
          ) : (
            <>
              Composite is taken from <code>FitnessPayload.composite</code> when
              set, else score directions are applied so higher comparable values
              are better.
            </>
          )}
        </p>
        <div className="mt-4 h-72 w-full">
          <ResponsiveContainer>
            <LineChart data={stats} margin={{ top: 8, right: 16, left: -8, bottom: 0 }}>
              <CartesianGrid
                stroke="currentColor"
                className="text-neutral-200 dark:text-neutral-800"
                strokeDasharray="3 3"
              />
              <XAxis
                dataKey="generation"
                stroke="currentColor"
                className="text-neutral-500"
                fontSize={11}
                label={{
                  value: xLabel,
                  position: "insideBottom",
                  dy: 8,
                  fill: "currentColor",
                  fontSize: 11,
                }}
              />
              <YAxis stroke="currentColor" className="text-neutral-500" fontSize={11} />
              <Tooltip
                contentStyle={{
                  background: "var(--tooltip-bg, #ffffff)",
                  border: "1px solid #e5e5e5",
                  fontSize: 12,
                  color: "#171717",
                }}
                labelStyle={{ color: "#525252" }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="best"
                name={singleSampleGenerations ? "fitness" : "best"}
                stroke="#059669"
                strokeWidth={2}
                dot={singleSampleGenerations ? { r: 3 } : false}
              />
              {!singleSampleGenerations ? (
                <>
                  <Line
                    type="monotone"
                    dataKey="median"
                    stroke="#737373"
                    strokeWidth={1.5}
                    dot={false}
                    strokeDasharray="3 3"
                  />
                  <Line
                    type="monotone"
                    dataKey="worst"
                    stroke="#dc2626"
                    strokeWidth={1.5}
                    dot={false}
                    strokeDasharray="6 3"
                  />
                </>
              ) : null}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-xs text-neutral-500 dark:border-neutral-800 dark:bg-neutral-950">
        {stats.length} generation{stats.length === 1 ? "" : "s"} ·{" "}
        {fitness.length} fitness sample{fitness.length === 1 ? "" : "s"}
      </div>
    </div>
  );
}
