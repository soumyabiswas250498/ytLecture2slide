import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  ExternalLink,
  FileSpreadsheet,
  Pencil,
  Plus,
  Power,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { ActionButton } from "@/components/shared/action-button";
import { DataTable } from "@/components/shared/data-table";
import { FilterToolbar } from "@/components/shared/filter-toolbar";
import { NotificationAlert } from "@/components/shared/notification-alert";
import { PageContainer } from "@/components/shared/page-container";
import { PageHeader } from "@/components/shared/page-header";
import { StatCard } from "@/components/shared/stat-card";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/shared/states";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Select, type SelectOption } from "@/components/ui/select";
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

const STATUS_OPTIONS: readonly SelectOption<StatusFilter>[] = [
  { value: "all", label: "All statuses" },
  { value: "active", label: "Active" },
  { value: "inactive", label: "Inactive" },
];

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
    <PageContainer>
      <PageHeader
        eyebrow="CHANNEL REGISTRY"
        title="Channels"
        description="Register YouTube channels, configure search keywords, and manage active discovery targets."
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void handleDownloadTemplate();
              }}
            >
              <FileSpreadsheet size={14} aria-hidden="true" />
              CSV template
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
              <Download size={14} aria-hidden="true" />
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
              <Upload size={14} aria-hidden="true" />
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
              <Plus size={14} aria-hidden="true" />
              Add channel
            </Button>
          </>
        }
      />

      <section aria-label="Channel summary" className="grid grid-cols-3 gap-3">
        <StatCard label="Total channels" value={summary.total} />
        <StatCard
          label="Active channels"
          value={summary.active}
          tone="success"
        />
        <StatCard
          label="Inactive channels"
          value={summary.inactive}
          tone="muted"
        />
      </section>

      {feedback && (
        <NotificationAlert
          tone={feedback.type}
          summary={feedback.message}
          onDismiss={() => setFeedback(null)}
        />
      )}

      <FilterToolbar ariaLabel="Channel filters">
        <div className="relative min-w-[220px] flex-1">
          <label htmlFor="channel-search" className="sr-only">
            Search channels by name or keyword
          </label>
          <Search
            size={15}
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground"
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
            className="h-9 w-full rounded-md border border-border bg-white py-1.5 pr-3 pl-8 text-sm focus:border-primary focus:outline-none"
          />
        </div>

        <div className="flex items-center gap-2">
          <label
            htmlFor="status-filter"
            className="text-xs font-medium text-muted-foreground"
          >
            Status
          </label>
          <Select
            id="status-filter"
            ariaLabel="Status"
            value={statusFilter}
            options={STATUS_OPTIONS}
            onValueChange={(val) => {
              setStatusFilter(val);
              setPage(1);
            }}
            className="w-36"
          />
        </div>

        {hasFilters && (
          <Button
            type="button"
            variant="ghost"
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
      </FilterToolbar>

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
        <div className="space-y-3">
          <DataTable>
            <thead>
              <tr className="border-b border-border bg-muted/40 text-xs text-muted-foreground uppercase">
                <th className="px-3 py-2.5 font-semibold">Channel name</th>
                <th className="px-3 py-2.5 font-semibold">Channel link</th>
                <th className="px-3 py-2.5 font-semibold">Sample video</th>
                <th className="px-3 py-2.5 font-semibold">Search keyword</th>
                <th className="px-3 py-2.5 font-semibold">Status</th>
                <th className="px-3 py-2.5 text-right font-semibold">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((channel) => (
                <tr
                  key={channel.id}
                  className="transition-colors hover:bg-muted/20"
                >
                  <td className="px-3 py-2 font-medium text-foreground">
                    {channel.name}
                  </td>
                  <td className="px-3 py-2">
                    <a
                      href={channel.channel_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      aria-label={`Visit ${channel.name} channel`}
                      title={channel.channel_url}
                      className="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium text-primary underline-offset-2 hover:underline"
                    >
                      <span>Visit channel</span>
                      <ExternalLink
                        size={12}
                        aria-hidden="true"
                        className="shrink-0"
                      />
                    </a>
                  </td>
                  <td className="px-3 py-2">
                    {channel.sample_video_url ? (
                      <a
                        href={channel.sample_video_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        aria-label={`Watch sample video for ${channel.name}`}
                        title={channel.sample_video_url}
                        className="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium text-primary underline-offset-2 hover:underline"
                      >
                        <span>Watch video</span>
                        <ExternalLink
                          size={12}
                          aria-hidden="true"
                          className="shrink-0"
                        />
                      </a>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span className="inline-block rounded bg-muted px-2 py-0.5 text-xs font-medium">
                      {channel.search_keyword}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge
                      label={channel.is_active ? "Active" : "Inactive"}
                      tone={channel.is_active ? "success" : "neutral"}
                    />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="inline-flex flex-nowrap items-center justify-end gap-1">
                      <ActionButton
                        tooltip={
                          channel.is_active
                            ? `Disable ${channel.name}`
                            : `Enable ${channel.name}`
                        }
                        ariaLabel={channel.is_active ? "Disable" : "Enable"}
                        disabled={toggleStatusMutation.isPending}
                        onClick={() => {
                          toggleStatusMutation.mutate({
                            channelId: channel.id,
                            isActive: !channel.is_active,
                          });
                        }}
                      >
                        <Power size={12} aria-hidden="true" />
                        {channel.is_active ? "Disable" : "Enable"}
                      </ActionButton>
                      <ActionButton
                        tooltip={`Edit ${channel.name}`}
                        ariaLabel={`Edit ${channel.name}`}
                        onClick={() => {
                          setEditingChannel(channel);
                          setFormError(null);
                          setFormOpen(true);
                        }}
                      >
                        <Pencil size={12} aria-hidden="true" />
                        Edit
                      </ActionButton>
                      <ActionButton
                        tooltip={`Delete ${channel.name}`}
                        ariaLabel={`Delete ${channel.name}`}
                        className="text-red-700 hover:bg-red-50"
                        onClick={() => {
                          setDeleteError(null);
                          setDeletingChannel(channel);
                        }}
                      >
                        <Trash2 size={12} aria-hidden="true" />
                        Delete
                      </ActionButton>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>

          {channelsQuery.data && channelsQuery.data.total_pages > 1 && (
            <div className="flex flex-wrap items-center justify-between gap-3 pt-1 text-xs text-muted-foreground">
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
    </PageContainer>
  );
}
