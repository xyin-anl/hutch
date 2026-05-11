/**
 * Vitest smoke tests for the run-list page.
 *
 * The page is a Client Component that uses SWR; we mock fetch to avoid
 * hitting a real daemon. Each test gets a fresh SWR cache provider so
 * cached responses don't leak between cases.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";

import HomePage from "@/app/page";

const fetchMock = vi.fn();

function renderWithFreshCache(ui: React.ReactElement) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {ui}
    </SWRConfig>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("HomePage", () => {
  it("renders the run-list heading", () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => [],
      text: async () => "[]",
    });
    renderWithFreshCache(<HomePage />);
    expect(
      screen.getByRole("heading", { level: 1, name: /runs/i }),
    ).toBeInTheDocument();
  });

  it("shows an empty state when no runs are returned", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => [],
      text: async () => "[]",
    });
    renderWithFreshCache(<HomePage />);
    await waitFor(() => {
      expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
    });
  });

  it("lists runs returned by the daemon", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => [
        {
          run_id: "run-abc",
          name: "circle-packing",
          project: "hutch",
          started_at_ns: 1_700_000_000_000_000_000,
          ended_at_ns: 1_700_000_010_000_000_000,
          event_count: 42,
          system_kind: "evolutionary",
        },
      ],
      text: async () => "ok",
    });
    renderWithFreshCache(<HomePage />);
    await waitFor(() => {
      expect(screen.getByText("run-abc")).toBeInTheDocument();
    });
    expect(screen.getByText("circle-packing")).toBeInTheDocument();
    expect(screen.getByText("evolutionary")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("does not infer linear from event-kind aggregates alone", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => [
        {
          run_id: "run-weak",
          project: "hutch",
          event_count: 3,
          kinds_seen: ["run_start", "operator", "fitness"],
        },
      ],
      text: async () => "ok",
    });
    renderWithFreshCache(<HomePage />);
    await waitFor(() => {
      expect(screen.getByText("run-weak")).toBeInTheDocument();
    });
    expect(screen.getByText("unknown")).toBeInTheDocument();
    expect(screen.queryByText("linear")).not.toBeInTheDocument();
  });

  it("shows daemon-unreachable empty state on fetch error", async () => {
    fetchMock.mockRejectedValue(new Error("connection refused"));
    renderWithFreshCache(<HomePage />);
    await waitFor(() => {
      expect(screen.getByText(/daemon unreachable/i)).toBeInTheDocument();
    });
  });
});
