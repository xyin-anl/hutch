"use client";

import Link from "next/link";
import useSWR from "swr";

import { Breadcrumbs } from "@/components/nav/Breadcrumbs";
import { TopBar } from "@/components/nav/TopBar";
import { EmptyState } from "@/components/ui/EmptyState";
import { fetcher } from "@/lib/api";
import type { EventKind, RunSummary, SystemKind } from "@/lib/types";

function formatTimestamp(ns: number | null | undefined): string {
  if (!ns) return "—";
  return new Date(ns / 1_000_000).toLocaleString();
}

/**
 * Cheap system-kind heuristic from the run's event_kinds_seen.
 *
 * Kept independent of the per-run inferSystemKind helper (which needs
 * the full operator + individual events) — here we only have aggregate
 * kind names, but they're enough to pick the right badge for the list:
 * self-improvement runs always emit ``self_mod``; tree-search runs
 * always emit ``tree_expansion``; descriptor/migration events imply
 * evolutionary search. With only aggregate event-kind names, operator shape is
 * unavailable, so the fallback is deliberately "unknown" rather than
 * pretending a run is linear.
 */
function inferKindFromKindsSeen(kinds: EventKind[] | undefined): SystemKind {
  const set = new Set(kinds ?? []);
  if (set.has("self_mod")) return "self-improving";
  if (set.has("tree_expansion")) return "tree-search";
  if (set.has("descriptor") || set.has("migration") || set.has("pareto_snapshot")) {
    return "evolutionary";
  }
  return "unknown";
}

const KIND_BADGE_STYLES: Record<SystemKind, string> = {
  unknown:
    "bg-neutral-100 text-neutral-700 border-neutral-200 dark:bg-neutral-900 dark:text-neutral-400 dark:border-neutral-800",
  linear:
    "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-900",
  evolutionary:
    "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-900",
  "self-improving":
    "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900",
  "tree-search":
    "bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950/40 dark:text-violet-300 dark:border-violet-900",
};

const STATUS_BADGE_STYLES: Record<string, string> = {
  finished:
    "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-900",
  running:
    "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900",
  failed:
    "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900",
  cancelled:
    "bg-neutral-100 text-neutral-700 border-neutral-200 dark:bg-neutral-900 dark:text-neutral-400 dark:border-neutral-800",
};

export default function HomePage() {
  const { data, error, isLoading } = useSWR<RunSummary[]>("/runs", fetcher, {
    refreshInterval: 5000,
  });

  return (
    <div className="min-h-screen">
      <TopBar />
      <main className="mx-auto max-w-6xl px-6 py-10">
        <Breadcrumbs items={[{ label: "The Hutch", href: "/" }, { label: "runs" }]} />
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">Runs</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Every run that has reported at least one event to the daemon.
        </p>

        <div className="mt-8">
          {error ? (
            <EmptyState
              title="Daemon unreachable"
              detail={
                <>
                  Couldn&apos;t fetch <code>/runs</code>. Is{" "}
                  <code>hutch serve</code> running?
                </>
              }
            />
          ) : isLoading ? (
            <div className="text-sm text-neutral-500">loading…</div>
          ) : !data || data.length === 0 ? (
            <EmptyState
              title="No runs yet"
              detail={
                <>
                  Run{" "}
                  <code>
                    HUTCH_DAEMON_URL=http://localhost:7777 python
                    examples/01-linear-research/run.py
                  </code>{" "}
                  to populate this page.
                </>
              }
            />
          ) : (
            <RunTable runs={data} />
          )}
        </div>
      </main>
    </div>
  );
}

function RunTable({ runs }: { runs: RunSummary[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-neutral-200 dark:border-neutral-800">
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500 dark:bg-neutral-950">
          <tr>
            <th className="px-4 py-2">Run</th>
            <th className="px-4 py-2">Kind</th>
            <th className="px-4 py-2">Project</th>
            <th className="px-4 py-2">Started</th>
            <th className="px-4 py-2">Status</th>
            <th className="px-4 py-2 text-right">Events</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-100 dark:divide-neutral-900">
          {runs.map((run) => {
            const kind = run.system_kind ?? inferKindFromKindsSeen(run.kinds_seen);
            const status = run.status ?? (run.ended_at_ns ? "finished" : "running");
            return (
              <tr
                key={run.run_id}
                className="hover:bg-neutral-50 dark:hover:bg-neutral-950"
              >
                <td className="px-4 py-2">
                  <Link
                    href={`/run?id=${encodeURIComponent(run.run_id)}`}
                    className="text-neutral-800 hover:underline dark:text-neutral-200"
                  >
                    {run.name ? (
                      <span className="font-medium">{run.name}</span>
                    ) : (
                      <span className="font-mono">{run.run_id}</span>
                    )}
                  </Link>
                  {run.name ? (
                    <div className="font-mono text-[11px] text-neutral-500">
                      {run.run_id}
                    </div>
                  ) : null}
                </td>
                <td className="px-4 py-2">
                  <span
                    className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${KIND_BADGE_STYLES[kind]}`}
                  >
                    {kind}
                  </span>
                </td>
                <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">
                  {run.project ?? "—"}
                </td>
                <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">
                  {formatTimestamp(run.started_at_ns)}
                </td>
                <td className="px-4 py-2">
                  <span
                    className={`inline-flex items-center rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide ${
                      STATUS_BADGE_STYLES[status] ??
                      "bg-neutral-100 text-neutral-600 border-neutral-200 dark:bg-neutral-900 dark:text-neutral-400 dark:border-neutral-800"
                    }`}
                  >
                    {status}
                  </span>
                </td>
                <td className="px-4 py-2 text-right font-mono text-neutral-700 dark:text-neutral-300">
                  {run.event_count}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
