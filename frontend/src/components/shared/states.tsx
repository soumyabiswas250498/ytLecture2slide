import { Button } from "@/components/ui/button";

export function LoadingState({ message = "Loading…" }: { message?: string }) {
  return (
    <p role="status" className="text-muted-foreground">
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
    <div role="alert" className="space-y-3">
      <p>{message}</p>
      {onRetry && (
        <Button variant="outline" onClick={onRetry}>
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
    <div className="rounded-xl border border-dashed border-border p-8">
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="mt-2 max-w-xl text-muted-foreground">{description}</p>
    </div>
  );
}
