import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type NotificationTone = "info" | "success" | "warning" | "error";

const toneClasses: Record<NotificationTone, string> = {
  info: "border-blue-200 bg-blue-50 text-blue-900",
  success: "border-emerald-200 bg-emerald-50 text-emerald-900",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  error: "border-red-200 bg-red-50 text-red-800",
};

export function NotificationAlert({
  tone = "info",
  summary,
  details,
  onDismiss,
  defaultExpanded = false,
}: {
  tone?: NotificationTone;
  summary: ReactNode;
  details?: ReactNode;
  onDismiss?: () => void;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      aria-live="polite"
      className={cn(
        "rounded-lg border px-3.5 py-2.5 text-sm",
        toneClasses[tone],
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-medium leading-snug">{summary}</div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {details && (
            <button
              type="button"
              onClick={() => setExpanded((prev) => !prev)}
              aria-expanded={expanded}
              className="inline-flex items-center gap-1 text-xs font-medium underline underline-offset-2 hover:opacity-80"
            >
              {expanded ? (
                <>
                  Hide details
                  <ChevronUp size={13} aria-hidden="true" />
                </>
              ) : (
                <>
                  Details
                  <ChevronDown size={13} aria-hidden="true" />
                </>
              )}
            </button>
          )}
          {onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              aria-label="Dismiss notification"
              title="Dismiss"
              className="rounded p-0.5 hover:bg-black/5"
            >
              <X size={14} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
      {details && expanded && (
        <div className="mt-2 border-t border-current/15 pt-2 text-xs leading-relaxed">
          {details}
        </div>
      )}
    </div>
  );
}
