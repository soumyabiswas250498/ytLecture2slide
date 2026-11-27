import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Play, RotateCcw, RotateCw, Trash2, XCircle } from "lucide-react";
import { ActionButton } from "@/components/shared/action-button";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DetailsPopover } from "@/components/shared/details-popover";
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
  cleaned: "neutral",
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
  const hasDetails = Boolean(
    state &&
    (state.input_count > 0 ||
      state.output_directory ||
      state.reconstructed_count > 0 ||
      state.review_count > 0),
  );

  return (
    <div className="min-w-[140px] space-y-1">
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
            {(state.output_count > 0 || state.status === "processed") && (
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {state.output_count}{" "}
                {state.output_count === 1 ? "slide" : "slides"}
              </span>
            )}
          </div>

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
              className="max-w-[200px] truncate text-xs text-red-700"
              title={state.error}
            >
              {state.error}
            </p>
          )}

          <div className="flex flex-nowrap items-center gap-1">
            {hasDetails && (
              <DetailsPopover
                title="Slide processing"
                ariaLabel="View slide processing details"
                items={[
                  { label: "Input frames", value: state.input_count },
                  { label: "Additional frames", value: state.additional_count },
                  {
                    label: "Confirmed duplicates excluded",
                    value: state.duplicate_count,
                  },
                  { label: "Output slides", value: state.output_count },
                  {
                    label: "Reconstructed slides",
                    value: state.reconstructed_count,
                  },
                  {
                    label: "Potentially obstructed slides",
                    value: state.review_count,
                  },
                ]}
                warnings={
                  state.review_count > 0
                    ? [
                        `${state.review_count} potentially obstructed ${state.review_count === 1 ? "slide" : "slides"} retained for manual review.`,
                      ]
                    : []
                }
              />
            )}
            {!active && ready && !isExcluded && (
              <ActionButton
                size="icon"
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
                  <RotateCw size={14} aria-hidden="true" />
                ) : (
                  <Play size={14} aria-hidden="true" />
                )}
              </ActionButton>
            )}
            {active && (
              <ActionButton
                size="icon"
                tooltip="Cancel slide processing"
                ariaLabel="Cancel slides"
                disabled={action.isPending}
                onClick={() => action.mutate("cancel")}
              >
                <XCircle size={14} aria-hidden="true" />
              </ActionButton>
            )}
            {!active &&
              !isExcluded &&
              ["failed", "cancelled"].includes(state.status) && (
                <ActionButton
                  size="icon"
                  tooltip="Retry slide processing"
                  ariaLabel="Retry slides"
                  disabled={action.isPending}
                  onClick={() => action.mutate("retry")}
                >
                  <RotateCcw size={14} aria-hidden="true" />
                </ActionButton>
              )}
            {state.output_directory && (
              <ActionButton
                size="icon"
                tooltip="Preview and compare slides"
                ariaLabel="Compare slides"
                onClick={() => setPreview(true)}
              >
                <Eye size={14} aria-hidden="true" />
              </ActionButton>
            )}
            {!active && state.output_directory && (
              <ActionButton
                size="icon"
                tooltip="Delete processed slides"
                ariaLabel="Delete processed slides"
                className="text-red-700 hover:bg-red-50"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 size={14} aria-hidden="true" />
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
