import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  ExternalLink,
  FileSpreadsheet,
  Pencil,
  Plus,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { ChannelBoardProfileModal } from "@/features/channels/channel-board-profile-modal";
import { ChannelDeleteModal } from "@/features/channels/channel-delete-modal";
import { ChannelFormModal } from "@/features/channels/channel-form-modal";
import { ChannelImportModal } from "@/features/channels/channel-import-modal";
import { ApiError } from "@/services/api";
import {
  createChannel,
  deleteChannel,
  downloadChannelsTemplate,
  exportChannelsCsv,
  importChannelsCsv,
  listChannels,
  updateChannel,
  type Channel,
  type ChannelCreatePayload,
  type ChannelUpdatePayload,
  type CsvImportResponse,
} from "@/services/channels";

type StatusFilter = "all" | "active" | "inactive";
const PAGE_SIZE = 10;

function triggerCsvDownload(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

export function ChannelsPage() {
  const queryClient = useQueryClient();

  const [searchInput, setSearchInput] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(1);
  const [profileChannel, setProfileChannel] = useState<Channel | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editingChannel, setEditingChannel] = useState<Channel | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const [deletingChannel, setDeletingChannel] = useState<Channel | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const [importOpen, setImportOpen] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<CsvImportResponse | null>(
    null,
  );

  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const isActiveParam =
    statusFilter === "all" ? null : statusFilter === "active";

  const channelsQuery = useQuery({
    queryKey: [
      "channels",
      { search: searchInput.trim(), isActive: isActiveParam, page },
    ],
    queryFn: ({ signal }) =>
      listChannels(
        {
          search: searchInput.trim(),
          isActive: isActiveParam,
          page,
          pageSize: PAGE_SIZE,
        },
        signal,
      ),
  });

  const invalidateChannels = () =>
    queryClient.invalidateQueries({ queryKey: ["channels"] });

  const createMutation = useMutation({
    mutationFn: (payload: ChannelCreatePayload) => createChannel(payload),
    onSuccess: async (created) => {
      await invalidateChannels();
      setFormOpen(false);
      setEditingChannel(null);
      setFormError(null);
      setPage(1);
      setFeedback({
        type: "success",
        message: `Added channel "${created.name}".`,
      });
    },
    onError: (error) => {
      setFormError(getErrorMessage(error));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({
      channelId,
      payload,
    }: {
      channelId: number;
      payload: ChannelUpdatePayload;
    }) => updateChannel(channelId, payload),
    onSuccess: async (updated) => {
      await invalidateChannels();
      setFormOpen(false);
      setEditingChannel(null);
      setFormError(null);
      setFeedback({
        type: "success",
        message: `Updated channel "${updated.name}".`,
      });
    },
    onError: (error) => {
      setFormError(getErrorMessage(error));
    },
  });

  const toggleStatusMutation = useMutation({
    mutationFn: ({
      channelId,
      isActive,
    }: {
      channelId: number;
      isActive: boolean;
    }) => updateChannel(channelId, { is_active: isActive }),
    onSuccess: async (updated) => {
      await invalidateChannels();
      setFeedback({
        type: "success",
        message: `Channel "${updated.name}" is now ${updated.is_active ? "active" : "inactive"}.`,
      });
    },
    onError: (error) => {
      setFeedback({ type: "error", message: getErrorMessage(error) });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (channelId: number) => deleteChannel(channelId),
    onSuccess: async () => {
      const deletedName = deletingChannel?.name ?? "Channel";
      const remainingOnPage = (channelsQuery.data?.items.length ?? 1) - 1;
      if (remainingOnPage === 0 && page > 1) {
        setPage((prev) => Math.max(1, prev - 1));
      }
      await invalidateChannels();
      setDeletingChannel(null);
      setDeleteError(null);
      setFeedback({
        type: "success",
        message: `Deleted channel "${deletedName}".`,
      });
    },
    onError: (error) => {
      setDeleteError(getErrorMessage(error));
    },
  });

  const importMutation = useMutation({
    mutationFn: (file: File) => importChannelsCsv(file),
    onSuccess: async (summary) => {
      await invalidateChannels();
      setImportError(null);
      setImportResult(summary);
      setPage(1);
      setFeedback({
        type: "success",
        message: `CSV import finished: ${summary.imported_count} imported, ${summary.skipped_count} skipped, ${summary.invalid_count} invalid.`,
      });
    },
    onError: (error) => {
      setImportResult(null);
      setImportError(getErrorMessage(error));
    },
  });

  async function handleExportCsv() {
    setIsExporting(true);
    try {
      const content = await exportChannelsCsv({
        search: searchInput.trim(),
        isActive: isActiveParam,
      });
      triggerCsvDownload("channels.csv", content);
      setFeedback({ type: "success", message: "Exported channels CSV." });
    } catch (error) {
      setFeedback({ type: "error", message: getErrorMessage(error) });
    } finally {
      setIsExporting(false);
    }
  }

  async function handleDownloadTemplate() {
    try {
      const content = await downloadChannelsTemplate();
      triggerCsvDownload("channels-template.csv", content);
    } catch (error) {
      setFeedback({ type: "error", message: getErrorMessage(error) });
    }
  }

  const summary = channelsQuery.data?.summary ?? {
    total: 0,
    active: 0,
    inactive: 0,
  };
  const items = channelsQuery.data?.items ?? [];
  const hasFilters = Boolean(searchInput.trim()) || statusFilter !== "all";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">CHANNEL REGISTRY</p>
          <h1>Channels</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Register YouTube channels, configure search keywords, and manage
            active discovery targets.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              void handleDownloadTemplate();
            }}
          >
            <FileSpreadsheet size={16} aria-hidden="true" />
            Download CSV template
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isExporting || summary.total === 0}
            onClick={() => {
              void handleExportCsv();
            }}
          >
            <Download size={16} aria-hidden="true" />
            {isExporting ? "Exporting…" : "Export CSV"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setImportError(null);
              setImportResult(null);
              setImportOpen(true);
            }}
          >
            <Upload size={16} aria-hidden="true" />
            Import CSV
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={() => {
              setEditingChannel(null);
              setFormError(null);
              setFormOpen(true);
            }}
          >
            <Plus size={16} aria-hidden="true" />
            Add channel
          </Button>
        </div>
      </div>

      <section
        aria-label="Channel summary"
        className="grid gap-4 sm:grid-cols-3"
      >
        <div className="rounded-xl border border-border bg-white p-5">
          <p className="eyebrow">TOTAL CHANNELS</p>
          <p className="mt-2 text-3xl font-semibold">{summary.total}</p>
        </div>
        <div className="rounded-xl border border-border bg-white p-5">
          <p className="eyebrow">ACTIVE CHANNELS</p>
          <p className="mt-2 text-3xl font-semibold text-emerald-700">
            {summary.active}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-white p-5">
          <p className="eyebrow">INACTIVE CHANNELS</p>
          <p className="mt-2 text-3xl font-semibold text-muted-foreground">
            {summary.inactive}
          </p>
        </div>
      </section>

      {feedback && (
        <div
          role={feedback.type === "error" ? "alert" : "status"}
          className={`flex items-center justify-between gap-4 rounded-xl border px-4 py-3 text-sm ${
            feedback.type === "error"
              ? "border-red-200 bg-red-50 text-red-800"
              : "border-emerald-200 bg-emerald-50 text-emerald-900"
          }`}
        >
          <span>{feedback.message}</span>
          <button
            type="button"
            onClick={() => setFeedback(null)}
            className="text-xs font-semibold underline"
          >
            Dismiss
          </button>
        </div>
      )}

      <section className="rounded-xl border border-border bg-white p-5">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[220px] flex-1">
            <label htmlFor="channel-search" className="sr-only">
              Search channels by name or keyword
            </label>
            <Search
              size={16}
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground"
            />
            <input
              id="channel-search"
              type="search"
              value={searchInput}
              onChange={(event) => {
                setSearchInput(event.target.value);
                setPage(1);
              }}
              placeholder="Search by channel name or keyword…"
              className="w-full rounded-md border border-border py-2 pr-3 pl-9 text-sm focus:border-primary focus:outline-none"
            />
          </div>

          <div className="flex items-center gap-2">
            <label htmlFor="status-filter" className="text-sm font-medium">
              Status
            </label>
            <select
              id="status-filter"
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value as StatusFilter);
                setPage(1);
              }}
              className="rounded-md border border-border bg-white px-3 py-2 text-sm focus:border-primary focus:outline-none"
            >
              <option value="all">All</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>

          {hasFilters && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setSearchInput("");
                setStatusFilter("all");
                setPage(1);
              }}
            >
              Clear filters
            </Button>
          )}
        </div>

        <div className="mt-5">
          {channelsQuery.isPending ? (
            <LoadingState message="Loading channels…" />
          ) : channelsQuery.isError ? (
            <ErrorState
              message={channelsQuery.error.message}
              onRetry={() => {
                void channelsQuery.refetch();
              }}
            />
          ) : items.length === 0 ? (
            <EmptyState
              title={
                hasFilters
                  ? "No channels match your filters"
                  : "No channels registered yet"
              }
              description={
                hasFilters
                  ? "Try adjusting your search query or status filter."
                  : "Add a YouTube channel or import an existing CSV list to get started."
              }
            />
          ) : (
            <div className="space-y-4">
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs text-muted-foreground uppercase">
                      <th className="py-3 pr-4 font-semibold">Channel name</th>
                      <th className="py-3 pr-4 font-semibold">Channel URL</th>
                      <th className="py-3 pr-4 font-semibold">Sample video</th>
                      <th className="py-3 pr-4 font-semibold">
                        Search keyword
                      </th>
                      <th className="py-3 pr-4 font-semibold">Status</th>
                      <th className="py-3 text-right font-semibold">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {items.map((channel) => (
                      <tr key={channel.id} className="align-top">
                        <td className="py-3.5 pr-4">
                          <div className="font-medium text-foreground">
                            {channel.name}
                          </div>
                          {channel.youtube_channel_id && (
                            <div className="mt-0.5 font-mono text-xs text-muted-foreground">
                              {channel.youtube_channel_id}
                            </div>
                          )}
                        </td>
                        <td className="py-3.5 pr-4">
                          <a
                            href={channel.channel_url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="inline-flex items-center gap-1 break-all text-primary underline-offset-2 hover:underline"
                          >
                            <span>{channel.channel_url}</span>
                            <ExternalLink
                              size={13}
                              aria-hidden="true"
                              className="shrink-0"
                            />
                          </a>
                        </td>
                        <td className="py-3.5 pr-4">
                          {channel.sample_video_url ? (
                            <a
                              href={channel.sample_video_url}
                              target="_blank"
                              rel="noreferrer noopener"
                              className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
                            >
                              <span>Sample video</span>
                              <ExternalLink size={13} aria-hidden="true" />
                            </a>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="py-3.5 pr-4">
                          <span className="inline-block rounded-md bg-muted px-2 py-0.5 text-xs font-medium">
                            {channel.search_keyword}
                          </span>
                        </td>
                        <td className="py-3.5 pr-4">
                          <span
                            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                              channel.is_active
                                ? "bg-emerald-100 text-emerald-800"
                                : "bg-stone-200 text-stone-700"
                            }`}
                          >
                            {channel.is_active ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td className="py-3.5 text-right">
                          <div className="inline-flex flex-wrap justify-end gap-1.5">
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={toggleStatusMutation.isPending}
                              onClick={() => {
                                toggleStatusMutation.mutate({
                                  channelId: channel.id,
                                  isActive: !channel.is_active,
                                });
                              }}
                            >
                              {channel.is_active ? "Disable" : "Enable"}
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              aria-label={`Board crop ${channel.name}`}
                              onClick={() => setProfileChannel(channel)}
                            >
                              Board crop
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              aria-label={`Edit ${channel.name}`}
                              onClick={() => {
                                setEditingChannel(channel);
                                setFormError(null);
                                setFormOpen(true);
                              }}
                            >
                              <Pencil size={14} aria-hidden="true" />
                              Edit
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              aria-label={`Delete ${channel.name}`}
                              className="text-red-700 hover:bg-red-50"
                              onClick={() => {
                                setDeleteError(null);
                                setDeletingChannel(channel);
                              }}
                            >
                              <Trash2 size={14} aria-hidden="true" />
                              Delete
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {channelsQuery.data && channelsQuery.data.total_pages > 1 && (
                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4 text-xs text-muted-foreground">
                  <span>
                    Page {channelsQuery.data.page} of{" "}
                    {channelsQuery.data.total_pages} ({channelsQuery.data.total}{" "}
                    matching)
                  </span>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={page <= 1}
                      onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                    >
                      Previous
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={page >= channelsQuery.data.total_pages}
                      onClick={() => setPage((prev) => prev + 1)}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      <ChannelFormModal
        open={formOpen}
        channel={editingChannel}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        serverError={formError}
        onClose={() => {
          setFormOpen(false);
          setEditingChannel(null);
          setFormError(null);
        }}
        onCreate={async (payload) => {
          await createMutation.mutateAsync(payload).catch(() => undefined);
        }}
        onUpdate={async (channelId, payload) => {
          await updateMutation
            .mutateAsync({ channelId, payload })
            .catch(() => undefined);
        }}
      />

      <ChannelDeleteModal
        channel={deletingChannel}
        isDeleting={deleteMutation.isPending}
        error={deleteError}
        onClose={() => {
          setDeletingChannel(null);
          setDeleteError(null);
        }}
        onConfirm={async (channelId) => {
          await deleteMutation.mutateAsync(channelId).catch(() => undefined);
        }}
      />

      <ChannelBoardProfileModal
        channel={profileChannel}
        onClose={() => setProfileChannel(null)}
      />

      <ChannelImportModal
        open={importOpen}
        isImporting={importMutation.isPending}
        error={importError}
        result={importResult}
        onClose={() => {
          setImportOpen(false);
          setImportError(null);
        }}
        onImport={async (file) => {
          await importMutation.mutateAsync(file).catch(() => undefined);
        }}
        onDownloadTemplate={handleDownloadTemplate}
      />
    </div>
  );
}
