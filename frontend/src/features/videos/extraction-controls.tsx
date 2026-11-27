import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Film, RotateCcw, Trash2, XCircle } from "lucide-react";
import { ActionButton } from "@/components/shared/action-button";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DetailsPopover } from "@/components/shared/details-popover";
import { ProgressIndicator } from "@/components/shared/progress-indicator";
import { StatusBadge, type StatusTone } from "@/components/shared/status-badge";
import { Modal } from "@/components/ui/modal";
import { formatISTDateTime } from "@/lib/utils";
import {
  deleteFrames,
  extractionAction,
  getExtraction,
  startExtraction,
} from "@/services/extractions";
import { FramePreview } from "./frame-preview";

const extractionTone: Record<string, StatusTone> = {
  pending: "neutral",
  extracting: "info",
  extracted: "success",
  failed: "error",
  cancelled: "warning",
  cleaned: "neutral",
};

export function ExtractionControls({
  videoId,
  downloaded,
  interval,
  isExcluded = false,
}: {
  videoId: number;
  downloaded: boolean;
  interval?: number;
  isExcluded?: boolean;
}) {
  const client = useQueryClient();
  const [preview, setPreview] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const query = useQuery({
    queryKey: ["extraction", videoId],
    queryFn: ({ signal }) => getExtraction(videoId, signal),
    refetchInterval: (q) => (q.state.data?.requested ? 1000 : false),
  });

  const action = useMutation({
    mutationFn: (kind: "start" | "cancel" | "retry" | "delete") => {
      if (kind === "delete") return deleteFrames(videoId);
      if (kind === "start")
        return startExtraction(videoId, interval).then(() => undefined);
      return extractionAction(videoId, kind).then(() => undefined);
    },
    onSuccess: () => {
      setConfirmDelete(false);
      void client.invalidateQueries({ queryKey: ["extraction", videoId] });
      void client.invalidateQueries({ queryKey: ["frames", videoId] });
    },
  });

  const state = query.data;
  const active = Boolean(state?.requested || state?.status === "extracting");

  return (
    <div className="min-w-[136px] space-y-1">
      {query.isPending && (
        <span className="text-xs text-muted-foreground">
          Loading extraction…
        </span>
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
              tone={extractionTone[state.status] ?? "neutral"}
            />
            {state.frame_count > 0 || state.expected_count ? (
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {state.frame_count} / {state.expected_count ?? "?"}
              </span>
            ) : null}
          </div>

          {active && (
            <ProgressIndicator
              value={state.progress}
              ariaLabel="Frame extraction progress"
            />
          )}

          {state.error && (
            <p
              role="alert"
              className="max-w-[180px] truncate text-xs text-red-700"
              title={state.error}
            >
              {state.error}
            </p>
          )}

          <div className="flex flex-nowrap items-center gap-1">
            {(state.status !== "pending" ||
              state.frame_count > 0 ||
              state.expected_count !== null) && (
              <DetailsPopover
                title="Frame extraction"
                ariaLabel="View frame extraction details"
                items={[
                  { label: "Interval", value: `${state.interval_seconds}s` },
                  { label: "Extracted frames", value: state.frame_count },
                  { label: "Expected frames", value: state.expected_count },
                  {
                    label: "Retries",
                    value: state.retry_count > 0 ? state.retry_count : null,
                  },
                  {
                    label: "Started",
                    value: state.started_at
                      ? formatISTDateTime(state.started_at)
                      : null,
                  },
                  {
                    label: "Completed",
                    value: state.completed_at
                      ? formatISTDateTime(state.completed_at)
                      : null,
                  },
                ]}
              />
            )}
            {downloaded &&
              !active &&
              !isExcluded &&
              state.status === "pending" && (
                <ActionButton
                  size="icon"
                  tooltip="Extract frames"
                  ariaLabel="Extract Frames"
                  disabled={
                    action.isPending ||
                    (interval !== undefined && interval < 0.001)
                  }
                  onClick={() => action.mutate("start")}
                >
                  <Film size={14} aria-hidden="true" />
                </ActionButton>
              )}
            {active && (
              <ActionButton
                size="icon"
                tooltip="Cancel frame extraction"
                ariaLabel="Cancel extraction"
                disabled={action.isPending}
                onClick={() => action.mutate("cancel")}
              >
                <XCircle size={14} aria-hidden="true" />
              </ActionButton>
            )}
            {downloaded &&
              !active &&
              !isExcluded &&
              ["failed", "cancelled"].includes(state.status) && (
                <ActionButton
                  size="icon"
                  tooltip="Retry frame extraction"
                  ariaLabel="Retry extraction"
                  disabled={action.isPending}
                  onClick={() => action.mutate("retry")}
                >
                  <RotateCcw size={14} aria-hidden="true" />
                </ActionButton>
              )}
            {state.manifest_path && (
              <ActionButton
                size="icon"
                tooltip="Preview extracted frames"
                ariaLabel="Preview frames"
                onClick={() => setPreview(true)}
              >
                <Eye size={14} aria-hidden="true" />
              </ActionButton>
            )}
            {!active && state.status !== "pending" && (
              <ActionButton
                size="icon"
                tooltip="Delete extracted frames"
                ariaLabel="Delete frames"
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
        title="Extracted frames"
        size="xl"
        onClose={() => setPreview(false)}
      >
        {preview && <FramePreview videoId={videoId} />}
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete extracted frames"
        description="Delete screenshots and extraction metadata? The downloaded source video is preserved."
        confirmLabel="Confirm delete frames"
        pendingLabel="Deleting…"
        isPending={action.isPending}
        onConfirm={() => action.mutate("delete")}
        onClose={() => setConfirmDelete(false)}
      />
    </div>
  );
}
