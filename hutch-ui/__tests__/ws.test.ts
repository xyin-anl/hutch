import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { subscribeRunStream } from "@/lib/ws";

const OLD_ENV = process.env;

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  onclose: (() => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;

  constructor(public readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  close = vi.fn();
}

beforeEach(() => {
  process.env = { ...OLD_ENV };
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  process.env = OLD_ENV;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("run stream websocket", () => {
  it("adds the public token to the websocket URL", () => {
    process.env.NEXT_PUBLIC_HUTCH_DAEMON_URL = "http://daemon.test";
    process.env.NEXT_PUBLIC_HUTCH_TOKEN = "secret";

    const sub = subscribeRunStream("run 1", vi.fn());

    expect(FakeWebSocket.instances[0]?.url).toBe(
      "ws://daemon.test/runs/run%201/stream?token=secret",
    );
    sub.close();
  });

  it("dispatches parsed events", () => {
    process.env.NEXT_PUBLIC_HUTCH_DAEMON_URL = "http://daemon.test";
    const onEvent = vi.fn();
    const sub = subscribeRunStream("run-1", onEvent);

    FakeWebSocket.instances[0]?.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({
          event_id: "e1",
          event_kind: "run_start",
          run_id: "run-1",
          timestamp_ns: 1,
          payload: {},
        }),
      }),
    );

    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ event_id: "e1" }));
    sub.close();
  });

  it("reconnects after close with backoff", () => {
    vi.useFakeTimers();
    process.env.NEXT_PUBLIC_HUTCH_DAEMON_URL = "http://daemon.test";
    const sub = subscribeRunStream("run-1", vi.fn());

    FakeWebSocket.instances[0]?.onclose?.();
    vi.advanceTimersByTime(500);

    expect(FakeWebSocket.instances).toHaveLength(2);
    sub.close();
  });
});
