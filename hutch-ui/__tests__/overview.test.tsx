import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { OverviewView } from "@/components/views/Overview";
import type { OperatorEvent, RunDetail } from "@/lib/types";

const detail: RunDetail = {
  run_id: "run-1",
  event_count: 1,
  kinds_seen: ["run_start"],
  first_timestamp_ns: 1_700_000_000_000_000_000,
  last_timestamp_ns: 1_700_000_000_000_000_000,
  status: "finished",
  capabilities: {},
};

function operator(cost_usd?: number | null): OperatorEvent {
  return {
    event_id: `op-${cost_usd ?? "missing"}`,
    event_kind: "operator",
    run_id: "run-1",
    timestamp_ns: 1,
    payload: {
      id: "op-1",
      kind: "propose",
      parent_ids: [],
      child_id: "ind-1",
      ...(cost_usd === undefined ? {} : { cost_usd }),
    },
  };
}

afterEach(() => cleanup());

describe("OverviewView truthful stats", () => {
  it("does not show LLM cost when no operator cost was logged", () => {
    render(
      <OverviewView
        detail={detail}
        individuals={[]}
        operators={[operator()]}
        fitness={[]}
      />,
    );

    expect(screen.queryByText("LLM cost")).not.toBeInTheDocument();
  });

  it("shows a logged zero LLM cost as true zero", () => {
    render(
      <OverviewView
        detail={detail}
        individuals={[]}
        operators={[operator(0)]}
        fitness={[]}
      />,
    );

    expect(screen.getByText("LLM cost")).toBeInTheDocument();
    expect(screen.getByText("$0.0000")).toBeInTheDocument();
  });

  it("uses unknown rather than defaulting empty runs to linear", () => {
    render(<OverviewView detail={detail} individuals={[]} operators={[]} fitness={[]} />);

    expect(screen.getByText("unknown")).toBeInTheDocument();
    expect(screen.queryByText("linear")).not.toBeInTheDocument();
  });

  it("prefers server-provided system kind when present", () => {
    render(
      <OverviewView
        detail={{ ...detail, system_kind: "evolutionary" }}
        individuals={[]}
        operators={[operator()]}
        fitness={[]}
      />,
    );

    expect(screen.getByText("evolutionary")).toBeInTheDocument();
  });
});
