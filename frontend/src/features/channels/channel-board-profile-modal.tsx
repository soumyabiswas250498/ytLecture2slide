import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import {
  deleteBoardProfile,
  getBoardProfile,
  upsertBoardProfile,
  type Channel,
} from "@/services/channels";

interface ChannelBoardProfileModalProps {
  channel: Channel | null;
  onClose: () => void;
}

const DEFAULT_CROP = { left: 0, top: 0, right: 1, bottom: 1 };

export function ChannelBoardProfileModal({
  channel,
  onClose,
}: ChannelBoardProfileModalProps) {
  const client = useQueryClient();
  const [draftCrop, setDraftCrop] = useState<typeof DEFAULT_CROP | null>(null);
  const [error, setError] = useState<string | null>(null);

  const profileQuery = useQuery({
    queryKey: ["board-profile", channel?.id],
    queryFn: ({ signal }) => getBoardProfile(channel!.id, signal),
    enabled: channel !== null,
  });

  const crop = draftCrop ?? profileQuery.data?.crop ?? DEFAULT_CROP;

  const handleClose = () => {
    setDraftCrop(null);
    setError(null);
    onClose();
  };

  const saveMutation = useMutation({
    mutationFn: () => upsertBoardProfile(channel!.id, crop),
    onSuccess: () => {
      void client.invalidateQueries({
        queryKey: ["board-profile", channel?.id],
      });
      handleClose();
    },
    onError: (err: Error) => setError(err.message),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteBoardProfile(channel!.id),
    onSuccess: () => {
      void client.invalidateQueries({
        queryKey: ["board-profile", channel?.id],
      });
      handleClose();
    },
    onError: (err: Error) => setError(err.message),
  });

  const valid =
    Object.values(crop).every(Number.isFinite) &&
    crop.left >= 0 &&
    crop.top >= 0 &&
    crop.right <= 1 &&
    crop.bottom <= 1 &&
    crop.left < crop.right &&
    crop.top < crop.bottom;

  return (
    <Modal
      open={channel !== null}
      title={channel ? `Board crop profile — ${channel.name}` : "Board crop"}
      onClose={handleClose}
    >
      <div className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          Normalized smartboard coordinates (0 to 1) are reused automatically
          for videos in this channel.
        </p>
        {profileQuery.isPending && <p>Loading saved profile…</p>}
        {profileQuery.isError && (
          <p role="alert" className="text-red-700">
            {profileQuery.error.message}
          </p>
        )}
        {!profileQuery.isPending && (
          <p className="text-xs text-muted-foreground">
            {profileQuery.data
              ? "Saved channel profile active."
              : "No saved profile yet (defaults to full frame / auto-detection)."}
          </p>
        )}
        <div className="grid grid-cols-2 gap-3">
          {(["left", "top", "right", "bottom"] as const).map((key) => (
            <label key={key} className="block font-medium">
              <span className="capitalize">{key}</span>
              <input
                aria-label={`Profile crop ${key}`}
                type="number"
                min={0}
                max={1}
                step={0.005}
                value={crop[key]}
                onChange={(e) =>
                  setDraftCrop({ ...crop, [key]: Number(e.target.value) })
                }
                className="mt-1 w-full rounded-md border border-border px-2.5 py-1.5"
              />
            </label>
          ))}
        </div>
        {!valid && (
          <p role="alert" className="text-red-700">
            Coordinates must satisfy 0 ≤ left &lt; right ≤ 1 and 0 ≤ top &lt;
            bottom ≤ 1.
          </p>
        )}
        {error && (
          <p role="alert" className="text-red-700">
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2 pt-2">
          {profileQuery.data && (
            <Button
              type="button"
              variant="outline"
              disabled={deleteMutation.isPending || saveMutation.isPending}
              onClick={() => deleteMutation.mutate()}
              className="text-red-700 hover:bg-red-50"
            >
              Delete profile
            </Button>
          )}
          <Button type="button" variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={
              !valid || saveMutation.isPending || deleteMutation.isPending
            }
            onClick={() => saveMutation.mutate()}
          >
            Save profile
          </Button>
        </div>
      </div>
    </Modal>
  );
}
