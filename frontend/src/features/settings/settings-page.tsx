import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Plus, Save, X } from "lucide-react";
import { NotificationAlert } from "@/components/shared/notification-alert";
import { PageContainer } from "@/components/shared/page-container";
import { PageHeader } from "@/components/shared/page-header";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { Select, type SelectOption } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/services/api";
import {
  getExclusionKeywords,
  getPipelineSettings,
  updateExclusionKeywords,
  updatePipelineSettings,
  type PipelineSettings,
} from "@/services/settings";

const TIMEZONE_OPTIONS: readonly SelectOption<string>[] = [
  { value: "Asia/Kolkata", label: "Asia/Kolkata (IST)" },
  { value: "UTC", label: "UTC" },
  { value: "Asia/Dhaka", label: "Asia/Dhaka" },
  { value: "Europe/London", label: "Europe/London" },
  { value: "America/New_York", label: "America/New_York" },
];

const CONCURRENCY_OPTIONS: readonly SelectOption<string>[] = [
  { value: "1", label: "1 video at a time (recommended)" },
  { value: "2", label: "2 videos concurrently" },
  { value: "3", label: "3 videos concurrently" },
];

function normalizeKeyword(raw: string): string {
  return raw.normalize("NFC").trim().replace(/\s+/g, " ");
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "An unexpected error occurred.";
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [draftKeywords, setDraftKeywords] = useState<string[] | null>(null);
  const [newKeyword, setNewKeyword] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const query = useQuery({
    queryKey: ["settings", "exclusion-keywords"],
    queryFn: ({ signal }) => getExclusionKeywords(signal),
  });

  const pipelineQuery = useQuery({
    queryKey: ["settings", "pipeline"],
    queryFn: ({ signal }) => getPipelineSettings(signal),
  });
  const [draftPipeline, setDraftPipeline] = useState<Omit<
    PipelineSettings,
    "updated_at"
  > | null>(null);
  const [pipelineFeedback, setPipelineFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const currentPipeline: Omit<PipelineSettings, "updated_at"> | null =
    draftPipeline ??
    (pipelineQuery.data
      ? {
          scheduler_enabled: pipelineQuery.data.scheduler_enabled,
          scheduler_frequency: pipelineQuery.data.scheduler_frequency,
          scheduler_time: pipelineQuery.data.scheduler_time,
          timezone: pipelineQuery.data.timezone,
          discovery_lookback_days: pipelineQuery.data.discovery_lookback_days,
          extraction_interval_seconds:
            pipelineQuery.data.extraction_interval_seconds,
          pipeline_concurrent_limit:
            pipelineQuery.data.pipeline_concurrent_limit,
          pipeline_retry_attempts: pipelineQuery.data.pipeline_retry_attempts,
          auto_cleanup_enabled: pipelineQuery.data.auto_cleanup_enabled,
          min_free_disk_mb: pipelineQuery.data.min_free_disk_mb,
        }
      : null);
  const pipelineDirty = draftPipeline !== null;

  const savePipelineMutation = useMutation({
    mutationFn: (payload: Omit<PipelineSettings, "updated_at">) =>
      updatePipelineSettings(payload),
    onSuccess: async () => {
      setDraftPipeline(null);
      setPipelineFeedback({
        type: "success",
        message: "Scheduling, processing, and storage settings saved.",
      });
      await queryClient.invalidateQueries({
        queryKey: ["settings", "pipeline"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["pipeline", "scheduler"],
      });
    },
    onError: (err) => {
      setPipelineFeedback({ type: "error", message: getErrorMessage(err) });
    },
  });

  const patchPipeline = (
    patch: Partial<Omit<PipelineSettings, "updated_at">>,
  ) => {
    if (!currentPipeline) return;
    setPipelineFeedback(null);
    setDraftPipeline({ ...currentPipeline, ...patch });
  };

  const dirty = draftKeywords !== null;
  const keywords = draftKeywords ?? query.data?.keywords ?? [];

  const saveMutation = useMutation({
    mutationFn: (nextKeywords: string[]) =>
      updateExclusionKeywords(nextKeywords),
    onSuccess: async (res) => {
      setDraftKeywords(null);
      setValidationError(null);
      setFeedback({
        type: "success",
        message: `Saved ${res.keywords.length} exclusion keyword${res.keywords.length === 1 ? "" : "s"}. ${res.excluded_video_count} excluded, ${res.eligible_video_count} eligible.`,
      });
      await queryClient.invalidateQueries({
        queryKey: ["settings", "exclusion-keywords"],
      });
      await queryClient.invalidateQueries({ queryKey: ["videos"] });
      await queryClient.invalidateQueries({ queryKey: ["video-summary"] });
    },
    onError: (err) => {
      setFeedback({ type: "error", message: getErrorMessage(err) });
    },
  });

  const handleAdd = (rawValue: string) => {
    const cleaned = normalizeKeyword(rawValue);
    if (!cleaned) {
      setValidationError("Keyword cannot be empty.");
      return;
    }
    const lower = cleaned.toLocaleLowerCase();
    if (keywords.some((k) => k.toLocaleLowerCase() === lower)) {
      setValidationError(`"${cleaned}" is already in the exclusion list.`);
      return;
    }
    setValidationError(null);
    setFeedback(null);
    setDraftKeywords([...keywords, cleaned]);
    setNewKeyword("");
  };

  const handleRemove = (index: number) => {
    setValidationError(null);
    setFeedback(null);
    setDraftKeywords(keywords.filter((_, idx) => idx !== index));
    if (editingIndex === index) {
      setEditingIndex(null);
      setEditingValue("");
    }
  };

  const handleSaveEdit = (index: number) => {
    const cleaned = normalizeKeyword(editingValue);
    if (!cleaned) {
      setValidationError("Keyword cannot be empty.");
      return;
    }
    const lower = cleaned.toLocaleLowerCase();
    if (
      keywords.some(
        (k, idx) => idx !== index && k.toLocaleLowerCase() === lower,
      )
    ) {
      setValidationError(`"${cleaned}" is already in the exclusion list.`);
      return;
    }
    setValidationError(null);
    setFeedback(null);
    setDraftKeywords(
      keywords.map((item, idx) => (idx === index ? cleaned : item)),
    );
    setEditingIndex(null);
    setEditingValue("");
  };

  const suggested = (query.data?.suggested_keywords ?? []).filter(
    (s) =>
      !keywords.some((k) => k.toLocaleLowerCase() === s.toLocaleLowerCase()),
  );

  return (
    <PageContainer>
      <PageHeader
        eyebrow="CONFIGURATION"
        title="Settings"
        description="Configure global application rules and video filtering."
      />

      {query.isPending && <LoadingState message="Loading settings…" />}
      {query.isError && (
        <ErrorState
          message={query.error.message}
          onRetry={() => void query.refetch()}
        />
      )}

      {query.data && (
        <section
          aria-labelledby="exclude-keywords-heading"
          className="rounded-xl border border-border bg-white p-5 shadow-xs"
        >
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
            <div>
              <h2
                id="exclude-keywords-heading"
                className="text-base font-semibold"
              >
                Exclude Keywords
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Videos whose titles contain any configured keyword or phrase
                (English or Bengali) are automatically marked as excluded and
                blocked from download and processing.
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              disabled={!dirty || saveMutation.isPending}
              onClick={() => saveMutation.mutate(keywords)}
            >
              <Save size={14} aria-hidden="true" />
              {saveMutation.isPending ? "Saving…" : "Save changes"}
            </Button>
          </div>

          {feedback && (
            <div className="mt-3">
              <NotificationAlert
                tone={feedback.type}
                summary={feedback.message}
                onDismiss={() => setFeedback(null)}
              />
            </div>
          )}

          <form
            className="mt-4 flex flex-wrap items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              handleAdd(newKeyword);
            }}
          >
            <label htmlFor="new-exclusion-keyword" className="sr-only">
              Add exclusion keyword
            </label>
            <input
              id="new-exclusion-keyword"
              type="text"
              value={newKeyword}
              onChange={(event) => {
                setNewKeyword(event.target.value);
                if (validationError) setValidationError(null);
              }}
              placeholder="Add keyword or phrase (e.g., Math, গণিত)…"
              className="h-9 min-w-[260px] flex-1 rounded-md border border-border bg-white px-3 text-sm focus:border-primary focus:outline-none"
            />
            <Button type="submit" variant="outline" size="sm">
              <Plus size={14} aria-hidden="true" />
              Add keyword
            </Button>
          </form>

          {validationError && (
            <p role="alert" className="mt-2 text-xs text-red-700">
              {validationError}
            </p>
          )}

          <div className="mt-4">
            <p className="text-xs font-medium text-muted-foreground">
              Active exclusion keywords ({keywords.length})
            </p>
            {keywords.length === 0 ? (
              <p className="mt-2 text-xs text-muted-foreground">
                No exclusion keywords configured. All discovered videos remain
                eligible.
              </p>
            ) : (
              <ul className="mt-2 flex flex-wrap gap-2">
                {keywords.map((kw, index) => (
                  <li
                    key={`${kw}-${index}`}
                    className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/60 px-2.5 py-1 text-xs"
                  >
                    {editingIndex === index ? (
                      <>
                        <input
                          type="text"
                          aria-label={`Edit keyword ${kw}`}
                          value={editingValue}
                          onChange={(e) => setEditingValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              handleSaveEdit(index);
                            } else if (e.key === "Escape") {
                              setEditingIndex(null);
                              setEditingValue("");
                            }
                          }}
                          className="h-5 w-32 rounded border border-border bg-white px-1.5 text-xs focus:border-primary focus:outline-none"
                        />
                        <button
                          type="button"
                          aria-label={`Save keyword ${kw}`}
                          onClick={() => handleSaveEdit(index)}
                          className="rounded p-0.5 text-emerald-700 hover:bg-emerald-100"
                        >
                          <Check size={12} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          aria-label="Cancel editing"
                          onClick={() => {
                            setEditingIndex(null);
                            setEditingValue("");
                          }}
                          className="rounded p-0.5 text-muted-foreground hover:bg-muted"
                        >
                          <X size={12} aria-hidden="true" />
                        </button>
                      </>
                    ) : (
                      <>
                        <span className="font-medium text-foreground">
                          {kw}
                        </span>
                        <button
                          type="button"
                          aria-label={`Edit ${kw}`}
                          title={`Edit ${kw}`}
                          onClick={() => {
                            setEditingIndex(index);
                            setEditingValue(kw);
                          }}
                          className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                        >
                          <Pencil size={11} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          aria-label={`Remove ${kw}`}
                          title={`Remove ${kw}`}
                          onClick={() => handleRemove(index)}
                          className="rounded p-0.5 text-muted-foreground hover:text-red-700"
                        >
                          <X size={12} aria-hidden="true" />
                        </button>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {suggested.length > 0 && (
            <div className="mt-4 border-t border-border pt-3">
              <p className="text-xs text-muted-foreground">
                Example keywords (click to add):
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {suggested.map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => handleAdd(example)}
                    className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
                  >
                    <Plus size={11} aria-hidden="true" />
                    {example}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {currentPipeline && (
        <section
          aria-labelledby="automation-settings-heading"
          className="rounded-lg border border-border bg-white p-4 sm:p-5"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2
                id="automation-settings-heading"
                className="text-sm font-semibold text-foreground"
              >
                Automation, Processing & Storage
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Configure daily scheduled execution, concurrency, retries, and
                automatic intermediate cleanup.
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              disabled={!pipelineDirty || savePipelineMutation.isPending}
              onClick={() => {
                if (currentPipeline) {
                  savePipelineMutation.mutate(currentPipeline);
                }
              }}
            >
              <Save size={14} aria-hidden="true" />
              {savePipelineMutation.isPending
                ? "Saving…"
                : "Save Pipeline Settings"}
            </Button>
          </div>

          {pipelineFeedback && (
            <div className="mt-3">
              <NotificationAlert
                tone={pipelineFeedback.type}
                summary={pipelineFeedback.message}
                onDismiss={() => setPipelineFeedback(null)}
              />
            </div>
          )}

          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <div className="space-y-3 rounded-md border border-border p-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Scheduling
              </h3>
              <div className="flex items-center justify-between gap-2">
                <label
                  htmlFor="scheduler-enabled-switch"
                  className="text-xs font-medium text-foreground"
                >
                  Automatic daily execution
                </label>
                <Switch
                  id="scheduler-enabled-switch"
                  checked={currentPipeline.scheduler_enabled}
                  onCheckedChange={(checked) =>
                    patchPipeline({ scheduler_enabled: checked })
                  }
                />
              </div>
              <div>
                <label
                  htmlFor="scheduler-time-input"
                  className="block text-xs font-medium text-foreground"
                >
                  Daily execution time
                </label>
                <input
                  id="scheduler-time-input"
                  type="time"
                  value={currentPipeline.scheduler_time}
                  onChange={(e) =>
                    patchPipeline({ scheduler_time: e.target.value })
                  }
                  className="mt-1 h-9 w-full rounded-md border border-border bg-white px-2.5 text-xs focus:border-primary focus:outline-none"
                />
              </div>
              <div>
                <label
                  htmlFor="scheduler-timezone-select"
                  className="block text-xs font-medium text-foreground"
                >
                  Timezone
                </label>
                <div className="mt-1">
                  <Select
                    id="scheduler-timezone-select"
                    ariaLabel="Timezone"
                    value={currentPipeline.timezone}
                    options={TIMEZONE_OPTIONS}
                    onValueChange={(val) => patchPipeline({ timezone: val })}
                  />
                </div>
              </div>
              <div>
                <label
                  htmlFor="lookback-days-input"
                  className="block text-xs font-medium text-foreground"
                >
                  Discovery lookback (days)
                </label>
                <input
                  id="lookback-days-input"
                  type="number"
                  min={1}
                  max={30}
                  value={currentPipeline.discovery_lookback_days}
                  onChange={(e) =>
                    patchPipeline({
                      discovery_lookback_days: Math.max(
                        1,
                        Math.min(30, Number(e.target.value) || 7),
                      ),
                    })
                  }
                  className="mt-1 h-9 w-full rounded-md border border-border bg-white px-2.5 text-xs focus:border-primary focus:outline-none"
                />
              </div>
            </div>

            <div className="space-y-3 rounded-md border border-border p-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Processing
              </h3>
              <div>
                <label
                  htmlFor="screenshot-interval-input"
                  className="block text-xs font-medium text-foreground"
                >
                  Screenshot interval (seconds)
                </label>
                <input
                  id="screenshot-interval-input"
                  type="number"
                  min={1}
                  max={3600}
                  value={currentPipeline.extraction_interval_seconds}
                  onChange={(e) =>
                    patchPipeline({
                      extraction_interval_seconds: Math.max(
                        1,
                        Math.min(3600, Number(e.target.value) || 60),
                      ),
                    })
                  }
                  className="mt-1 h-9 w-full rounded-md border border-border bg-white px-2.5 text-xs focus:border-primary focus:outline-none"
                />
              </div>
              <div>
                <label
                  htmlFor="concurrency-select"
                  className="block text-xs font-medium text-foreground"
                >
                  Maximum concurrent videos
                </label>
                <div className="mt-1">
                  <Select
                    id="concurrency-select"
                    ariaLabel="Maximum concurrent videos"
                    value={String(currentPipeline.pipeline_concurrent_limit)}
                    options={CONCURRENCY_OPTIONS}
                    onValueChange={(val) =>
                      patchPipeline({
                        pipeline_concurrent_limit: Number(val) || 1,
                      })
                    }
                  />
                </div>
              </div>
              <div>
                <label
                  htmlFor="retry-limit-input"
                  className="block text-xs font-medium text-foreground"
                >
                  Retry limit per video
                </label>
                <input
                  id="retry-limit-input"
                  type="number"
                  min={0}
                  max={10}
                  value={currentPipeline.pipeline_retry_attempts}
                  onChange={(e) =>
                    patchPipeline({
                      pipeline_retry_attempts: Math.max(
                        0,
                        Math.min(10, Number(e.target.value) || 0),
                      ),
                    })
                  }
                  className="mt-1 h-9 w-full rounded-md border border-border bg-white px-2.5 text-xs focus:border-primary focus:outline-none"
                />
              </div>
            </div>

            <div className="space-y-3 rounded-md border border-border p-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Storage
              </h3>
              <div className="flex items-center justify-between gap-2">
                <label
                  htmlFor="auto-cleanup-switch"
                  className="text-xs font-medium text-foreground"
                >
                  Automatic intermediate cleanup
                </label>
                <Switch
                  id="auto-cleanup-switch"
                  checked={currentPipeline.auto_cleanup_enabled}
                  onCheckedChange={(checked) =>
                    patchPipeline({ auto_cleanup_enabled: checked })
                  }
                />
              </div>
              <p className="text-[11px] text-muted-foreground">
                Removes downloaded videos, raw frames, and processed slides only
                after PDF validation succeeds.
              </p>
              <div>
                <label
                  htmlFor="min-disk-input"
                  className="block text-xs font-medium text-foreground"
                >
                  Minimum free disk space (MB)
                </label>
                <input
                  id="min-disk-input"
                  type="number"
                  min={50}
                  max={102400}
                  value={currentPipeline.min_free_disk_mb}
                  onChange={(e) =>
                    patchPipeline({
                      min_free_disk_mb: Math.max(
                        50,
                        Math.min(102400, Number(e.target.value) || 500),
                      ),
                    })
                  }
                  className="mt-1 h-9 w-full rounded-md border border-border bg-white px-2.5 text-xs focus:border-primary focus:outline-none"
                />
              </div>
            </div>
          </div>
        </section>
      )}
    </PageContainer>
  );
}
