import { cn } from "@/lib/utils";

export function ProgressIndicator({
  value,
  ariaLabel,
  detail,
  className,
}: {
  value: number;
  ariaLabel: string;
  detail?: string;
  className?: string;
}) {
  const clamped = Math.min(100, Math.max(0, value));
  return (
    <div className={cn("space-y-1", className)}>
      <div
        role="progressbar"
        aria-label={ariaLabel}
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full bg-primary transition-all"
          style={{ width: `${clamped}%` }}
        />
      </div>
      {detail && (
        <p className="text-[11px] tabular-nums text-muted-foreground">
          {detail}
        </p>
      )}
    </div>
  );
}
