import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function FilterToolbar({
  ariaLabel = "Filters",
  children,
  className,
}: {
  ariaLabel?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-label={ariaLabel}
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-lg border border-border bg-white p-2.5",
        className,
      )}
    >
      {children}
    </section>
  );
}
