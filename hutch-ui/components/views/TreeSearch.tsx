"use client";

import {
  interpolateViridis,
  select as d3Select,
  zoom as d3Zoom,
  zoomIdentity,
  type ZoomBehavior,
} from "d3";
import { useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { StatCard } from "@/components/ui/StatCard";
import type { IndividualEvent, TreeExpansionEvent } from "@/lib/types";

interface TreeNode {
  id: string;
  parentId: string | null;
  depth: number;
  visitCount: number;
  value: number | null;
  isBuggy: boolean;
}

interface LaidOut extends TreeNode {
  x: number;
  y: number;
}

const NODE_R = 5;
const LEVEL_H = 70;

function buildTree(
  expansions: TreeExpansionEvent[],
  individuals: IndividualEvent[],
): { roots: TreeNode[]; nodes: Map<string, TreeNode>; childrenOf: Map<string, string[]> } {
  const buggy = new Set(
    individuals
      .filter((i) => {
        const meta = i.payload.metadata;
        return (
          meta &&
          typeof meta === "object" &&
          (meta as Record<string, unknown>)["exc_type"]
        );
      })
      .map((i) => i.payload.id),
  );

  const nodes = new Map<string, TreeNode>();
  const childrenOf = new Map<string, string[]>();

  for (const ind of individuals) {
    nodes.set(ind.payload.id, {
      id: ind.payload.id,
      parentId: ind.payload.parent_ids[0] ?? null,
      depth: ind.payload.generation_index ?? 0,
      visitCount: 0,
      value: null,
      isBuggy: buggy.has(ind.payload.id),
    });
  }
  for (const e of expansions) {
    const child = nodes.get(e.payload.child_node) ?? {
      id: e.payload.child_node,
      parentId: e.payload.parent_node,
      depth: 0,
      visitCount: 0,
      value: null,
      isBuggy: false,
    };
    child.visitCount = (child.visitCount ?? 0) + (e.payload.visit_count ?? 1);
    if (
      e.payload.value_estimate !== null &&
      e.payload.value_estimate !== undefined &&
      Number.isFinite(e.payload.value_estimate)
    ) {
      child.value = e.payload.value_estimate;
    }
    child.parentId = e.payload.parent_node;
    nodes.set(child.id, child);
    const arr = childrenOf.get(e.payload.parent_node) ?? [];
    arr.push(child.id);
    childrenOf.set(e.payload.parent_node, arr);
  }

  const computeDepth = (id: string, seen: Set<string>): number => {
    if (seen.has(id)) return 0;
    seen.add(id);
    const node = nodes.get(id);
    if (!node) return 0;
    if (!node.parentId) return 0;
    return computeDepth(node.parentId, seen) + 1;
  };
  for (const node of nodes.values()) {
    node.depth = computeDepth(node.id, new Set());
  }

  const roots = Array.from(nodes.values()).filter((n) => !n.parentId || !nodes.has(n.parentId));
  return { roots, nodes, childrenOf };
}

function layoutTree(
  roots: TreeNode[],
  nodes: Map<string, TreeNode>,
  childrenOf: Map<string, string[]>,
  width: number,
): LaidOut[] {
  const out: LaidOut[] = [];
  const leafCount = (id: string): number => {
    const c = childrenOf.get(id) ?? [];
    if (c.length === 0) return 1;
    return c.reduce((acc, cid) => acc + leafCount(cid), 0);
  };

  const totalLeaves = roots.reduce((acc, r) => acc + leafCount(r.id), 0) || 1;
  const slotW = width / totalLeaves;

  let cursor = 0;
  const place = (id: string, depth: number): { center: number } => {
    const c = childrenOf.get(id) ?? [];
    const node = nodes.get(id)!;
    if (c.length === 0) {
      const x = (cursor + 0.5) * slotW;
      cursor += 1;
      out.push({ ...node, x, y: 30 + depth * LEVEL_H });
      return { center: x };
    }
    const childCenters = c.map((cid) => place(cid, depth + 1).center);
    const x = (childCenters[0]! + childCenters[childCenters.length - 1]!) / 2;
    out.push({ ...node, x, y: 30 + depth * LEVEL_H });
    return { center: x };
  };
  for (const root of roots) place(root.id, 0);
  return out;
}

export function TreeSearchView({
  expansions,
  individuals,
}: {
  expansions: TreeExpansionEvent[];
  individuals: IndividualEvent[];
}) {
  const tree = useMemo(
    () => buildTree(expansions, individuals),
    [expansions, individuals],
  );
  const [hoverId, setHoverId] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const zoomBehaviorRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [transform, setTransform] = useState({ k: 1, x: 0, y: 0 });

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

  if (expansions.length === 0) {
    return (
      <EmptyState
        title="No tree expansions logged"
        detail="The Tree-Search view activates for runs that emit TreeExpansion events (AIDE-style or MCTS)."
      />
    );
  }

  const width = 920;
  const laid = layoutTree(tree.roots, tree.nodes, tree.childrenOf, width);
  const maxDepth = laid.reduce((acc, n) => Math.max(acc, n.depth), 0);
  const height = 50 + maxDepth * LEVEL_H + 30;

  const values = laid.map((n) => n.value).filter((v): v is number => v !== null);
  const minV = values.length ? Math.min(...values) : 0;
  const maxV = values.length ? Math.max(...values) : 1;
  const colorOf = (n: LaidOut): string => {
    if (n.isBuggy) return "#dc2626";
    if (n.value === null || maxV === minV) return "#a3a3a3";
    return interpolateViridis((n.value - minV) / (maxV - minV));
  };

  const byId = new Map(laid.map((n) => [n.id, n]));
  const totalVisits = laid.reduce((a, n) => a + n.visitCount, 0);
  const buggyCount = laid.filter((n) => n.isBuggy).length;
  const bestValue = values.length ? Math.max(...values) : null;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Nodes" value={laid.length} />
        <StatCard label="Max depth" value={maxDepth + 1} hint="root counts as depth 1" />
        <StatCard label="Total visits" value={totalVisits} />
        <StatCard
          label="Best value"
          value={bestValue === null ? "—" : bestValue.toFixed(3)}
          hint={`${buggyCount} buggy node${buggyCount === 1 ? "" : "s"}`}
        />
      </div>

      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
        <div className="mb-3 flex items-center justify-between">
          <p className="text-[11px] text-neutral-500">
            Drag to pan · scroll / pinch to zoom
          </p>
          <button
            type="button"
            onClick={resetZoom}
            className="rounded border border-neutral-200 px-2 py-1 text-[11px] text-neutral-600 transition-colors hover:border-neutral-300 hover:text-neutral-900 dark:border-neutral-800 dark:text-neutral-400 dark:hover:border-neutral-700 dark:hover:text-neutral-100"
          >
            reset {transform.k.toFixed(1)}×
          </button>
        </div>
        <svg
          ref={svgRef}
          viewBox={`0 0 ${width} ${height}`}
          className="w-full cursor-grab select-none rounded bg-neutral-50 active:cursor-grabbing dark:bg-neutral-900"
          style={{ maxHeight: "560px" }}
        >
          <g
            transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`}
          >
            <g
              className="stroke-neutral-300 dark:stroke-neutral-700"
              strokeOpacity={0.8}
            >
              {laid.map((n) => {
                if (!n.parentId) return null;
                const parent = byId.get(n.parentId);
                if (!parent) return null;
                return (
                  <line
                    key={`e-${n.id}`}
                    x1={parent.x}
                    y1={parent.y}
                    x2={n.x}
                    y2={n.y}
                    strokeWidth={1}
                  />
                );
              })}
            </g>
            <g>
              {laid.map((n) => (
                <g
                  key={n.id}
                  transform={`translate(${n.x}, ${n.y})`}
                  onMouseEnter={() => setHoverId(n.id)}
                  onMouseLeave={() => setHoverId(null)}
                  className="cursor-pointer"
                >
                  <circle
                    r={NODE_R + Math.min(8, Math.log2(1 + n.visitCount))}
                    fill={colorOf(n)}
                    className={
                      hoverId === n.id
                        ? "stroke-neutral-900 dark:stroke-neutral-50"
                        : "stroke-white dark:stroke-neutral-950"
                    }
                    strokeWidth={hoverId === n.id ? 2 : 1.25}
                  />
                  {hoverId === n.id ? (
                    <g>
                      <text
                        x={9}
                        y={4}
                        fontSize={11}
                        className="fill-neutral-900 dark:fill-neutral-50"
                        stroke="white"
                        strokeWidth={3}
                        paintOrder="stroke"
                      >
                        {n.id}
                        {n.value !== null ? ` · v=${n.value.toFixed(3)}` : ""}
                        {n.visitCount ? ` · n=${n.visitCount}` : ""}
                      </text>
                      <text
                        x={9}
                        y={4}
                        fontSize={11}
                        className="fill-neutral-900 dark:fill-neutral-50"
                      >
                        {n.id}
                        {n.value !== null ? ` · v=${n.value.toFixed(3)}` : ""}
                        {n.visitCount ? ` · n=${n.visitCount}` : ""}
                      </text>
                    </g>
                  ) : null}
                </g>
              ))}
            </g>
          </g>
        </svg>
      </div>

      <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-xs text-neutral-500 dark:border-neutral-800 dark:bg-neutral-950">
        Each node is one expansion target. Circle radius scales with visit
        count; color encodes the value estimate (purple → yellow). Red nodes
        are buggy. AIDE-style trees grow downward; MCTS trees place the
        children of a node side-by-side under the parent.
      </div>
    </div>
  );
}
