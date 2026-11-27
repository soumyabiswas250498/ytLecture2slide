import type { ComponentProps } from "react";
import { Button } from "@/components/ui/button";

export function ActionButton({
  tooltip,
  ariaLabel,
  size = "xs",
  variant = "outline",
  ...props
}: ComponentProps<typeof Button> & {
  tooltip?: string;
  ariaLabel?: string;
}) {
  return (
    <Button
      size={size}
      variant={variant}
      title={tooltip}
      aria-label={ariaLabel ?? tooltip}
      {...props}
    />
  );
}
