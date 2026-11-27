import { SlideControls, SlideToolbar } from "./slide-controls";
import { ExtractionControls, ExtractionToolbar } from "./extraction-controls";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  ExternalLink,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { ApiError } from "@/services/api";
import { listChannels } from "@/services/channels";
import {
  cancelVideoDownload,
  deleteLocalVideo,
  getActiveDownloads,
  getVideoSummary,
  listVideos,
  retryVideoDownload,
  runChannelDiscovery,
  runDiscovery,
  startBulkDownload,
  startVideoDownload,
  type BulkDownloadResponse,
  type DiscoveryRun,
  type DownloadProgress,
  type DownloadStatus,
  type ProcessingStatus,
  type Video,
} from "@/services/videos";

const PAGE_SIZE = 20;

function formatDuration(seconds: number): string {
  const rounded = Math.max(0, Math.round(seconds));
  const h = Math.floor(rounded / 3600);
  const m = Math.floor((rounded % 3600) / 60);
  const s = rounded % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

function formatSpeed(bytesPerSec: number): string {
  return `${formatBytes(bytesPerSec)}/s`;
}

function formatIST(iso: string): string {
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

function getStatusBadgeClass(status: ProcessingStatus): string {
  const map: Record<ProcessingStatus, string> = {
    pending: "bg-yellow-100 text-yellow-800",
    queued: "bg-blue-100 text-blue-800",
    running: "bg-indigo-100 text-indigo-800",
    succeeded: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
    skipped: "bg-gray-100 text-gray-600",
  };
  return map[status] ?? "bg-gray-100 text-gray-600";
}

function getDownloadBadgeClass(status: DownloadStatus): string {
  const map: Record<DownloadStatus, string> = {
    pending: "bg-slate-100 text-slate-700",
    downloading: "bg-blue-100 text-blue-800",
    downloaded: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
    cancelled: "bg-amber-100 text-amber-800",
  };
  return map[status] ?? "bg-gray-100 text-gray-600";
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "An unexpected error occurred.";
}

type SortBy = "published_at" | "discovered_at" | "title" | "duration_seconds";
type SortOrder = "asc" | "desc";

function DiscoverySummaryBanner({ run }: { run: DiscoveryRun }) {
  const hasErrors = run.errors.length > 0;
  return (
    <div
      role="status"
      aria-live="polite"
      className={`rounded-lg border p-4 text-sm ${
        hasErrors
          ? "border-yellow-300 bg-yellow-50"
          : "border-green-300 bg-green-50"
      }`}
    >
      <p className="font-semibold">
        Discovery complete — {run.new_videos_added} new video
        {run.new_videos_added !== 1 ? "s" : ""} added
      </p>
      <ul className="mt-2 list-inside list-disc text-muted-foreground">
        <li>Channels checked: {run.channels_checked}</li>
        <li>Videos found: {run.videos_found}</li>
        <li>Existing skipped: {run.existing_videos_skipped}</li>
        <li>Rejected (duration): {run.videos_rejected_duration}</li>
        <li>Livestreams deferred: {run.livestreams_deferred}</li>
        <li>
          API requests: {run.api_requests_made} (search:{" "}
          {run.search_requests_made})
        </li>
        <li>Duration: {run.duration_seconds.toFixed(1)}s</li>
      </ul>
      {hasErrors && (
        <ul className="mt-2 list-inside list-disc text-red-700">
          {run.errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BulkDownloadBanner({ result }: { result: BulkDownloadResponse }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm"
    >
      <p className="font-semibold text-blue-900">
        Bulk download requested: {result.started_ids.length} started
        {result.skipped.length > 0 ? `, ${result.skipped.length} skipped` : ""}
        {result.errors.length > 0 ? `, ${result.errors.length} failed` : ""}
      </p>
      {result.errors.length > 0 && (
        <ul className="mt-1 list-inside list-disc text-red-700">
          {result.errors.map((item) => (
            <li key={item.video_id}>
              Video #{item.video_id}: {item.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function VideosPage() {
  const queryClient = useQueryClient();
  const [extractionInterval, setExtractionInterval] = useState<
    number | undefined
  >(undefined);

  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [channelIdFilter, setChannelIdFilter] = useState<number | undefined>(
    undefined,
  );
  const [statusFilter, setStatusFilter] = useState<ProcessingStatus | "">("");
  const [downloadStatusFilter, setDownloadStatusFilter] = useState<
    DownloadStatus | ""
  >("");
  const [publishedAfterDate, setPublishedAfterDate] = useState("");
  const [publishedBeforeDate, setPublishedBeforeDate] = useState("");
  const [sortBy, setSortBy] = useState<SortBy>("published_at");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [page, setPage] = useState(1);
  const [lastRun, setLastRun] = useState<DiscoveryRun | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkDownloadResponse | null>(
    null,
  );
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [deleteTarget, setDeleteTarget] = useState<Video | null>(null);

  const handleSearchChange = (value: string) => {
    setSearch(value);
    clearTimeout(
      (window as unknown as Record<string, ReturnType<typeof setTimeout>>)
        ._videoSearchTimer,
    );
    (
      window as unknown as Record<string, ReturnType<typeof setTimeout>>
    )._videoSearchTimer = setTimeout(() => {
      setDebouncedSearch(value);
      setPage(1);
    }, 300);
  };

  const channelsQuery = useQuery({
    queryKey: ["channels", "videos-filter"],
    queryFn: ({ signal }) => listChannels({ page: 1, pageSize: 100 }, signal),
  });

  const channelNameById = useMemo(() => {
    const map = new Map<number, string>();
    for (const ch of channelsQuery.data?.items ?? []) {
      map.set(ch.id, ch.name);
    }
    return map;
  }, [channelsQuery.data]);

  const summaryQuery = useQuery({
    queryKey: ["video-summary"],
    queryFn: ({ signal }) => getVideoSummary(signal),
  });

  const publishedAfterIso = publishedAfterDate
    ? `${publishedAfterDate}T00:00:00+05:30`
    : undefined;
  const publishedBeforeIso = publishedBeforeDate
    ? `${publishedBeforeDate}T23:59:59+05:30`
    : undefined;

  const videosQuery = useQuery({
    queryKey: [
      "videos",
      debouncedSearch,
      channelIdFilter,
      statusFilter,
      downloadStatusFilter,
      publishedAfterIso,
      publishedBeforeIso,
      sortBy,
      sortOrder,
      page,
    ],
    queryFn: ({ signal }) =>
      listVideos(
        {
          search: debouncedSearch || undefined,
          channel_id: channelIdFilter,
          processing_status: statusFilter || undefined,
          download_status: downloadStatusFilter || undefined,
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

  const hasDownloadingRows = Boolean(
    videosQuery.data?.items.some((v) => v.download_status === "downloading"),
  );

  // Poll active downloads only while downloads are active.
  const activeDownloadsQuery = useQuery({
    queryKey: ["active-downloads"],
    queryFn: ({ signal }) => getActiveDownloads(signal),
    refetchInterval: (query) => {
      const liveItems = query.state.data ?? [];
      return hasDownloadingRows || liveItems.length > 0 ? 1500 : false;
    },
  });

  const prevActiveCountRef = useRef(0);
  useEffect(() => {
    const currentCount = activeDownloadsQuery.data?.length ?? 0;
    if (
      prevActiveCountRef.current > 0 &&
      currentCount < prevActiveCountRef.current
    ) {
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      queryClient.invalidateQueries({ queryKey: ["video-summary"] });
    }
    prevActiveCountRef.current = currentCount;
  }, [activeDownloadsQuery.data, queryClient]);

  const liveProgressByVideoId = useMemo(() => {
    const map = new Map<number, DownloadProgress>();
    for (const item of activeDownloadsQuery.data ?? []) {
      map.set(item.video_id, item);
    }
    return map;
  }, [activeDownloadsQuery.data]);

  const invalidateDownloads = () => {
    queryClient.invalidateQueries({ queryKey: ["videos"] });
    queryClient.invalidateQueries({ queryKey: ["active-downloads"] });
  };

  const discoverMutation = useMutation({
    mutationFn: () => runDiscovery(),
    onSuccess: (run) => {
      setLastRun(run);
      setMutationError(null);
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      queryClient.invalidateQueries({ queryKey: ["video-summary"] });
    },
    onError: (err) => setMutationError(getErrorMessage(err)),
  });

  const discoverChannelMutation = useMutation({
    mutationFn: (channelId: number) => runChannelDiscovery(channelId),
    onSuccess: (run) => {
      setLastRun(run);
      setMutationError(null);
      queryClient.invalidateQueries({ queryKey: ["videos"] });
      queryClient.invalidateQueries({ queryKey: ["video-summary"] });
    },
    onError: (err) => setMutationError(getErrorMessage(err)),
  });

  const downloadMutation = useMutation({
    mutationFn: (videoId: number) => startVideoDownload(videoId),
    onSuccess: () => {
      setMutationError(null);
      invalidateDownloads();
    },
    onError: (err) => setMutationError(getErrorMessage(err)),
  });

  const bulkDownloadMutation = useMutation({
    mutationFn: (videoIds: number[]) => startBulkDownload(videoIds),
    onSuccess: (res) => {
      setBulkResult(res);
      setMutationError(null);
      setSelectedIds(new Set());
      invalidateDownloads();
    },
    onError: (err) => setMutationError(getErrorMessage(err)),
  });

  const cancelMutation = useMutation({
    mutationFn: (videoId: number) => cancelVideoDownload(videoId),
    onSuccess: () => {
      setMutationError(null);
      invalidateDownloads();
    },
    onError: (err) => setMutationError(getErrorMessage(err)),
  });

  const retryMutation = useMutation({
    mutationFn: (videoId: number) => retryVideoDownload(videoId),
    onSuccess: () => {
      setMutationError(null);
      invalidateDownloads();
    },
    onError: (err) => setMutationError(getErrorMessage(err)),
  });

  const deleteLocalMutation = useMutation({
    mutationFn: (videoId: number) => deleteLocalVideo(videoId),
    onSuccess: () => {
      setMutationError(null);
      setDeleteTarget(null);
      invalidateDownloads();
    },
    onError: (err) => {
      setDeleteTarget(null);
      setMutationError(getErrorMessage(err));
    },
  });

  const isDiscovering =
    discoverMutation.isPending || discoverChannelMutation.isPending;
  const summary = summaryQuery.data;
  const videoList = videosQuery.data;
  const selectedChannelName =
    channelIdFilter !== undefined
      ? channelNameById.get(channelIdFilter)
      : undefined;

  const hasActiveFilters = Boolean(
    debouncedSearch ||
    channelIdFilter !== undefined ||
    statusFilter ||
    downloadStatusFilter ||
    publishedAfterDate ||
    publishedBeforeDate,
  );

  const resetFilters = () => {
    setSearch("");
    setDebouncedSearch("");
    setChannelIdFilter(undefined);
    setStatusFilter("");
    setDownloadStatusFilter("");
    setPublishedAfterDate("");
    setPublishedBeforeDate("");
    setPage(1);
  };

  const pageItems = videoList?.items ?? [];
  const allPageSelected =
    pageItems.length > 0 && pageItems.every((v) => selectedIds.has(v.id));

  const toggleSelectAllOnPage = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allPageSelected) {
        for (const v of pageItems) next.delete(v.id);
      } else {
        for (const v of pageItems) next.add(v.id);
      }
      return next;
    });
  };

  const toggleSelectOne = (videoId: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(videoId)) next.delete(videoId);
      else next.add(videoId);
      return next;
    });
  };

  return (
    <div className="space-y-8">
      <SlideToolbar selectedIds={[...selectedIds]} />
      <ExtractionToolbar
        selectedIds={[...selectedIds]}
        interval={extractionInterval}
        setInterval={setExtractionInterval}
      />
      {/* Page header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="eyebrow">WORKSPACE</p>
          <h1>Videos</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          {selectedIds.size > 0 && (
            <Button
              variant="outline"
              onClick={() =>
                bulkDownloadMutation.mutate(Array.from(selectedIds))
              }
              disabled={bulkDownloadMutation.isPending}
              aria-busy={bulkDownloadMutation.isPending}
            >
              <Download size={16} aria-hidden="true" />
              {bulkDownloadMutation.isPending
                ? "Starting downloads…"
                : `Download Selected (${selectedIds.size})`}
            </Button>
          )}
          {channelIdFilter !== undefined && (
            <Button
              variant="outline"
              onClick={() => discoverChannelMutation.mutate(channelIdFilter)}
              disabled={isDiscovering}
              aria-busy={discoverChannelMutation.isPending}
            >
              <RefreshCw
                size={16}
                className={
                  discoverChannelMutation.isPending ? "animate-spin" : ""
                }
                aria-hidden="true"
              />
              {discoverChannelMutation.isPending
                ? "Discovering channel…"
                : `Discover ${selectedChannelName ?? "Channel"}`}
            </Button>
          )}
          <Button
            onClick={() => discoverMutation.mutate()}
            disabled={isDiscovering}
            aria-busy={discoverMutation.isPending}
          >
            <RefreshCw
              size={16}
              className={discoverMutation.isPending ? "animate-spin" : ""}
              aria-hidden="true"
            />
            {discoverMutation.isPending ? "Discovering…" : "Discover Videos"}
          </Button>
        </div>
      </div>

      {/* Mutation error */}
      {mutationError && (
        <div
          role="alert"
          className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700"
        >
          {mutationError}
        </div>
      )}

      {/* Last run summary */}
      {lastRun && <DiscoverySummaryBanner run={lastRun} />}
      {bulkResult && <BulkDownloadBanner result={bulkResult} />}

      {/* Summary cards */}
      <section
        aria-label="Video summary"
        className="grid grid-cols-2 gap-4 sm:grid-cols-4"
      >
        {[
          { label: "Total videos", value: summary?.total ?? "—" },
          { label: "Pending", value: summary?.pending ?? "—" },
          { label: "Discovered today", value: summary?.today ?? "—" },
          {
            label: "Latest run",
            value: summary?.latest_discovery_at
              ? formatIST(summary.latest_discovery_at)
              : "—",
          },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="rounded-xl border border-border bg-white p-4"
          >
            <p className="text-xs font-medium text-muted-foreground">{label}</p>
            <p className="mt-1 text-2xl font-bold leading-tight">{value}</p>
          </div>
        ))}
      </section>

      {/* Filters */}
      <section aria-label="Filters" className="flex flex-wrap items-end gap-3">
        <div className="relative min-w-[200px] flex-1">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            aria-label="Search videos by title"
            placeholder="Search by title…"
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="w-full rounded-lg border border-border py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>

        <select
          aria-label="Filter by channel"
          value={channelIdFilter !== undefined ? String(channelIdFilter) : ""}
          onChange={(e) => {
            const val = e.target.value;
            setChannelIdFilter(val ? Number(val) : undefined);
            setPage(1);
          }}
          className="rounded-lg border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
        >
          <option value="">All channels</option>
          {(channelsQuery.data?.items ?? []).map((ch) => (
            <option key={ch.id} value={ch.id}>
              {ch.name}
            </option>
          ))}
        </select>

        <select
          aria-label="Filter by processing status"
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value as ProcessingStatus | "");
            setPage(1);
          }}
          className="rounded-lg border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
        >
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="queued">Queued</option>
          <option value="running">Running</option>
          <option value="succeeded">Succeeded</option>
          <option value="failed">Failed</option>
          <option value="skipped">Skipped</option>
        </select>

        <select
          aria-label="Filter by download status"
          value={downloadStatusFilter}
          onChange={(e) => {
            setDownloadStatusFilter(e.target.value as DownloadStatus | "");
            setPage(1);
          }}
          className="rounded-lg border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
        >
          <option value="">All downloads</option>
          <option value="pending">Not downloaded</option>
          <option value="downloading">Downloading</option>
          <option value="downloaded">Downloaded</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>

        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Published from
          <input
            type="date"
            aria-label="Published after"
            value={publishedAfterDate}
            onChange={(e) => {
              setPublishedAfterDate(e.target.value);
              setPage(1);
            }}
            className="rounded-lg border border-border px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Published to
          <input
            type="date"
            aria-label="Published before"
            value={publishedBeforeDate}
            onChange={(e) => {
              setPublishedBeforeDate(e.target.value);
              setPage(1);
            }}
            className="rounded-lg border border-border px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </label>

        <select
          aria-label="Sort videos"
          value={`${sortBy}:${sortOrder}`}
          onChange={(e) => {
            const [by, order] = e.target.value.split(":") as [
              SortBy,
              SortOrder,
            ];
            setSortBy(by);
            setSortOrder(order);
            setPage(1);
          }}
          className="rounded-lg border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
        >
          <option value="published_at:desc">Newest published</option>
          <option value="published_at:asc">Oldest published</option>
          <option value="discovered_at:desc">Recently discovered</option>
          <option value="duration_seconds:desc">Longest first</option>
          <option value="title:asc">Title A–Z</option>
        </select>

        {hasActiveFilters && (
          <Button variant="ghost" size="sm" onClick={resetFilters}>
            <X size={14} aria-hidden="true" />
            Clear filters
          </Button>
        )}
      </section>

      {/* Video table */}
      {videosQuery.isLoading ? (
        <LoadingState message="Loading videos…" />
      ) : videosQuery.isError ? (
        <ErrorState
          message={getErrorMessage(videosQuery.error)}
          onRetry={() => videosQuery.refetch()}
        />
      ) : videoList && videoList.total > 0 ? (
        <div className="space-y-4">
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/40">
                  <th className="w-10 px-3 py-3 text-left">
                    <input
                      type="checkbox"
                      aria-label="Select all videos on page"
                      checked={allPageSelected}
                      onChange={toggleSelectAllOnPage}
                      className="h-4 w-4 rounded border-border"
                    />
                  </th>
                  <th className="w-12 px-4 py-3 text-left font-medium text-muted-foreground">
                    <span className="sr-only">Thumbnail</span>
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Title
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Channel
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Duration
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Published
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Download
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Frames
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Processing
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {videoList.items.map((video) => {
                  const channelLabel =
                    video.channel_id !== null
                      ? (channelNameById.get(video.channel_id) ??
                        `Channel #${video.channel_id}`)
                      : "Deleted channel";
                  const live = liveProgressByVideoId.get(video.id);
                  const dlStatus = live?.status ?? video.download_status;
                  const progressPct =
                    live?.progress_percent ?? video.download_progress;

                  return (
                    <tr
                      key={video.id}
                      className="border-b border-border transition-colors last:border-0 hover:bg-muted/20"
                    >
                      <td className="px-3 py-3">
                        <input
                          type="checkbox"
                          aria-label={`Select ${video.title}`}
                          checked={selectedIds.has(video.id)}
                          onChange={() => toggleSelectOne(video.id)}
                          className="h-4 w-4 rounded border-border"
                        />
                      </td>
                      <td className="px-4 py-3">
                        {video.thumbnail_url ? (
                          <img
                            src={video.thumbnail_url}
                            alt={`Thumbnail for ${video.title}`}
                            className="h-10 w-16 rounded object-cover"
                            loading="lazy"
                          />
                        ) : (
                          <div
                            className="flex h-10 w-16 items-center justify-center rounded bg-muted"
                            aria-hidden="true"
                          >
                            <Play size={16} className="text-muted-foreground" />
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <p className="line-clamp-2 max-w-xs font-medium">
                          {video.title}
                        </p>
                        <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                          <span>{video.youtube_video_id}</span>
                          <a
                            href={video.video_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label={`Watch ${video.title} on YouTube`}
                            className="inline-flex items-center gap-0.5 text-primary hover:underline"
                          >
                            <ExternalLink size={12} aria-hidden="true" />
                            Watch
                          </a>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {channelLabel}
                      </td>
                      <td className="px-4 py-3 tabular-nums text-muted-foreground">
                        {formatDuration(video.duration_seconds)}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {formatIST(video.published_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="space-y-1">
                          <span
                            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize ${getDownloadBadgeClass(dlStatus)}`}
                          >
                            {dlStatus}
                          </span>

                          {dlStatus === "downloading" && (
                            <div className="w-40 space-y-1">
                              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                                <div
                                  className="h-full bg-blue-600 transition-all"
                                  style={{
                                    width: `${Math.min(100, Math.max(0, progressPct))}%`,
                                  }}
                                />
                              </div>
                              <p className="text-xs tabular-nums text-muted-foreground">
                                {progressPct.toFixed(1)}%
                                {live?.is_live &&
                                  live.speed_bytes_per_sec != null &&
                                  ` · ${formatSpeed(live.speed_bytes_per_sec)}`}
                                {live?.is_live &&
                                  live.eta_seconds != null &&
                                  ` · ETA ${formatDuration(live.eta_seconds)}`}
                              </p>
                              {(live?.downloaded_bytes ??
                                video.downloaded_bytes) > 0 && (
                                <p className="text-xs tabular-nums text-muted-foreground">
                                  {formatBytes(
                                    live?.downloaded_bytes ??
                                      video.downloaded_bytes,
                                  )}
                                  {(live?.total_bytes ?? video.total_bytes) !=
                                    null &&
                                    ` / ${formatBytes((live?.total_bytes ?? video.total_bytes) as number)}`}
                                </p>
                              )}
                            </div>
                          )}

                          {dlStatus === "downloaded" && (
                            <p className="text-xs text-muted-foreground">
                              {video.actual_resolution ?? "Verified"}
                              {video.file_size_bytes != null &&
                                ` · ${formatBytes(video.file_size_bytes)}`}
                            </p>
                          )}

                          {(dlStatus === "failed" ||
                            dlStatus === "cancelled") &&
                            video.download_error && (
                              <p
                                className="max-w-[200px] truncate text-xs text-red-700"
                                title={video.download_error}
                              >
                                {video.download_error}
                              </p>
                            )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <ExtractionControls
                          videoId={video.id}
                          downloaded={dlStatus === "downloaded"}
                          interval={extractionInterval}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize ${getStatusBadgeClass(video.processing_status)}`}
                        >
                          {video.processing_status}
                        </span>
                        <SlideControls videoId={video.id} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          {dlStatus === "pending" && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => downloadMutation.mutate(video.id)}
                              disabled={downloadMutation.isPending}
                              aria-label={`Download ${video.title}`}
                            >
                              <Download size={14} aria-hidden="true" />
                              Download
                            </Button>
                          )}
                          {dlStatus === "downloading" && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => cancelMutation.mutate(video.id)}
                              disabled={cancelMutation.isPending}
                              aria-label={`Cancel download for ${video.title}`}
                            >
                              <XCircle size={14} aria-hidden="true" />
                              Cancel
                            </Button>
                          )}
                          {(dlStatus === "failed" ||
                            dlStatus === "cancelled") && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => retryMutation.mutate(video.id)}
                              disabled={retryMutation.isPending}
                              aria-label={`Retry download for ${video.title}`}
                            >
                              <RotateCcw size={14} aria-hidden="true" />
                              Retry
                            </Button>
                          )}
                          {dlStatus === "downloaded" && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setDeleteTarget(video)}
                              aria-label={`Delete local video for ${video.title}`}
                              className="text-red-700 hover:bg-red-50 hover:text-red-800"
                            >
                              <Trash2 size={14} aria-hidden="true" />
                              Delete
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {videoList.total_pages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                Page {videoList.page} of {videoList.total_pages} (
                {videoList.total} videos)
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  disabled={page >= videoList.total_pages}
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
          title="No videos discovered yet"
          description="Click 'Discover Videos' to search for lecture videos from your registered channels."
        />
      )}

      {/* Delete confirmation modal */}
      <Modal
        open={deleteTarget !== null}
        title="Delete local video file"
        description={
          deleteTarget
            ? `Remove the downloaded file for "${deleteTarget.title}"? The video record will remain in your library and can be re-downloaded later.`
            : undefined
        }
        onClose={() => setDeleteTarget(null)}
      >
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setDeleteTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={deleteLocalMutation.isPending}
            onClick={() => {
              if (deleteTarget) deleteLocalMutation.mutate(deleteTarget.id);
            }}
          >
            {deleteLocalMutation.isPending ? "Deleting…" : "Delete local file"}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
