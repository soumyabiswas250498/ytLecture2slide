import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Clock,
  FileText,
  Play,
  RotateCcw,
  ScrollText,
  XCircle,
} from "lucide-react";
import { ActionButton } from "@/components/shared/action-button";
import { DataTable } from "@/components/shared/data-table";
import { DetailsPopover } from "@/components/shared/details-popover";
import { NotificationAlert } from "@/components/shared/notification-alert";
import { PageContainer } from "@/components/shared/page-container";
import { PageHeader } from "@/components/shared/page-header";
import { ProgressIndicator } from "@/components/shared/progress-indicator";
import { StatCard } from "@/components/shared/stat-card";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/shared/states";
import { StatusBadge, type StatusTone } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { formatISTDateTime } from "@/lib/utils";
import { ApiError } from "@/services/api";
import {
  cancelPipelineRun,
  getActivePipelineRun,
  getSchedulerStatus,
  listPipelineRuns,
  retryFailedPipelineRun,
  triggerPipelineRun,
  type PipelineRun,
} from "@/services/pipeline";

const RUN_STATUS_TONE: Record<PipelineRun["status"], StatusTone> = {
  queued: "info",
  running: "info",
  completed: "success",
  completed_with_errors: "warning",
  failed: "error",
  cancelled: "warning",
};

const STAGE_LABEL: Record<PipelineRun["current_stage"], string> = {
  idle: "Idle",
  discovering: "Discovering videos",
  evaluating: "Evaluating eligibility",
  downloading: "Downloading video",
  extracting: "Extracting screenshots",
  processing_slides: "Processing slides",
  generating_pdf: "Generating PDF",
  validating_pdf: "Validating PDF",
  cleaning: "Cleaning intermediates",
  completed: "Completed",
};

function formatElapsed(
  startedAt: string | null | undefined,
  completedAt: string | null | undefined,
): string {
  if (!startedAt) return "—";
  const startMs = Date.parse(startedAt);
  const endMs = completedAt ? Date.parse(completedAt) : Date.now();
  if (Number.isNaN(startMs) || Number.isNaN(endMs)) return "—";
  const secs = Math.max(0, Math.round((endMs - startMs) / 1000));
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatDurationSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return "—";
  }
  const secs = Math.max(0, Math.round(seconds));
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "An unexpected error occurred.";
}

export function ProcessingJobsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [logModalRun, setLogModalRun] = useState<PipelineRun | null>(null);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const schedulerQuery = useQuery({
    queryKey: ["pipeline", "scheduler"],
    queryFn: ({ signal }) => getSchedulerStatus(signal),
    refetchInterval: 15000,
  });

  const activeQuery = useQuery({
    queryKey: ["pipeline", "active"],
    queryFn: ({ signal }) => getActivePipelineRun(signal),
    refetchInterval: (q) => (q.state.data ? 1500 : 10000),
  });

  const runsQuery = useQuery({
    queryKey: ["pipeline", "runs", page],
    queryFn: ({ signal }) => listPipelineRuns(page, 15, signal),
    refetchInterval: activeQuery.data ? 2000 : false,
  });

  const invalidateAll = async () => {
    await queryClient.invalidateQueries({ queryKey: ["pipeline"] });
    await queryClient.invalidateQueries({ queryKey: ["videos"] });
    await queryClient.invalidateQueries({ queryKey: ["pdf-library"] });
  };

  const runNowMutation = useMutation({
    mutationFn: () => triggerPipelineRun({}),
    onSuccess: async (run) => {
      setFeedback({
        type: "success",
        message: `Started pipeline run #${run.id}.`,
      });
      await invalidateAll();
    },
    onError: (err) => {
      setFeedback({ type: "error", message: getErrorMessage(err) });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (runId: number) => cancelPipelineRun(runId),
    onSuccess: async (run) => {
      setFeedback({
        type: "success",
        message: `Cancellation requested for run #${run.id}.`,
      });
      await invalidateAll();
    },
    onError: (err) => {
      setFeedback({ type: "error", message: getErrorMessage(err) });
    },
  });

  const retryFailedMutation = useMutation({
    mutationFn: (runId: number) => retryFailedPipelineRun(runId),
    onSuccess: async (run) => {
      setFeedback({
        type: "success",
        message: `Started retry run #${run.id} for failed videos.`,
      });
      await invalidateAll();
    },
    onError: (err) => {
      setFeedback({ type: "error", message: getErrorMessage(err) });
    },
  });

  const activeRun = activeQuery.data ?? null;
  const scheduler = schedulerQuery.data;
  const latestRun = runsQuery.data?.items[0] ?? null;
  const displayedRun = activeRun ?? latestRun;

  return (
    <PageContainer>
      <PageHeader
        eyebrow="AUTOMATION"
        title="Processing Jobs"
        description="Automated daily pipeline status, manual trigger, and execution history."
        actions={
          <div className="flex items-center gap-2">
            {activeRun && (
              <ActionButton
                variant="outline"
                size="sm"
                tooltip="Cancel active pipeline run"
                ariaLabel="Cancel Run"
                disabled={cancelMutation.isPending}
                onClick={() => cancelMutation.mutate(activeRun.id)}
              >
                <XCircle size={14} aria-hidden="true" />
                Cancel Run
              </ActionButton>
            )}
            <ActionButton
              variant="default"
              size="sm"
              tooltip={
                activeRun
                  ? "A pipeline run is already in progress"
                  : "Start automated pipeline run now"
              }
              ariaLabel="Run Now"
              disabled={Boolean(activeRun) || runNowMutation.isPending}
              onClick={() => runNowMutation.mutate()}
            >
              <Play size={14} aria-hidden="true" />
              Run Now
            </ActionButton>
          </div>
        }
      />

      {feedback && (
        <NotificationAlert
          tone={feedback.type}
          summary={feedback.message}
          onDismiss={() => setFeedback(null)}
        />
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Pipeline status"
          value={
            activeRun
              ? STAGE_LABEL[activeRun.current_stage]
              : displayedRun
                ? displayedRun.status.replace(/_/g, " ")
                : "Idle"
          }
          tone={activeRun ? "warning" : "default"}
        />
        <StatCard
          label="Next scheduled run"
          value={scheduler?.enabled ? `${scheduler.time} IST` : "Disabled"}
        />
        <StatCard
          label="Completed / Total"
          value={
            displayedRun
              ? `${displayedRun.completed_videos} / ${displayedRun.total_videos}`
              : "0 / 0"
          }
          tone="success"
        />
        <StatCard
          label="Failed / Skipped"
          value={
            displayedRun
              ? `${displayedRun.failed_videos} / ${displayedRun.skipped_videos}`
              : "0 / 0"
          }
          tone={
            displayedRun && displayedRun.failed_videos > 0
              ? "warning"
              : "default"
          }
        />
      </div>

      {activeRun && (
        <section
          aria-label="Active pipeline progress"
          className="rounded-lg border border-border bg-white p-3.5"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-xs font-semibold text-foreground">
                Run #{activeRun.id} · {STAGE_LABEL[activeRun.current_stage]}
              </p>
              {activeRun.current_video_title && (
                <p className="truncate text-xs text-muted-foreground">
                  {activeRun.current_video_title}
                </p>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <Clock size={12} aria-hidden="true" />
                {formatElapsed(activeRun.started_at, null)}
              </span>
              {activeRun.estimated_remaining_seconds !== null &&
                activeRun.estimated_remaining_seconds !== undefined && (
                  <span>
                    ETA{" "}
                    {formatDurationSeconds(
                      activeRun.estimated_remaining_seconds,
                    )}
                  </span>
                )}
            </div>
          </div>
          <div className="mt-2">
            <ProgressIndicator
              value={activeRun.current_stage_progress}
              ariaLabel="Current pipeline stage progress"
            />
          </div>
        </section>
      )}

      {runsQuery.isPending ? (
        <LoadingState message="Loading pipeline runs…" />
      ) : runsQuery.isError ? (
        <ErrorState
          message={getErrorMessage(runsQuery.error)}
          onRetry={() => void runsQuery.refetch()}
        />
      ) : !runsQuery.data || runsQuery.data.items.length === 0 ? (
        <EmptyState
          title="No pipeline runs yet"
          description="Click Run Now to execute discovery, acquisition, extraction, slide processing, PDF generation, and cleanup."
        />
      ) : (
        <div className="space-y-3">
          <DataTable>
            <thead className="border-b border-border bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Run</th>
                <th className="px-3 py-2 font-medium">Videos</th>
                <th className="px-3 py-2 font-medium">Timing</th>
                <th className="px-3 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {runsQuery.data.items.map((run) => (
                <tr key={run.id} className="hover:bg-muted/20">
                  <td className="px-3 py-1.5">
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-semibold">
                          #{run.id}
                        </span>
                        <StatusBadge
                          tone={RUN_STATUS_TONE[run.status]}
                          label={run.status.replace(/_/g, " ")}
                        />
                      </div>
                      <p className="text-[11px] capitalize text-muted-foreground">
                        {run.trigger_type} · {STAGE_LABEL[run.current_stage]}
                      </p>
                    </div>
                  </td>
                  <td className="px-3 py-1.5 text-xs">
                    <span className="font-medium">
                      {run.completed_videos}/{run.total_videos}
                    </span>{" "}
                    <span className="text-muted-foreground">done</span>
                    {(run.failed_videos > 0 ||
                      run.skipped_videos > 0 ||
                      run.excluded_videos > 0) && (
                      <p className="text-[11px] text-muted-foreground">
                        {run.failed_videos > 0
                          ? `${run.failed_videos} failed · `
                          : ""}
                        {run.skipped_videos > 0
                          ? `${run.skipped_videos} skipped · `
                          : ""}
                        {run.excluded_videos > 0
                          ? `${run.excluded_videos} excluded`
                          : ""}
                      </p>
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-xs">
                    <p>{formatISTDateTime(run.started_at ?? run.created_at)}</p>
                    <p className="text-[11px] text-muted-foreground">
                      Elapsed: {formatElapsed(run.started_at, run.completed_at)}
                    </p>
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {(run.status === "queued" ||
                        run.status === "running") && (
                        <ActionButton
                          variant="ghost"
                          size="icon"
                          tooltip="Cancel run"
                          ariaLabel={`Cancel run #${run.id}`}
                          disabled={cancelMutation.isPending}
                          onClick={() => cancelMutation.mutate(run.id)}
                        >
                          <XCircle size={15} aria-hidden="true" />
                        </ActionButton>
                      )}
                      {run.failed_videos > 0 &&
                        run.status !== "queued" &&
                        run.status !== "running" && (
                          <ActionButton
                            variant="ghost"
                            size="icon"
                            tooltip="Retry failed videos"
                            ariaLabel={`Retry failed videos in run #${run.id}`}
                            disabled={
                              Boolean(activeRun) ||
                              retryFailedMutation.isPending
                            }
                            onClick={() => retryFailedMutation.mutate(run.id)}
                          >
                            <RotateCcw size={15} aria-hidden="true" />
                          </ActionButton>
                        )}
                      <ActionButton
                        variant="ghost"
                        size="icon"
                        tooltip="View execution logs"
                        ariaLabel={`View logs for run #${run.id}`}
                        onClick={() => setLogModalRun(run)}
                      >
                        <ScrollText size={15} aria-hidden="true" />
                      </ActionButton>
                      <DetailsPopover
                        title={`Run #${run.id} details`}
                        items={[
                          { label: "Trigger", value: run.trigger_type },
                          {
                            label: "Stage",
                            value: STAGE_LABEL[run.current_stage],
                          },
                          {
                            label: "Completed",
                            value: `${run.completed_videos} / ${run.total_videos}`,
                          },
                          {
                            label: "Skipped",
                            value: String(run.skipped_videos),
                          },
                          {
                            label: "Excluded",
                            value: String(run.excluded_videos),
                          },
                          { label: "Failed", value: String(run.failed_videos) },
                          {
                            label: "Cancelled",
                            value: String(run.cancelled_videos),
                          },
                        ]}
                        warnings={run.last_error ? [run.last_error] : undefined}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
          {runsQuery.data.total_pages > 1 && (
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>
                Page {runsQuery.data.page} of {runsQuery.data.total_pages} (
                {runsQuery.data.total} runs)
              </span>
              <div className="flex gap-1.5">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Previous
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={page >= runsQuery.data.total_pages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {logModalRun && (
        <Modal
          open={Boolean(logModalRun)}
          onClose={() => setLogModalRun(null)}
          title={`Run #${logModalRun.id} Execution Logs`}
          size="lg"
        >
          <div className="space-y-3">
            {logModalRun.videos.length > 0 && (
              <div>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Video Outcomes ({logModalRun.videos.length})
                </h3>
                <ul className="max-h-40 space-y-1 overflow-y-auto rounded border border-border p-2 text-xs">
                  {logModalRun.videos.map((v) => (
                    <li
                      key={v.id}
                      className="flex items-center justify-between gap-2 border-b border-border/50 pb-1 last:border-b-0 last:pb-0"
                    >
                      <span className="truncate font-medium">
                        {v.video_title || `Video #${v.video_id}`}
                      </span>
                      <span className="shrink-0 text-muted-foreground">
                        {v.status}
                        {v.cleaned ? " · cleaned" : ""}
                        {v.error ? ` (${v.error})` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div>
              <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <FileText size={12} aria-hidden="true" />
                Logs ({logModalRun.logs.length})
              </h3>
              {logModalRun.logs.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No log entries recorded for this run.
                </p>
              ) : (
                <ul className="max-h-72 space-y-1 overflow-y-auto rounded border border-border bg-muted/20 p-2 font-mono text-[11px]">
                  {logModalRun.logs.map((entry, idx) => (
                    <li key={idx} className="leading-4">
                      <span className="text-muted-foreground">
                        [{formatISTDateTime(entry.timestamp)}]
                      </span>{" "}
                      <span
                        className={
                          entry.level === "ERROR"
                            ? "font-semibold text-red-700"
                            : entry.level === "WARNING"
                              ? "font-semibold text-amber-700"
                              : "text-foreground"
                        }
                      >
                        {entry.level}
                      </span>{" "}
                      <span>{entry.message}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Modal>
      )}
    </PageContainer>
  );
}
