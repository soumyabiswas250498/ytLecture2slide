import { Button } from "@/components/ui/button";

export function LoadingState({ message = "Loading…" }: { message?: string }) {
  return (
    <p role="status" className="py-2 text-sm text-muted-foreground">
      {message}
    </p>
  );
}
export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"
    >
      <p>{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
export function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-white p-6">
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="mt-1 max-w-xl text-sm text-muted-foreground">
        {description}
      </p>
    </div>
  );
}
