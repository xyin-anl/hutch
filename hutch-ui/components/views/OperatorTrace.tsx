"use client";

import { useMemo } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import type {
  IndividualEvent,
  OperatorEvent,
} from "@/lib/types";

interface Lane {
  id: string;
  ops: { ts: number; kind: string; childId: string; parents: string[] }[];
}

const ROW_H = 28;
const PAD_LEFT = 96;
const PAD_RIGHT = 16;
const PAD_TOP = 28;
const W = 900;
const KIND_COLOR: Record<string, string> = {
  refine: "#34d399",
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
  edit_diff: "#10b981",
  evaluate: "#737373",
  review: "#737373",
};

export function OperatorTraceView({
  operators,
  individuals,
}: {
  operators: OperatorEvent[];
  individuals: IndividualEvent[];
}) {
  /**
   * Lane id for each Individual: the explicit stream_id / worker_id wins,
   * else fall back to island_id (so multi-island runs without stream_id
   * still split into per-island lanes), else "default".
   */
  const individualLane = useMemo(() => {
    const out = new Map<string, string>();
    for (const i of individuals) {
      const lane =
        i.stream_id ??
        i.worker_id ??
        (i.payload.island_id != null ? `island-${i.payload.island_id}` : null) ??
        "default";
      out.set(i.payload.id, lane);
    }
    return out;
  }, [individuals]);

  /**
   * Lane id for each operator: explicit envelope wins, else inherit from
   * the child Individual's lane (most agents set island_id on the child
   * but not on the operator). Without this fallback, agent-driven runs
   * pile every operator into a single "default" lane even when the work
   * is clearly per-island.
   */
  function streamFor(ev: OperatorEvent): string {
    if (ev.stream_id) return ev.stream_id;
    if (ev.worker_id) return ev.worker_id;
    const childLane = individualLane.get(ev.payload.child_id);
    if (childLane) return childLane;
    return "default";
  }

  const lanes = useMemo<Lane[]>(() => {
    const byLane = new Map<string, Lane["ops"]>();
    for (const op of operators) {
      const lane = streamFor(op);
      const arr = byLane.get(lane) ?? [];
      arr.push({
        ts: op.timestamp_ns,
        kind: op.payload.kind,
        childId: op.payload.child_id,
        parents: op.payload.parent_ids,
      });
      byLane.set(lane, arr);
    }
    return Array.from(byLane.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([id, ops]) => ({
        id,
        ops: ops.sort((a, b) => a.ts - b.ts),
      }));
    // streamFor depends on individualLane which is in scope; we list the
    // primary inputs for clarity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [operators, individualLane]);

  if (operators.length === 0) {
    return (
      <EmptyState
        title="No operators logged"
        detail="The Operator-trace view activates once a run logs OperatorEvents."
      />
    );
  }

  const allTs = operators.map((o) => o.timestamp_ns);
  const tsMin = Math.min(...allTs);
  const tsMax = Math.max(...allTs);
  const tsR = tsMax - tsMin || 1;
  const xOf = (ts: number) =>
    PAD_LEFT + ((ts - tsMin) / tsR) * (W - PAD_LEFT - PAD_RIGHT);
  const yOf = (laneId: string) => {
    const idx = lanes.findIndex((l) => l.id === laneId);
    return PAD_TOP + idx * ROW_H + ROW_H / 2;
  };
  const totalH = PAD_TOP + lanes.length * ROW_H + 24;

  // Cross-lane edges: an operator on lane L whose parent's lane != L.
  const crossLane: { fromX: number; fromY: number; toX: number; toY: number }[] = [];
  for (const lane of lanes) {
    for (const op of lane.ops) {
      for (const p of op.parents) {
        const parentLane = individualLane.get(p);
        if (parentLane && parentLane !== lane.id) {
          crossLane.push({
            fromX: xOf(op.ts),
            fromY: yOf(parentLane),
            toX: xOf(op.ts),
            toY: yOf(lane.id),
          });
        }
      }
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
        <h3 className="mb-2 text-sm font-medium text-neutral-800 dark:text-neutral-200">
          {lanes.length} stream{lanes.length === 1 ? "" : "s"} ·{" "}
          {operators.length} operator{operators.length === 1 ? "" : "s"}
        </h3>
        <svg
          viewBox={`0 0 ${W} ${totalH}`}
          className="w-full select-none"
          style={{ height: `${totalH}px`, maxHeight: "560px" }}
        >
          {/* lane bands + labels */}
          {lanes.map((lane, i) => (
            <g key={lane.id}>
              <rect
                x={PAD_LEFT}
                y={PAD_TOP + i * ROW_H}
                width={W - PAD_LEFT - PAD_RIGHT}
                height={ROW_H - 2}
                className={
                  i % 2 === 0
                    ? "fill-neutral-50 dark:fill-neutral-900"
                    : "fill-neutral-100 dark:fill-neutral-925"
                }
              />
              <text
                x={PAD_LEFT - 8}
                y={yOf(lane.id) + 3}
                textAnchor="end"
                fontSize={10}
                className="fill-neutral-600 dark:fill-neutral-400"
                style={{ fontFamily: "ui-monospace,monospace" }}
              >
                {lane.id}
              </text>
            </g>
          ))}
          {/* cross-lane connectors first (behind dots) */}
          {crossLane.map((e, i) => (
            <line
              key={`xl-${i}`}
              x1={e.fromX}
              y1={e.fromY}
              x2={e.toX}
              y2={e.toY}
              className="stroke-neutral-400 dark:stroke-neutral-600"
              strokeOpacity={0.7}
              strokeWidth={0.8}
              strokeDasharray="2 2"
            />
          ))}
          {/* operator markers */}
          {lanes.map((lane) =>
            lane.ops.map((op, idx) => (
              <g key={`${lane.id}-${idx}`}>
                <circle
                  cx={xOf(op.ts)}
                  cy={yOf(lane.id)}
                  r={4}
                  fill={KIND_COLOR[op.kind] ?? "#6b7280"}
                  className="stroke-white dark:stroke-neutral-950"
                  strokeWidth={0.75}
                >
                  <title>{`${op.kind}\n→ ${op.childId}\nparents ${op.parents.join(", ") || "(none)"}\nstream ${lane.id}`}</title>
                </circle>
              </g>
            )),
          )}
          {/* x-axis labels */}
          <g>
            <text
              x={PAD_LEFT}
              y={PAD_TOP - 10}
              fontSize={10}
              className="fill-neutral-500"
              style={{ fontFamily: "ui-monospace,monospace" }}
            >
              t=0
            </text>
            <text
              x={W - PAD_RIGHT}
              y={PAD_TOP - 10}
              textAnchor="end"
              fontSize={10}
              className="fill-neutral-500"
              style={{ fontFamily: "ui-monospace,monospace" }}
            >
              {((tsMax - tsMin) / 1_000_000).toFixed(1)} ms span
            </text>
          </g>
        </svg>

        {/* legend */}
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500">
          {Array.from(new Set(operators.map((o) => o.payload.kind)))
            .sort()
            .map((kind) => (
              <span key={kind} className="flex items-center gap-1.5">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: KIND_COLOR[kind] ?? "#6b7280" }}
                />
                {kind}
              </span>
            ))}
        </div>
      </div>

      <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-xs text-neutral-500 dark:border-neutral-800 dark:bg-neutral-950">
        One row per <code>stream_id</code> / <code>worker_id</code>; falls back
        to <code>island_id</code> for the parent lookup when streams aren&apos;t
        explicit. Dashed connectors mark cross-lane parent→child relationships
        (e.g. crossover between islands).
      </div>
    </div>
  );
}
