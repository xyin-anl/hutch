"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useMemo } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { StatCard } from "@/components/ui/StatCard";
import { formatUsd, isFiniteNumber, sumObservedNumbers } from "@/lib/observed";
import type { OperatorEvent } from "@/lib/types";

const KIND_COLOR: Record<string, string> = {
  refine: "#10b981",
  mutate: "#22c55e",
  crossover: "#a855f7",
  select: "#f59e0b",
  diversify: "#06b6d4",
  self_modify: "#ef4444",
  propose: "#3b82f6",
  distill: "#fb7185",
  migrate: "#f97316",
  meta_mutate: "#eab308",
  tree_expand: "#8b5cf6",
  edit_diff: "#14b8a6",
  evaluate: "#737373",
  review: "#a3a3a3",
};

interface KindRow {
  kind: string;
  count: number;
  color: string;
  totalCostUsd: number;
  costCount: number;
  avgCostUsd: number | null;
  totalTokensIn: number;
  totalTokensOut: number;
  tokenCount: number;
  fanout: number;
  crossover: number;
}

function buildKindRows(operators: OperatorEvent[]): KindRow[] {
  const byKind = new Map<string, OperatorEvent[]>();
  for (const o of operators) {
    const arr = byKind.get(o.payload.kind) ?? [];
    arr.push(o);
    byKind.set(o.payload.kind, arr);
  }
  return Array.from(byKind.entries())
    .map(([kind, ops]) => {
      const costs = ops
        .map((o) => o.payload.cost_usd)
        .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
      const tokensIn = ops
        .map((o) => o.payload.tokens_in)
        .filter(isFiniteNumber);
      const tokensOut = ops
        .map((o) => o.payload.tokens_out)
        .filter(isFiniteNumber);
      const fanouts = ops.map((o) => o.payload.parent_ids.length);
      const avgFanout =
        fanouts.length > 0 ? fanouts.reduce((a, b) => a + b, 0) / fanouts.length : 0;
      const crossover = ops.filter((o) => o.payload.parent_ids.length >= 2).length;
      return {
        kind,
        count: ops.length,
        color: KIND_COLOR[kind] ?? "#6b7280",
        totalCostUsd: costs.reduce((a, b) => a + b, 0),
        costCount: costs.length,
        avgCostUsd: costs.length > 0 ? costs.reduce((a, b) => a + b, 0) / costs.length : null,
        totalTokensIn: tokensIn.reduce((a, b) => a + b, 0),
        totalTokensOut: tokensOut.reduce((a, b) => a + b, 0),
        tokenCount: tokensIn.length + tokensOut.length,
        fanout: avgFanout,
        crossover,
      };
    })
    .sort((a, b) => b.count - a.count);
}

interface BucketRow {
  bucket: number;
  /** counts per operator kind, plus a total */
  total: number;
  [k: string]: number;
}

function buildTimeSeries(
  operators: OperatorEvent[],
  buckets: number,
): { rows: BucketRow[]; kinds: string[] } {
  if (operators.length === 0) return { rows: [], kinds: [] };
  const tsMin = Math.min(...operators.map((o) => o.timestamp_ns));
  const tsMax = Math.max(...operators.map((o) => o.timestamp_ns));
  const tsR = tsMax - tsMin || 1;
  const kinds = Array.from(new Set(operators.map((o) => o.payload.kind))).sort();
  const rows: BucketRow[] = Array.from({ length: buckets }, (_, i) => {
    const row: BucketRow = { bucket: i, total: 0 };
    for (const k of kinds) row[k] = 0;
    return row;
  });
  for (const o of operators) {
    const t = (o.timestamp_ns - tsMin) / tsR;
    const idx = Math.min(buckets - 1, Math.floor(t * buckets));
    rows[idx]!.total += 1;
    rows[idx]![o.payload.kind] = (rows[idx]![o.payload.kind] ?? 0) + 1;
  }
  return { rows, kinds };
}

export function OperatorsView({ operators }: { operators: OperatorEvent[] }) {
  const kindRows = useMemo(() => buildKindRows(operators), [operators]);
  const series = useMemo(
    () => buildTimeSeries(operators, Math.min(20, Math.max(6, Math.floor(operators.length / 8)))),
    [operators],
  );

  if (operators.length === 0) {
    return (
      <EmptyState
        title="No operators logged"
        detail="The Operators view shows the per-kind breakdown for runs that emit OperatorEvents."
      />
    );
  }

  const loggedCost = sumObservedNumbers(operators, (o) => o.payload.cost_usd);
  const hasLoggedTokens = kindRows.some((r) => r.tokenCount > 0);
  const totalCrossover = kindRows.reduce((a, r) => a + r.crossover, 0);
  const distinctKinds = kindRows.length;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Operators" value={operators.length} />
        <StatCard
          label="Distinct kinds"
          value={distinctKinds}
          hint={kindRows.map((r) => r.kind).join(", ")}
        />
        <StatCard
          label="Crossover ops"
          value={totalCrossover}
          hint="parent_ids ≥ 2"
        />
        {loggedCost.observed ? (
          <StatCard
            label="Total LLM cost"
            value={formatUsd(loggedCost.total)}
            hint={`sum of ${loggedCost.count} logged value${loggedCost.count === 1 ? "" : "s"}`}
          />
        ) : null}
      </div>

      {/* per-kind breakdown */}
      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
        <h3 className="mb-2 text-sm font-medium text-neutral-800 dark:text-neutral-200">
          Per-kind breakdown
        </h3>
        <div className="grid gap-4 md:grid-cols-[2fr_3fr]">
          <div className="h-56 w-full">
            <ResponsiveContainer>
              <BarChart
                data={kindRows}
                layout="vertical"
                margin={{ top: 4, right: 8, left: 8, bottom: 0 }}
              >
                <CartesianGrid
                  stroke="currentColor"
                  className="text-neutral-200 dark:text-neutral-800"
                  strokeDasharray="3 3"
                />
                <XAxis
                  type="number"
                  stroke="currentColor"
                  className="text-neutral-500"
                  fontSize={10}
                />
                <YAxis
                  type="category"
                  dataKey="kind"
                  stroke="currentColor"
                  className="text-neutral-500"
                  fontSize={11}
                  width={88}
                />
                <Tooltip
                  contentStyle={{
                    background: "#ffffff",
                    border: "1px solid #e5e5e5",
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "#525252" }}
                />
                <Bar dataKey="count" radius={[0, 3, 3, 0]}>
                  {kindRows.map((r) => (
                    <Cell key={r.kind} fill={r.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="py-1 pr-3">Kind</th>
                  <th className="py-1 pr-3 text-right">Count</th>
                  <th className="py-1 pr-3 text-right">Avg fanout</th>
                  {loggedCost.observed ? (
                    <th className="py-1 pr-3 text-right">Cost (sum)</th>
                  ) : null}
                  {hasLoggedTokens ? (
                    <th className="py-1 text-right">Tokens (in/out)</th>
                  ) : null}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 text-neutral-700 dark:divide-neutral-900 dark:text-neutral-300">
                {kindRows.map((r) => (
                  <tr key={r.kind}>
                    <td className="py-1 pr-3">
                      <span className="inline-flex items-center gap-2">
                        <span
                          className="inline-block h-2 w-2 rounded-full"
                          style={{ background: r.color }}
                        />
                        <span className="font-mono text-xs">{r.kind}</span>
                      </span>
                    </td>
                    <td className="py-1 pr-3 text-right font-mono text-xs">{r.count}</td>
                    <td className="py-1 pr-3 text-right font-mono text-xs">
                      {r.fanout.toFixed(2)}
                    </td>
                    {loggedCost.observed ? (
                      <td className="py-1 pr-3 text-right font-mono text-xs">
                        {r.costCount > 0 ? formatUsd(r.totalCostUsd) : "—"}
                      </td>
                    ) : null}
                    {hasLoggedTokens ? (
                      <td className="py-1 text-right font-mono text-xs text-neutral-500">
                        {r.tokenCount > 0
                          ? `${r.totalTokensIn} / ${r.totalTokensOut}`
                          : "—"}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* operators over time */}
      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
        <h3 className="text-sm font-medium text-neutral-800 dark:text-neutral-200">
          Operators over time
        </h3>
        <p className="text-xs text-neutral-500">
          Operators bucketed across the run&apos;s wall-clock span. One line per kind.
        </p>
        <div className="mt-3 h-64 w-full">
          <ResponsiveContainer>
            <LineChart data={series.rows} margin={{ top: 8, right: 16, left: -8, bottom: 0 }}>
              <CartesianGrid
                stroke="currentColor"
                className="text-neutral-200 dark:text-neutral-800"
                strokeDasharray="3 3"
              />
              <XAxis
                dataKey="bucket"
                stroke="currentColor"
                className="text-neutral-500"
                fontSize={11}
              />
              <YAxis stroke="currentColor" className="text-neutral-500" fontSize={11} />
              <Tooltip
                contentStyle={{
                  background: "#ffffff",
                  border: "1px solid #e5e5e5",
                  fontSize: 12,
                }}
                labelStyle={{ color: "#525252" }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {series.kinds.map((k) => (
                <Line
                  key={k}
                  type="monotone"
                  dataKey={k}
                  stroke={KIND_COLOR[k] ?? "#6b7280"}
                  strokeWidth={1.5}
                  dot={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-xs text-neutral-500 dark:border-neutral-800 dark:bg-neutral-950">
        For a system that records mutate / crossover / select distinctly (e.g.
        the SDK-direct path or the skill-driven path), this view shows the
        evolutionary cadence at a glance. Adapters that conservatively label
        every operator <code>refine</code> (OpenEvolve, AlphaEvolve checkpoints)
        will collapse to a single row here.
      </div>
    </div>
  );
}
