import type { ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";

export function BulkActionToolbar({
  selectedCount,
  onClearSelection,
  children,
}: {
  selectedCount: number;
  onClearSelection: () => void;
  children: ReactNode;
}) {
  return (
    <section
      aria-label="Bulk actions"
      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-white px-3 py-2"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex h-7 items-center rounded-md bg-muted px-2.5 text-xs font-semibold text-foreground tabular-nums">
          {selectedCount} selected
        </span>
        {children}
      </div>
      {selectedCount > 0 && (
        <Button
          type="button"
          variant="ghost"
          size="xs"
          onClick={onClearSelection}
        >
          <X size={13} aria-hidden="true" />
          Clear selection
        </Button>
      )}
    </section>
  );
}
