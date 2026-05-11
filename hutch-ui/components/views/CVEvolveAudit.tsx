"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";

import { EmptyState } from "@/components/ui/EmptyState";
import { StatCard } from "@/components/ui/StatCard";
import { fetcher } from "@/lib/api";
import type { StreamEvent, StreamEventsPage } from "@/lib/types";

type AuditFilter = "all" | "message" | "tool_call";
const PAGE_SIZE = 200;
const EMPTY_EVENTS: StreamEvent[] = [];

function auditKind(event: StreamEvent): "message" | "tool_call" | null {
  const raw = event.payload.metadata?.audit_kind;
  if (raw === "message" || raw === "tool_call") return raw;
  if (event.payload.label === "cvevolve_message") return "message";
  if (event.payload.label === "cvevolve_tool_call") return "tool_call";
  return null;
}

function labelForFilter(filter: AuditFilter): string | null {
  if (filter === "message") return "cvevolve_message";
  if (filter === "tool_call") return "cvevolve_tool_call";
  return null;
}

function metadataString(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatTime(timestampNs: number): string {
  const millis = Math.floor(timestampNs / 1_000_000);
  if (!Number.isFinite(millis) || millis <= 0) return "unknown";
  return new Date(millis).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function eventTitle(event: StreamEvent): string {
  const metadata = event.payload.metadata ?? {};
  const kind = auditKind(event);
  if (kind === "tool_call") return metadataString(metadata.tool_name) || "tool call";
  return metadataString(metadata.message_type) || "message";
}

function auditPath(
  runId: string,
  filter: AuditFilter,
  query: string,
  offset: number,
): string {
  const search = new URLSearchParams();
  const label = labelForFilter(filter);
  if (label) search.set("label", label);
  const trimmed = query.trim();
  if (trimmed) search.set("query", trimmed);
  search.set("offset", String(offset));
  search.set("limit", String(PAGE_SIZE));
  return `/runs/${encodeURIComponent(runId)}/stream_events?${search.toString()}`;
}

export function CVEvolveAuditView({ runId }: { runId: string }) {
  const [filter, setFilter] = useState<AuditFilter>("all");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    setOffset(0);
    setSelectedId(null);
  }, [filter, query]);

  const path = useMemo(
    () => auditPath(runId, filter, query, offset),
    [runId, filter, query, offset],
  );
  const page = useSWR<StreamEventsPage>(path, fetcher, {
    keepPreviousData: true,
    refreshInterval: 5000,
  });
  const events = page.data?.events ?? EMPTY_EVENTS;
  const total = page.data?.total ?? 0;
  const currentOffset = page.data?.offset ?? offset;
  const currentLimit = page.data?.limit ?? PAGE_SIZE;
  const selected = events.find((event) => event.event_id === selectedId) ?? events[0] ?? null;
  const pageEnd = Math.min(currentOffset + events.length, total);

  const counts = useMemo(() => {
    let messages = 0;
    let toolCalls = 0;
    let truncated = 0;
    for (const event of events) {
      const kind = auditKind(event);
      if (kind === "message") messages += 1;
      if (kind === "tool_call") toolCalls += 1;
      if (event.payload.metadata?.truncated === true) truncated += 1;
    }
    return { messages, toolCalls, truncated };
  }, [events]);

  if (page.error) {
    return (
      <EmptyState
        title="Couldn't load CVEvolve audit"
        detail="The daemon audit endpoint returned an error."
      />
    );
  }

  if (!page.isLoading && total === 0) {
    return (
      <div className="space-y-4">
        <AuditControls
          filter={filter}
          query={query}
          onFilter={setFilter}
          onQuery={setQuery}
          total={total}
          currentOffset={0}
          pageEnd={0}
        />
        <EmptyState
          title="No CVEvolve audit events"
          detail="Run the CVEvolve adapter with --include-audit to import messages.sqlite and tool_calls.sqlite rows."
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Matched audit events" value={total} />
        <StatCard label="Page messages" value={counts.messages} />
        <StatCard label="Page tool calls" value={counts.toolCalls} />
        <StatCard label="Page truncated" value={counts.truncated} />
      </div>

      <AuditControls
        filter={filter}
        query={query}
        onFilter={setFilter}
        onQuery={setQuery}
        total={total}
        currentOffset={currentOffset}
        pageEnd={pageEnd}
      />

      <div className="flex items-center justify-between text-xs text-neutral-500">
        <button
          type="button"
          disabled={currentOffset <= 0}
          onClick={() => setOffset(Math.max(0, currentOffset - currentLimit))}
          className="rounded border border-neutral-200 px-2 py-1 disabled:opacity-40 dark:border-neutral-800"
        >
          Previous
        </button>
        <span>
          {page.isLoading ? "loading..." : `${currentOffset + 1}-${pageEnd} of ${total}`}
        </span>
        <button
          type="button"
          disabled={pageEnd >= total}
          onClick={() => setOffset(currentOffset + currentLimit)}
          className="rounded border border-neutral-200 px-2 py-1 disabled:opacity-40 dark:border-neutral-800"
        >
          Next
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(280px,2fr)]">
        <div className="overflow-hidden rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full table-fixed text-sm">
            <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500 dark:bg-neutral-950">
              <tr>
                <th className="w-24 px-3 py-2">Time</th>
                <th className="w-28 px-3 py-2">Kind</th>
                <th className="w-36 px-3 py-2">Source</th>
                <th className="px-3 py-2">Text</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-900">
              {events.map((event) => {
                const metadata = event.payload.metadata ?? {};
                return (
                  <tr
                    key={event.event_id}
                    onClick={() => setSelectedId(event.event_id)}
                    className={`cursor-pointer align-top ${
                      selected?.event_id === event.event_id
                        ? "bg-neutral-100 dark:bg-neutral-900"
                        : "hover:bg-neutral-50 dark:hover:bg-neutral-950"
                    }`}
                  >
                    <td className="px-3 py-2 font-mono text-xs text-neutral-600 dark:text-neutral-400">
                      {formatTime(event.timestamp_ns)}
                    </td>
                    <td className="px-3 py-2">
                      <span className="inline-flex rounded border border-neutral-200 px-2 py-0.5 text-[10px] text-neutral-600 dark:border-neutral-800 dark:text-neutral-300">
                        {(auditKind(event) ?? "audit").replace("_", " ")}
                      </span>
                    </td>
                    <td className="break-words px-3 py-2 font-mono text-xs text-neutral-600 dark:text-neutral-400">
                      {eventTitle(event)}
                      {metadata.round_index !== undefined && metadata.round_index !== null ? (
                        <span className="block text-neutral-400">
                          r{metadataString(metadata.round_index)}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-xs text-neutral-700 dark:text-neutral-300">
                      <div className="line-clamp-3 whitespace-pre-wrap break-words">
                        {event.payload.text || "-"}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
          {selected ? (
            <div className="space-y-3 text-sm">
              <div>
                <div className="text-xs uppercase tracking-wide text-neutral-500">
                  Selected Event
                </div>
                <div className="mt-1 break-all font-mono text-xs text-neutral-800 dark:text-neutral-200">
                  {selected.event_id}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <div className="text-neutral-500">kind</div>
                  <div className="mt-1 font-mono">{auditKind(selected)}</div>
                </div>
                <div>
                  <div className="text-neutral-500">worker</div>
                  <div className="mt-1 font-mono">{selected.worker_id ?? "-"}</div>
                </div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-neutral-500">
                  Text
                </div>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-800 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-200">
                  {selected.payload.text || ""}
                </pre>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-neutral-500">
                  Metadata
                </div>
                <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-800 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-200">
                  {metadataString(selected.payload.metadata)}
                </pre>
              </div>
            </div>
          ) : (
            <div className="text-sm text-neutral-500">No matching audit event.</div>
          )}
        </div>
      </div>
    </div>
  );
}

function AuditControls({
  filter,
  query,
  onFilter,
  onQuery,
  total,
  currentOffset,
  pageEnd,
}: {
  filter: AuditFilter;
  query: string;
  onFilter: (filter: AuditFilter) => void;
  onQuery: (query: string) => void;
  total: number;
  currentOffset: number;
  pageEnd: number;
}) {
  return (
    <div className="flex flex-col gap-3 text-xs text-neutral-500 md:flex-row md:items-center">
      <div className="flex items-center gap-2">
        <span>filter</span>
        {(["all", "message", "tool_call"] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => onFilter(value)}
            className={`rounded border px-2 py-1 ${
              filter === value
                ? "border-emerald-500 text-emerald-700 dark:border-emerald-600 dark:text-emerald-200"
                : "border-neutral-200 text-neutral-600 hover:text-neutral-900 dark:border-neutral-800 dark:text-neutral-400 dark:hover:text-neutral-200"
            }`}
          >
            {value.replace("_", " ")}
          </button>
        ))}
      </div>
      <input
        value={query}
        onChange={(event) => onQuery(event.target.value)}
        placeholder="Search audit text or metadata"
        className="min-w-0 flex-1 rounded border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none focus:border-emerald-500 md:max-w-sm dark:border-neutral-800 dark:bg-neutral-950 dark:text-neutral-100"
      />
      <span className="md:ml-auto">
        {total === 0 ? "0 matched" : `${currentOffset + 1}-${pageEnd} of ${total}`}
      </span>
    </div>
  );
}
