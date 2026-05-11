"use client";

import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import type { FitnessEvent, OperatorEvent, ScoreDirection } from "@/lib/types";

// ---------- shared types --------------------------------------------------

interface PointSample {
  individualId: string;
  operatorKind: string;
  scores: Record<string, number>;
  ts: number;
}

type Direction = "higher" | "lower";

type SubMode = "tradeoff" | "best-so-far" | "distribution" | "parallel";

const SUBMODE_LABEL: Record<SubMode, string> = {
  tradeoff: "Trade-off",
  "best-so-far": "Best so far",
  distribution: "Distribution",
  parallel: "Parallel coords",
};

const OPERATION_COLOR: Record<string, string> = {
  seed: "#9ca3af",
  propose: "#3b82f6",
  refine: "#10b981",
  mutate: "#22c55e",
  crossover: "#8b5cf6",
  select: "#f59e0b",
  diversify: "#06b6d4",
  self_modify: "#ef4444",
  distill: "#fb7185",
  migrate: "#f97316",
  meta_mutate: "#eab308",
  tree_expand: "#8b5cf6",
  edit_diff: "#10b981",
  evaluate: "#737373",
  review: "#737373",
};

function colorForOperation(kind: string): string {
  return OPERATION_COLOR[kind] ?? "#737373";
}

// ---------- direction helpers ---------------------------------------------

const LOWER_HINTS = [
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

function guessDirection(metric: string): Direction {
  return LOWER_HINTS.some((re) => re.test(metric)) ? "lower" : "higher";
}

function makeResolveDirection(
  scoreDirections: Record<string, ScoreDirection> | undefined,
) {
  return (metric: string): Direction =>
    scoreDirections?.[metric] ?? guessDirection(metric);
}

// ---------- shared data prep ----------------------------------------------

function collectPoints(
  fitness: FitnessEvent[],
  operators: OperatorEvent[],
): PointSample[] {
  const operationByIndividual = new Map<string, string>();
  for (const op of operators) {
    operationByIndividual.set(op.payload.child_id, op.payload.kind);
  }
  const out: PointSample[] = [];
  for (const f of fitness) {
    if (f.payload.invalid_reason) continue;
    const valid = Object.entries(f.payload.scores ?? {})
      .filter(([, v]) => Number.isFinite(v))
      .reduce<Record<string, number>>((acc, [k, v]) => {
        acc[k] = v;
        return acc;
      }, {});
    if (Object.keys(valid).length >= 1) {
      out.push({
        individualId: f.payload.individual_id,
        operatorKind: operationByIndividual.get(f.payload.individual_id) ?? "seed",
        scores: valid,
        ts: f.timestamp_ns,
      });
    }
  }
  return out;
}

function rankObjectives(points: PointSample[]): string[] {
  const counts = new Map<string, number>();
  for (const p of points)
    for (const k of Object.keys(p.scores)) counts.set(k, (counts.get(k) ?? 0) + 1);
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([k]) => k);
}

// ---------- top-level dispatcher ------------------------------------------

export function ObjectivesView({
  fitness,
  operators,
  scoreDirections,
}: {
  fitness: FitnessEvent[];
  operators: OperatorEvent[];
  scoreDirections?: Record<string, ScoreDirection>;
}) {
  const points = useMemo(() => collectPoints(fitness, operators), [fitness, operators]);
  const objectives = useMemo(() => rankObjectives(points), [points]);
  const [mode, setMode] = useState<SubMode>("tradeoff");

  if (points.length === 0 || objectives.length === 0) {
    return (
      <EmptyState
        title="No fitness scores yet"
        detail="The Objectives view activates once a run logs FitnessEvents with named scores."
      />
    );
  }

  const resolveDirection = makeResolveDirection(scoreDirections);

  // Sub-mode availability:
  //  - tradeoff: needs ≥2 metrics
  //  - parallel: needs ≥3 metrics (otherwise it's just two axes)
  //  - best-so-far / distribution: any number, including 1
  const tradeoffAvailable = objectives.length >= 2;
  const parallelAvailable = objectives.length >= 3;
  const isModeAvailable = (m: SubMode) =>
    !(
      (m === "tradeoff" && !tradeoffAvailable) ||
      (m === "parallel" && !parallelAvailable)
    );
  const effectiveMode = isModeAvailable(mode)
    ? mode
    : tradeoffAvailable
      ? "tradeoff"
      : "best-so-far";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1 rounded-lg border border-neutral-200 bg-white p-1 dark:border-neutral-800 dark:bg-neutral-950">
          {(["tradeoff", "best-so-far", "distribution", "parallel"] as SubMode[]).map(
            (m) => {
              const disabled =
                (m === "tradeoff" && !tradeoffAvailable) ||
                (m === "parallel" && !parallelAvailable);
              const active = effectiveMode === m;
              return (
                <button
                  key={m}
                  type="button"
                  disabled={disabled}
                  onClick={() => !disabled && setMode(m)}
                  className={`rounded px-3 py-1 text-xs transition-colors ${
                    active
                      ? "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-neutral-950"
                      : disabled
                        ? "cursor-not-allowed text-neutral-400 dark:text-neutral-600"
                        : "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-900"
                  }`}
                  title={
                    m === "tradeoff" && !tradeoffAvailable
                      ? "needs ≥2 distinct metrics"
                      : m === "parallel" && !parallelAvailable
                        ? "needs ≥3 distinct metrics"
                        : undefined
                  }
                >
                  {SUBMODE_LABEL[m]}
                </button>
              );
            },
          )}
        </div>
        <div className="text-xs text-neutral-500">
          <span className="font-mono">{points.length}</span> fitness samples ·{" "}
          <span className="font-mono">{objectives.length}</span>{" "}
          {objectives.length === 1 ? "metric" : "metrics"}
        </div>
      </div>

      {effectiveMode === "tradeoff" && tradeoffAvailable ? (
        <TradeoffPanel
          points={points}
          objectives={objectives}
          resolveDirection={resolveDirection}
        />
      ) : effectiveMode === "best-so-far" ? (
        <BestSoFarPanel
          points={points}
          objectives={objectives}
          resolveDirection={resolveDirection}
        />
      ) : effectiveMode === "distribution" ? (
        <DistributionPanel
          points={points}
          objectives={objectives}
          resolveDirection={resolveDirection}
        />
      ) : effectiveMode === "parallel" && parallelAvailable ? (
        <ParallelPanel
          points={points}
          objectives={objectives}
          resolveDirection={resolveDirection}
        />
      ) : (
        <EmptyState
          title="Sub-mode unavailable"
          detail="Try a different mode above."
        />
      )}
    </div>
  );
}

// ============================================================================
// Sub-mode 1: Trade-off (the original Pareto scatter + frontier)
// ============================================================================

const PAD = 36;
const W = 920;
const H = 420;

function paretoFrontIndices(
  pts: PointSample[],
  xKey: string,
  yKey: string,
  xDir: Direction,
  yDir: Direction,
): Set<number> {
  const xSign = xDir === "higher" ? 1 : -1;
  const ySign = yDir === "higher" ? 1 : -1;
  const front = new Set<number>();
  for (let i = 0; i < pts.length; i++) {
    const xi = xSign * pts[i]!.scores[xKey]!;
    const yi = ySign * pts[i]!.scores[yKey]!;
    let dominated = false;
    for (let j = 0; j < pts.length; j++) {
      if (i === j) continue;
      const xj = xSign * pts[j]!.scores[xKey]!;
      const yj = ySign * pts[j]!.scores[yKey]!;
      if (xj >= xi && yj >= yi && (xj > xi || yj > yi)) {
        dominated = true;
        break;
      }
    }
    if (!dominated) front.add(i);
  }
  return front;
}

function hypervolume2D(
  front: PointSample[],
  xKey: string,
  yKey: string,
  refX: number,
  refY: number,
  xDir: Direction,
  yDir: Direction,
): number {
  const xSign = xDir === "higher" ? 1 : -1;
  const ySign = yDir === "higher" ? 1 : -1;
  const sorted = [...front].sort(
    (a, b) =>
      xSign * (a.scores[xKey]! - b.scores[xKey]!) ||
      ySign * (a.scores[yKey]! - b.scores[yKey]!),
  );
  const refXEff = xSign * refX;
  const refYEff = ySign * refY;
  let area = 0;
  let prevX = refXEff;
  for (const p of sorted) {
    const x = xSign * p.scores[xKey]!;
    const y = ySign * p.scores[yKey]!;
    if (x <= refXEff || y <= refYEff) continue;
    area += (x - prevX) * (y - refYEff);
    prevX = x;
  }
  return area;
}

function TradeoffPanel({
  points,
  objectives,
  resolveDirection,
}: {
  points: PointSample[];
  objectives: string[];
  resolveDirection: (m: string) => Direction;
}) {
  const [xKey, setXKey] = useState<string>(objectives[0] ?? "");
  const [yKey, setYKey] = useState<string>(objectives[1] ?? "");
  const [xDir, setXDir] = useState<Direction>(() => resolveDirection(objectives[0] ?? ""));
  const [yDir, setYDir] = useState<Direction>(() => resolveDirection(objectives[1] ?? ""));

  const filtered = points.filter(
    (p) => Number.isFinite(p.scores[xKey]) && Number.isFinite(p.scores[yKey]),
  );
  const xs = filtered.map((p) => p.scores[xKey]!);
  const ys = filtered.map((p) => p.scores[yKey]!);
  if (xs.length === 0 || ys.length === 0) {
    return (
      <EmptyState
        title="No samples carry both selected metrics"
        detail="Pick a different x / y above."
      />
    );
  }
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const xR = xMax - xMin || 1;
  const yR = yMax - yMin || 1;
  const sx = (v: number) => PAD + ((v - xMin) / xR) * (W - 2 * PAD);
  const sy = (v: number) => H - PAD - ((v - yMin) / yR) * (H - 2 * PAD);

  const frontIdx = paretoFrontIndices(filtered, xKey, yKey, xDir, yDir);
  const front = Array.from(frontIdx).map((i) => filtered[i]!);
  const refX = xDir === "higher" ? xMin : xMax;
  const refY = yDir === "higher" ? yMin : yMax;
  const hv = hypervolume2D(front, xKey, yKey, refX, refY, xDir, yDir);
  const ticks = (axisMin: number, axisMax: number) =>
    Array.from({ length: 5 }, (_, i) => axisMin + ((axisMax - axisMin) / 4) * i);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs text-neutral-500">
          <AxisPicker
            label="x"
            value={xKey}
            options={objectives}
            dir={xDir}
            onChange={(k) => {
              setXKey(k);
              setXDir(resolveDirection(k));
            }}
            onFlip={() => setXDir((d) => (d === "higher" ? "lower" : "higher"))}
          />
          <AxisPicker
            label="y"
            value={yKey}
            options={objectives}
            dir={yDir}
            onChange={(k) => {
              setYKey(k);
              setYDir(resolveDirection(k));
            }}
            onFlip={() => setYDir((d) => (d === "higher" ? "lower" : "higher"))}
          />
        </div>
        <div className="flex items-center gap-3 text-xs text-neutral-600 dark:text-neutral-400">
          <span>
            <span className="text-neutral-500">front size</span>{" "}
            <span className="font-mono">{front.length}</span>
          </span>
          <span>
            <span className="text-neutral-500">hypervolume</span>{" "}
            <span className="font-mono">{hv.toFixed(4)}</span>
          </span>
        </div>
      </div>

      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-[440px] w-full select-none">
          <line
            x1={PAD}
            y1={H - PAD}
            x2={W - PAD}
            y2={H - PAD}
            className="stroke-neutral-300 dark:stroke-neutral-700"
            strokeWidth={1}
          />
          <line
            x1={PAD}
            y1={PAD}
            x2={PAD}
            y2={H - PAD}
            className="stroke-neutral-300 dark:stroke-neutral-700"
            strokeWidth={1}
          />
          {ticks(xMin, xMax).map((t, i) => (
            <g key={`x-${i}`}>
              <line
                x1={sx(t)}
                y1={H - PAD}
                x2={sx(t)}
                y2={H - PAD + 4}
                className="stroke-neutral-400 dark:stroke-neutral-600"
              />
              <text
                x={sx(t)}
                y={H - PAD + 16}
                textAnchor="middle"
                fontSize={10}
                className="fill-neutral-500"
              >
                {t.toFixed(2)}
              </text>
            </g>
          ))}
          {ticks(yMin, yMax).map((t, i) => (
            <g key={`y-${i}`}>
              <line
                x1={PAD}
                y1={sy(t)}
                x2={PAD - 4}
                y2={sy(t)}
                className="stroke-neutral-400 dark:stroke-neutral-600"
              />
              <text
                x={PAD - 6}
                y={sy(t) + 3}
                textAnchor="end"
                fontSize={10}
                className="fill-neutral-500"
              >
                {t.toFixed(2)}
              </text>
            </g>
          ))}
          <text
            x={W / 2}
            y={H - 4}
            textAnchor="middle"
            fontSize={11}
            className="fill-neutral-700 dark:fill-neutral-300"
          >
            {xKey} ({xDir === "higher" ? "↑ better" : "↓ better"})
          </text>
          <text
            x={12}
            y={H / 2}
            textAnchor="middle"
            fontSize={11}
            className="fill-neutral-700 dark:fill-neutral-300"
            transform={`rotate(-90 12 ${H / 2})`}
          >
            {yKey} ({yDir === "higher" ? "↑ better" : "↓ better"})
          </text>
          {filtered.map((p, i) =>
            frontIdx.has(i) ? null : (
              <circle
                key={p.individualId + i}
                cx={sx(p.scores[xKey]!)}
                cy={sy(p.scores[yKey]!)}
                r={3}
                className="fill-neutral-400 dark:fill-neutral-600"
                fillOpacity={0.85}
              >
                <title>{`${p.individualId}\n${xKey}=${p.scores[xKey]!.toFixed(3)}\n${yKey}=${p.scores[yKey]!.toFixed(3)}`}</title>
              </circle>
            ),
          )}
          <g>
            {(() => {
              const sortedFront = [...front].sort(
                (a, b) => a.scores[xKey]! - b.scores[xKey]!,
              );
              const path = sortedFront
                .map(
                  (p, i) =>
                    `${i === 0 ? "M" : "L"} ${sx(p.scores[xKey]!)} ${sy(p.scores[yKey]!)}`,
                )
                .join(" ");
              return (
                <path
                  d={path}
                  fill="none"
                  stroke="#059669"
                  strokeOpacity={0.7}
                  strokeWidth={1.25}
                />
              );
            })()}
          </g>
          {filtered.map((p, i) =>
            frontIdx.has(i) ? (
              <circle
                key={p.individualId + i}
                cx={sx(p.scores[xKey]!)}
                cy={sy(p.scores[yKey]!)}
                r={5}
                fill="#059669"
                className="stroke-white dark:stroke-neutral-950"
                strokeWidth={1.5}
              >
                <title>{`pareto front: ${p.individualId}\n${xKey}=${p.scores[xKey]!.toFixed(3)}\n${yKey}=${p.scores[yKey]!.toFixed(3)}`}</title>
              </circle>
            ) : null,
          )}
        </svg>
      </div>

      <p className="text-xs text-neutral-500">
        Green points are the Pareto-optimal individuals — no other individual
        beats them on both axes. The ▲/▼ buttons next to each selector flip
        which direction is &quot;better.&quot; Hypervolume is computed against
        the worst-observed corner per direction; treat it as a relative
        number, not an absolute QD score.
      </p>
    </div>
  );
}

function AxisPicker({
  label,
  value,
  options,
  dir,
  onChange,
  onFlip,
}: {
  label: string;
  value: string;
  options: string[];
  dir: Direction;
  onChange: (v: string) => void;
  onFlip: () => void;
}) {
  return (
    <span className="flex items-center gap-1">
      <span>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-neutral-200 bg-white px-2 py-1 text-neutral-800 dark:border-neutral-800 dark:bg-neutral-950 dark:text-neutral-200"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={onFlip}
        title={`${dir === "higher" ? "higher is better" : "lower is better"} (click to flip)`}
        className="rounded border border-neutral-200 bg-white px-1.5 py-1 font-mono text-neutral-600 hover:border-neutral-400 dark:border-neutral-800 dark:bg-neutral-950 dark:text-neutral-400"
      >
        {dir === "higher" ? "▲" : "▼"}
      </button>
    </span>
  );
}

// ============================================================================
// Sub-mode 2: Best-so-far staircase
// ============================================================================

function BestSoFarPanel({
  points,
  objectives,
  resolveDirection,
}: {
  points: PointSample[];
  objectives: string[];
  resolveDirection: (m: string) => Direction;
}) {
  // Sort by timestamp once; per metric, walk and emit the running best.
  const sorted = useMemo(() => [...points].sort((a, b) => a.ts - b.ts), [points]);
  const tsMin = sorted[0]?.ts ?? 0;
  const tsMax = sorted[sorted.length - 1]?.ts ?? 1;
  const tsR = tsMax - tsMin || 1;

  // Per-metric step series.
  const series = useMemo(() => {
    return objectives.map((m) => {
      const dir = resolveDirection(m);
      const cmp = (a: number, b: number) => (dir === "higher" ? a > b : a < b);
      let best: number | null = null;
      const samples = sorted
        .filter((p) => Number.isFinite(p.scores[m]))
        .map((p) => ({
          individualId: p.individualId,
          operatorKind: p.operatorKind,
          t: (p.ts - tsMin) / tsR,
          v: p.scores[m]!,
          improves: false,
        }));
      const steps: {
        t: number;
        v: number;
        individualId: string;
        operatorKind: string;
      }[] = [];
      const improvingIds = new Set<string>();
      for (const p of sorted) {
        const v = p.scores[m];
        if (!Number.isFinite(v)) continue;
        if (best === null || cmp(v!, best)) {
          best = v!;
          steps.push({
            t: (p.ts - tsMin) / tsR,
            v: best,
            individualId: p.individualId,
            operatorKind: p.operatorKind,
          });
          improvingIds.add(p.individualId);
        }
      }
      for (const sample of samples) {
        sample.improves = improvingIds.has(sample.individualId);
      }
      const operations = Array.from(new Set(samples.map((s) => s.operatorKind))).sort();
      return { metric: m, dir, samples, steps, operations, finalBest: best };
    });
  }, [sorted, objectives, resolveDirection, tsMin, tsR]);

  const PADX = 48;
  const PADY = 34;
  const PW = 920;
  const PH = 320;

  return (
    <div className="space-y-4">
      <p className="text-xs text-neutral-500">
        Per-metric cumulative best over wall-clock time. Each metric is
        normalised so the y-axis always reads &quot;better → up,&quot; using
        the schema-declared direction (or a name-based fallback). One panel
        per metric; the labelled value is the final best.
      </p>
      <div className="space-y-4">
        {series.map(({ metric, dir, samples, steps, operations, finalBest }) => {
          if (steps.length === 0) return null;
          const vs = samples.map((s) => s.v);
          // Normalise to [0,1] in the "better" direction so the y-axis
          // always points up = better.
          const vMin = Math.min(...vs);
          const vMax = Math.max(...vs);
          const vR = vMax - vMin || 1;
          const sx = (t: number) => PADX + t * (PW - 2 * PADX);
          const sy = (v: number) =>
            PH - PADY -
            ((dir === "higher" ? v - vMin : vMax - v) / vR) * (PH - 2 * PADY);
          const path = steps
            .flatMap((s, i) =>
              i === 0
                ? [`M ${sx(s.t)} ${sy(s.v)}`]
                : [
                    `L ${sx(s.t)} ${sy(steps[i - 1]!.v)}`,
                    `L ${sx(s.t)} ${sy(s.v)}`,
                  ],
            )
            .concat([`L ${sx(1)} ${sy(steps[steps.length - 1]!.v)}`])
            .join(" ");
          return (
            <div
              key={metric}
              className="rounded-lg border border-neutral-200 bg-white p-3 dark:border-neutral-800 dark:bg-neutral-950"
            >
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="font-mono text-neutral-700 dark:text-neutral-300">
                  {metric}
                </span>
                <span className="text-neutral-500">
                  {dir === "higher" ? "↑ better" : "↓ better"} ·{" "}
                  <span className="font-mono">
                    best {finalBest !== null ? finalBest.toFixed(3) : "—"}
                  </span>{" "}
                  · {steps.length} improvement{steps.length === 1 ? "" : "s"}
                </span>
              </div>
              <svg viewBox={`0 0 ${PW} ${PH}`} className="h-72 w-full">
                <line
                  x1={PADX}
                  y1={PH - PADY}
                  x2={PW - PADX}
                  y2={PH - PADY}
                  className="stroke-neutral-300 dark:stroke-neutral-700"
                />
                <line
                  x1={PADX}
                  y1={PADY}
                  x2={PADX}
                  y2={PH - PADY}
                  className="stroke-neutral-300 dark:stroke-neutral-700"
                />
                <text
                  x={PADX - 4}
                  y={PADY + 8}
                  textAnchor="end"
                  fontSize={10}
                  className="fill-neutral-500"
                >
                  {dir === "higher" ? vMax.toFixed(2) : vMin.toFixed(2)}
                </text>
                <text
                  x={PADX - 4}
                  y={PH - PADY + 2}
                  textAnchor="end"
                  fontSize={10}
                  className="fill-neutral-500"
                >
                  {dir === "higher" ? vMin.toFixed(2) : vMax.toFixed(2)}
                </text>
                <path d={path} fill="none" stroke="#059669" strokeWidth={1.75} />
                {samples.map((s) => (
                  <circle
                    key={`${s.individualId}-${s.t}-${s.v}`}
                    cx={sx(s.t)}
                    cy={sy(s.v)}
                    r={s.improves ? 4 : 3}
                    fill={colorForOperation(s.operatorKind)}
                    fillOpacity={s.improves ? 0.95 : 0.45}
                    className="stroke-white dark:stroke-neutral-950"
                    strokeWidth={s.improves ? 1.25 : 0.5}
                  >
                    <title>{`${s.individualId}\n${s.operatorKind}\n${metric} = ${s.v.toFixed(3)}${s.improves ? "\nimproved best" : ""}`}</title>
                  </circle>
                ))}
              </svg>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500">
                <span className="flex items-center gap-1.5">
                  <span className="h-0.5 w-5 bg-emerald-600" />
                  incumbent best
                </span>
                {operations.map((operation) => (
                  <span key={operation} className="flex items-center gap-1.5">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ background: colorForOperation(operation) }}
                    />
                    {operation}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ============================================================================
// Sub-mode 3: Distribution histogram per metric
// ============================================================================

function DistributionPanel({
  points,
  objectives,
  resolveDirection,
}: {
  points: PointSample[];
  objectives: string[];
  resolveDirection: (m: string) => Direction;
}) {
  const PADX = 36;
  const PADY = 28;
  const PW = 920;
  const PH = 260;
  const BINS = 16;

  return (
    <div className="space-y-4">
      <p className="text-xs text-neutral-500">
        Marginal distribution of each metric across all valid fitness
        samples. Bin count fixed at {BINS}. The arrow on each title indicates
        the &quot;better&quot; direction; the histogram itself isn&apos;t flipped
        — read it as raw observed values.
      </p>
      <div className="space-y-4">
        {objectives.map((metric) => {
          const dir = resolveDirection(metric);
          const values = points
            .map((p) => p.scores[metric])
            .filter((v): v is number => Number.isFinite(v));
          if (values.length === 0) return null;
          const vMin = Math.min(...values);
          const vMax = Math.max(...values);
          const vR = vMax - vMin || 1;
          const bins = new Array(BINS).fill(0) as number[];
          for (const v of values) {
            const idx = Math.min(BINS - 1, Math.floor(((v - vMin) / vR) * BINS));
            bins[idx]! += 1;
          }
          const maxCount = Math.max(...bins);
          const barW = (PW - 2 * PADX) / BINS;
          return (
            <div
              key={metric}
              className="rounded-lg border border-neutral-200 bg-white p-3 dark:border-neutral-800 dark:bg-neutral-950"
            >
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="font-mono text-neutral-700 dark:text-neutral-300">
                  {metric}
                </span>
                <span className="text-neutral-500">
                  {dir === "higher" ? "↑ better" : "↓ better"} · n=
                  <span className="font-mono">{values.length}</span>
                </span>
              </div>
              <svg viewBox={`0 0 ${PW} ${PH}`} className="h-64 w-full">
                <line
                  x1={PADX}
                  y1={PH - PADY}
                  x2={PW - PADX}
                  y2={PH - PADY}
                  className="stroke-neutral-300 dark:stroke-neutral-700"
                />
                {bins.map((count, i) => {
                  const h = ((PH - 2 * PADY) * count) / (maxCount || 1);
                  return (
                    <rect
                      key={i}
                      x={PADX + i * barW + 1}
                      y={PH - PADY - h}
                      width={Math.max(0, barW - 2)}
                      height={h}
                      fill="#10b981"
                      fillOpacity={0.85}
                    >
                      <title>{`${metric} ∈ [${(vMin + (i * vR) / BINS).toFixed(3)}, ${(vMin + ((i + 1) * vR) / BINS).toFixed(3)}] · n=${count}`}</title>
                    </rect>
                  );
                })}
                <text
                  x={PADX}
                  y={PH - 6}
                  textAnchor="start"
                  fontSize={10}
                  className="fill-neutral-500"
                >
                  {vMin.toFixed(2)}
                </text>
                <text
                  x={PW - PADX}
                  y={PH - 6}
                  textAnchor="end"
                  fontSize={10}
                  className="fill-neutral-500"
                >
                  {vMax.toFixed(2)}
                </text>
              </svg>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ============================================================================
// Sub-mode 4: Parallel coordinates (3+ metrics)
// ============================================================================

function ParallelPanel({
  points,
  objectives,
  resolveDirection,
}: {
  points: PointSample[];
  objectives: string[];
  resolveDirection: (m: string) => Direction;
}) {
  const PADX = 60;
  const PADY = 36;
  const PW = 920;
  const PH = 360;

  // Per-metric min/max across observed values.
  const ranges = useMemo(() => {
    const out = new Map<string, { min: number; max: number; dir: Direction }>();
    for (const m of objectives) {
      const vs = points
        .map((p) => p.scores[m])
        .filter((v): v is number => Number.isFinite(v));
      if (vs.length === 0) continue;
      out.set(m, { min: Math.min(...vs), max: Math.max(...vs), dir: resolveDirection(m) });
    }
    return out;
  }, [points, objectives, resolveDirection]);

  // Score color: average normalised "better-ness" across metrics, in [0,1].
  function betternessOf(p: PointSample): number {
    let sum = 0;
    let n = 0;
    for (const m of objectives) {
      const r = ranges.get(m);
      const v = p.scores[m];
      if (!r || !Number.isFinite(v)) continue;
      const span = r.max - r.min || 1;
      const norm =
        r.dir === "higher" ? (v! - r.min) / span : (r.max - v!) / span;
      sum += norm;
      n += 1;
    }
    return n === 0 ? 0 : sum / n;
  }

  const xOf = (idx: number) =>
    PADX + (idx / Math.max(1, objectives.length - 1)) * (PW - 2 * PADX);
  const yOf = (m: string, v: number): number => {
    const r = ranges.get(m);
    if (!r) return PH / 2;
    const span = r.max - r.min || 1;
    // Normalise to [0,1] in the "better" direction, then place on the
    // vertical axis (top = better).
    const norm =
      r.dir === "higher" ? (v - r.min) / span : (r.max - v) / span;
    return PH - PADY - norm * (PH - 2 * PADY);
  };

  // Sort by betterness so the best lines render on top.
  const sortedPoints = useMemo(
    () => [...points].sort((a, b) => betternessOf(a) - betternessOf(b)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [points, ranges],
  );

  return (
    <div className="space-y-3">
      <p className="text-xs text-neutral-500">
        Each line is one Individual; each vertical axis is one metric,
        normalised so the top is always &quot;better&quot; using the
        schema-declared direction. Lines are coloured by overall
        betterness (mean normalised score across metrics) so the best
        runs render in green near the top.
      </p>
      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
        <svg viewBox={`0 0 ${PW} ${PH}`} className="h-[360px] w-full select-none">
          {objectives.map((m, i) => (
            <g key={m}>
              <line
                x1={xOf(i)}
                y1={PADY}
                x2={xOf(i)}
                y2={PH - PADY}
                className="stroke-neutral-300 dark:stroke-neutral-700"
                strokeWidth={1}
              />
              <text
                x={xOf(i)}
                y={PADY - 8}
                textAnchor="middle"
                fontSize={11}
                className="fill-neutral-700 dark:fill-neutral-300"
              >
                {m}
              </text>
              <text
                x={xOf(i)}
                y={PADY - 22}
                textAnchor="middle"
                fontSize={9}
                className="fill-neutral-500"
              >
                {resolveDirection(m) === "higher" ? "↑ better" : "↓ better"}
              </text>
              <text
                x={xOf(i)}
                y={PADY + 4}
                textAnchor="middle"
                fontSize={9}
                className="fill-neutral-500"
              >
                {ranges.get(m)?.dir === "higher"
                  ? ranges.get(m)?.max.toFixed(2)
                  : ranges.get(m)?.min.toFixed(2)}
              </text>
              <text
                x={xOf(i)}
                y={PH - PADY + 12}
                textAnchor="middle"
                fontSize={9}
                className="fill-neutral-500"
              >
                {ranges.get(m)?.dir === "higher"
                  ? ranges.get(m)?.min.toFixed(2)
                  : ranges.get(m)?.max.toFixed(2)}
              </text>
            </g>
          ))}
          {sortedPoints.map((p, idx) => {
            const b = betternessOf(p);
            const stroke = colorRamp(b);
            const path = objectives
              .map((m, i) => {
                const v = p.scores[m];
                if (!Number.isFinite(v)) return null;
                return `${i === 0 ? "M" : "L"} ${xOf(i)} ${yOf(m, v!)}`;
              })
              .filter(Boolean)
              .join(" ");
            if (!path) return null;
            return (
              <path
                key={p.individualId + idx}
                d={path}
                fill="none"
                stroke={stroke}
                strokeOpacity={0.55}
                strokeWidth={1.0}
              >
                <title>
                  {`${p.individualId}\n${objectives
                    .map((m) =>
                      Number.isFinite(p.scores[m])
                        ? `${m}=${p.scores[m]!.toFixed(3)}`
                        : null,
                    )
                    .filter(Boolean)
                    .join("\n")}`}
                </title>
              </path>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

/** Tiny inline viridis-ish ramp from grey → emerald. */
function colorRamp(t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  // grey (#9ca3af) → emerald (#059669)
  const r = Math.round(156 + (5 - 156) * clamped);
  const g = Math.round(163 + (150 - 163) * clamped);
  const b = Math.round(175 + (105 - 175) * clamped);
  return `rgb(${r},${g},${b})`;
}
