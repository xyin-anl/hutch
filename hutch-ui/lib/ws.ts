/**
 * WebSocket helper for the live event stream.
 *
 * Subscribes to `WS /runs/{id}/stream` on the daemon and dispatches every
 * incoming event (a JSON-encoded canonical event) to the supplied callback.
 * Reconnects with exponential backoff if the connection drops.
 */

import type { HutchEvent } from "@/lib/types";
import { daemonToken, daemonUrl } from "@/lib/api";

export interface RunStreamSubscription {
  close: () => void;
}

function toWebSocketUrl(httpUrl: string, path: string): string {
  // Same-origin (empty) base means the UI was served by the daemon — derive
  // the WS URL from the current page so the port matches even when the
  // daemon binds something other than the default.
  const base =
    httpUrl.length > 0
      ? httpUrl
      : typeof window !== "undefined"
        ? `${window.location.protocol}//${window.location.host}`
        : "http://127.0.0.1:7777";
  const url = new URL(path, base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function subscribeRunStream(
  runId: string,
  onEvent: (event: HutchEvent) => void,
  onError?: (error: Error) => void,
  onOpen?: () => void,
  onClose?: () => void,
): RunStreamSubscription {
  let socket: WebSocket | null = null;
  let backoff = 500;
  const maxBackoff = 10_000;
  let closed = false;

  const connect = () => {
    if (closed) return;
    const url = toWebSocketUrl(daemonUrl(), `/runs/${encodeURIComponent(runId)}/stream`);
    const token = daemonToken();
    const wsUrl = new URL(url);
    if (token) wsUrl.searchParams.set("token", token);
    try {
      socket = new WebSocket(wsUrl.toString());
    } catch (err) {
      onError?.(err as Error);
      scheduleReconnect();
      return;
    }

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as HutchEvent;
        onEvent(data);
      } catch (err) {
        onError?.(err as Error);
      }
    };

    socket.onopen = () => {
      backoff = 500;
      onOpen?.();
    };

    socket.onclose = () => {
      socket = null;
      onClose?.();
      scheduleReconnect();
    };

    socket.onerror = (event) => {
      onError?.(new Error(`WebSocket error on run ${runId}: ${String(event)}`));
    };
  };

  const scheduleReconnect = () => {
    if (closed) return;
    const delay = backoff;
    backoff = Math.min(backoff * 2, maxBackoff);
    window.setTimeout(connect, delay);
  };

  connect();

  return {
    close: () => {
      closed = true;
      socket?.close();
    },
  };
}
