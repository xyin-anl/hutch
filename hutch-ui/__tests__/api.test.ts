import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ackSteering,
  fetcher,
  getStreamEvents,
  getStreamEventsPage,
  issueSteering,
} from "@/lib/api";

const OLD_ENV = process.env;

beforeEach(() => {
  process.env = { ...OLD_ENV };
});

afterEach(() => {
  process.env = OLD_ENV;
  vi.unstubAllGlobals();
});

describe("daemon API client", () => {
  it("builds relative URLs and bearer headers for fetcher", async () => {
    process.env.NEXT_PUBLIC_HUTCH_TOKEN = "secret";
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
      text: async () => "ok",
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetcher("/runs")).resolves.toEqual({ ok: true });

    expect(fetchMock).toHaveBeenCalledWith("/runs", {
      cache: "no-store",
      headers: { authorization: "Bearer secret" },
    });
  });

  it("prefixes daemon URL for steering mutations", async () => {
    process.env.NEXT_PUBLIC_HUTCH_DAEMON_URL = "http://daemon.test";
    process.env.NEXT_PUBLIC_HUTCH_TOKEN = "secret";
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ command_id: "cmd-1" }),
      text: async () => "ok",
    });
    vi.stubGlobal("fetch", fetchMock);

    await issueSteering("run 1", { command: "pause_run" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://daemon.test/steering/run%201",
      expect.objectContaining({
        method: "POST",
        headers: { "content-type": "application/json", authorization: "Bearer secret" },
      }),
    );
  });

  it("encodes ack paths", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ command_id: "cmd/1" }),
      text: async () => "ok",
    });
    vi.stubGlobal("fetch", fetchMock);

    await ackSteering("run/1", "cmd/1", "done");

    expect(fetchMock).toHaveBeenCalledWith(
      "/steering/run%2F1/cmd%2F1/ack",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("uses bounded stream-event helpers", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ events: [], total: 0, offset: 20, limit: 10 }),
      text: async () => "ok",
    });
    vi.stubGlobal("fetch", fetchMock);

    await getStreamEventsPage("run 1", {
      label: "cvevolve_message",
      query: "alpha",
      offset: 20,
      limit: 10,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/runs/run%201/stream_events?label=cvevolve_message&query=alpha&offset=20&limit=10",
      expect.any(Object),
    );

    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
      text: async () => "ok",
    });
    await getStreamEvents("run 1");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/runs/run%201/events?event_kind=stream_event&limit=200",
      expect.any(Object),
    );
  });
});
