import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function DataTable({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "overflow-x-auto rounded-lg border border-border bg-white",
        className,
      )}
    >
      <table className="w-full border-collapse text-left text-sm">
        {children}
      </table>
    </div>
  );
}
