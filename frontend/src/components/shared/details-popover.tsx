import type { ReactNode } from "react";
import { AlertTriangle, Info } from "lucide-react";
import { ActionButton } from "@/components/shared/action-button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

export interface DetailsPopoverItem {
  label: string;
  value: ReactNode;
}

export function DetailsPopover({
  title,
  items,
  warnings = [],
  tooltip = "View details",
  ariaLabel = "View details",
  align = "start",
}: {
  title: string;
  items: readonly DetailsPopoverItem[];
  warnings?: readonly string[];
  tooltip?: string;
  ariaLabel?: string;
  align?: "start" | "center" | "end";
}) {
  const visibleItems = items.filter(
    (item) =>
      item.value !== null && item.value !== undefined && item.value !== "",
  );
  const visibleWarnings = warnings.filter((w) => w.trim().length > 0);

  if (visibleItems.length === 0 && visibleWarnings.length === 0) {
    return null;
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <ActionButton
          type="button"
          size="icon"
          tooltip={tooltip}
          ariaLabel={ariaLabel}
        >
          <Info size={14} aria-hidden="true" />
        </ActionButton>
      </PopoverTrigger>
      <PopoverContent align={align} aria-label={title}>
        <div className="space-y-2">
          <p className="border-b border-border pb-1.5 text-xs font-semibold text-foreground">
            {title}
          </p>
          {visibleItems.length > 0 && (
            <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 text-xs">
              {visibleItems.map((item) => (
                <div key={item.label} className="contents">
                  <dt className="text-muted-foreground">{item.label}</dt>
                  <dd className="text-right font-medium tabular-nums text-foreground">
                    {item.value}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          {visibleWarnings.length > 0 && (
            <div className="space-y-1 rounded-md border border-amber-200 bg-amber-50 p-2 text-[11px] text-amber-900">
              {visibleWarnings.map((warning) => (
                <p key={warning} className="flex items-start gap-1.5">
                  <AlertTriangle
                    size={12}
                    aria-hidden="true"
                    className="mt-0.5 shrink-0 text-amber-700"
                  />
                  <span>{warning}</span>
                </p>
              ))}
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
