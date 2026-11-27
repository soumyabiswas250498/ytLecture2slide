import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import type { Channel } from "@/services/channels";

export function ChannelDeleteModal({
  channel,
  isDeleting,
  error,
  onClose,
  onConfirm,
}: {
  channel: Channel | null;
  isDeleting: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (channelId: number) => Promise<void>;
}) {
  return (
    <Modal
      open={channel !== null}
      title="Delete channel"
      description="Remove this channel from the registry. This action cannot be undone."
      onClose={onClose}
    >
      {channel && (
        <div className="space-y-4">
          {error && (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
            >
              {error}
            </div>
          )}
          <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm">
            <p className="font-semibold">{channel.name}</p>
            <p className="mt-1 break-all text-xs text-muted-foreground">
              {channel.channel_url}
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={isDeleting}
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={isDeleting}
              onClick={() => {
                void onConfirm(channel.id);
              }}
            >
              {isDeleting ? "Deleting…" : "Confirm delete"}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
