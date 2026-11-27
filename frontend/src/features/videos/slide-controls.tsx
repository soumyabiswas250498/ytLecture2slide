import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  Eye,
  Play,
  RotateCcw,
  RotateCw,
  Trash2,
  XCircle,
} from "lucide-react";
import { ActionButton } from "@/components/shared/action-button";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { ProgressIndicator } from "@/components/shared/progress-indicator";
import { StatusBadge, type StatusTone } from "@/components/shared/status-badge";
import { Modal } from "@/components/ui/modal";
import {
  deleteSlides,
  getSlideState,
  processSlides,
  slideAction,
} from "@/services/slides";
import { getExtraction } from "@/services/extractions";
import { SlidePreview } from "./slide-preview";

const slideStatusTone: Record<string, StatusTone> = {
  pending: "neutral",
  processing: "info",
  processed: "success",
  failed: "error",
  cancelled: "warning",
};

export function SlideControls({
  videoId,
  isExcluded = false,
}: {
  videoId: number;
  isExcluded?: boolean;
}) {
  const client = useQueryClient();
  const [preview, setPreview] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const query = useQuery({
    queryKey: ["slide-processing", videoId],
    queryFn: ({ signal }) => getSlideState(videoId, signal),
    refetchInterval: (q) => (q.state.data?.requested ? 1000 : false),
  });
  const extraction = useQuery({
    queryKey: ["extraction", videoId],
    queryFn: ({ signal }) => getExtraction(videoId, signal),
  });

  const action = useMutation({
    mutationFn: async (kind: "start" | "retry" | "cancel" | "delete") => {
      if (kind === "delete") return deleteSlides(videoId);
      if (kind === "start") {
        await processSlides(videoId, undefined, !!query.data?.output_directory);
        return;
      }
      await slideAction(videoId, kind);
    },
    onSuccess: () => {
      setConfirmDelete(false);
      void client.invalidateQueries({
        queryKey: ["slide-processing", videoId],
      });
      void client.invalidateQueries({ queryKey: ["slides", videoId] });
    },
  });

  const state = query.data;
  const active = Boolean(state?.requested || state?.status === "processing");
  const ready = extraction.data?.status === "extracted";
  const hasDiagnostics = Boolean(
    state && (state.reconstructed_count > 0 || state.review_count > 0),
  );

  return (
    <div className="min-w-[176px] space-y-1">
      {query.isPending && (
        <span className="text-xs text-muted-foreground">Loading slides…</span>
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
              tone={slideStatusTone[state.status] ?? "neutral"}
            />
            {state.input_count > 0 && (
              <span className="text-[11px] tabular-nums text-muted-foreground">
                In {state.input_count} · +{state.additional_count} · Dup{" "}
                {state.duplicate_count} · Out {state.output_count}
              </span>
            )}
          </div>

          {hasDiagnostics && (
            <div>
              <button
                type="button"
                onClick={() => setDetailsOpen((prev) => !prev)}
                className="inline-flex items-center gap-0.5 text-[11px] text-muted-foreground hover:text-foreground"
              >
                {detailsOpen ? "Hide details" : "Details"}
                {detailsOpen ? (
                  <ChevronUp size={11} aria-hidden="true" />
                ) : (
                  <ChevronDown size={11} aria-hidden="true" />
                )}
              </button>
              {detailsOpen && (
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  Reconstructed: {state.reconstructed_count}
                  {state.review_count > 0 &&
                    ` · Potentially obstructed: ${state.review_count} (retained)`}
                </p>
              )}
            </div>
          )}

          {active && (
            <ProgressIndicator
              value={state.progress}
              ariaLabel="Slide processing progress"
              detail={`${state.completed_count} / ${state.input_count} primary screenshots examined`}
            />
          )}

          {state.error && (
            <p
              role="alert"
              className="max-w-[220px] truncate text-xs text-red-700"
              title={state.error}
            >
              {state.error}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-1">
            {!active && ready && !isExcluded && (
              <ActionButton
                tooltip={
                  state.output_directory ? "Reprocess slides" : "Process slides"
                }
                ariaLabel={
                  state.output_directory ? "Reprocess Slides" : "Process Slides"
                }
                disabled={action.isPending}
                onClick={() => action.mutate("start")}
              >
                {state.output_directory ? (
                  <RotateCw size={12} aria-hidden="true" />
                ) : (
                  <Play size={12} aria-hidden="true" />
                )}
                {state.output_directory ? "Reprocess" : "Process"}
              </ActionButton>
            )}
            {active && (
              <ActionButton
                tooltip="Cancel slide processing"
                ariaLabel="Cancel slides"
                disabled={action.isPending}
                onClick={() => action.mutate("cancel")}
              >
                <XCircle size={12} aria-hidden="true" />
                Cancel
              </ActionButton>
            )}
            {!active &&
              !isExcluded &&
              ["failed", "cancelled"].includes(state.status) && (
                <ActionButton
                  tooltip="Retry slide processing"
                  ariaLabel="Retry slides"
                  disabled={action.isPending}
                  onClick={() => action.mutate("retry")}
                >
                  <RotateCcw size={12} aria-hidden="true" />
                  Retry
                </ActionButton>
              )}
            {state.output_directory && (
              <ActionButton
                tooltip="Preview and compare slides"
                ariaLabel="Compare slides"
                onClick={() => setPreview(true)}
              >
                <Eye size={12} aria-hidden="true" />
                Preview
              </ActionButton>
            )}
            {!active && state.output_directory && (
              <ActionButton
                tooltip="Delete processed slides"
                ariaLabel="Delete processed slides"
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

      <Modal
        open={preview}
        title="Slide comparison"
        size="fullscreen"
        onClose={() => setPreview(false)}
      >
        {preview && <SlidePreview videoId={videoId} />}
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete processed slides"
        description="Delete generated slide comparisons? Original screenshots and source videos are preserved."
        confirmLabel="Confirm delete slides"
        pendingLabel="Deleting…"
        isPending={action.isPending}
        onConfirm={() => action.mutate("delete")}
        onClose={() => setConfirmDelete(false)}
      />
    </div>
  );
}
