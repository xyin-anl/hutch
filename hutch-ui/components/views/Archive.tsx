"use client";

import { interpolateViridis } from "d3";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { bestFitnessByIndividual } from "@/lib/fitness";
import type { DescriptorEvent, FitnessEvent, ScoreDirection } from "@/lib/types";

const CELL_PX = 32;

interface Cell {
  cellId: string;
  coords: number[];
  individualId: string;
  fitness: number | null;
}

interface Archive {
  id: string;
  cells: Cell[];
}

function buildArchives(
  descriptors: DescriptorEvent[],
  fitness: FitnessEvent[],
  scoreDirections: Record<string, ScoreDirection> | undefined,
): Archive[] {
  const fitMap = bestFitnessByIndividual(fitness, scoreDirections);
  const byArchive = new Map<string, Cell[]>();
  for (const d of descriptors) {
    const cells = byArchive.get(d.payload.archive_id) ?? [];
    cells.push({
      cellId: d.payload.cell_id ?? `(${d.payload.coordinates.join(", ")})`,
      coords: d.payload.coordinates,
      individualId: d.payload.individual_id,
      fitness: fitMap.get(d.payload.individual_id) ?? null,
    });
    byArchive.set(d.payload.archive_id, cells);
  }
  return Array.from(byArchive.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([id, cells]) => ({ id, cells }));
}

export function ArchiveView({
  descriptors,
  fitness,
  scoreDirections,
}: {
  descriptors: DescriptorEvent[];
  fitness: FitnessEvent[];
  scoreDirections?: Record<string, ScoreDirection>;
}) {
  const archives = useMemo(
    () => buildArchives(descriptors, fitness, scoreDirections),
    [descriptors, fitness, scoreDirections],
  );
  const [selected, setSelected] = useState<string | null>(
    archives[0]?.id ?? null,
  );

  if (descriptors.length === 0) {
    return (
      <EmptyState
        title="No descriptors logged"
        detail="The Archive view activates once a run logs DescriptorEvents (e.g. MAP-Elites coordinates)."
      />
    );
  }

  const archive = archives.find((a) => a.id === selected) ?? archives[0];
  if (!archive) return null;

  const fitnessVals = archive.cells
    .map((c) => c.fitness)
    .filter((v): v is number => v !== null);
  const minF = fitnessVals.length > 0 ? Math.min(...fitnessVals) : 0;
  const maxF = fitnessVals.length > 0 ? Math.max(...fitnessVals) : 1;
  const colorOf = (v: number | null): string => {
    if (v === null || maxF === minF) return "#a1a1aa";
    return interpolateViridis((v - minF) / (maxF - minF));
  };

  // Bin coords into a coarse grid for display.
  const dim = archive.cells[0]?.coords.length ?? 0;
  const usable = dim >= 2 ? archive.cells : [];

  const xs = usable.map((c) => c.coords[0]!).filter(Number.isFinite);
  const ys = usable.map((c) => c.coords[1]!).filter(Number.isFinite);
  const xMin = xs.length ? Math.min(...xs) : 0;
  const xMax = xs.length ? Math.max(...xs) : 1;
  const yMin = ys.length ? Math.min(...ys) : 0;
  const yMax = ys.length ? Math.max(...ys) : 1;
  const RES = 16; // 16x16 cells
  const xBin = (x: number) =>
    Math.min(RES - 1, Math.max(0, Math.floor(((x - xMin) / (xMax - xMin || 1)) * RES)));
  const yBin = (y: number) =>
    Math.min(RES - 1, Math.max(0, Math.floor(((y - yMin) / (yMax - yMin || 1)) * RES)));

  const grid = new Map<string, Cell>();
  for (const c of usable) {
    const key = `${xBin(c.coords[0]!)}:${yBin(c.coords[1]!)}`;
    const prev = grid.get(key);
    if (!prev || (c.fitness ?? -Infinity) > (prev.fitness ?? -Infinity)) {
      grid.set(key, c);
    }
  }

  const coverage = grid.size / (RES * RES);
  const qdScore = Array.from(grid.values())
    .map((cell) => cell.fitness)
    .filter((value): value is number => value !== null)
    .reduce((a, b) => a + b, 0);

  const width = RES * CELL_PX;
  const height = RES * CELL_PX;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {archives.length > 1 ? (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-neutral-500">archive</span>
            <select
              value={archive.id}
              onChange={(e) => setSelected(e.target.value)}
              className="rounded border border-neutral-200 bg-white px-2 py-1 text-neutral-800 dark:border-neutral-800 dark:bg-neutral-950 dark:text-neutral-200"
            >
              {archives.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.id}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="text-xs text-neutral-500">archive: {archive.id}</div>
        )}
        <div className="flex items-center gap-3 text-xs text-neutral-600 dark:text-neutral-400">
          <span>
            <span className="text-neutral-500">coverage</span>{" "}
            <span className="font-mono">{(coverage * 100).toFixed(1)}%</span>
          </span>
          <span>
            <span className="text-neutral-500">qd-score</span>{" "}
            <span className="font-mono">{qdScore.toFixed(3)}</span>
          </span>
          <span>
            <span className="text-neutral-500">filled</span>{" "}
            <span className="font-mono">
              {grid.size}/{RES * RES}
            </span>
          </span>
        </div>
      </div>

      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-950">
        {dim < 2 ? (
          <EmptyState
            title="Descriptors are <2-dimensional"
            detail="The grid heatmap activates for runs with 2D+ coordinates. CVT and AURORA renderers are scheduled post-v0.1.0."
          />
        ) : (
          <svg
            viewBox={`0 0 ${width + 24} ${height + 24}`}
            className="h-[440px] w-full select-none"
          >
            {/* background grid */}
            <g>
              {Array.from({ length: RES }, (_, i) =>
                Array.from({ length: RES }, (_, j) => (
                  <rect
                    key={`bg-${i}-${j}`}
                    x={i * CELL_PX + 12}
                    y={(RES - 1 - j) * CELL_PX + 12}
                    width={CELL_PX - 1}
                    height={CELL_PX - 1}
                    className="fill-neutral-100 stroke-neutral-200 dark:fill-neutral-900 dark:stroke-neutral-800"
                  />
                )),
              )}
            </g>
            {/* filled cells */}
            <g>
              {Array.from(grid.entries()).map(([key, cell]) => {
                const [i, j] = key.split(":").map(Number) as [number, number];
                return (
                  <rect
                    key={key}
                    x={i * CELL_PX + 12}
                    y={(RES - 1 - j) * CELL_PX + 12}
                    width={CELL_PX - 1}
                    height={CELL_PX - 1}
                    fill={colorOf(cell.fitness)}
                    className="stroke-white dark:stroke-neutral-950"
                  >
                    <title>{`${cell.individualId}\ncell ${cell.cellId}\nfitness ${
                      cell.fitness?.toFixed(3) ?? "—"
                    }`}</title>
                  </rect>
                );
              })}
            </g>
          </svg>
        )}
      </div>

      <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-xs text-neutral-500 dark:border-neutral-800 dark:bg-neutral-950">
        {RES}×{RES} grid, color-coded by best composite fitness reached in each
        cell (purple → yellow). Hover a cell for the individual id and exact
        fitness. Coverage is the fraction of cells that any individual has
        reached; QD-score is the sum of best fitness across filled cells.
      </div>
    </div>
  );
}
