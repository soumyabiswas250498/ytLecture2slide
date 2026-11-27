import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";

export type ModalSize = "sm" | "md" | "lg" | "xl" | "fullscreen";

const SIZE_CLASSES: Record<ModalSize, string> = {
  sm: "max-h-[90vh] w-full max-w-md",
  md: "max-h-[90vh] w-full max-w-xl",
  lg: "max-h-[90vh] w-full max-w-4xl",
  xl: "max-h-[92vh] w-full max-w-6xl",
  fullscreen: "h-[95vh] max-h-[95vh] w-[95vw] max-w-[95vw]",
};

export function Modal({
  open,
  title,
  description,
  size = "md",
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  description?: string;
  size?: ModalSize;
  onClose: () => void;
  children: ReactNode;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (previousFocus && typeof previousFocus.focus === "function") {
        previousFocus.focus();
      }
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-2 sm:p-4"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={`flex flex-col rounded-2xl border border-border bg-white shadow-xl outline-none ${SIZE_CLASSES[size]}`}
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-5 py-3.5">
          <div className="min-w-0">
            <h2 id={titleId} className="truncate text-base font-semibold">
              {title}
            </h2>
            {description && (
              <p
                id={descriptionId}
                className="mt-0.5 text-xs text-muted-foreground"
              >
                {description}
              </p>
            )}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={18} aria-hidden="true" />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {children}
        </div>
      </div>
    </div>
  );
}
