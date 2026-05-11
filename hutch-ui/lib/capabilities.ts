import type { RunDetail } from "@/lib/types";
import type { SteeringRecord } from "@/lib/api";

export function hasCapability(
  detail: Pick<RunDetail, "capabilities"> | undefined,
  key: string,
): boolean {
  return detail?.capabilities?.[key] === true;
}

export function canShowSteering(
  detail: Pick<RunDetail, "capabilities"> | undefined,
  records: SteeringRecord[],
): boolean {
  return hasCapability(detail, "steering") || records.length > 0;
}

export function canIssueSteering(
  detail: Pick<RunDetail, "capabilities" | "status"> | undefined,
): boolean {
  return hasCapability(detail, "steering") && detail?.status === "running";
}
