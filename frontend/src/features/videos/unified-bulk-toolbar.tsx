import { useMemo, useState } from "react";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Download, FileText, Film, Layers } from "lucide-react";
import { ActionButton } from "@/components/shared/action-button";
import { BulkActionToolbar } from "@/components/shared/bulk-action-toolbar";
import {
  NotificationAlert,
  type NotificationTone,
} from "@/components/shared/notification-alert";
import { ApiError } from "@/services/api";
import {
  extractSelected,
  getExtraction,
  getExtractionConfig,
  type extractionSchema,
} from "@/services/extractions";
import {
  generateSelectedPdfs,
  getPdfState,
  type PdfState,
} from "@/services/pdfs";
import {
  getSlideState,
  processSelected,
  type getSlideState as getSlideStateFn,
} from "@/services/slides";
import { startBulkDownload, type Video } from "@/services/videos";
import type { z } from "zod";

type ExtractionState = z.infer<typeof extractionSchema>;
type SlideState = Awaited<ReturnType<typeof getSlideStateFn>>;

interface BulkFeedback {
  tone: NotificationTone;
  summary: string;
  details: string[];
}

function pluralizeVideos(count: number): string {
  return `${count} video${count === 1 ? "" : "s"}`;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "An unexpected error occurred.";
}

export function UnifiedBulkToolbar({
  selectedVideos,
  interval,
  onIntervalChange,
  onClearSelection,
}: {
  selectedVideos: Video[];
  interval: number | undefined;
  onIntervalChange: (value: number) => void;
  onClearSelection: () => void;
}) {
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState<BulkFeedback | null>(null);

  const selectedIds = useMemo(
    () => selectedVideos.map((v) => v.id),
    [selectedVideos],
  );

  const titleById = useMemo(() => {
    const map = new Map<number, string>();
    for (const v of selectedVideos) map.set(v.id, v.title);
    return map;
  }, [selectedVideos]);

  const configQuery = useQuery({
    queryKey: ["extraction-config"],
    queryFn: ({ signal }) => getExtractionConfig(signal),
  });

  const extractionQueries = useQueries({
    queries: selectedIds.map((id) => ({
      queryKey: ["extraction", id],
      queryFn: ({ signal }: { signal?: AbortSignal }) =>
        getExtraction(id, signal),
    })),
  });

  const slideQueries = useQueries({
    queries: selectedIds.map((id) => ({
      queryKey: ["slide-processing", id],
      queryFn: ({ signal }: { signal?: AbortSignal }) =>
        getSlideState(id, signal),
    })),
  });

  const pdfQueries = useQueries({
    queries: selectedIds.map((id) => ({
      queryKey: ["pdf-generation", id],
      queryFn: ({ signal }: { signal?: AbortSignal }) =>
        getPdfState(id, signal),
    })),
  });

  const extractionById = useMemo(() => {
    const map = new Map<number, ExtractionState>();
    selectedIds.forEach((id, idx) => {
      const data = extractionQueries[idx]?.data;
      if (data) map.set(id, data);
    });
    return map;
  }, [selectedIds, extractionQueries]);

  const slideById = useMemo(() => {
    const map = new Map<number, SlideState>();
    selectedIds.forEach((id, idx) => {
      const data = slideQueries[idx]?.data;
      if (data) map.set(id, data);
    });
    return map;
  }, [selectedIds, slideQueries]);

  const pdfById = useMemo(() => {
    const map = new Map<number, PdfState>();
    selectedIds.forEach((id, idx) => {
      const data = pdfQueries[idx]?.data;
      if (data) map.set(id, data);
    });
    return map;
  }, [selectedIds, pdfQueries]);

  const downloadEligibility = useMemo(() => {
    const eligible: Video[] = [];
    const excluded: { title: string; reason: string }[] = [];
    for (const v of selectedVideos) {
      if (v.is_excluded) {
        excluded.push({
          title: v.title,
          reason:
            v.excluded_keywords.length > 0
              ? `Excluded by keyword(s): ${v.excluded_keywords.join(", ")}`
              : "Excluded by keyword",
        });
      } else if (v.download_status === "downloading") {
        excluded.push({
          title: v.title,
          reason: "Download already in progress",
        });
      } else if (v.download_status === "downloaded") {
        excluded.push({ title: v.title, reason: "Already downloaded" });
      } else {
        eligible.push(v);
      }
    }
    return { eligible, excluded };
  }, [selectedVideos]);

  const extractionEligibility = useMemo(() => {
    const eligible: Video[] = [];
    const excluded: { title: string; reason: string }[] = [];
    for (const v of selectedVideos) {
      const ext = extractionById.get(v.id);
      if (v.is_excluded) {
        excluded.push({
          title: v.title,
          reason:
            v.excluded_keywords.length > 0
              ? `Excluded by keyword(s): ${v.excluded_keywords.join(", ")}`
              : "Excluded by keyword",
        });
      } else if (v.download_status !== "downloaded") {
        excluded.push({
          title: v.title,
          reason: "Source video not downloaded yet",
        });
      } else if (ext?.requested || ext?.status === "extracting") {
        excluded.push({
          title: v.title,
          reason: "Frame extraction already in progress",
        });
      } else if (ext?.status === "extracted") {
        excluded.push({
          title: v.title,
          reason: "Frames already extracted",
        });
      } else {
        eligible.push(v);
      }
    }
    return { eligible, excluded };
  }, [selectedVideos, extractionById]);

  const slideEligibility = useMemo(() => {
    const eligible: Video[] = [];
    const excluded: { title: string; reason: string }[] = [];
    for (const v of selectedVideos) {
      const ext = extractionById.get(v.id);
      const slide = slideById.get(v.id);
      if (v.is_excluded) {
        excluded.push({
          title: v.title,
          reason:
            v.excluded_keywords.length > 0
              ? `Excluded by keyword(s): ${v.excluded_keywords.join(", ")}`
              : "Excluded by keyword",
        });
      } else if (ext?.status !== "extracted") {
        excluded.push({
          title: v.title,
          reason: "Frames must be extracted first",
        });
      } else if (slide?.requested || slide?.status === "processing") {
        excluded.push({
          title: v.title,
          reason: "Slide processing already in progress",
        });
      } else {
        eligible.push(v);
      }
    }
    return { eligible, excluded };
  }, [selectedVideos, extractionById, slideById]);

  const pdfEligibility = useMemo(() => {
    const eligible: Video[] = [];
    const excluded: { title: string; reason: string }[] = [];
    for (const v of selectedVideos) {
      const slide = slideById.get(v.id);
      const pdf = pdfById.get(v.id);
      if (v.is_excluded) {
        excluded.push({
          title: v.title,
          reason:
            v.excluded_keywords.length > 0
              ? `Excluded by keyword(s): ${v.excluded_keywords.join(", ")}`
              : "Excluded by keyword",
        });
      } else if (slide?.status !== "processed" || !slide?.output_directory) {
        excluded.push({
          title: v.title,
          reason: "Slides must be processed first",
        });
      } else if (pdf?.requested || pdf?.status === "generating") {
        excluded.push({
          title: v.title,
          reason: "PDF generation already in progress",
        });
      } else if (pdf?.status === "generated" && pdf?.pdf_path) {
        excluded.push({
          title: v.title,
          reason: "PDF already generated",
        });
      } else {
        eligible.push(v);
      }
    }
    return { eligible, excluded };
  }, [selectedVideos, slideById, pdfById]);

  const buildBulkFeedback = (
    actionLabel: string,
    startedCount: number,
    excluded: { title: string; reason: string }[],
    apiErrors: { video_id: number; reason: string }[],
    apiSkipped: { video_id: number; reason: string }[] = [],
  ): BulkFeedback => {
    const details: string[] = [];
    for (const item of excluded) {
      details.push(`${item.title}: Excluded — ${item.reason}`);
    }
    for (const item of apiSkipped) {
      const title = titleById.get(item.video_id) ?? `Video #${item.video_id}`;
      details.push(`${title}: Skipped — ${item.reason}`);
    }
    for (const item of apiErrors) {
      const title = titleById.get(item.video_id) ?? `Video #${item.video_id}`;
      details.push(`${title}: Failed — ${item.reason}`);
    }

    const totalSkipped = excluded.length + apiSkipped.length;
    const parts = [`${actionLabel}: ${pluralizeVideos(startedCount)} started`];
    if (totalSkipped > 0) parts.push(`${totalSkipped} excluded`);
    if (apiErrors.length > 0) parts.push(`${apiErrors.length} failed`);

    const tone: NotificationTone =
      apiErrors.length > 0
        ? startedCount > 0
          ? "warning"
          : "error"
        : totalSkipped > 0
          ? "info"
          : "success";

    return { tone, summary: parts.join(" · "), details };
  };

  const downloadMutation = useMutation({
    mutationFn: (ids: number[]) => startBulkDownload(ids),
    onSuccess: (res) => {
      setFeedback(
        buildBulkFeedback(
          "Bulk download",
          res.started_ids.length,
          downloadEligibility.excluded,
          res.errors,
          res.skipped,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["videos"] });
      void queryClient.invalidateQueries({ queryKey: ["active-downloads"] });
    },
    onError: (err) => {
      setFeedback({
        tone: "error",
        summary: `Bulk download failed: ${getErrorMessage(err)}`,
        details: [],
      });
    },
  });

  const extractionMutation = useMutation({
    mutationFn: (ids: number[]) => extractSelected(ids, interval),
    onSuccess: (res) => {
      setFeedback(
        buildBulkFeedback(
          "Frame extraction",
          res.started_ids.length,
          extractionEligibility.excluded,
          res.errors,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["extraction"] });
    },
    onError: (err) => {
      setFeedback({
        tone: "error",
        summary: `Frame extraction failed: ${getErrorMessage(err)}`,
        details: [],
      });
    },
  });

  const slideMutation = useMutation({
    mutationFn: (ids: number[]) => processSelected(ids),
    onSuccess: (res) => {
      setFeedback(
        buildBulkFeedback(
          "Slide processing",
          res.started_ids.length,
          slideEligibility.excluded,
          res.errors,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["slide-processing"] });
    },
    onError: (err) => {
      setFeedback({
        tone: "error",
        summary: `Slide processing failed: ${getErrorMessage(err)}`,
        details: [],
      });
    },
  });

  const pdfMutation = useMutation({
    mutationFn: (ids: number[]) => generateSelectedPdfs(ids),
    onSuccess: (res) => {
      setFeedback(
        buildBulkFeedback(
          "PDF generation",
          res.started_ids.length,
          pdfEligibility.excluded,
          res.errors,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["pdf-generation"] });
      void queryClient.invalidateQueries({ queryKey: ["pdf-library"] });
    },
    onError: (err) => {
      setFeedback({
        tone: "error",
        summary: `PDF generation failed: ${getErrorMessage(err)}`,
        details: [],
      });
    },
  });

  const intervalInvalid =
    interval !== undefined && (!Number.isFinite(interval) || interval < 0.001);
  const anyPending =
    downloadMutation.isPending ||
    extractionMutation.isPending ||
    slideMutation.isPending ||
    pdfMutation.isPending;

  const downloadDisabled =
    downloadEligibility.eligible.length === 0 || anyPending;
  const extractionDisabled =
    extractionEligibility.eligible.length === 0 ||
    anyPending ||
    intervalInvalid;
  const slideDisabled = slideEligibility.eligible.length === 0 || anyPending;
  const pdfDisabled = pdfEligibility.eligible.length === 0 || anyPending;

  return (
    <div className="space-y-2">
      <BulkActionToolbar
        selectedCount={selectedVideos.length}
        onClearSelection={onClearSelection}
      >
        <ActionButton
          variant="outline"
          size="sm"
          disabled={downloadDisabled}
          tooltip={
            selectedVideos.length === 0
              ? "Select videos to download"
              : downloadEligibility.eligible.length === 0
                ? "No selected videos are eligible for download"
                : `Download ${pluralizeVideos(downloadEligibility.eligible.length)}`
          }
          ariaLabel={`Download (${downloadEligibility.eligible.length})`}
          onClick={() =>
            downloadMutation.mutate(
              downloadEligibility.eligible.map((v) => v.id),
            )
          }
        >
          <Download size={14} aria-hidden="true" />
          Download ({downloadEligibility.eligible.length})
        </ActionButton>

        <span className="text-xs text-muted-foreground" aria-hidden="true">
          →
        </span>

        <ActionButton
          variant="outline"
          size="sm"
          disabled={extractionDisabled}
          tooltip={
            selectedVideos.length === 0
              ? "Select downloaded videos to extract frames"
              : extractionEligibility.eligible.length === 0
                ? "No selected videos have downloaded source files ready for extraction"
                : `Extract frames for ${pluralizeVideos(extractionEligibility.eligible.length)}`
          }
          ariaLabel={`Extract Frames (${extractionEligibility.eligible.length})`}
          onClick={() =>
            extractionMutation.mutate(
              extractionEligibility.eligible.map((v) => v.id),
            )
          }
        >
          <Film size={14} aria-hidden="true" />
          Extract Frames ({extractionEligibility.eligible.length})
        </ActionButton>

        <span className="text-xs text-muted-foreground" aria-hidden="true">
          →
        </span>

        <ActionButton
          variant="outline"
          size="sm"
          disabled={slideDisabled}
          tooltip={
            selectedVideos.length === 0
              ? "Select videos with extracted frames to process slides"
              : slideEligibility.eligible.length === 0
                ? "No selected videos have completed frame extraction"
                : `Process slides for ${pluralizeVideos(slideEligibility.eligible.length)}`
          }
          ariaLabel={`Process Slides (${slideEligibility.eligible.length})`}
          onClick={() =>
            slideMutation.mutate(slideEligibility.eligible.map((v) => v.id))
          }
        >
          <Layers size={14} aria-hidden="true" />
          Process Slides ({slideEligibility.eligible.length})
        </ActionButton>

        <span className="text-xs text-muted-foreground" aria-hidden="true">
          →
        </span>

        <ActionButton
          variant="outline"
          size="sm"
          disabled={pdfDisabled}
          tooltip={
            selectedVideos.length === 0
              ? "Select videos with processed slides to generate PDFs"
              : pdfEligibility.eligible.length === 0
                ? "No selected videos have processed slides ready for PDF generation"
                : `Generate PDF for ${pluralizeVideos(pdfEligibility.eligible.length)}`
          }
          ariaLabel={`Generate PDF (${pdfEligibility.eligible.length})`}
          onClick={() =>
            pdfMutation.mutate(pdfEligibility.eligible.map((v) => v.id))
          }
        >
          <FileText size={14} aria-hidden="true" />
          Generate PDF ({pdfEligibility.eligible.length})
        </ActionButton>

        <label className="ml-1 flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>Interval (s)</span>
          <input
            type="number"
            min="0.001"
            step="any"
            aria-label="Screenshot interval (seconds)"
            value={interval ?? configQuery.data?.interval_seconds ?? ""}
            onChange={(e) => onIntervalChange(Number(e.target.value))}
            className="h-8 w-20 rounded-md border border-border bg-white px-2 text-xs text-foreground tabular-nums focus:border-primary focus:outline-none"
          />
        </label>
      </BulkActionToolbar>

      {feedback && (
        <NotificationAlert
          tone={feedback.tone}
          summary={feedback.summary}
          details={
            feedback.details.length > 0 ? (
              <ul className="list-inside list-disc space-y-0.5">
                {feedback.details.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            ) : undefined
          }
          onDismiss={() => setFeedback(null)}
        />
      )}
    </div>
  );
}
