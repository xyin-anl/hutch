export interface ObservedSum {
  observed: boolean;
  count: number;
  total: number;
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function sumObservedNumbers<T>(
  items: T[],
  pick: (item: T) => unknown,
): ObservedSum {
  let count = 0;
  let total = 0;
  for (const item of items) {
    const value = pick(item);
    if (!isFiniteNumber(value)) continue;
    count += 1;
    total += value;
  }
  return { observed: count > 0, count, total };
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(4)}`;
}
