"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { StatCard } from "@/components/ui/StatCard";
import type { SelfModEvent, SelfModVerdict } from "@/lib/types";

const VERDICT_BADGE: Record<SelfModVerdict, string> = {
  accepted:
    "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-200",
  rejected:
    "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-700 dark:bg-rose-950 dark:text-rose-200",
  pending:
    "border-neutral-300 bg-neutral-100 text-neutral-700 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300",
};

function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toFixed(3);
}

function formatDelta(before: number | null | undefined, after: number | null | undefined): string {
  if (
    before === null ||
    before === undefined ||
    after === null ||
    after === undefined ||
    !Number.isFinite(before) ||
    !Number.isFinite(after)
  ) {
    return "";
  }
  const delta = after - before;
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta.toFixed(3)}`;
}

export function SelfModAuditView({
  runId,
  selfMods,
}: {
  runId: string;
  selfMods: SelfModEvent[];
}) {
  const [selected, setSelected] = useState<string | null>(
    selfMods[0]?.payload.child_agent_id ?? null,
  );
  const [verdictFilter, setVerdictFilter] = useState<SelfModVerdict | "all">("all");

  const filtered = useMemo(
    () =>
      selfMods.filter((sm) =>
        verdictFilter === "all" ? true : sm.payload.overseer_verdict === verdictFilter,
      ),
    [selfMods, verdictFilter],
  );

  const counts = useMemo(() => {
    const c: Record<SelfModVerdict, number> = { accepted: 0, rejected: 0, pending: 0 };
    for (const sm of selfMods) c[sm.payload.overseer_verdict] += 1;
    return c;
  }, [selfMods]);

  const acceptedDeltas = useMemo(
    () =>
      selfMods
        .filter((sm) => sm.payload.overseer_verdict === "accepted")
        .map((sm) => {
          const d =
            sm.payload.score_after !== null &&
            sm.payload.score_after !== undefined &&
            sm.payload.score_before !== null &&
            sm.payload.score_before !== undefined
              ? sm.payload.score_after - sm.payload.score_before
              : null;
          return d;
        })
        .filter((v): v is number => v !== null && Number.isFinite(v)),
    [selfMods],
  );
  const cumulativeGain = acceptedDeltas.reduce((a, b) => a + b, 0);

  const focused = useMemo(
    () => filtered.find((sm) => sm.payload.child_agent_id === selected) ?? filtered[0],
    [filtered, selected],
  );

  if (selfMods.length === 0) {
    return (
      <EmptyState
        title="No self-modifications logged"
        detail="The Self-Mod Audit view activates once a run logs SelfMod events (DGM/SICA-style self-improvement)."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Total proposals" value={selfMods.length} />
        <StatCard
          label="Accepted"
          value={counts.accepted}
          hint={`${counts.rejected} rejected · ${counts.pending} pending`}
        />
        <StatCard
          label="Cumulative Δ score"
          value={cumulativeGain >= 0 ? `+${cumulativeGain.toFixed(3)}` : cumulativeGain.toFixed(3)}
          hint="sum of accepted deltas"
        />
        <StatCard
          label="Best leap"
          value={
            acceptedDeltas.length === 0
              ? "—"
              : `+${Math.max(...acceptedDeltas).toFixed(3)}`
          }
          hint="largest single accepted delta"
        />
      </div>

      <div className="flex items-center gap-2 text-xs text-neutral-500">
        <span>filter</span>
        {(["all", "accepted", "rejected", "pending"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setVerdictFilter(v)}
            className={`rounded border px-2 py-1 ${
              verdictFilter === v
                ? "border-emerald-500 text-emerald-700 dark:border-emerald-600 dark:text-emerald-200"
                : "border-neutral-200 text-neutral-600 hover:text-neutral-900 dark:border-neutral-800 dark:text-neutral-400 dark:hover:text-neutral-200"
            }`}
          >
            {v}
          </button>
        ))}
        <span className="ml-auto">{filtered.length} shown</span>
      </div>

      <div className="grid gap-4 md:grid-cols-[3fr_2fr]">
        <div className="overflow-hidden rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500 dark:bg-neutral-950">
              <tr>
                <th className="px-3 py-2">Child agent</th>
                <th className="px-3 py-2">Proposal</th>
                <th className="px-3 py-2 text-right">Δ</th>
                <th className="px-3 py-2">Verdict</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-900">
              {filtered.map((sm) => (
                <tr
                  key={sm.event_id}
                  onClick={() => setSelected(sm.payload.child_agent_id)}
                  className={`cursor-pointer ${
                    focused?.event_id === sm.event_id
                      ? "bg-neutral-100 dark:bg-neutral-900"
                      : "hover:bg-neutral-50 dark:hover:bg-neutral-950"
                  }`}
                >
                  <td className="px-3 py-2 font-mono text-xs text-neutral-800 dark:text-neutral-200">
                    {sm.payload.child_agent_id}
                  </td>
                  <td className="px-3 py-2 text-xs text-neutral-600 dark:text-neutral-400">
                    {sm.payload.proposal ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-neutral-700 dark:text-neutral-300">
                    {formatDelta(sm.payload.score_before, sm.payload.score_after)}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-flex rounded border px-2 py-0.5 text-[10px] ${
                        VERDICT_BADGE[sm.payload.overseer_verdict]
                      }`}
                    >
                      {sm.payload.overseer_verdict}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
          {focused ? (
            <div className="space-y-3 text-sm">
              <div>
                <div className="text-xs uppercase tracking-wide text-neutral-500">
                  Parent → Child
                </div>
                <div className="mt-1 space-y-1 font-mono text-xs">
                  <div>
                    <Link
                      href={`/individual/?run=${encodeURIComponent(
                        runId,
                      )}&id=${encodeURIComponent(focused.payload.parent_agent_id)}`}
                      className="text-neutral-700 hover:underline dark:text-neutral-300"
                    >
                      {focused.payload.parent_agent_id}
                    </Link>
                  </div>
                  <div className="text-neutral-500">↓</div>
                  <div>
                    <Link
                      href={`/individual/?run=${encodeURIComponent(
                        runId,
                      )}&id=${encodeURIComponent(focused.payload.child_agent_id)}`}
                      className="text-neutral-900 hover:underline dark:text-neutral-100"
                    >
                      {focused.payload.child_agent_id}
                    </Link>
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <div className="text-neutral-500">score before</div>
                  <div className="font-mono text-neutral-800 dark:text-neutral-200">
                    {formatScore(focused.payload.score_before)}
                  </div>
                </div>
                <div>
                  <div className="text-neutral-500">score after</div>
                  <div className="font-mono text-neutral-800 dark:text-neutral-200">
                    {formatScore(focused.payload.score_after)}
                  </div>
                </div>
                <div>
                  <div className="text-neutral-500">overseer</div>
                  <div className="font-mono text-neutral-700 dark:text-neutral-300">
                    {focused.payload.overseer_id ?? "—"}
                  </div>
                </div>
                <div>
                  <div className="text-neutral-500">benchmark</div>
                  <div className="font-mono text-neutral-700 dark:text-neutral-300">
                    {focused.payload.benchmark ?? "—"}
                  </div>
                </div>
              </div>
              {focused.payload.target_path ? (
                <div className="text-xs">
                  <div className="text-neutral-500">target_path</div>
                  <div className="break-all font-mono text-neutral-700 dark:text-neutral-300">
                    {focused.payload.target_path}
                  </div>
                </div>
              ) : null}
              {focused.payload.proposal ? (
                <div>
                  <div className="text-xs text-neutral-500">proposal</div>
                  <p className="mt-1 rounded bg-neutral-100 p-2 text-xs text-neutral-800 dark:bg-neutral-900 dark:text-neutral-200">
                    {focused.payload.proposal}
                  </p>
                </div>
              ) : null}
              {focused.payload.diff_uri ? (
                <div className="text-xs text-neutral-500">
                  diff_uri:{" "}
                  <code className="text-neutral-700 dark:text-neutral-300">
                    {focused.payload.diff_uri}
                  </code>
                  <p className="mt-1 italic">
                    Inline diff rendering scheduled post-v0.1.0; the Phylogeny
                    drill-down already shows the parent/child link.
                  </p>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="text-xs text-neutral-500">Pick a row.</div>
          )}
        </div>
      </div>
    </div>
  );
}
