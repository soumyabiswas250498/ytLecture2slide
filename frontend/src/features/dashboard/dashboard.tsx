import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, CircleCheck } from "lucide-react";
import { getHealth } from "@/services/api";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/shared/states";
import { Button } from "@/components/ui/button";

export function Dashboard() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => getHealth(signal),
  });
  return (
    <div className="space-y-8">
      <div>
        <p className="eyebrow">YOUR WORKSPACE</p>
        <h1>Dashboard</h1>
        <p className="mt-3 text-muted-foreground">
          A home for your lectures. A foundation for what comes next.
        </p>
      </div>
      <section
        className="rounded-2xl bg-primary p-7 text-primary-foreground sm:p-10"
        aria-labelledby="intro-title"
      >
        <span className="rounded-full border border-white/30 px-3 py-1 text-xs">
          Phase 1 · Project foundation
        </span>
        <h2
          id="intro-title"
          className="mt-6 max-w-lg text-3xl font-semibold leading-tight"
        >
          From long lectures to
          <br className="hidden sm:block" /> lasting knowledge.
        </h2>
        <p className="mt-4 max-w-lg text-sm leading-6 text-white/75">
          This workspace is being built to turn educational videos into useful
          slide PDFs, with all video and image processing running locally.
        </p>
        <div className="mt-7 flex items-center gap-2 text-xs text-white/75">
          <ArrowUpRight size={16} aria-hidden="true" /> Processing features
          arrive in later phases.
        </div>
      </section>
      <section
        className="rounded-xl border border-border bg-white p-6"
        aria-labelledby="connection-title"
      >
        <div className="mb-4 flex items-center gap-2">
          <CircleCheck size={18} aria-hidden="true" />
          <h2 id="connection-title" className="font-semibold">
            Backend connection
          </h2>
        </div>
        {health.isPending ? (
          <LoadingState message="Checking backend connection…" />
        ) : health.isError ? (
          <ErrorState
            message={health.error.message}
            onRetry={() => {
              void health.refetch();
            }}
          />
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <p role="status" className="text-sm">
              <span className="mr-2 inline-block h-2 w-2 rounded-full bg-emerald-600" />
              Backend is healthy
            </p>
            <Button
              variant="outline"
              size="sm"
              disabled={health.isFetching}
              onClick={() => {
                void health.refetch();
              }}
            >
              {health.isFetching ? "Checking…" : "Check again"}
            </Button>
          </div>
        )}
      </section>
      <EmptyState
        title="Your lecture library starts here"
        description="Channel management is available in Channels. Video discovery, processing jobs and PDF management arrive in later phases."
      />
    </div>
  );
}
