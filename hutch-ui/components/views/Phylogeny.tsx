"use client";

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  interpolateViridis,
  select as d3Select,
  zoom as d3Zoom,
  zoomIdentity,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
  type ZoomBehavior,
} from "d3";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { bestFitnessByIndividual } from "@/lib/fitness";
import type { FitnessEvent, IndividualEvent, ScoreDirection } from "@/lib/types";

interface Node extends SimulationNodeDatum {
  id: string;
  kind: string;
  isSeed: boolean;
  fitness: number | null;
  parentCount: number;
  parentIds: string[];
}

interface Link extends SimulationLinkDatum<Node> {
  source: string | Node;
  target: string | Node;
  isCrossover: boolean;
}

type Layout = "force" | "hierarchical" | "radial";

const WIDTH = 720;
const HEIGHT = 480;

function buildGraph(
  individuals: IndividualEvent[],
  fitness: FitnessEvent[],
  scoreDirections: Record<string, ScoreDirection> | undefined,
): { nodes: Node[]; links: Link[]; minF: number; maxF: number } {
  const fitMap = bestFitnessByIndividual(fitness, scoreDirections);
  const nodes: Node[] = individuals.map((ind) => ({
    id: ind.payload.id,
    kind: ind.payload.kind,
    isSeed: ind.payload.is_seed,
    fitness: fitMap.get(ind.payload.id) ?? null,
    parentCount: ind.payload.parent_ids.length,
    parentIds: ind.payload.parent_ids,
  }));
  const ids = new Set(nodes.map((n) => n.id));
  const links: Link[] = [];
  for (const ind of individuals) {
    const isCrossover = ind.payload.parent_ids.length >= 2;
    for (const parentId of ind.payload.parent_ids) {
      if (ids.has(parentId)) {
        links.push({ source: parentId, target: ind.payload.id, isCrossover });
      }
    }
  }
  const fitnessVals = nodes.map((n) => n.fitness).filter((v): v is number => v !== null);
  const minF = fitnessVals.length > 0 ? Math.min(...fitnessVals) : 0;
  const maxF = fitnessVals.length > 0 ? Math.max(...fitnessVals) : 1;
  return { nodes, links, minF, maxF };
}

/** Compute parent-chain depth for every node. Cycles or unknown parents → 0. */
function computeDepths(nodes: Node[]): Map<string, number> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const memo = new Map<string, number>();
  const visit = (id: string, seen: Set<string>): number => {
    if (memo.has(id)) return memo.get(id)!;
    if (seen.has(id)) return 0;
    seen.add(id);
    const node = byId.get(id);
    if (!node) return 0;
    if (node.parentIds.length === 0) {
      memo.set(id, 0);
      return 0;
    }
    const parentDepths = node.parentIds
      .filter((pid) => byId.has(pid))
      .map((pid) => visit(pid, seen));
    const d = parentDepths.length === 0 ? 0 : 1 + Math.max(...parentDepths);
    memo.set(id, d);
    return d;
  };
  for (const n of nodes) visit(n.id, new Set());
  return memo;
}

function applyHierarchical(nodes: Node[]): void {
  const depths = computeDepths(nodes);
  const byDepth = new Map<number, Node[]>();
  for (const n of nodes) {
    const d = depths.get(n.id) ?? 0;
    const arr = byDepth.get(d) ?? [];
    arr.push(n);
    byDepth.set(d, arr);
  }
  const maxDepth = Math.max(...Array.from(byDepth.keys()), 0);
  const margin = 32;
  const usableW = WIDTH - 2 * margin;
  const usableH = HEIGHT - 2 * margin;
  const layerH = maxDepth === 0 ? 0 : usableH / maxDepth;
  for (const [d, arr] of byDepth.entries()) {
    arr.sort((a, b) => a.id.localeCompare(b.id));
    const slot = arr.length === 0 ? 0 : usableW / arr.length;
    arr.forEach((n, i) => {
      n.x = margin + slot * (i + 0.5);
      n.y = margin + layerH * d;
    });
  }
}

function applyRadial(nodes: Node[]): void {
  const depths = computeDepths(nodes);
  const byDepth = new Map<number, Node[]>();
  for (const n of nodes) {
    const d = depths.get(n.id) ?? 0;
    const arr = byDepth.get(d) ?? [];
    arr.push(n);
    byDepth.set(d, arr);
  }
  const maxDepth = Math.max(...Array.from(byDepth.keys()), 0);
  const cx = WIDTH / 2;
  const cy = HEIGHT / 2;
  const maxR = Math.min(WIDTH, HEIGHT) / 2 - 24;
  const ringR = (d: number) => (maxDepth === 0 ? 0 : (d / maxDepth) * maxR);
  for (const [d, arr] of byDepth.entries()) {
    arr.sort((a, b) => a.id.localeCompare(b.id));
    const r = ringR(d);
    if (d === 0 && arr.length === 1) {
      arr[0]!.x = cx;
      arr[0]!.y = cy;
      continue;
    }
    arr.forEach((n, i) => {
      const theta = (i / arr.length) * 2 * Math.PI - Math.PI / 2;
      n.x = cx + r * Math.cos(theta);
      n.y = cy + r * Math.sin(theta);
    });
  }
}

export function PhylogenyView({
  runId,
  individuals,
  fitness,
  scoreDirections,
}: {
  runId?: string;
  individuals: IndividualEvent[];
  fitness: FitnessEvent[];
  scoreDirections?: Record<string, ScoreDirection>;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const zoomGroupRef = useRef<SVGGElement | null>(null);
  const zoomBehaviorRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [transform, setTransform] = useState({ k: 1, x: 0, y: 0 });
  const [layout, setLayout] = useState<Layout>("force");
  const router = useRouter();
  const openIndividual = (id: string) => {
    if (!runId) return;
    router.push(
      `/individual/?run=${encodeURIComponent(runId)}&id=${encodeURIComponent(id)}`,
    );
  };

  const graph = useMemo(
    () => buildGraph(individuals, fitness, scoreDirections),
    [individuals, fitness, scoreDirections],
  );

  const positionsRef = useRef<Node[]>([]);
  const [, setTick] = useState(0);
  const simRef = useRef<Simulation<Node, Link> | null>(null);

  useEffect(() => {
    // Stop any prior simulation before re-laying out.
    simRef.current?.stop();
    simRef.current = null;
    if (graph.nodes.length === 0) {
      positionsRef.current = [];
      setTick((t) => t + 1);
      return;
    }
    const nodes = graph.nodes.map((n) => ({ ...n }));

    if (layout === "force") {
      const links = graph.links.map((l) => ({ ...l }));
      const simulation = forceSimulation<Node>(nodes)
        .force(
          "link",
          forceLink<Node, Link>(links)
            .id((d) => d.id)
            .distance(50)
            .strength(0.7),
        )
        .force("charge", forceManyBody<Node>().strength(-160))
        .force("center", forceCenter(WIDTH / 2, HEIGHT / 2))
        .force("collide", forceCollide<Node>(14))
        .alphaDecay(0.04);
      simulation.on("tick", () => setTick((t) => t + 1));
      simRef.current = simulation;
    } else if (layout === "hierarchical") {
      applyHierarchical(nodes);
    } else {
      applyRadial(nodes);
    }
    positionsRef.current = nodes;
    setTick((t) => t + 1);
    return () => {
      simRef.current?.stop();
    };
  }, [graph, layout]);

  // Wire d3-zoom into the SVG. Drag to pan, scroll/pinch to zoom.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const behavior = d3Zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 8])
      .on("zoom", (event) => {
        setTransform({
          k: event.transform.k,
          x: event.transform.x,
          y: event.transform.y,
        });
      });
    zoomBehaviorRef.current = behavior;
    d3Select<SVGSVGElement, unknown>(svg).call(behavior);
    return () => {
      d3Select<SVGSVGElement, unknown>(svg).on(".zoom", null);
    };
  }, []);

  const resetZoom = () => {
    const svg = svgRef.current;
    const behavior = zoomBehaviorRef.current;
    if (!svg || !behavior) return;
    d3Select<SVGSVGElement, unknown>(svg)
      .transition()
      .duration(250)
      .call(behavior.transform, zoomIdentity);
  };

  if (individuals.length === 0) {
    return (
      <EmptyState
        title="No individuals yet"
        detail="Call h.log_individual(...) to populate the lineage graph."
      />
    );
  }

  const colorScale = (v: number | null): string => {
    if (v === null || graph.maxF === graph.minF) return "#a3a3a3";
    const t = (v - graph.minF) / (graph.maxF - graph.minF);
    return interpolateViridis(t);
  };

  const nodes = positionsRef.current;
  const nodeIndex = new Map(nodes.map((n) => [n.id, n]));
  const linkLine = (l: Link): { x1: number; y1: number; x2: number; y2: number } | null => {
    const sourceId = typeof l.source === "string" ? l.source : (l.source as Node).id;
    const targetId = typeof l.target === "string" ? l.target : (l.target as Node).id;
    const s = nodeIndex.get(sourceId);
    const t = nodeIndex.get(targetId);
    if (!s || !t) return null;
    if (s.x == null || s.y == null || t.x == null || t.y == null) return null;
    return { x1: s.x, y1: s.y, x2: t.x, y2: t.y };
  };

  const crossoverEdgeCount = graph.links.filter((l) => l.isCrossover).length;

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-medium text-neutral-800 dark:text-neutral-200">
              Lineage ({nodes.length} individuals · {graph.links.length} edges
              {crossoverEdgeCount > 0
                ? `, ${crossoverEdgeCount} crossover`
                : ""}
              )
            </h3>
            <p className="text-[11px] text-neutral-500">
              Drag to pan · scroll / pinch to zoom · click a node for the
              individual drill-down · hover for fitness
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <FitnessLegend min={graph.minF} max={graph.maxF} colorScale={colorScale} />
            <LayoutToggle layout={layout} onChange={setLayout} />
            <button
              type="button"
              onClick={resetZoom}
              className="rounded border border-neutral-200 px-2 py-1 text-[11px] text-neutral-600 transition-colors hover:border-neutral-300 hover:text-neutral-900 dark:border-neutral-800 dark:text-neutral-400 dark:hover:border-neutral-700 dark:hover:text-neutral-100"
            >
              reset {transform.k.toFixed(1)}×
            </button>
          </div>
        </div>
        <svg
          ref={svgRef}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-[480px] w-full cursor-grab select-none rounded bg-neutral-50 active:cursor-grabbing dark:bg-neutral-900"
        >
          <g
            ref={zoomGroupRef}
            transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`}
          >
            <g
              className="stroke-neutral-300 dark:stroke-neutral-700"
              strokeOpacity={0.8}
            >
              {graph.links.map((l, i) => {
                const line = linkLine(l);
                if (!line) return null;
                return (
                  <line
                    key={i}
                    x1={line.x1}
                    y1={line.y1}
                    x2={line.x2}
                    y2={line.y2}
                    strokeWidth={l.isCrossover ? 1.5 : 1}
                    strokeDasharray={l.isCrossover ? "4 2" : undefined}
                  />
                );
              })}
            </g>
            <g>
              {nodes.map((n) => (
                <g
                  key={n.id}
                  transform={`translate(${n.x ?? 0}, ${n.y ?? 0})`}
                  onMouseEnter={() => setHoverId(n.id)}
                  onMouseLeave={() => setHoverId(null)}
                  onClick={() => openIndividual(n.id)}
                  className="cursor-pointer"
                >
                  <circle
                    r={n.isSeed ? 7 : 5}
                    fill={colorScale(n.fitness)}
                    className={
                      hoverId === n.id
                        ? "stroke-neutral-900 dark:stroke-neutral-50"
                        : "stroke-white dark:stroke-neutral-950"
                    }
                    strokeWidth={hoverId === n.id ? 2 : 1.25}
                  />
                  {hoverId === n.id ? (
                    <NodeLabel
                      x={9}
                      y={4}
                      label={`${n.id}${n.fitness !== null ? ` · ${n.fitness.toFixed(3)}` : ""}`}
                    />
                  ) : null}
                </g>
              ))}
            </g>
          </g>
        </svg>
      </div>

      <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-xs text-neutral-500 dark:border-neutral-800 dark:bg-neutral-950">
        Layout: <code>{layout}</code>. Larger circles are seed individuals
        (<code>is_seed=True</code>). Color encodes the best composite fitness
        recorded for that individual (gray = no fitness recorded).{" "}
        {crossoverEdgeCount > 0
          ? "Dashed edges are crossover-derived (child has ≥2 parents)."
          : null}
      </div>
    </div>
  );
}

function LayoutToggle({
  layout,
  onChange,
}: {
  layout: Layout;
  onChange: (l: Layout) => void;
}) {
  const opts: { key: Layout; label: string }[] = [
    { key: "force", label: "force" },
    { key: "hierarchical", label: "tree" },
    { key: "radial", label: "radial" },
  ];
  return (
    <div className="flex items-center gap-0 overflow-hidden rounded border border-neutral-200 text-[11px] dark:border-neutral-800">
      {opts.map((o) => (
        <button
          key={o.key}
          type="button"
          onClick={() => onChange(o.key)}
          className={`px-2 py-1 transition-colors ${
            layout === o.key
              ? "bg-neutral-100 text-neutral-900 dark:bg-neutral-800 dark:text-neutral-100"
              : "text-neutral-600 hover:bg-neutral-50 dark:text-neutral-400 dark:hover:bg-neutral-900"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function NodeLabel({ x, y, label }: { x: number; y: number; label: string }) {
  return (
    <g>
      <text
        x={x}
        y={y}
        fontSize={11}
        className="fill-neutral-900 dark:fill-neutral-50"
        stroke="white"
        strokeWidth={3}
        paintOrder="stroke"
      >
        {label}
      </text>
      <text
        x={x}
        y={y}
        fontSize={11}
        className="fill-neutral-900 dark:fill-neutral-50"
      >
        {label}
      </text>
    </g>
  );
}

function FitnessLegend({
  min,
  max,
  colorScale,
}: {
  min: number;
  max: number;
  colorScale: (v: number | null) => string;
}) {
  if (min === max) {
    return (
      <span className="text-xs text-neutral-500">single fitness value: {min.toFixed(3)}</span>
    );
  }
  const stops = Array.from({ length: 8 }, (_, i) => min + (i / 7) * (max - min));
  return (
    <div className="flex items-center gap-2 text-xs text-neutral-500">
      <span className="font-mono">{min.toFixed(2)}</span>
      <div className="flex h-2 w-32 overflow-hidden rounded">
        {stops.map((v, i) => (
          <div key={i} className="h-full flex-1" style={{ background: colorScale(v) }} />
        ))}
      </div>
      <span className="font-mono">{max.toFixed(2)}</span>
    </div>
  );
}
