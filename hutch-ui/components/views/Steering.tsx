"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";

import { EmptyState } from "@/components/ui/EmptyState";
import { StatCard } from "@/components/ui/StatCard";
import {
  ackSteering,
  fetcher,
  issueSteering,
  type SteeringRecord,
} from "@/lib/api";
import type { SteeringActor, SteeringCommandKind } from "@/lib/types";

const COMMAND_LABELS: Record<SteeringCommandKind, string> = {
  cancel_individual: "cancel individual",
  freeze_island: "freeze island",
  fork_from: "fork from",
  override_param: "override param",
  pause_run: "pause run",
  resume_run: "resume run",
  cancel_self_mod: "cancel self-mod",
  approve_hitl: "approve HITL",
  inject_hint: "inject hint",
};

const COMMAND_NEEDS_TARGET: Partial<Record<SteeringCommandKind, "individual" | "island" | "agent">> =
  {
    cancel_individual: "individual",
    fork_from: "individual",
    freeze_island: "island",
    cancel_self_mod: "agent",
    approve_hitl: "individual",
    inject_hint: "individual",
  };

const STATUS_COLOR: Record<SteeringRecord["status"], string> = {
  pending: "text-amber-700 bg-amber-50 dark:text-amber-300 dark:bg-amber-950/40",
  delivered: "text-blue-700 bg-blue-50 dark:text-blue-300 dark:bg-blue-950/40",
  acked: "text-emerald-700 bg-emerald-50 dark:text-emerald-300 dark:bg-emerald-950/40",
};

function formatRelative(ns: number, nowNs: number): string {
  const deltaMs = (nowNs - ns) / 1_000_000;
  if (deltaMs < 1000) return "just now";
  if (deltaMs < 60_000) return `${Math.floor(deltaMs / 1000)}s ago`;
  if (deltaMs < 3_600_000) return `${Math.floor(deltaMs / 60_000)}m ago`;
  return `${Math.floor(deltaMs / 3_600_000)}h ago`;
}

export function SteeringView({
  runId,
  canIssue = true,
  readOnlyReason,
}: {
  runId: string;
  canIssue?: boolean;
  readOnlyReason?: string;
}) {
  const history = useSWR<SteeringRecord[]>(
    `/steering/${encodeURIComponent(runId)}`,
    fetcher,
    { refreshInterval: 2000 },
  );
  const records = useMemo(() => history.data ?? [], [history.data]);

  const [command, setCommand] = useState<SteeringCommandKind>("pause_run");
  const [targetId, setTargetId] = useState("");
  const [paramsText, setParamsText] = useState("{}");
  const [actor, setActor] = useState<SteeringActor>("human");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Tick once a second to refresh "just now" / "12s ago" labels.
  const [now, setNow] = useState<number>(Date.now() * 1_000_000);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() * 1_000_000), 1000);
    return () => clearInterval(t);
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    let params: Record<string, unknown>;
    try {
      params = paramsText.trim() === "" ? {} : JSON.parse(paramsText);
    } catch {
      setSubmitError("params must be valid JSON");
      return;
    }
    setSubmitting(true);
    try {
      await issueSteering(runId, {
        command,
        target_id: targetId.trim() || null,
        params,
        actor,
      });
      void history.mutate();
      setTargetId("");
      setParamsText("{}");
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const onAck = async (rec: SteeringRecord, outcome: "accepted" | "rejected") => {
    try {
      await ackSteering(runId, rec.command_id, outcome, `manual ack from UI (${outcome})`);
      void history.mutate();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    }
  };

  const pending = records.filter((r) => r.status === "pending");
  const delivered = records.filter((r) => r.status === "delivered");
  const acked = records.filter((r) => r.status === "acked");
  const hitlOpen = records.filter(
    (r) => r.command === "approve_hitl" && r.status !== "acked",
  );

  const targetHint = COMMAND_NEEDS_TARGET[command];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Pending" value={pending.length} hint="awaiting agent poll" />
        <StatCard
          label="Delivered"
          value={delivered.length}
          hint="agent received but not yet acked"
        />
        <StatCard label="Acked" value={acked.length} hint="agent reported outcome" />
        <StatCard
          label="HITL open"
          value={hitlOpen.length}
          hint="approve_hitl awaiting decision"
        />
      </div>

      {canIssue ? (
        <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
          <h3 className="mb-3 text-sm font-medium text-neutral-800 dark:text-neutral-200">
            Issue command
          </h3>
          <form onSubmit={onSubmit} className="grid gap-3 md:grid-cols-[1fr_1fr_2fr_auto]">
            <label className="flex flex-col text-xs text-neutral-500">
              command
              <select
                value={command}
                onChange={(e) => setCommand(e.target.value as SteeringCommandKind)}
                className="mt-1 rounded border border-neutral-300 bg-white px-2 py-1.5 font-mono text-xs text-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
              >
                {(Object.keys(COMMAND_LABELS) as SteeringCommandKind[]).map((k) => (
                  <option key={k} value={k}>
                    {COMMAND_LABELS[k]}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col text-xs text-neutral-500">
              target id {targetHint ? `(${targetHint})` : "(optional)"}
              <input
                type="text"
                value={targetId}
                onChange={(e) => setTargetId(e.target.value)}
                placeholder={targetHint === "individual" ? "ind-…" : ""}
                className="mt-1 rounded border border-neutral-300 bg-white px-2 py-1.5 font-mono text-xs text-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
              />
            </label>
            <label className="flex flex-col text-xs text-neutral-500">
              params (JSON)
              <input
                type="text"
                value={paramsText}
                onChange={(e) => setParamsText(e.target.value)}
                placeholder='{"reason": "user requested"}'
                className="mt-1 rounded border border-neutral-300 bg-white px-2 py-1.5 font-mono text-xs text-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
              />
            </label>
            <label className="flex flex-col text-xs text-neutral-500">
              actor
              <select
                value={actor}
                onChange={(e) => setActor(e.target.value as SteeringActor)}
                className="mt-1 rounded border border-neutral-300 bg-white px-2 py-1.5 font-mono text-xs text-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
              >
                <option value="human">human</option>
                <option value="agent">agent</option>
                <option value="policy">policy</option>
              </select>
            </label>
            <button
              type="submit"
              disabled={submitting}
              className="md:col-span-4 inline-flex items-center justify-center gap-2 rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-neutral-950"
            >
              {submitting ? "sending…" : "Issue command"}
            </button>
          </form>
          {submitError ? (
            <div className="mt-2 text-xs text-rose-600 dark:text-rose-400">{submitError}</div>
          ) : null}
        </div>
      ) : (
        <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-600 dark:border-neutral-800 dark:bg-neutral-950 dark:text-neutral-400">
          {readOnlyReason ?? "Steering is read-only for this run."}
        </div>
      )}

      {/* HITL queue */}
      {canIssue && hitlOpen.length > 0 ? (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
          <h3 className="mb-2 text-sm font-medium text-amber-800 dark:text-amber-200">
            Human-in-the-loop approvals
          </h3>
          <div className="space-y-2">
            {hitlOpen.map((rec) => (
              <div
                key={rec.command_id}
                className="flex items-center justify-between rounded border border-amber-200 bg-white px-3 py-2 dark:border-amber-900 dark:bg-neutral-950"
              >
                <div>
                  <div className="text-sm text-neutral-800 dark:text-neutral-200">
                    Approve <span className="font-mono text-xs">{rec.target_id}</span>?
                  </div>
                  <div className="text-xs text-neutral-500">
                    {Object.keys(rec.params || {}).length > 0
                      ? `params: ${JSON.stringify(rec.params)}`
                      : "no params"}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void onAck(rec, "accepted")}
                    className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700"
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    onClick={() => void onAck(rec, "rejected")}
                    className="rounded bg-rose-600 px-3 py-1 text-xs font-medium text-white hover:bg-rose-700"
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Queue / history */}
      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
        <h3 className="mb-2 text-sm font-medium text-neutral-800 dark:text-neutral-200">
          Command queue
        </h3>
        {records.length === 0 ? (
          <EmptyState
            title="No steering commands yet"
            detail={
              canIssue
                ? "Issue a command above; it will appear here and become visible to any agent polling hutch.steering.poll() against this run id."
                : "No steering commands were logged for this run."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="py-1 pr-3">Command</th>
                  <th className="py-1 pr-3">Target</th>
                  <th className="py-1 pr-3">Actor</th>
                  <th className="py-1 pr-3">Status</th>
                  <th className="py-1 pr-3">Outcome</th>
                  <th className="py-1">Issued</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 text-neutral-700 dark:divide-neutral-900 dark:text-neutral-300">
                {records
                  .slice()
                  .sort((a, b) => b.created_at_ns - a.created_at_ns)
                  .map((rec) => (
                    <tr key={rec.command_id}>
                      <td className="py-1.5 pr-3 font-mono text-xs">{rec.command}</td>
                      <td className="py-1.5 pr-3 font-mono text-xs text-neutral-500">
                        {rec.target_id ?? "—"}
                      </td>
                      <td className="py-1.5 pr-3 text-xs">{rec.actor}</td>
                      <td className="py-1.5 pr-3">
                        <span
                          className={`rounded px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide ${STATUS_COLOR[rec.status]}`}
                        >
                          {rec.status}
                        </span>
                      </td>
                      <td className="py-1.5 pr-3 text-xs text-neutral-500">
                        {rec.outcome ?? "—"}
                        {rec.outcome_note ? (
                          <span className="ml-1 italic">({rec.outcome_note})</span>
                        ) : null}
                      </td>
                      <td className="py-1.5 text-xs text-neutral-500">
                        {formatRelative(rec.created_at_ns, now)}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-xs text-neutral-500 dark:border-neutral-800 dark:bg-neutral-950">
        Commands are available only for running runs that advertise the steering
        capability. Historical steering commands are shown read-only from the
        event log when present.
      </div>
    </div>
  );
}
