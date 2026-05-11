"use client";

export function LiveDot({ live }: { live: boolean }) {
  return (
    <div className="flex items-center gap-2 text-xs text-neutral-500">
      <span
        aria-hidden
        className={`inline-block h-2 w-2 rounded-full ${
          live ? "animate-pulse bg-emerald-400" : "bg-neutral-600"
        }`}
      />
      <span>{live ? "live" : "offline"}</span>
    </div>
  );
}
