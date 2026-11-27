import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import {
  deleteSlides,
  getSlideState,
  processSelected,
  processSlides,
  slideAction,
  type Crop,
} from "@/services/slides";
import { frameUrl, getExtraction, getFrames } from "@/services/extractions";
import { SlidePreview } from "./slide-preview";

export function SlideToolbar({ selectedIds }: { selectedIds: number[] }) {
  const client = useQueryClient();
  const bulk = useMutation({
    mutationFn: () => processSelected(selectedIds),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["slide-processing"] });
    },
  });
  return (
    <div className="space-y-2">
      <Button
        variant="outline"
        disabled={!selectedIds.length || bulk.isPending}
        onClick={() => bulk.mutate()}
      >
        Process selected slides
      </Button>
      {bulk.isError && <p role="alert">{bulk.error.message}</p>}
      {bulk.data && (
        <div role="status">
          {bulk.data.started_ids.length} slide jobs queued
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

export function SlideControls({ videoId }: { videoId: number }) {
  const client = useQueryClient();
  const [preview, setPreview] = useState(false);
  const [adjust, setAdjust] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [crop, setCrop] = useState<Crop>({
    left: 0,
    top: 0,
    right: 1,
    bottom: 1,
  });
  const query = useQuery({
    queryKey: ["slide-processing", videoId],
    queryFn: ({ signal }) => getSlideState(videoId, signal),
    refetchInterval: (query) => (query.state.data?.requested ? 1000 : false),
  });
  const extraction = useQuery({
    queryKey: ["extraction", videoId],
    queryFn: ({ signal }) => getExtraction(videoId, signal),
  });
  const cropPreview = useQuery({
    queryKey: ["frames", videoId, 1],
    queryFn: ({ signal }) => getFrames(videoId, 1, signal),
    enabled: adjust,
  });
  const action = useMutation({
    mutationFn: async (
      kind: "start" | "retry" | "cancel" | "crop" | "delete",
    ) => {
      if (kind === "delete") return deleteSlides(videoId);
      if (kind === "start" || kind === "crop") {
        await processSlides(
          videoId,
          kind === "crop" ? crop : undefined,
          !!query.data?.output_directory,
        );
        return;
      }
      await slideAction(videoId, kind);
    },
    onSuccess: () => {
      setAdjust(false);
      setConfirmDelete(false);
      void client.invalidateQueries({
        queryKey: ["slide-processing", videoId],
      });
      void client.invalidateQueries({ queryKey: ["slides", videoId] });
    },
  });
  const state = query.data;
  const active = state?.requested || state?.status === "processing";
  const ready = extraction.data?.status === "extracted";
  const validCrop =
    Object.values(crop).every(Number.isFinite) &&
    crop.left >= 0 &&
    crop.top >= 0 &&
    crop.right <= 1 &&
    crop.bottom <= 1 &&
    crop.left < crop.right &&
    crop.top < crop.bottom;
  return (
    <div className="min-w-52 space-y-2">
      {query.isPending && <p>Loading slides…</p>}
      {query.isError && <p role="alert">{query.error.message}</p>}
      {state && (
        <>
          <p>Slides: {state.status}</p>
          <p>
            Input: {state.input_count} · Additional: {state.additional_count} ·
            Output: {state.output_count}
          </p>
          <p>
            Duplicates: {state.duplicate_count} · Reconstructed:{" "}
            {state.reconstructed_count} · Review: {state.review_count}
          </p>
          {active && (
            <>
              <progress
                aria-label="Slide processing progress"
                value={state.progress}
                max={100}
              />
              <p>
                {state.completed_count} / {state.input_count} primary
                screenshots examined
              </p>
            </>
          )}
          {state.error && <p role="alert">{state.error}</p>}
          <div className="flex flex-wrap gap-2">
            {!active && ready && (
              <Button
                size="sm"
                variant="outline"
                disabled={action.isPending}
                onClick={() => action.mutate("start")}
              >
                {state.output_directory ? "Reprocess Slides" : "Process Slides"}
              </Button>
            )}
            {active && (
              <Button
                size="sm"
                variant="outline"
                disabled={action.isPending}
                onClick={() => action.mutate("cancel")}
              >
                Cancel slides
              </Button>
            )}
            {!active && ["failed", "cancelled"].includes(state.status) && (
              <Button
                size="sm"
                variant="outline"
                disabled={action.isPending}
                onClick={() => action.mutate("retry")}
              >
                Retry slides
              </Button>
            )}
            {state.output_directory && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setPreview(true)}
              >
                Compare slides
              </Button>
            )}
            {!active && ready && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setAdjust(true)}
              >
                Adjust board crop
              </Button>
            )}
            {!active && state.output_directory && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setConfirmDelete(true)}
              >
                Delete processed slides
              </Button>
            )}
          </div>
        </>
      )}
      {action.isError && <p role="alert">{action.error.message}</p>}
      <Modal
        open={preview}
        title="Slide comparison"
        onClose={() => setPreview(false)}
      >
        {preview && <SlidePreview videoId={videoId} />}
      </Modal>
      <Modal
        open={adjust}
        title="Adjust board crop"
        onClose={() => setAdjust(false)}
      >
        <p>
          Normalized coordinates from 0 to 1. Reprocessing preserves the
          previous successful generation until the replacement succeeds. Preview
          the current originals under Compare slides.
        </p>
        {cropPreview.data?.items[0] && (
          <div className="relative my-3">
            <img
              src={frameUrl(videoId, cropPreview.data.items[0].filename)}
              alt="First source screenshot for crop adjustment"
              className="w-full"
            />
            {validCrop && (
              <div
                aria-label="Selected board crop"
                className="pointer-events-none absolute border-2 border-red-500"
                style={{
                  left: `${crop.left * 100}%`,
                  top: `${crop.top * 100}%`,
                  width: `${(crop.right - crop.left) * 100}%`,
                  height: `${(crop.bottom - crop.top) * 100}%`,
                }}
              />
            )}
          </div>
        )}
        {(["left", "top", "right", "bottom"] as const).map((key) => (
          <label key={key} className="m-2 block">
            {key}
            <input
              aria-label={`Crop ${key}`}
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={crop[key]}
              onChange={(e) =>
                setCrop({ ...crop, [key]: Number(e.target.value) })
              }
              className="ml-2 rounded border p-2"
            />
          </label>
        ))}
        {!validCrop && (
          <p role="alert">Choose a positive rectangle within the image.</p>
        )}
        <Button
          disabled={!validCrop || action.isPending}
          onClick={() => action.mutate("crop")}
        >
          Apply crop and reprocess
        </Button>
      </Modal>
      <Modal
        open={confirmDelete}
        title="Delete processed slides"
        onClose={() => setConfirmDelete(false)}
      >
        <p>
          Remove processed generations? Source video and original extracted
          screenshots remain available.
        </p>
        <Button
          variant="destructive"
          disabled={action.isPending}
          onClick={() => action.mutate("delete")}
        >
          Confirm delete processed slides
        </Button>
      </Modal>
    </div>
  );
}
