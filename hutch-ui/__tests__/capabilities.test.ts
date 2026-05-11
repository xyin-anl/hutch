import { describe, expect, it } from "vitest";

import { canIssueSteering, canShowSteering, hasCapability } from "@/lib/capabilities";
import type { RunDetail } from "@/lib/types";

const baseDetail: RunDetail = {
  run_id: "run-1",
  event_count: 1,
  kinds_seen: ["run_start"],
  first_timestamp_ns: 1,
  last_timestamp_ns: 1,
  status: "running",
  capabilities: {},
};

describe("capability helpers", () => {
  it("treats absent capabilities as unsupported", () => {
    expect(hasCapability(baseDetail, "steering")).toBe(false);
    expect(canShowSteering(baseDetail, [])).toBe(false);
    expect(canIssueSteering(baseDetail)).toBe(false);
  });

  it("shows steering for logged history even when the run is not writable", () => {
    expect(
      canShowSteering(baseDetail, [
        {
          command_id: "cmd-1",
          run_id: "run-1",
          command: "pause_run",
          target_id: null,
          params: {},
          actor: "human",
          created_at_ns: 1,
          status: "acked",
          delivered_at_ns: null,
          acked_at_ns: 2,
          outcome: "done",
          outcome_note: null,
        },
      ]),
    ).toBe(true);
  });

  it("allows issuing only when steering is declared and the run is running", () => {
    expect(
      canIssueSteering({
        ...baseDetail,
        capabilities: { steering: true },
      }),
    ).toBe(true);
    expect(
      canIssueSteering({
        ...baseDetail,
        status: "finished",
        capabilities: { steering: true },
      }),
    ).toBe(false);
  });
});
