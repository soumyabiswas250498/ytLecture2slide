import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import {
  deleteFrames,
  extractSelected,
  extractionAction,
  getExtraction,
  getExtractionConfig,
  startExtraction,
} from "@/services/extractions";
import { FramePreview } from "./frame-preview";

export function ExtractionToolbar({
  selectedIds,
  interval,
  setInterval,
}: {
  selectedIds: number[];
  interval: number | undefined;
  setInterval: (value: number) => void;
}) {
  const client = useQueryClient();
  const config = useQuery({
    queryKey: ["extraction-config"],
    queryFn: ({ signal }) => getExtractionConfig(signal),
  });
  const bulk = useMutation({
    mutationFn: () => extractSelected(selectedIds, interval),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["extraction"] });
    },
  });
  return (
    <div className="flex flex-wrap items-center gap-3 rounded border p-3">
      <label>
        Screenshot interval (seconds){" "}
        <input
          type="number"
          min="0.001"
          step="any"
          aria-label="Screenshot interval (seconds)"
          value={interval ?? config.data?.interval_seconds ?? ""}
          onChange={(e) => setInterval(Number(e.target.value))}
          className="w-24 rounded border p-2"
        />
      </label>
      <Button
        variant="outline"
        disabled={
          !selectedIds.length ||
          bulk.isPending ||
          (interval !== undefined &&
            (!Number.isFinite(interval) || interval < 0.001))
        }
        onClick={() => bulk.mutate()}
      >
        Extract selected frames
      </Button>
      {bulk.isError && <p role="alert">{bulk.error.message}</p>}
      {config.isError && <p role="alert">{config.error.message}</p>}
      {bulk.data && (
        <div role="status">
          {bulk.data.started_ids.length} extraction jobs queued
          {bulk.data.errors.map((item) => (
            <p key={item.video_id}>
              Video #{item.video_id}: {item.reason}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export function ExtractionControls({
  videoId,
  downloaded,
  interval,
}: {
  videoId: number;
  downloaded: boolean;
  interval?: number;
}) {
  const client = useQueryClient();
  const [preview, setPreview] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const query = useQuery({
    queryKey: ["extraction", videoId],
    queryFn: ({ signal }) => getExtraction(videoId, signal),
    refetchInterval: (query) => (query.state.data?.requested ? 1000 : false),
  });
  const action = useMutation({
    mutationFn: (action: "start" | "cancel" | "retry" | "delete") => {
      if (action === "delete") return deleteFrames(videoId);
      if (action === "start")
        return startExtraction(videoId, interval).then(() => undefined);
      return extractionAction(videoId, action).then(() => undefined);
    },
    onSuccess: () => {
      setConfirmDelete(false);
      void client.invalidateQueries({ queryKey: ["extraction", videoId] });
      void client.invalidateQueries({ queryKey: ["frames", videoId] });
    },
  });
  const state = query.data;
  const active = state?.requested || state?.status === "extracting";
  return (
    <div className="min-w-48 space-y-2">
      {query.isPending && <p>Loading extraction…</p>}
      {query.isError && <p role="alert">{query.error.message}</p>}
      {state && (
        <>
          <p className="capitalize">Frames: {state.status}</p>
          <p>
            {state.frame_count} / {state.expected_count ?? "unknown"} frames
          </p>
          {active && (
            <progress
              aria-label="Frame extraction progress"
              value={state.progress}
              max={100}
            />
          )}
          {state.error && <p role="alert">{state.error}</p>}
          <div className="flex flex-wrap gap-2">
            {downloaded && !active && state.status === "pending" && (
              <Button
                size="sm"
                variant="outline"
                disabled={
                  action.isPending ||
                  (interval !== undefined && interval < 0.001)
                }
                onClick={() => action.mutate("start")}
              >
                Extract Frames
              </Button>
            )}
            {active && (
              <Button
                size="sm"
                variant="outline"
                disabled={action.isPending}
                onClick={() => action.mutate("cancel")}
              >
                Cancel extraction
              </Button>
            )}
            {downloaded &&
              !active &&
              ["failed", "cancelled"].includes(state.status) && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={action.isPending}
                  onClick={() => action.mutate("retry")}
                >
                  Retry extraction
                </Button>
              )}
            {state.manifest_path && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setPreview(true)}
              >
                Preview frames
              </Button>
            )}
            {!active && state.status !== "pending" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setConfirmDelete(true)}
              >
                Delete frames
              </Button>
            )}
          </div>
        </>
      )}
      {action.isError && <p role="alert">{action.error.message}</p>}
      <Modal
        open={preview}
        title="Extracted frames"
        onClose={() => setPreview(false)}
      >
        {preview && <FramePreview videoId={videoId} />}
      </Modal>
      <Modal
        open={confirmDelete}
        title="Delete extracted frames"
        description="Delete screenshots and extraction metadata? The downloaded source video is preserved."
        onClose={() => setConfirmDelete(false)}
      >
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setConfirmDelete(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={action.isPending}
            onClick={() => action.mutate("delete")}
          >
            Confirm delete frames
          </Button>
        </div>
      </Modal>
    </div>
  );
}
