import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import type {
  Channel,
  ChannelCreatePayload,
  ChannelUpdatePayload,
} from "@/services/channels";
import {
  validateChannelUrl,
  validateSampleVideoUrl,
  validateYoutubeChannelId,
} from "@/features/channels/channel-validation";

const DEFAULT_KEYWORD = "IDO";

interface ChannelFormModalProps {
  open: boolean;
  channel: Channel | null;
  isSubmitting: boolean;
  serverError: string | null;
  onClose: () => void;
  onCreate: (payload: ChannelCreatePayload) => Promise<void>;
  onUpdate: (channelId: number, payload: ChannelUpdatePayload) => Promise<void>;
}

function ChannelFormBody({
  channel,
  isSubmitting,
  serverError,
  onClose,
  onCreate,
  onUpdate,
}: Omit<ChannelFormModalProps, "open">) {
  const isEdit = channel !== null;
  const [name, setName] = useState(channel?.name ?? "");
  const [channelUrl, setChannelUrl] = useState(channel?.channel_url ?? "");
  const [sampleVideoUrl, setSampleVideoUrl] = useState(
    channel?.sample_video_url ?? "",
  );
  const [searchKeyword, setSearchKeyword] = useState(
    channel?.search_keyword ?? DEFAULT_KEYWORD,
  );
  const [youtubeChannelId, setYoutubeChannelId] = useState(
    channel?.youtube_channel_id ?? "",
  );
  const [isActive, setIsActive] = useState(channel?.is_active ?? true);
  const [validationError, setValidationError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanName = name.trim();
    if (!cleanName) {
      setValidationError("Channel name is required.");
      return;
    }
    const urlError = validateChannelUrl(channelUrl);
    if (urlError) {
      setValidationError(urlError);
      return;
    }
    const sampleError = validateSampleVideoUrl(sampleVideoUrl);
    if (sampleError) {
      setValidationError(sampleError);
      return;
    }
    const ytIdError = validateYoutubeChannelId(youtubeChannelId);
    if (ytIdError) {
      setValidationError(ytIdError);
      return;
    }
    const cleanKeyword = searchKeyword.trim();
    if (isEdit && !cleanKeyword) {
      setValidationError("Search keyword cannot be empty.");
      return;
    }

    setValidationError(null);
    if (isEdit && channel) {
      await onUpdate(channel.id, {
        name: cleanName,
        channel_url: channelUrl.trim(),
        sample_video_url: sampleVideoUrl.trim() || null,
        search_keyword: cleanKeyword,
        youtube_channel_id: youtubeChannelId.trim() || null,
        is_active: isActive,
      });
      return;
    }

    await onCreate({
      name: cleanName,
      channel_url: channelUrl.trim(),
      sample_video_url: sampleVideoUrl.trim() || null,
      search_keyword: cleanKeyword || DEFAULT_KEYWORD,
      youtube_channel_id: youtubeChannelId.trim() || null,
      is_active: isActive,
    });
  }

  const displayedError = validationError ?? serverError;

  return (
    <form
      noValidate
      onSubmit={(event) => {
        void handleSubmit(event);
      }}
      className="space-y-4"
    >
      {displayedError && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          {displayedError}
        </div>
      )}

      <div>
        <label
          htmlFor="channel-name"
          className="mb-1 block text-sm font-medium"
        >
          Channel name
        </label>
        <input
          id="channel-name"
          type="text"
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. WBPSC Study Hub"
          className="w-full rounded-md border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none"
        />
      </div>

      <div>
        <label htmlFor="channel-url" className="mb-1 block text-sm font-medium">
          Channel URL
        </label>
        <input
          id="channel-url"
          type="url"
          required
          value={channelUrl}
          onChange={(event) => setChannelUrl(event.target.value)}
          placeholder="https://www.youtube.com/@channelhandle"
          className="w-full rounded-md border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Supports /@handle, /channel/UC..., /c/name, or /user/name URLs.
        </p>
      </div>

      <div>
        <label
          htmlFor="sample-video-url"
          className="mb-1 block text-sm font-medium"
        >
          Sample video URL{" "}
          <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <input
          id="sample-video-url"
          type="url"
          value={sampleVideoUrl}
          onChange={(event) => setSampleVideoUrl(event.target.value)}
          placeholder="https://www.youtube.com/watch?v=..."
          className="w-full rounded-md border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none"
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label
            htmlFor="search-keyword"
            className="mb-1 block text-sm font-medium"
          >
            Search keyword
          </label>
          <input
            id="search-keyword"
            type="text"
            value={searchKeyword}
            onChange={(event) => setSearchKeyword(event.target.value)}
            placeholder="IDO"
            className="w-full rounded-md border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none"
          />
        </div>

        <div>
          <label
            htmlFor="youtube-channel-id"
            className="mb-1 block text-sm font-medium"
          >
            YouTube channel ID{" "}
            <span className="font-normal text-muted-foreground">
              (optional)
            </span>
          </label>
          <input
            id="youtube-channel-id"
            type="text"
            value={youtubeChannelId}
            onChange={(event) => setYoutubeChannelId(event.target.value)}
            placeholder="UC..."
            className="w-full rounded-md border border-border px-3 py-2 text-sm focus:border-primary focus:outline-none"
          />
        </div>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={isActive}
          onChange={(event) => setIsActive(event.target.checked)}
          className="h-4 w-4 rounded border-border accent-primary"
        />
        Active channel (included in scheduled discovery)
      </label>

      <div className="flex justify-end gap-2 pt-2">
        <Button
          type="button"
          variant="outline"
          disabled={isSubmitting}
          onClick={onClose}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting
            ? isEdit
              ? "Saving…"
              : "Adding…"
            : isEdit
              ? "Save changes"
              : "Add channel"}
        </Button>
      </div>
    </form>
  );
}

export function ChannelFormModal({
  open,
  channel,
  isSubmitting,
  serverError,
  onClose,
  onCreate,
  onUpdate,
}: ChannelFormModalProps) {
  const isEdit = channel !== null;
  return (
    <Modal
      open={open}
      title={isEdit ? "Edit channel" : "Add channel"}
      description="Register a YouTube channel for future video discovery. External YouTube lookups are not performed here."
      onClose={onClose}
    >
      {open && (
        <ChannelFormBody
          key={channel?.id ?? "new"}
          channel={channel}
          isSubmitting={isSubmitting}
          serverError={serverError}
          onClose={onClose}
          onCreate={onCreate}
          onUpdate={onUpdate}
        />
      )}
    </Modal>
  );
}
