"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import useSWR from "swr";

import { Breadcrumbs } from "@/components/nav/Breadcrumbs";
import { TopBar } from "@/components/nav/TopBar";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatCard } from "@/components/ui/StatCard";
import { fetcher } from "@/lib/api";
import type { FitnessEvent, IndividualEvent, OperatorEvent } from "@/lib/types";

export default function IndividualPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-neutral-500">loading…</div>}>
      <IndividualDrillDown />
    </Suspense>
  );
}

function IndividualDrillDown() {
  const params = useSearchParams();
  const runId = params.get("run") ?? "";
  const indId = params.get("id") ?? "";

  const individuals = useSWR<IndividualEvent[]>(
    runId ? `/runs/${encodeURIComponent(runId)}/individuals` : null,
    fetcher,
  );
  const operators = useSWR<OperatorEvent[]>(
    runId ? `/runs/${encodeURIComponent(runId)}/operators` : null,
    fetcher,
  );
  const fitness = useSWR<FitnessEvent[]>(
    runId ? `/runs/${encodeURIComponent(runId)}/fitness` : null,
    fetcher,
  );

  const individual = useMemo(
    () => (individuals.data ?? []).find((e) => e.payload.id === indId),
    [individuals.data, indId],
  );
  const incomingOps = useMemo(
    () => (operators.data ?? []).filter((o) => o.payload.child_id === indId),
    [operators.data, indId],
  );
  const outgoingOps = useMemo(
    () => (operators.data ?? []).filter((o) => o.payload.parent_ids.includes(indId)),
    [operators.data, indId],
  );
  const fits = useMemo(
    () => (fitness.data ?? []).filter((f) => f.payload.individual_id === indId),
    [fitness.data, indId],
  );

  if (!runId || !indId) {
    return (
      <div className="min-h-screen">
        <TopBar />
        <main className="mx-auto max-w-4xl px-6 py-10">
          <EmptyState
            title="Missing query parameters"
            detail={<>This page expects <code>?run=&lt;run_id&gt;&id=&lt;ind_id&gt;</code>.</>}
          />
        </main>
      </div>
    );
  }

  if (!individual && !individuals.isLoading) {
    return (
      <div className="min-h-screen">
        <TopBar />
        <main className="mx-auto max-w-4xl px-6 py-10">
          <EmptyState
            title="Individual not found"
            detail={
              <>
                No individual <code className="font-mono">{indId}</code> in run{" "}
                <Link
                  className="underline hover:text-neutral-900 dark:hover:text-neutral-200"
                  href={`/run/?id=${encodeURIComponent(runId)}`}
                >
                  {runId}
                </Link>
                .
              </>
            }
          />
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <TopBar />
      <main className="mx-auto max-w-4xl px-6 py-8">
        <Breadcrumbs
          items={[
            { label: "The Hutch", href: "/" },
            { label: "runs", href: "/" },
            {
              label: <span className="font-mono">{runId}</span>,
              href: `/run/?id=${encodeURIComponent(runId)}`,
            },
            { label: "individual" },
            { label: <span className="font-mono">{indId}</span> },
          ]}
        />
        <div className="mt-3">
          <Link
            href={`/run/?id=${encodeURIComponent(runId)}`}
            className="inline-flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
          >
            <span aria-hidden>←</span> Back to run
          </Link>
        </div>
        <h1 className="mt-2 break-all font-mono text-2xl text-neutral-900 dark:text-neutral-100">
          {indId}
        </h1>
        {individual ? (
          <div className="mt-1 text-sm text-neutral-500">
            kind={individual.payload.kind} · is_seed=
            {String(individual.payload.is_seed)}
            {individual.payload.island_id ? ` · island=${individual.payload.island_id}` : ""}
            {individual.payload.generation_index !== null &&
            individual.payload.generation_index !== undefined
              ? ` · generation=${individual.payload.generation_index}`
              : ""}
          </div>
        ) : null}

        <section className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Parents" value={individual?.payload.parent_ids.length ?? 0} />
          <StatCard label="Children" value={outgoingOps.length} />
          <StatCard label="Fitness samples" value={fits.length} />
          <StatCard
            label="Best composite"
            value={
              fits.length > 0
                ? bestComposite(fits).toFixed(3)
                : "—"
            }
          />
        </section>

        <section className="mt-6 grid gap-4 md:grid-cols-2">
          <Card title="Parents">
            {individual && individual.payload.parent_ids.length > 0 ? (
              <ul className="space-y-1 text-sm">
                {individual.payload.parent_ids.map((p) => (
                  <li key={p}>
                    <Link
                      className="font-mono text-neutral-800 hover:underline dark:text-neutral-200"
                      href={`/individual/?run=${encodeURIComponent(
                        runId,
                      )}&id=${encodeURIComponent(p)}`}
                    >
                      {p}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-xs text-neutral-500">
                Seed individual — no parents.
              </div>
            )}
          </Card>
          <Card title="Children">
            {outgoingOps.length > 0 ? (
              <ul className="space-y-1 text-sm">
                {outgoingOps.map((op) => (
                  <li key={op.event_id} className="flex items-center gap-2">
                    <span className="rounded border border-neutral-200 px-1.5 py-0.5 font-mono text-[10px] text-neutral-600 dark:border-neutral-800 dark:text-neutral-400">
                      {op.payload.kind}
                    </span>
                    <Link
                      className="font-mono text-neutral-800 hover:underline dark:text-neutral-200"
                      href={`/individual/?run=${encodeURIComponent(
                        runId,
                      )}&id=${encodeURIComponent(op.payload.child_id)}`}
                    >
                      {op.payload.child_id}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-xs text-neutral-500">No descendants yet.</div>
            )}
          </Card>
        </section>

        <section className="mt-4">
          <Card title="Fitness samples">
            {fits.length === 0 ? (
              <div className="text-xs text-neutral-500">No fitness recorded.</div>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-xs uppercase tracking-wide text-neutral-500">
                  <tr>
                    <th className="py-1 text-left">evaluator</th>
                    <th className="py-1 text-right">composite</th>
                    <th className="py-1 text-right">scores</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100 text-neutral-700 dark:divide-neutral-900 dark:text-neutral-300">
                  {fits.map((f) => (
                    <tr key={f.event_id}>
                      <td className="py-1 font-mono text-xs">{f.payload.evaluator_kind}</td>
                      <td className="py-1 text-right font-mono">
                        {f.payload.composite !== null && f.payload.composite !== undefined
                          ? f.payload.composite.toFixed(3)
                          : "—"}
                      </td>
                      <td className="py-1 text-right font-mono text-xs text-neutral-500">
                        {Object.entries(f.payload.scores)
                          .map(
                            ([k, v]) => `${k}=${typeof v === "number" ? v.toFixed(3) : v}`,
                          )
                          .join(" ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </section>

        {incomingOps.length > 0 ? (
          <section className="mt-4">
            <Card title="Produced by">
              {incomingOps.map((op) => (
                <div
                  key={op.event_id}
                  className="text-sm text-neutral-700 dark:text-neutral-300"
                >
                  <span className="rounded border border-neutral-200 px-1.5 py-0.5 font-mono text-[10px] text-neutral-600 dark:border-neutral-800 dark:text-neutral-400 mr-2">
                    {op.payload.kind}
                  </span>
                  {op.payload.llm_id ? (
                    <span className="text-xs text-neutral-500">
                      via {op.payload.llm_id}
                      {op.payload.cost_usd !== null && op.payload.cost_usd !== undefined
                        ? ` · $${op.payload.cost_usd.toFixed(4)}`
                        : ""}
                    </span>
                  ) : null}
                </div>
              ))}
            </Card>
          </section>
        ) : null}
      </main>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
      <h3 className="mb-2 text-xs uppercase tracking-wide text-neutral-500">{title}</h3>
      {children}
    </div>
  );
}

function bestComposite(fits: FitnessEvent[]): number {
  const vals = fits
    .map((f) => {
      if (f.payload.composite !== null && f.payload.composite !== undefined) {
        return f.payload.composite;
      }
      const scores = Object.values(f.payload.scores).filter(Number.isFinite);
      return scores.length ? Math.max(...scores) : -Infinity;
    })
    .filter((v) => Number.isFinite(v));
  return vals.length ? Math.max(...vals) : 0;
}
