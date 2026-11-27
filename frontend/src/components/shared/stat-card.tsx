import { cn } from "@/lib/utils";

export type StatTone = "default" | "success" | "muted" | "warning";

const toneClasses: Record<StatTone, string> = {
  default: "text-foreground",
  success: "text-emerald-700",
  muted: "text-muted-foreground",
  warning: "text-amber-700",
};

export function StatCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string | number;
  tone?: StatTone;
}) {
  return (
    <div className="rounded-lg border border-border bg-white px-3.5 py-2.5">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          "mt-0.5 text-lg font-semibold leading-tight tabular-nums",
          toneClasses[tone],
        )}
      >
        {value}
      </p>
    </div>
  );
}
