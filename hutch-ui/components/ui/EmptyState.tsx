import type { ReactNode } from "react";

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="grid place-items-center rounded-lg border border-neutral-200 bg-neutral-50 px-8 py-16 text-center dark:border-neutral-800 dark:bg-neutral-950">
      <div className="max-w-md space-y-2">
        <h3 className="text-base font-medium text-neutral-800 dark:text-neutral-200">
          {title}
        </h3>
        {detail ? <p className="text-sm text-neutral-500">{detail}</p> : null}
        {action ? <div className="pt-2">{action}</div> : null}
      </div>
    </div>
  );
}
