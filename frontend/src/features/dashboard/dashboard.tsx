import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, CircleCheck } from "lucide-react";
import { getHealth } from "@/services/api";
import { PageContainer } from "@/components/shared/page-container";
import { PageHeader } from "@/components/shared/page-header";
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
    <PageContainer>
      <PageHeader
        eyebrow="YOUR WORKSPACE"
        title="Dashboard"
        description="A home for your lectures. Local video discovery, frame extraction, and smartboard processing."
      />
      <section
        className="rounded-xl bg-primary p-5 text-primary-foreground sm:p-6"
        aria-labelledby="intro-title"
      >
        <span className="rounded-full border border-white/30 px-2.5 py-0.5 text-xs">
          Local-first workspace
        </span>
        <h2
          id="intro-title"
          className="mt-3 max-w-xl text-xl font-semibold leading-snug sm:text-2xl"
        >
          From long lectures to lasting knowledge.
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-5 text-white/80">
          Turn educational videos into clean slide collections, with all video
          and image processing running locally on your server.
        </p>
        <div className="mt-4 flex items-center gap-1.5 text-xs text-white/80">
          <ArrowUpRight size={14} aria-hidden="true" />
          Manage channels and process lecture videos from the sidebar.
        </div>
      </section>
      <section
        className="rounded-lg border border-border bg-white p-4"
        aria-labelledby="connection-title"
      >
        <div className="mb-3 flex items-center gap-2">
          <CircleCheck size={16} aria-hidden="true" />
          <h2 id="connection-title" className="text-sm font-semibold">
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
          <div className="flex flex-wrap items-center justify-between gap-3">
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
        description="Channel management and video processing are available in Channels and Videos."
      />
    </PageContainer>
  );
}
