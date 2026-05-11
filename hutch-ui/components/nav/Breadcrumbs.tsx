import Link from "next/link";
import type { ReactNode } from "react";

export interface Crumb {
  label: ReactNode;
  href?: string;
}

/**
 * A simple "hutch / runs / <run-id> / individual" trail. The last entry is
 * rendered as plain text (the current page); earlier entries are clickable
 * back-links.
 */
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav
      aria-label="Breadcrumb"
      className="flex flex-wrap items-center gap-1 text-xs text-neutral-500"
    >
      {items.map((item, idx) => {
        const isLast = idx === items.length - 1;
        return (
          <span key={idx} className="flex items-center gap-1">
            {idx > 0 ? (
              <span aria-hidden className="text-neutral-300 dark:text-neutral-700">
                /
              </span>
            ) : null}
            {item.href && !isLast ? (
              <Link
                href={item.href}
                className="rounded hover:text-neutral-900 hover:underline dark:hover:text-neutral-100"
              >
                {item.label}
              </Link>
            ) : (
              <span
                className={
                  isLast
                    ? "text-neutral-700 dark:text-neutral-300"
                    : "text-neutral-500"
                }
              >
                {item.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
