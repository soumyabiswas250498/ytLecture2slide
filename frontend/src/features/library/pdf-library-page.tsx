import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Download, Eye, Search, Trash2, X } from "lucide-react";
import { ActionButton } from "@/components/shared/action-button";
import { BulkActionToolbar } from "@/components/shared/bulk-action-toolbar";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
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
import { Button } from "@/components/ui/button";
import { Select, type SelectOption } from "@/components/ui/select";
import { ApiError } from "@/services/api";
import { listChannels } from "@/services/channels";
import {
  deletePdf,
  downloadPdfsZip,
  listPdfs,
  pdfDownloadUrl,
  type PdfLibraryItem,
  type PdfSortBy,
  type PdfSortOrder,
} from "@/services/pdfs";
import { PdfPreviewModal } from "./pdf-preview-modal";

const PAGE_SIZE = 20;

const SORT_OPTIONS: readonly SelectOption<string>[] = [
  { value: "generated_at:desc", label: "Newest generated" },
  { value: "generated_at:asc", label: "Oldest generated" },
  { value: "published_at:desc", label: "Newest published" },
  { value: "published_at:asc", label: "Oldest published" },
  { value: "page_count:desc", label: "Most pages" },
  { value: "file_size_bytes:desc", label: "Largest file" },
  { value: "title:asc", label: "Title A–Z" },
];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

function formatISTDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat("en-IN", {
      timeZone: "Asia/Kolkata",
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "An unexpected error occurred.";
}

export function PdfLibraryPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [channelIdFilter, setChannelIdFilter] = useState<number | undefined>(
    undefined,
  );
  const [publishedAfterDate, setPublishedAfterDate] = useState("");
  const [publishedBeforeDate, setPublishedBeforeDate] = useState("");
  const [sortBy, setSortBy] = useState<PdfSortBy>("generated_at");
  const [sortOrder, setSortOrder] = useState<PdfSortOrder>("desc");
  const [page, setPage] = useState(1);

  const [selectedMap, setSelectedMap] = useState<Map<number, PdfLibraryItem>>(
    new Map(),
  );
  const [previewTarget, setPreviewTarget] = useState<PdfLibraryItem | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<PdfLibraryItem | null>(null);
  const [feedback, setFeedback] = useState<{
    tone: "success" | "warning" | "error";
    summary: string;
  } | null>(null);

  const handleSearchChange = (value: string) => {
    setSearch(value);
    clearTimeout(
      (window as unknown as Record<string, ReturnType<typeof setTimeout>>)
        ._pdfSearchTimer,
    );
    (
      window as unknown as Record<string, ReturnType<typeof setTimeout>>
    )._pdfSearchTimer = setTimeout(() => {
      setDebouncedSearch(value);
      setPage(1);
    }, 300);
  };

  const channelsQuery = useQuery({
    queryKey: ["channels", "library-filter"],
    queryFn: ({ signal }) => listChannels({ page: 1, pageSize: 100 }, signal),
  });

  const channelOptions = useMemo<SelectOption<string>[]>(
    () => [
      { value: "", label: "All channels" },
      ...(channelsQuery.data?.items ?? []).map((ch) => ({
        value: String(ch.id),
        label: ch.name,
      })),
    ],
    [channelsQuery.data],
  );

  const publishedAfterIso = publishedAfterDate
    ? `${publishedAfterDate}T00:00:00+05:30`
    : undefined;
  const publishedBeforeIso = publishedBeforeDate
    ? `${publishedBeforeDate}T23:59:59+05:30`
    : undefined;

  const libraryQuery = useQuery({
    queryKey: [
      "pdf-library",
      debouncedSearch,
      channelIdFilter,
      publishedAfterIso,
      publishedBeforeIso,
      sortBy,
      sortOrder,
      page,
    ],
    queryFn: ({ signal }) =>
      listPdfs(
        {
          search: debouncedSearch || undefined,
          channel_id: channelIdFilter,
          published_after: publishedAfterIso,
          published_before: publishedBeforeIso,
          sort_by: sortBy,
          sort_order: sortOrder,
          page,
          page_size: PAGE_SIZE,
        },
        signal,
      ),
  });

  const deleteMutation = useMutation({
    mutationFn: (videoId: number) => deletePdf(videoId),
    onSuccess: (_data, videoId) => {
      setDeleteTarget(null);
      setSelectedMap((prev) => {
        const next = new Map(prev);
        next.delete(videoId);
        return next;
      });
      setFeedback({ tone: "success", summary: "PDF deleted." });
      void queryClient.invalidateQueries({ queryKey: ["pdf-library"] });
      void queryClient.invalidateQueries({
        queryKey: ["pdf-generation", videoId],
      });
    },
    onError: (err) => {
      setDeleteTarget(null);
      setFeedback({ tone: "error", summary: getErrorMessage(err) });
    },
  });

  const zipMutation = useMutation({
    mutationFn: (ids: number[]) => downloadPdfsZip(ids),
    onSuccess: ({ blob, filename, unavailableCount }) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);

      if (unavailableCount > 0) {
        setFeedback({
          tone: "warning",
          summary: `ZIP downloaded (${unavailableCount} unavailable PDF${unavailableCount === 1 ? "" : "s"} skipped).`,
        });
      } else {
        setFeedback({
          tone: "success",
          summary: "ZIP archive downloaded.",
        });
      }
    },
    onError: (err) => {
      setFeedback({ tone: "error", summary: getErrorMessage(err) });
    },
  });

  const data = libraryQuery.data;
  const pageItems = useMemo(() => data?.items ?? [], [data?.items]);
  const allPageSelected =
    pageItems.length > 0 &&
    pageItems.every((item) => selectedMap.has(item.video_id));

  const toggleSelectAllOnPage = () => {
    setSelectedMap((prev) => {
      const next = new Map(prev);
      if (allPageSelected) {
        for (const item of pageItems) next.delete(item.video_id);
      } else {
        for (const item of pageItems) next.set(item.video_id, item);
      }
      return next;
    });
  };

  const toggleSelectOne = (item: PdfLibraryItem) => {
    setSelectedMap((prev) => {
      const next = new Map(prev);
      if (next.has(item.video_id)) next.delete(item.video_id);
      else next.set(item.video_id, item);
      return next;
    });
  };

  const selectedIds = useMemo(
    () => Array.from(selectedMap.keys()),
    [selectedMap],
  );

  const hasActiveFilters = Boolean(
    debouncedSearch ||
    channelIdFilter !== undefined ||
    publishedAfterDate ||
    publishedBeforeDate,
  );

  const resetFilters = () => {
    setSearch("");
    setDebouncedSearch("");
    setChannelIdFilter(undefined);
    setPublishedAfterDate("");
    setPublishedBeforeDate("");
    setPage(1);
  };

  return (
    <PageContainer>
      <PageHeader
        eyebrow="LIBRARY"
        title="PDF Library"
        description="Preview and download generated lecture slide PDFs."
      />

      {feedback && (
        <NotificationAlert
          tone={feedback.tone}
          summary={feedback.summary}
          onDismiss={() => setFeedback(null)}
        />
      )}

      <section
        aria-label="PDF library summary"
        className="grid grid-cols-3 gap-3"
      >
        <StatCard label="Generated PDFs" value={data?.total ?? "—"} />
        <StatCard label="Total pages" value={data?.total_pages_sum ?? "—"} />
        <StatCard
          label="Total size"
          value={data ? formatBytes(data.total_bytes) : "—"}
        />
      </section>

      <FilterToolbar ariaLabel="PDF filters">
        <div className="relative min-w-[180px] flex-1">
          <Search
            size={14}
            className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            aria-label="Search PDFs by video title"
            placeholder="Search by video title…"
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="h-9 w-full rounded-md border border-border bg-white py-1.5 pr-3 pl-8 text-sm focus:border-primary focus:outline-none"
          />
        </div>

        <Select
          ariaLabel="Filter by channel"
          value={channelIdFilter !== undefined ? String(channelIdFilter) : ""}
          options={channelOptions}
          onValueChange={(val) => {
            setChannelIdFilter(val ? Number(val) : undefined);
            setPage(1);
          }}
          className="w-44"
        />

        <input
          type="date"
          aria-label="Published after"
          title="Published after"
          value={publishedAfterDate}
          onChange={(e) => {
            setPublishedAfterDate(e.target.value);
            setPage(1);
          }}
          className="h-9 rounded-md border border-border bg-white px-2.5 text-sm text-foreground focus:border-primary focus:outline-none"
        />

        <input
          type="date"
          aria-label="Published before"
          title="Published before"
          value={publishedBeforeDate}
          onChange={(e) => {
            setPublishedBeforeDate(e.target.value);
            setPage(1);
          }}
          className="h-9 rounded-md border border-border bg-white px-2.5 text-sm text-foreground focus:border-primary focus:outline-none"
        />

        <Select
          ariaLabel="Sort PDFs"
          value={`${sortBy}:${sortOrder}`}
          options={SORT_OPTIONS}
          onValueChange={(val) => {
            const [by, order] = val.split(":") as [PdfSortBy, PdfSortOrder];
            setSortBy(by);
            setSortOrder(order);
            setPage(1);
          }}
          className="w-44"
        />

        {hasActiveFilters && (
          <Button variant="ghost" size="sm" onClick={resetFilters}>
            <X size={14} aria-hidden="true" />
            Clear filters
          </Button>
        )}
      </FilterToolbar>

      <BulkActionToolbar
        selectedCount={selectedIds.length}
        onClearSelection={() => setSelectedMap(new Map())}
      >
        <ActionButton
          variant="outline"
          size="sm"
          disabled={selectedIds.length === 0 || zipMutation.isPending}
          tooltip={
            selectedIds.length === 0
              ? "Select PDFs to download as ZIP"
              : `Download ${selectedIds.length} PDF${selectedIds.length === 1 ? "" : "s"} as ZIP`
          }
          ariaLabel={`Download ZIP (${selectedIds.length})`}
          onClick={() => zipMutation.mutate(selectedIds)}
        >
          <Archive size={14} aria-hidden="true" />
          {zipMutation.isPending
            ? "Preparing ZIP…"
            : `Download ZIP (${selectedIds.length})`}
        </ActionButton>
      </BulkActionToolbar>

      {libraryQuery.isLoading ? (
        <LoadingState message="Loading PDF library…" />
      ) : libraryQuery.isError ? (
        <ErrorState
          message={getErrorMessage(libraryQuery.error)}
          onRetry={() => libraryQuery.refetch()}
        />
      ) : data && data.total > 0 ? (
        <div className="space-y-3">
          <DataTable>
            <thead>
              <tr className="border-b border-border bg-muted/40 text-xs text-muted-foreground uppercase">
                <th className="w-8 px-2 py-1.5 text-left">
                  <input
                    type="checkbox"
                    aria-label="Select all PDFs on page"
                    checked={allPageSelected}
                    disabled={pageItems.length === 0}
                    onChange={toggleSelectAllOnPage}
                    className="h-4 w-4 rounded border-border"
                  />
                </th>
                <th className="px-2 py-1.5 text-left font-semibold">
                  Video Title
                </th>
                <th className="px-2 py-1.5 text-left font-semibold">Channel</th>
                <th className="px-2 py-1.5 text-left font-semibold">
                  Published
                </th>
                <th className="px-2 py-1.5 text-left font-semibold">
                  Generated
                </th>
                <th className="px-2 py-1.5 text-left font-semibold">Pages</th>
                <th className="px-2 py-1.5 text-left font-semibold">Size</th>
                <th className="px-2 py-1.5 text-right font-semibold">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {pageItems.map((item) => (
                <tr
                  key={item.video_id}
                  className="align-middle transition-colors hover:bg-muted/20"
                >
                  <td className="px-2 py-1.5">
                    <input
                      type="checkbox"
                      aria-label={`Select ${item.video_title}`}
                      checked={selectedMap.has(item.video_id)}
                      onChange={() => toggleSelectOne(item)}
                      className="h-4 w-4 rounded border-border"
                    />
                  </td>
                  <td className="max-w-[320px] px-2 py-1.5">
                    <p className="line-clamp-2 text-xs font-medium leading-snug">
                      {item.video_title}
                    </p>
                    <p
                      className="mt-0.5 truncate text-[11px] text-muted-foreground"
                      title={item.pdf_filename}
                    >
                      {item.pdf_filename}
                    </p>
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-xs text-muted-foreground">
                    {item.channel_name}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-xs text-muted-foreground">
                    {formatISTDate(item.published_at)}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-xs text-muted-foreground">
                    {formatISTDate(item.generated_at)}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-xs tabular-nums">
                    {item.page_count}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5 text-xs tabular-nums text-muted-foreground">
                    {formatBytes(item.file_size_bytes)}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <div className="inline-flex flex-nowrap items-center justify-end gap-1">
                      <ActionButton
                        size="icon"
                        tooltip="Preview PDF"
                        ariaLabel={`Preview ${item.video_title}`}
                        onClick={() => setPreviewTarget(item)}
                      >
                        <Eye size={14} aria-hidden="true" />
                      </ActionButton>
                      <a
                        href={pdfDownloadUrl(item.video_id)}
                        download={item.pdf_filename}
                        title="Download PDF"
                        aria-label={`Download ${item.video_title}`}
                        className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-white text-foreground hover:bg-muted"
                      >
                        <Download size={14} aria-hidden="true" />
                      </a>
                      <ActionButton
                        size="icon"
                        variant="ghost"
                        tooltip="Delete PDF"
                        ariaLabel={`Delete ${item.video_title}`}
                        className="text-red-700 hover:bg-red-50 hover:text-red-800"
                        onClick={() => setDeleteTarget(item)}
                      >
                        <Trash2 size={14} aria-hidden="true" />
                      </ActionButton>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>

          {data.total_pages > 1 && (
            <div className="flex items-center justify-between pt-1 text-xs text-muted-foreground">
              <span>
                Page {data.page} of {data.total_pages} ({data.total} PDFs)
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= data.total_pages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <EmptyState
          title="No generated PDFs yet"
          description="Generate PDFs from processed lecture slides on the Videos page."
        />
      )}

      <PdfPreviewModal
        open={previewTarget !== null}
        videoId={previewTarget?.video_id ?? null}
        title={previewTarget?.video_title ?? "PDF preview"}
        filename={previewTarget?.pdf_filename}
        onClose={() => setPreviewTarget(null)}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete generated PDF"
        description={
          deleteTarget
            ? `Delete "${deleteTarget.pdf_filename}"? Source videos, extracted frames, and processed slides will be preserved.`
            : undefined
        }
        confirmLabel="Confirm delete PDF"
        pendingLabel="Deleting…"
        isPending={deleteMutation.isPending}
        onConfirm={() => {
          if (deleteTarget) deleteMutation.mutate(deleteTarget.video_id);
        }}
        onClose={() => setDeleteTarget(null)}
      />
    </PageContainer>
  );
}
