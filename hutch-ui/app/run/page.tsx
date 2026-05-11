"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import useSWR, { useSWRConfig } from "swr";

import { Breadcrumbs } from "@/components/nav/Breadcrumbs";
import { LiveDot } from "@/components/nav/LiveDot";
import { TopBar } from "@/components/nav/TopBar";
import { EmptyState } from "@/components/ui/EmptyState";
import { ArchiveView } from "@/components/views/Archive";
import { CVEvolveAuditView } from "@/components/views/CVEvolveAudit";
import { EvidenceView } from "@/components/views/Evidence";
import { OperatorTraceView } from "@/components/views/OperatorTrace";
import { OperatorsView } from "@/components/views/Operators";
import { OverviewView } from "@/components/views/Overview";
import { ObjectivesView } from "@/components/views/Objectives";
import { PhylogenyView } from "@/components/views/Phylogeny";
import { PopulationView } from "@/components/views/Population";
import { SelfModAuditView } from "@/components/views/SelfModAudit";
import { SteeringView } from "@/components/views/Steering";
import { TreeSearchView } from "@/components/views/TreeSearch";
import { fetcher } from "@/lib/api";
import type { SteeringRecord } from "@/lib/api";
import { canIssueSteering, canShowSteering } from "@/lib/capabilities";
import type {
  ClaimEvent,
  DescriptorEvent,
  EvidenceEvent,
  FitnessEvent,
  IndividualEvent,
  OperatorEvent,
  RunDetail,
  SelfModEvent,
  TreeExpansionEvent,
} from "@/lib/types";
import { subscribeRunStream } from "@/lib/ws";

type TabKey =
  | "overview"
  | "phylogeny"
  | "population"
  | "archive"
  | "objectives"
  | "operators"
  | "operator-trace"
  | "cvevolve-audit"
  | "self-mod"
  | "tree-search"
  | "evidence"
  | "steering";

interface TabSpec {
  key: TabKey;
  label: string;
  // When false, the tab is hidden in the nav.
  available: boolean;
}

export default function RunPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-neutral-500">loading…</div>}>
      <RunDashboard />
    </Suspense>
  );
}

function RunDashboard() {
  const searchParams = useSearchParams();
  const runId = searchParams.get("id") ?? "";
  const encodedRunId = runId ? encodeURIComponent(runId) : "";
  const [tab, setTab] = useState<TabKey>("overview");

  const { mutate } = useSWRConfig();
  const [live, setLive] = useState(false);

  const detail = useSWR<RunDetail>(
    runId ? `/runs/${encodedRunId}` : null,
    fetcher,
    { refreshInterval: 5000 },
  );
  const auditTabAvailable = detail.data?.capabilities?.audit === true;
  const shouldLoadSteering =
    runId.length > 0 &&
    (detail.data?.capabilities?.steering === true ||
      detail.data?.kinds_seen.includes("steering_command") === true);
  const individuals = useSWR<IndividualEvent[]>(
    runId ? `/runs/${encodedRunId}/individuals` : null,
    fetcher,
  );
  const operators = useSWR<OperatorEvent[]>(
    runId ? `/runs/${encodedRunId}/operators` : null,
    fetcher,
  );
  const fitness = useSWR<FitnessEvent[]>(
    runId ? `/runs/${encodedRunId}/fitness` : null,
    fetcher,
  );
  const descriptors = useSWR<DescriptorEvent[]>(
    runId ? `/runs/${encodedRunId}/descriptors` : null,
    fetcher,
  );
  const selfMods = useSWR<SelfModEvent[]>(
    runId ? `/runs/${encodedRunId}/self_mods` : null,
    fetcher,
  );
  const treeExpansions = useSWR<TreeExpansionEvent[]>(
    runId ? `/runs/${encodedRunId}/tree_expansions` : null,
    fetcher,
  );
  const claims = useSWR<ClaimEvent[]>(
    runId ? `/runs/${encodedRunId}/claims` : null,
    fetcher,
  );
  const evidence = useSWR<EvidenceEvent[]>(
    runId ? `/runs/${encodedRunId}/evidence` : null,
    fetcher,
  );
  const steeringHistory = useSWR<SteeringRecord[]>(
    shouldLoadSteering ? `/steering/${encodedRunId}` : null,
    fetcher,
  );

  useEffect(() => {
    if (!runId) return;
    const sub = subscribeRunStream(
      runId,
      () => {
        setLive(true);
        const enc = encodeURIComponent(runId);
        void mutate(`/runs/${enc}`);
        void mutate(`/runs/${enc}/individuals`);
        void mutate(`/runs/${enc}/operators`);
        void mutate(`/runs/${enc}/fitness`);
        void mutate(`/runs/${enc}/descriptors`);
        void mutate(`/runs/${enc}/claims`);
        void mutate(`/runs/${enc}/evidence`);
        if (shouldLoadSteering) void mutate(`/steering/${enc}`);
      },
      () => setLive(false),
      () => setLive(true),
      () => setLive(false),
    );
    return () => sub.close();
  }, [runId, mutate, shouldLoadSteering]);

  const inds = useMemo(() => individuals.data ?? [], [individuals.data]);
  const ops = useMemo(() => operators.data ?? [], [operators.data]);
  const fits = useMemo(() => fitness.data ?? [], [fitness.data]);
  const descs = useMemo(() => descriptors.data ?? [], [descriptors.data]);
  const selfModEvents = useMemo(() => selfMods.data ?? [], [selfMods.data]);
  const treeEvents = useMemo(
    () => treeExpansions.data ?? [],
    [treeExpansions.data],
  );
  const claimEvents = useMemo(() => claims.data ?? [], [claims.data]);
  const evidenceEvents = useMemo(() => evidence.data ?? [], [evidence.data]);
  const steeringRecords = useMemo(
    () => (shouldLoadSteering ? steeringHistory.data ?? [] : []),
    [shouldLoadSteering, steeringHistory.data],
  );
  const steeringVisible =
    shouldLoadSteering && canShowSteering(detail.data, steeringRecords);
  const steeringWritable = canIssueSteering(detail.data);

  const tabs: TabSpec[] = [
    { key: "overview", label: "Overview", available: true },
    { key: "phylogeny", label: "Phylogeny", available: inds.length > 0 },
    { key: "population", label: "Population", available: fits.length > 0 },
    { key: "archive", label: "Archive", available: descs.length > 0 },
    {
      key: "objectives",
      label: "Objectives",
      // Best-so-far + distribution sub-modes work with any number of
      // metrics (including 1); Trade-off + Parallel require ≥2 / ≥3 and
      // gate themselves inside the view. So the tab itself shows up
      // whenever the run has at least one valid fitness sample.
      available: fits.some((f) => !f.payload.invalid_reason && Object.keys(f.payload.scores ?? {}).length >= 1),
    },
    { key: "operators", label: "Operators", available: ops.length > 0 },
    {
      key: "operator-trace",
      label: "Operator-trace",
      available: ops.length > 0,
    },
    {
      key: "cvevolve-audit",
      label: "CVEvolve Audit",
      available: auditTabAvailable,
    },
    {
      key: "self-mod",
      label: "Self-Mod Audit",
      available: selfModEvents.length > 0,
    },
    {
      key: "tree-search",
      label: "Tree Search",
      available: treeEvents.length > 0,
    },
    {
      key: "evidence",
      label: "Evidence Graph",
      available: claimEvents.length > 0 || evidenceEvents.length > 0,
    },
    {
      key: "steering",
      label: "Steering",
      available: steeringVisible,
    },
  ];
  const visibleTabs = tabs.filter((t) => t.available);

  // If the active tab disappeared (e.g. data hasn't loaded), bounce to Overview.
  useEffect(() => {
    if (!visibleTabs.some((t) => t.key === tab)) setTab("overview");
  }, [tab, visibleTabs]);

  if (!runId) {
    return (
      <div className="min-h-screen">
        <TopBar />
        <main className="mx-auto max-w-6xl px-6 py-10">
          <EmptyState
            title="No run id"
            detail={<>This page expects a <code>?id=&lt;run_id&gt;</code> query string.</>}
          />
        </main>
      </div>
    );
  }

  const isLoading =
    detail.isLoading ||
    individuals.isLoading ||
    operators.isLoading ||
    fitness.isLoading ||
    descriptors.isLoading ||
    selfMods.isLoading ||
    treeExpansions.isLoading ||
    claims.isLoading ||
    evidence.isLoading ||
    (shouldLoadSteering && steeringHistory.isLoading);
  const error =
    detail.error ||
    individuals.error ||
    operators.error ||
    fitness.error ||
    descriptors.error ||
    selfMods.error ||
    treeExpansions.error ||
    claims.error ||
    evidence.error ||
    (shouldLoadSteering ? steeringHistory.error : undefined);

  return (
    <div className="min-h-screen">
      <TopBar>
        <LiveDot live={live} />
      </TopBar>
      <main className="mx-auto max-w-6xl px-6 py-8">
        <Breadcrumbs
          items={[
            { label: "The Hutch", href: "/" },
            { label: "runs", href: "/" },
            { label: <span className="font-mono">{runId}</span> },
          ]}
        />
        <div className="mt-3">
          <Link
            href="/"
            className="inline-flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
          >
            <span aria-hidden>←</span> All runs
          </Link>
        </div>
        <header className="mt-2 space-y-1">
          <h1 className="break-all font-mono text-2xl text-neutral-900 dark:text-neutral-100">
            {runId}
          </h1>
          {detail.data ? (
            <div className="text-sm text-neutral-500">
              {detail.data.event_count} events ·{" "}
              {detail.data.kinds_seen.length} event kinds
            </div>
          ) : null}
        </header>

        {error ? (
          <div className="mt-8">
            <EmptyState
              title="Couldn't load this run"
              detail={
                (error as { status?: number; message: string }).status === 404
                  ? "The daemon doesn't have any events under this id."
                  : "Network error talking to the daemon."
              }
            />
          </div>
        ) : (
          <>
            <nav className="mt-6 flex flex-wrap gap-1 border-b border-neutral-200 dark:border-neutral-900">
              {visibleTabs.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setTab(t.key)}
                  className={`px-4 py-2 text-sm transition-colors ${
                    tab === t.key
                      ? "border-b-2 border-emerald-600 text-neutral-900 dark:border-emerald-400 dark:text-neutral-100"
                      : "border-b-2 border-transparent text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </nav>
            <section className="mt-6">
              {isLoading ? (
                <div className="text-sm text-neutral-500">loading…</div>
              ) : tab === "overview" ? (
                <OverviewView
                  detail={detail.data}
                  individuals={inds}
                  operators={ops}
                  fitness={fits}
                />
              ) : tab === "phylogeny" ? (
                <PhylogenyView
                  runId={runId}
                  individuals={inds}
                  fitness={fits}
                  scoreDirections={detail.data?.score_directions}
                />
              ) : tab === "population" ? (
                <PopulationView
                  individuals={inds}
                  fitness={fits}
                  scoreDirections={detail.data?.score_directions}
                />
              ) : tab === "archive" ? (
                <ArchiveView
                  descriptors={descs}
                  fitness={fits}
                  scoreDirections={detail.data?.score_directions}
                />
              ) : tab === "objectives" ? (
                <ObjectivesView
                  fitness={fits}
                  scoreDirections={detail.data?.score_directions}
                />
              ) : tab === "operators" ? (
                <OperatorsView operators={ops} />
              ) : tab === "operator-trace" ? (
                <OperatorTraceView operators={ops} individuals={inds} />
              ) : tab === "cvevolve-audit" ? (
                <CVEvolveAuditView runId={runId} />
              ) : tab === "self-mod" ? (
                <SelfModAuditView runId={runId} selfMods={selfModEvents} />
              ) : tab === "tree-search" ? (
                <TreeSearchView expansions={treeEvents} individuals={inds} />
              ) : tab === "evidence" ? (
                <EvidenceView claims={claimEvents} evidence={evidenceEvents} />
              ) : (
                <SteeringView
                  runId={runId}
                  canIssue={steeringWritable}
                  readOnlyReason={
                    detail.data?.capabilities?.steering === true
                      ? "This run is not currently running; steering history is read-only."
                      : "This run does not advertise live steering; showing logged history only."
                  }
                />
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
