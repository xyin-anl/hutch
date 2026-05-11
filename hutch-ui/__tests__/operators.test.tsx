import { cleanup, render, screen } from "@testing-library/react";
import type React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OperatorEvent } from "@/lib/types";

vi.mock("recharts", () => {
  const Passthrough = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  const NullComponent = () => null;
  return {
    Bar: Passthrough,
    BarChart: Passthrough,
    CartesianGrid: NullComponent,
    Cell: NullComponent,
    Legend: NullComponent,
    Line: NullComponent,
    LineChart: Passthrough,
    ResponsiveContainer: Passthrough,
    Tooltip: NullComponent,
    XAxis: NullComponent,
    YAxis: NullComponent,
  };
});

import { OperatorsView } from "@/components/views/Operators";

function operator(
  payload: Partial<OperatorEvent["payload"]> = {},
): OperatorEvent {
  return {
    event_id: `op-${payload.id ?? "1"}`,
    event_kind: "operator",
    run_id: "run-1",
    timestamp_ns: 1,
    payload: {
      id: "op-1",
      kind: "propose",
      parent_ids: [],
      child_id: "ind-1",
      ...payload,
    },
  };
}

afterEach(() => cleanup());

describe("OperatorsView truthful usage columns", () => {
  it("hides cost and token columns when usage was not logged", () => {
    render(<OperatorsView operators={[operator()]} />);

    expect(screen.queryByText("Total LLM cost")).not.toBeInTheDocument();
    expect(screen.queryByText("Cost (sum)")).not.toBeInTheDocument();
    expect(screen.queryByText("Tokens (in/out)")).not.toBeInTheDocument();
  });

  it("shows logged zero cost as a real value", () => {
    render(<OperatorsView operators={[operator({ cost_usd: 0 })]} />);

    expect(screen.getByText("Total LLM cost")).toBeInTheDocument();
    expect(screen.getAllByText("$0.0000").length).toBeGreaterThan(0);
    expect(screen.getByText("Cost (sum)")).toBeInTheDocument();
  });
});
