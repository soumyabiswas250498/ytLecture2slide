import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SelectOption<T extends string = string> {
  value: T;
  label: string;
  disabled?: boolean;
}

export interface SelectProps<T extends string = string> {
  id?: string;
  value: T;
  options: readonly SelectOption<T>[];
  onValueChange: (value: T) => void;
  placeholder?: string;
  disabled?: boolean;
  ariaLabel?: string;
  ariaLabelledBy?: string;
  className?: string;
}

export function Select<T extends string = string>({
  id,
  value,
  options,
  onValueChange,
  placeholder = "Select…",
  disabled = false,
  ariaLabel,
  ariaLabelledBy,
  className,
}: SelectProps<T>) {
  const [open, setOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState<number>(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listboxId = useId();

  const selectedOption = options.find((opt) => opt.value === value);

  useEffect(() => {
    if (!open) return;
    const handleOutsideClick = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, [open]);

  const findNextEnabledIndex = (start: number, step: 1 | -1): number => {
    if (options.length === 0) return -1;
    let idx = start;
    for (let i = 0; i < options.length; i += 1) {
      idx = (idx + step + options.length) % options.length;
      if (!options[idx]?.disabled) return idx;
    }
    return -1;
  };

  const openMenu = () => {
    if (disabled) return;
    const selectedIdx = options.findIndex(
      (opt) => opt.value === value && !opt.disabled,
    );
    const firstEnabled = options.findIndex((opt) => !opt.disabled);
    setHighlightedIndex(selectedIdx >= 0 ? selectedIdx : firstEnabled);
    setOpen(true);
  };

  const selectIndex = (index: number) => {
    const opt = options[index];
    if (!opt || opt.disabled) return;
    onValueChange(opt.value);
    setOpen(false);
    triggerRef.current?.focus();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    if (!open) {
      if (
        event.key === "ArrowDown" ||
        event.key === "ArrowUp" ||
        event.key === "Enter" ||
        event.key === " "
      ) {
        event.preventDefault();
        openMenu();
      }
      return;
    }

    switch (event.key) {
      case "Escape":
        event.preventDefault();
        setOpen(false);
        break;
      case "Tab":
        setOpen(false);
        break;
      case "ArrowDown": {
        event.preventDefault();
        const next = findNextEnabledIndex(
          highlightedIndex < 0 ? -1 : highlightedIndex,
          1,
        );
        if (next >= 0) setHighlightedIndex(next);
        break;
      }
      case "ArrowUp": {
        event.preventDefault();
        const prev = findNextEnabledIndex(
          highlightedIndex < 0 ? 0 : highlightedIndex,
          -1,
        );
        if (prev >= 0) setHighlightedIndex(prev);
        break;
      }
      case "Home": {
        event.preventDefault();
        const first = options.findIndex((opt) => !opt.disabled);
        if (first >= 0) setHighlightedIndex(first);
        break;
      }
      case "End": {
        event.preventDefault();
        for (let i = options.length - 1; i >= 0; i -= 1) {
          if (!options[i]?.disabled) {
            setHighlightedIndex(i);
            break;
          }
        }
        break;
      }
      case "Enter":
      case " ":
        event.preventDefault();
        if (highlightedIndex >= 0) selectIndex(highlightedIndex);
        break;
    }
  };

  return (
    <div ref={containerRef} className={cn("relative inline-block", className)}>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls={listboxId}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-activedescendant={
          open && highlightedIndex >= 0
            ? `${listboxId}-opt-${highlightedIndex}`
            : undefined
        }
        disabled={disabled}
        onClick={() => {
          if (open) setOpen(false);
          else openMenu();
        }}
        onKeyDown={handleKeyDown}
        className={cn(
          "flex h-9 w-full min-w-[130px] items-center justify-between gap-2 rounded-md border border-border bg-white px-2.5 text-left text-sm text-foreground transition-colors",
          "hover:bg-muted/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
          "disabled:cursor-not-allowed disabled:opacity-50",
        )}
      >
        <span
          className={cn("truncate", !selectedOption && "text-muted-foreground")}
        >
          {selectedOption ? selectedOption.label : placeholder}
        </span>
        <ChevronDown
          size={14}
          aria-hidden="true"
          className={cn(
            "shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={ariaLabel}
          aria-labelledby={ariaLabelledBy}
          className="absolute left-0 z-50 mt-1 max-h-60 min-w-full w-max max-w-xs overflow-y-auto rounded-md border border-border bg-white p-1 shadow-lg"
        >
          {options.map((opt, idx) => {
            const isSelected = opt.value === value;
            const isHighlighted = idx === highlightedIndex;
            return (
              <li
                key={opt.value}
                id={`${listboxId}-opt-${idx}`}
                role="option"
                aria-selected={isSelected}
                aria-disabled={opt.disabled || undefined}
                onMouseEnter={() => {
                  if (!opt.disabled) setHighlightedIndex(idx);
                }}
                onClick={() => selectIndex(idx)}
                className={cn(
                  "flex cursor-pointer items-center justify-between gap-2 rounded px-2.5 py-1.5 text-sm",
                  isHighlighted && "bg-muted",
                  isSelected && "font-medium text-primary",
                  opt.disabled && "cursor-not-allowed opacity-50",
                )}
              >
                <span className="break-words">{opt.label}</span>
                {isSelected && (
                  <Check size={14} aria-hidden="true" className="shrink-0" />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
