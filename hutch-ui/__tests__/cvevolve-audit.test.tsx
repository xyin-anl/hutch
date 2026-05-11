import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import { CVEvolveAuditView } from "@/components/views/CVEvolveAudit";

const fetchMock = vi.fn();

function renderWithFreshCache() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <CVEvolveAuditView runId="run 1" />
    </SWRConfig>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({
    ok: true,
    json: async () => ({
      events: [
        {
          event_id: "ev-1",
          event_kind: "stream_event",
          run_id: "run 1",
          timestamp_ns: 1_700_000_000_000_000_000,
          payload: {
            label: "cvevolve_message",
            text: "alpha prompt",
            metadata: { audit_kind: "message", message_type: "user" },
          },
        },
      ],
      total: 1,
      offset: 0,
      limit: 200,
    }),
    text: async () => "ok",
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CVEvolveAuditView", () => {
  it("uses paged server-side audit fetches", async () => {
    renderWithFreshCache();

    await waitFor(() => {
      expect(screen.getAllByText("alpha prompt").length).toBeGreaterThan(0);
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/runs/run%201/stream_events?offset=0&limit=200",
      expect.any(Object),
    );
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes("limit=50000")),
    ).toBe(false);
  });

  it("passes filter and query to the daemon", async () => {
    renderWithFreshCache();

    await waitFor(() => {
      expect(screen.getAllByText("alpha prompt").length).toBeGreaterThan(0);
    });
    fireEvent.click(screen.getByRole("button", { name: "tool call" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).includes("label=cvevolve_tool_call"),
        ),
      ).toBe(true);
    });

    fireEvent.change(screen.getByPlaceholderText("Search audit text or metadata"), {
      target: { value: "alpha" },
    });
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).includes("query=alpha")),
      ).toBe(true);
    });
  });
});
