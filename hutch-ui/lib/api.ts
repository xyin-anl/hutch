/**
 * Daemon API client.
 *
 * The daemon URL is read from the `NEXT_PUBLIC_HUTCH_DAEMON_URL` environment
 * variable at build/runtime; for local dev it defaults to
 * `http://127.0.0.1:7777`. SWR consumes the `fetcher` helper.
 */

import type {
  ClaimEvent,
  DescriptorEvent,
  EvidenceEvent,
  FitnessEvent,
  IndividualEvent,
  OperatorEvent,
  ParetoSnapshotEvent,
  RunDetail,
  RunSummary,
  SelfModEvent,
  SteeringActor,
  SteeringCommandKind,
  TreeExpansionEvent,
} from "@/lib/types";

/**
 * Daemon base URL.
 *
 * Resolution order (first non-empty wins):
 *
 * 1. ``NEXT_PUBLIC_HUTCH_DAEMON_URL`` — set this for ``pnpm dev`` when the
 *    UI runs on its own origin (``:7700``) and needs to call out to a
 *    daemon on a different origin (``:7777``).
 * 2. *(empty string)* — when the UI is served *by* the daemon, fetches
 *    are same-origin and don't need any prefix at all. This is the
 *    production path: ``hutch serve`` mounts the static bundle, so
 *    ``GET /runs`` resolves to the daemon that delivered the page.
 */
export function daemonUrl(): string {
  if (typeof process !== "undefined") {
    const env = process.env.NEXT_PUBLIC_HUTCH_DAEMON_URL;
    if (env && env.length > 0) return env;
  }
  return "";
}

export function daemonToken(): string {
  // This is a local-development convenience, not a browser secret. Hosted
  // dashboards should rely on same-origin proxy/session auth.
  if (typeof process !== "undefined") {
    const env = process.env.NEXT_PUBLIC_HUTCH_TOKEN;
    if (env && env.length > 0) return env;
  }
  return "";
}

function authHeaders(): HeadersInit {
  const token = daemonToken();
  return token ? { authorization: `Bearer ${token}` } : {};
}

export async function fetcher<T>(path: string): Promise<T> {
  const base = daemonUrl();
  const url = path.startsWith("http") ? path : base + path;
  const response = await fetch(url, { cache: "no-store", headers: authHeaders() });
  if (!response.ok) {
    const text = await response.text();
    const err: Error & { status?: number } = new Error(
      `Daemon returned ${response.status} for ${path}: ${text}`,
    );
    err.status = response.status;
    throw err;
  }
  return (await response.json()) as T;
}

// Strongly-typed wrappers.
export const listRuns = (): Promise<RunSummary[]> => fetcher<RunSummary[]>("/runs");
export const getRun = (runId: string): Promise<RunDetail> =>
  fetcher<RunDetail>(`/runs/${encodeURIComponent(runId)}`);
export const getIndividuals = (runId: string): Promise<IndividualEvent[]> =>
  fetcher<IndividualEvent[]>(`/runs/${encodeURIComponent(runId)}/individuals`);
export const getOperators = (runId: string): Promise<OperatorEvent[]> =>
  fetcher<OperatorEvent[]>(`/runs/${encodeURIComponent(runId)}/operators`);
export const getFitness = (runId: string): Promise<FitnessEvent[]> =>
  fetcher<FitnessEvent[]>(`/runs/${encodeURIComponent(runId)}/fitness`);
export const getDescriptors = (runId: string): Promise<DescriptorEvent[]> =>
  fetcher<DescriptorEvent[]>(`/runs/${encodeURIComponent(runId)}/descriptors`);
export const getParetoSnapshots = (runId: string): Promise<ParetoSnapshotEvent[]> =>
  fetcher<ParetoSnapshotEvent[]>(`/runs/${encodeURIComponent(runId)}/pareto_snapshots`);
export const getSelfMods = (runId: string): Promise<SelfModEvent[]> =>
  fetcher<SelfModEvent[]>(`/runs/${encodeURIComponent(runId)}/self_mods`);
export const getTreeExpansions = (runId: string): Promise<TreeExpansionEvent[]> =>
  fetcher<TreeExpansionEvent[]>(`/runs/${encodeURIComponent(runId)}/tree_expansions`);
export const getClaims = (runId: string): Promise<ClaimEvent[]> =>
  fetcher<ClaimEvent[]>(`/runs/${encodeURIComponent(runId)}/claims`);
export const getEvidence = (runId: string): Promise<EvidenceEvent[]> =>
  fetcher<EvidenceEvent[]>(`/runs/${encodeURIComponent(runId)}/evidence`);

// ---------- steering ------------------------------------------------------

export interface SteeringRecord {
  command_id: string;
  run_id: string;
  command: SteeringCommandKind;
  target_id: string | null;
  params: Record<string, unknown>;
  actor: SteeringActor;
  created_at_ns: number;
  status: "pending" | "delivered" | "acked";
  delivered_at_ns: number | null;
  acked_at_ns: number | null;
  outcome: string | null;
  outcome_note: string | null;
}

export const getSteeringHistory = (runId: string): Promise<SteeringRecord[]> =>
  fetcher<SteeringRecord[]>(`/steering/${encodeURIComponent(runId)}`);

export async function issueSteering(
  runId: string,
  body: {
    command: SteeringCommandKind;
    target_id?: string | null;
    params?: Record<string, unknown>;
    actor?: SteeringActor;
  },
): Promise<SteeringRecord> {
  const base = daemonUrl();
  const response = await fetch(
    `${base}/steering/${encodeURIComponent(runId)}`,
    {
      method: "POST",
      headers: { "content-type": "application/json", ...authHeaders() },
      body: JSON.stringify({ actor: "human", ...body }),
    },
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`POST /steering returned ${response.status}: ${text}`);
  }
  return (await response.json()) as SteeringRecord;
}

export async function ackSteering(
  runId: string,
  commandId: string,
  outcome: "accepted" | "rejected" | "done",
  note?: string,
): Promise<SteeringRecord> {
  const base = daemonUrl();
  const response = await fetch(
    `${base}/steering/${encodeURIComponent(runId)}/${encodeURIComponent(commandId)}/ack`,
    {
      method: "POST",
      headers: { "content-type": "application/json", ...authHeaders() },
      body: JSON.stringify({ outcome, note: note ?? null }),
    },
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`ack returned ${response.status}: ${text}`);
  }
  return (await response.json()) as SteeringRecord;
}
