import { cn } from "@/lib/utils";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "error";

const toneClasses: Record<StatusTone, string> = {
  neutral: "bg-stone-100 text-stone-700",
  info: "bg-blue-100 text-blue-800",
  success: "bg-emerald-100 text-emerald-800",
  warning: "bg-amber-100 text-amber-800",
  error: "bg-red-100 text-red-800",
};

export function StatusBadge({
  label,
  tone = "neutral",
  title,
  className,
}: {
  label: string;
  tone?: StatusTone;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium capitalize",
        toneClasses[tone],
        className,
      )}
    >
      {label}
    </span>
  );
}
