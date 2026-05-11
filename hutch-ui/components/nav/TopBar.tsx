import Link from "next/link";
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/nav/ThemeToggle";

export function TopBar({ children }: { children?: ReactNode }) {
  return (
    <header className="border-b border-neutral-200 bg-white/80 backdrop-blur dark:border-neutral-900 dark:bg-black/40">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-6 py-3">
        <Link
          href="/"
          className="font-semibold tracking-tight text-neutral-900 hover:text-black dark:text-neutral-100 dark:hover:text-white"
        >
          The Hutch
        </Link>
        <div className="ml-auto flex items-center gap-3">
          {children}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
