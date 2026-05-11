"use client";

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  select as d3Select,
  zoom as d3Zoom,
  zoomIdentity,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
  type ZoomBehavior,
} from "d3";
import { useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { StatCard } from "@/components/ui/StatCard";
import type { ClaimEvent, EvidenceEvent, EvidenceStance } from "@/lib/types";

interface ClaimNode extends SimulationNodeDatum {
  kind: "claim";
  id: string;
  text: string;
  requiresReproduction: boolean;
  supportCount: number;
  contradictCount: number;
}

interface SourceNode extends SimulationNodeDatum {
  kind: "source";
  id: string;
  uri: string;
  quality: number | null;
  /** Net stance toward this source's connected claims, used for tinting. */
  netStance: number;
}

type AnyNode = ClaimNode | SourceNode;

interface Link extends SimulationLinkDatum<AnyNode> {
  source: string | AnyNode;
  target: string | AnyNode;
  stance: EvidenceStance;
  confidence: number | null;
}

const STANCE_COLOR: Record<EvidenceStance, string> = {
  supports: "#10b981",
  contradicts: "#ef4444",
  mentions: "#94a3b8",
};

const WIDTH = 720;
const HEIGHT = 480;

interface BuildResult {
  nodes: AnyNode[];
  links: Link[];
}

function buildEvidenceGraph(claims: ClaimEvent[], evidence: EvidenceEvent[]): BuildResult {
  const claimNodes: ClaimNode[] = claims.map((c) => {
    const myEvidence = evidence.filter((e) => e.payload.claim_id === c.payload.id);
    return {
      kind: "claim",
      id: c.payload.id,
      text: c.payload.text,
      requiresReproduction: c.payload.requires_reproduction,
      supportCount: myEvidence.filter((e) => e.payload.stance === "supports").length,
      contradictCount: myEvidence.filter((e) => e.payload.stance === "contradicts").length,
    };
  });

  const sourceMap = new Map<string, SourceNode>();
  for (const e of evidence) {
    const uri = e.payload.source_uri;
    const sourceId = `src::${uri}`;
    let node = sourceMap.get(sourceId);
    if (node === undefined) {
      node = {
        kind: "source",
        id: sourceId,
        uri,
        quality: e.payload.source_quality ?? null,
        netStance: 0,
      };
      sourceMap.set(sourceId, node);
    } else if (e.payload.source_quality !== null && e.payload.source_quality !== undefined) {
      // Keep the highest reported quality.
      node.quality = Math.max(node.quality ?? 0, e.payload.source_quality);
    }
    if (e.payload.stance === "supports") node.netStance += 1;
    if (e.payload.stance === "contradicts") node.netStance -= 1;
  }

  const claimIds = new Set(claimNodes.map((c) => c.id));
  const links: Link[] = [];
  for (const e of evidence) {
    if (!claimIds.has(e.payload.claim_id)) continue;
    links.push({
      source: `src::${e.payload.source_uri}`,
      target: e.payload.claim_id,
      stance: e.payload.stance,
      confidence: e.payload.confidence ?? null,
    });
  }

  return { nodes: [...claimNodes, ...sourceMap.values()], links };
}

export function EvidenceView({
  claims,
  evidence,
}: {
  claims: ClaimEvent[];
  evidence: EvidenceEvent[];
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const groupRef = useRef<SVGGElement>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const simRef = useRef<Simulation<AnyNode, Link> | null>(null);
  const [selectedClaim, setSelectedClaim] = useState<string | null>(null);

  const graph = useMemo(() => buildEvidenceGraph(claims, evidence), [claims, evidence]);

  const claimList = useMemo(
    () => graph.nodes.filter((n): n is ClaimNode => n.kind === "claim"),
    [graph.nodes],
  );

  useEffect(() => {
    if (graph.nodes.length === 0 || svgRef.current === null || groupRef.current === null) {
      return;
    }
    const svg = d3Select(svgRef.current);
    const g = d3Select(groupRef.current);

    const zoomBehavior = d3Zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on("zoom", (event) => {
        g.attr("transform", event.transform.toString());
      });
    svg.call(zoomBehavior).call(zoomBehavior.transform, zoomIdentity);
    zoomRef.current = zoomBehavior;

    const sim = forceSimulation<AnyNode>(graph.nodes)
      .force(
        "link",
        forceLink<AnyNode, Link>(graph.links)
          .id((d) => d.id)
          .distance(80)
          .strength(0.6),
      )
      .force("charge", forceManyBody<AnyNode>().strength(-220))
      .force("center", forceCenter(WIDTH / 2, HEIGHT / 2))
      .force(
        "collide",
        forceCollide<AnyNode>().radius((d) => (d.kind === "claim" ? 26 : 14)),
      );
    simRef.current = sim;

    const nodeIndex = new Map<string, AnyNode>(graph.nodes.map((n) => [n.id, n]));
    const linkSel = g
      .select<SVGGElement>("g.evidence-links")
      .selectAll<SVGLineElement, Link>("line")
      .data(graph.links)
      .join("line")
      .attr("stroke", (d) => STANCE_COLOR[d.stance])
      .attr("stroke-width", (d) =>
        d.confidence !== null && Number.isFinite(d.confidence) ? 0.8 + d.confidence * 2.5 : 1.2,
      )
      .attr("stroke-dasharray", (d) => (d.stance === "mentions" ? "4 3" : null))
      .attr("opacity", 0.85);

    const nodeSel = g
      .select<SVGGElement>("g.evidence-nodes")
      .selectAll<SVGGElement, AnyNode>("g.node")
      .data(graph.nodes, (d) => d.id)
      .join((enter) => {
        const ge = enter.append("g").attr("class", "node").style("cursor", "pointer");
        ge.append("circle");
        ge.append("text")
          .attr("text-anchor", "middle")
          .attr("dy", "0.3em")
          .attr("font-size", 10)
          .attr("fill", "currentColor")
          .attr("class", "fill-neutral-50 dark:fill-neutral-900")
          .attr("pointer-events", "none");
        return ge;
      });

    nodeSel
      .select("circle")
      .attr("r", (d) => (d.kind === "claim" ? 18 : 8 + Math.min(6, (d.quality ?? 0.5) * 8)))
      .attr("fill", (d) => {
        if (d.kind === "claim") {
          return d.contradictCount > d.supportCount
            ? "#ef4444"
            : d.supportCount > 0
              ? "#10b981"
              : "#6366f1";
        }
        return d.netStance > 0 ? "#34d399" : d.netStance < 0 ? "#fb7185" : "#cbd5e1";
      })
      .attr("stroke", "#0f172a")
      .attr("stroke-width", 0.6);

    nodeSel
      .select("text")
      .text((d) => (d.kind === "claim" ? "C" : "S"));

    nodeSel
      .on("click", (_, d) => {
        if (d.kind === "claim") setSelectedClaim((prev) => (prev === d.id ? null : d.id));
      })
      .append("title")
      .text((d) =>
        d.kind === "claim"
          ? `claim ${d.id}\n${d.text}\nsupports=${d.supportCount} contradicts=${d.contradictCount}`
          : `source ${d.uri}\nquality=${d.quality ?? "—"}\nnet=${d.netStance}`,
      );

    sim.on("tick", () => {
      linkSel
        .attr("x1", (d) => {
          const n = typeof d.source === "string" ? nodeIndex.get(d.source) : d.source;
          return n?.x ?? 0;
        })
        .attr("y1", (d) => {
          const n = typeof d.source === "string" ? nodeIndex.get(d.source) : d.source;
          return n?.y ?? 0;
        })
        .attr("x2", (d) => {
          const n = typeof d.target === "string" ? nodeIndex.get(d.target) : d.target;
          return n?.x ?? 0;
        })
        .attr("y2", (d) => {
          const n = typeof d.target === "string" ? nodeIndex.get(d.target) : d.target;
          return n?.y ?? 0;
        });
      nodeSel.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    return () => {
      sim.stop();
    };
  }, [graph]);

  if (claims.length === 0 && evidence.length === 0) {
    return (
      <EmptyState
        title="No claims or evidence in this run"
        detail={
          <>
            Emit{" "}
            <code className="font-mono">h.log_claim()</code> and{" "}
            <code className="font-mono">h.log_evidence(stance=&quot;supports&quot;|&quot;contradicts&quot;|&quot;mentions&quot;)</code>{" "}
            from your loop to populate this view. Sources fan in toward claims; supports = green, contradicts = red, mentions = grey dashed.
          </>
        }
      />
    );
  }

  const supportCount = evidence.filter((e) => e.payload.stance === "supports").length;
  const contradictCount = evidence.filter((e) => e.payload.stance === "contradicts").length;
  const mentionsCount = evidence.filter((e) => e.payload.stance === "mentions").length;

  const selected = claimList.find((c) => c.id === selectedClaim) ?? null;
  const selectedEvidence = evidence
    .filter((e) => selected !== null && e.payload.claim_id === selected.id)
    .sort((a, b) => (b.payload.confidence ?? 0) - (a.payload.confidence ?? 0));

  const onResetZoom = () => {
    if (zoomRef.current === null || svgRef.current === null) return;
    d3Select(svgRef.current).transition().call(zoomRef.current.transform, zoomIdentity);
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Claims" value={claims.length} />
        <StatCard label="Supports" value={supportCount} hint="evidence.stance == supports" />
        <StatCard
          label="Contradicts"
          value={contradictCount}
          hint="evidence.stance == contradicts"
        />
        <StatCard label="Mentions" value={mentionsCount} hint="evidence.stance == mentions" />
      </div>

      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-medium text-neutral-800 dark:text-neutral-200">
            Claim ↔ source graph
          </h3>
          <div className="flex items-center gap-2 text-xs">
            <button
              type="button"
              onClick={onResetZoom}
              className="rounded border border-neutral-200 px-2 py-1 text-neutral-700 hover:bg-neutral-50 dark:border-neutral-800 dark:text-neutral-300 dark:hover:bg-neutral-900"
            >
              reset zoom
            </button>
            <span className="text-neutral-500">scroll to zoom · drag background to pan</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-3 text-xs text-neutral-500">
          <span>
            <span className="mr-1 inline-block h-2 w-3 align-middle bg-emerald-500" /> supports
          </span>
          <span>
            <span className="mr-1 inline-block h-2 w-3 align-middle bg-rose-500" /> contradicts
          </span>
          <span>
            <span className="mr-1 inline-block h-0.5 w-3 align-middle border-t-2 border-dashed border-neutral-400" />{" "}
            mentions
          </span>
          <span>edge thickness ∝ confidence · source disc ∝ source_quality</span>
        </div>
        <svg
          ref={svgRef}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="mt-2 h-[480px] w-full rounded bg-neutral-50 text-neutral-50 dark:bg-neutral-900 dark:text-neutral-900"
        >
          <g ref={groupRef}>
            <g className="evidence-links" />
            <g className="evidence-nodes" />
          </g>
        </svg>
      </div>

      {/* Claim list / drill-down */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
          <h3 className="mb-2 text-sm font-medium text-neutral-800 dark:text-neutral-200">
            Claims
          </h3>
          <ul className="space-y-2 text-sm">
            {claimList.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => setSelectedClaim(c.id === selectedClaim ? null : c.id)}
                  className={`w-full rounded px-2 py-1 text-left text-sm transition-colors ${
                    selectedClaim === c.id
                      ? "bg-emerald-50 text-neutral-900 dark:bg-emerald-950/40 dark:text-neutral-100"
                      : "hover:bg-neutral-50 dark:hover:bg-neutral-900"
                  }`}
                >
                  <div className="font-mono text-[11px] text-neutral-500">{c.id}</div>
                  <div className="text-sm text-neutral-800 dark:text-neutral-200">{c.text}</div>
                  <div className="mt-0.5 text-xs text-neutral-500">
                    <span className="text-emerald-600 dark:text-emerald-400">
                      {c.supportCount} supports
                    </span>{" "}
                    ·{" "}
                    <span className="text-rose-600 dark:text-rose-400">
                      {c.contradictCount} contradicts
                    </span>
                    {c.requiresReproduction ? (
                      <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                        needs repro
                      </span>
                    ) : null}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
          <h3 className="mb-2 text-sm font-medium text-neutral-800 dark:text-neutral-200">
            Evidence{" "}
            {selected ? (
              <span className="ml-1 text-xs text-neutral-500">for {selected.id}</span>
            ) : null}
          </h3>
          {selected === null ? (
            <p className="text-sm text-neutral-500">
              Click a claim on the left or in the graph to see its evidence breakdown.
            </p>
          ) : selectedEvidence.length === 0 ? (
            <p className="text-sm text-neutral-500">No evidence logged for this claim.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="py-1 pr-3">Stance</th>
                  <th className="py-1 pr-3">Source</th>
                  <th className="py-1 pr-3 text-right">Conf.</th>
                  <th className="py-1 text-right">Quality</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 text-neutral-700 dark:divide-neutral-900 dark:text-neutral-300">
                {selectedEvidence.map((e, i) => (
                  <tr key={`${e.payload.source_uri}-${i}`}>
                    <td className="py-1 pr-3">
                      <span
                        className="rounded px-2 py-0.5 text-[10px] font-mono uppercase tracking-wide"
                        style={{
                          background: STANCE_COLOR[e.payload.stance] + "22",
                          color: STANCE_COLOR[e.payload.stance],
                        }}
                      >
                        {e.payload.stance}
                      </span>
                    </td>
                    <td className="py-1 pr-3 font-mono text-xs">{e.payload.source_uri}</td>
                    <td className="py-1 pr-3 text-right font-mono text-xs">
                      {e.payload.confidence !== null && e.payload.confidence !== undefined
                        ? e.payload.confidence.toFixed(2)
                        : "—"}
                    </td>
                    <td className="py-1 text-right font-mono text-xs">
                      {e.payload.source_quality !== null && e.payload.source_quality !== undefined
                        ? e.payload.source_quality.toFixed(2)
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
