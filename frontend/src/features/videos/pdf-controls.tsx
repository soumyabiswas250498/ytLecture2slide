import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  Eye,
  FileText,
  RotateCcw,
  RotateCw,
  Trash2,
  XCircle,
} from "lucide-react";
import { ActionButton } from "@/components/shared/action-button";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { ProgressIndicator } from "@/components/shared/progress-indicator";
import { StatusBadge, type StatusTone } from "@/components/shared/status-badge";
import { Select, type SelectOption } from "@/components/ui/select";
import { PdfPreviewModal } from "@/features/library/pdf-preview-modal";
import {
  deletePdf,
  generatePdf,
  getPdfState,
  PDF_COMPRESSION_LABELS,
  pdfAction,
  pdfDownloadUrl,
  type PdfCompressionMode,
} from "@/services/pdfs";
import { getSlideState } from "@/services/slides";

const PDF_STATUS_TONE: Record<string, StatusTone> = {
  pending: "neutral",
  generating: "info",
  generated: "success",
  failed: "error",
  cancelled: "warning",
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

export function PdfControls({
  videoId,
  videoTitle,
  isExcluded = false,
}: {
  videoId: number;
  videoTitle: string;
  isExcluded?: boolean;
}) {
  const client = useQueryClient();
  const [previewOpen, setPreviewOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [compressionOverride, setCompressionOverride] = useState<
    "default" | PdfCompressionMode
  >("default");

  const query = useQuery({
    queryKey: ["pdf-generation", videoId],
    queryFn: ({ signal }) => getPdfState(videoId, signal),
    refetchInterval: (q) => (q.state.data?.requested ? 1000 : false),
  });

  const slidesQuery = useQuery({
    queryKey: ["slide-processing", videoId],
    queryFn: ({ signal }) => getSlideState(videoId, signal),
  });

  const action = useMutation({
    mutationFn: async (kind: "generate" | "retry" | "cancel" | "delete") => {
      if (kind === "delete") return deletePdf(videoId);
      if (kind === "generate") {
        const hasPdf = Boolean(
          query.data?.pdf_path && query.data?.page_count > 0,
        );
        return generatePdf(
          videoId,
          hasPdf,
          compressionOverride === "default" ? undefined : compressionOverride,
        );
      }
      return pdfAction(videoId, kind);
    },
    onSuccess: () => {
      setConfirmDelete(false);
      void client.invalidateQueries({ queryKey: ["pdf-generation", videoId] });
      void client.invalidateQueries({ queryKey: ["pdf-library"] });
    },
  });

  const state = query.data;
  const active = Boolean(state?.requested || state?.status === "generating");
  const slidesReady = Boolean(
    slidesQuery.data?.status === "processed" &&
    slidesQuery.data?.output_directory,
  );
  const hasPublishedPdf = Boolean(
    state?.pdf_path && state.page_count > 0 && state.pdf_filename,
  );

  return (
    <div className="min-w-[164px] space-y-1">
      {query.isPending && (
        <span className="text-xs text-muted-foreground">Loading PDF…</span>
      )}
      {query.isError && (
        <p role="alert" className="text-xs text-red-700">
          {query.error.message}
        </p>
      )}
      {state && (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusBadge
              label={state.status}
              tone={PDF_STATUS_TONE[state.status] ?? "neutral"}
            />
            {hasPublishedPdf && (
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {state.page_count} {state.page_count === 1 ? "page" : "pages"} ·{" "}
                {formatBytes(state.file_size_bytes)} ·{" "}
                {PDF_COMPRESSION_LABELS[state.compression]}
              </span>
            )}
          </div>

          {active && (
            <ProgressIndicator
              value={state.progress}
              ariaLabel="PDF generation progress"
              detail={`${state.completed_pages} / ${state.total_pages} pages`}
            />
          )}

          {state.error && (
            <p
              role="alert"
              className="max-w-[200px] truncate text-xs text-red-700"
              title={state.error}
            >
              {state.error}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-1">
            {!active && !isExcluded && slidesReady && (
              <Select
                value={compressionOverride}
                ariaLabel={`Compression mode for ${videoTitle}`}
                options={
                  [
                    { value: "default", label: "Default compression" },
                    { value: "lossless", label: "Lossless (PNG)" },
                    { value: "maximum_quality", label: "Max quality (95)" },
                    { value: "high_quality", label: "High quality (90)" },
                    { value: "compact", label: "Compact (85)" },
                  ] satisfies readonly SelectOption<
                    "default" | PdfCompressionMode
                  >[]
                }
                onValueChange={setCompressionOverride}
                className="text-xs"
              />
            )}
            {!active && !isExcluded && (
              <ActionButton
                tooltip={
                  !slidesReady
                    ? "Process slides before generating PDF"
                    : hasPublishedPdf
                      ? "Regenerate PDF"
                      : "Generate PDF"
                }
                ariaLabel={
                  hasPublishedPdf
                    ? `Regenerate PDF for ${videoTitle}`
                    : `Generate PDF for ${videoTitle}`
                }
                disabled={!slidesReady || action.isPending}
                onClick={() => action.mutate("generate")}
              >
                {hasPublishedPdf ? (
                  <RotateCw size={12} aria-hidden="true" />
                ) : (
                  <FileText size={12} aria-hidden="true" />
                )}
                {hasPublishedPdf ? "Regenerate" : "Generate"}
              </ActionButton>
            )}

            {active && (
              <ActionButton
                tooltip="Cancel PDF generation"
                ariaLabel={`Cancel PDF for ${videoTitle}`}
                disabled={action.isPending}
                onClick={() => action.mutate("cancel")}
              >
                <XCircle size={12} aria-hidden="true" />
                Cancel
              </ActionButton>
            )}

            {!active &&
              !isExcluded &&
              slidesReady &&
              ["failed", "cancelled"].includes(state.status) && (
                <ActionButton
                  tooltip="Retry PDF generation"
                  ariaLabel={`Retry PDF for ${videoTitle}`}
                  disabled={action.isPending}
                  onClick={() => action.mutate("retry")}
                >
                  <RotateCcw size={12} aria-hidden="true" />
                  Retry
                </ActionButton>
              )}

            {hasPublishedPdf && (
              <>
                <ActionButton
                  tooltip="Preview PDF"
                  ariaLabel={`Preview PDF for ${videoTitle}`}
                  onClick={() => setPreviewOpen(true)}
                >
                  <Eye size={12} aria-hidden="true" />
                  Preview
                </ActionButton>
                <a
                  href={pdfDownloadUrl(videoId)}
                  download={state.pdf_filename ?? undefined}
                  title="Download PDF"
                  aria-label={`Download PDF for ${videoTitle}`}
                  className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-white px-2 text-xs font-medium text-foreground hover:bg-muted"
                >
                  <Download size={12} aria-hidden="true" />
                </a>
              </>
            )}

            {!active && hasPublishedPdf && (
              <ActionButton
                tooltip="Delete generated PDF"
                ariaLabel={`Delete PDF for ${videoTitle}`}
                className="text-red-700 hover:bg-red-50"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 size={12} aria-hidden="true" />
              </ActionButton>
            )}
          </div>
        </>
      )}

      {action.isError && (
        <p role="alert" className="text-xs text-red-700">
          {action.error.message}
        </p>
      )}

      <PdfPreviewModal
        open={previewOpen}
        videoId={videoId}
        title={videoTitle}
        filename={state?.pdf_filename}
        onClose={() => setPreviewOpen(false)}
      />

      <ConfirmDialog
        open={confirmDelete}
        title="Delete generated PDF"
        description={`Delete the generated PDF for "${videoTitle}"? Source videos, extracted frames, and processed slides will be preserved.`}
        confirmLabel="Confirm delete PDF"
        pendingLabel="Deleting…"
        isPending={action.isPending}
        onConfirm={() => action.mutate("delete")}
        onClose={() => setConfirmDelete(false)}
      />
    </div>
  );
}
