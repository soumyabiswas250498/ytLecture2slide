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
import { ActionButton } from "@/components/shared/action-button";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { DataTable } from "@/components/shared/data-table";
import { DetailsPopover } from "@/components/shared/details-popover";
import { FilterToolbar } from "@/components/shared/filter-toolbar";
import { NotificationAlert } from "@/components/shared/notification-alert";
import { PageContainer } from "@/components/shared/page-container";
import { PageHeader } from "@/components/shared/page-header";
import { ProgressIndicator } from "@/components/shared/progress-indicator";
import { StatCard } from "@/components/shared/stat-card";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/shared/states";
import { StatusBadge, type StatusTone } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Select, type SelectOption } from "@/components/ui/select";
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
  startVideoDownload,
  type DiscoveryRun,
  type DownloadProgress,
  type DownloadStatus,
  type EligibilityFilter,
  type ProcessingStatus,
  type Video,
} from "@/services/videos";
import { ExtractionControls } from "./extraction-controls";
import { PdfControls } from "./pdf-controls";
import { SlideControls } from "./slide-controls";
import { UnifiedBulkToolbar } from "./unified-bulk-toolbar";

const PAGE_SIZE = 20;

const DOWNLOAD_STATUS_TONE: Record<DownloadStatus, StatusTone> = {
  pending: "neutral",
  downloading: "info",
  downloaded: "success",
  failed: "error",
  cancelled: "warning",
  cleaned: "neutral",
};

const PROCESSING_OPTIONS: readonly SelectOption<ProcessingStatus | "">[] = [
  { value: "", label: "All statuses" },
  { value: "pending", label: "Pending" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "skipped", label: "Skipped" },
];

const DOWNLOAD_OPTIONS: readonly SelectOption<DownloadStatus | "">[] = [
  { value: "", label: "All downloads" },
  { value: "pending", label: "Not downloaded" },
  { value: "downloading", label: "Downloading" },
  { value: "downloaded", label: "Downloaded" },
  { value: "cleaned", label: "Cleaned" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

const ELIGIBILITY_OPTIONS: readonly SelectOption<EligibilityFilter>[] = [
  { value: "all", label: "All videos" },
  { value: "eligible", label: "Eligible videos" },
  { value: "excluded", label: "Excluded videos" },
];

type SortBy = "published_at" | "discovered_at" | "title" | "duration_seconds";
type SortOrder = "asc" | "desc";

const SORT_OPTIONS: readonly SelectOption<string>[] = [
  { value: "published_at:desc", label: "Newest published" },
  { value: "published_at:asc", label: "Oldest published" },
  { value: "discovered_at:desc", label: "Recently discovered" },
  { value: "duration_seconds:desc", label: "Longest first" },
  { value: "title:asc", label: "Title A–Z" },
];

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

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "An unexpected error occurred.";
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
  const [eligibilityFilter, setEligibilityFilter] =
    useState<EligibilityFilter>("all");
  const [publishedAfterDate, setPublishedAfterDate] = useState("");
  const [publishedBeforeDate, setPublishedBeforeDate] = useState("");
  const [sortBy, setSortBy] = useState<SortBy>("published_at");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [page, setPage] = useState(1);
  const [lastRun, setLastRun] = useState<DiscoveryRun | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [selectedVideosMap, setSelectedVideosMap] = useState<
    Map<number, Video>
  >(new Map());
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
      eligibilityFilter,
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
          eligibility: eligibilityFilter,
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
      void queryClient.invalidateQueries({ queryKey: ["videos"] });
      void queryClient.invalidateQueries({ queryKey: ["video-summary"] });
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
    void queryClient.invalidateQueries({ queryKey: ["videos"] });
    void queryClient.invalidateQueries({ queryKey: ["active-downloads"] });
  };

  const discoverMutation = useMutation({
    mutationFn: () => runDiscovery(),
    onSuccess: (run) => {
      setLastRun(run);
      setMutationError(null);
      void queryClient.invalidateQueries({ queryKey: ["videos"] });
      void queryClient.invalidateQueries({ queryKey: ["video-summary"] });
    },
    onError: (err) => setMutationError(getErrorMessage(err)),
  });

  const discoverChannelMutation = useMutation({
    mutationFn: (channelId: number) => runChannelDiscovery(channelId),
    onSuccess: (run) => {
      setLastRun(run);
      setMutationError(null);
      void queryClient.invalidateQueries({ queryKey: ["videos"] });
      void queryClient.invalidateQueries({ queryKey: ["video-summary"] });
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
    eligibilityFilter !== "all" ||
    publishedAfterDate ||
    publishedBeforeDate,
  );

  const resetFilters = () => {
    setSearch("");
    setDebouncedSearch("");
    setChannelIdFilter(undefined);
    setStatusFilter("");
    setDownloadStatusFilter("");
    setEligibilityFilter("all");
    setPublishedAfterDate("");
    setPublishedBeforeDate("");
    setPage(1);
  };

  const pageItems = useMemo(() => videoList?.items ?? [], [videoList?.items]);
  const eligiblePageItems = useMemo(
    () => pageItems.filter((v) => !v.is_excluded),
    [pageItems],
  );
  const allPageSelected =
    eligiblePageItems.length > 0 &&
    eligiblePageItems.every((v) => selectedVideosMap.has(v.id));

  const toggleSelectAllOnPage = () => {
    setSelectedVideosMap((prev) => {
      const next = new Map(prev);
      if (allPageSelected) {
        for (const v of eligiblePageItems) next.delete(v.id);
      } else {
        for (const v of eligiblePageItems) next.set(v.id, v);
      }
      return next;
    });
  };

  const toggleSelectOne = (video: Video) => {
    if (video.is_excluded) return;
    setSelectedVideosMap((prev) => {
      const next = new Map(prev);
      if (next.has(video.id)) next.delete(video.id);
      else next.set(video.id, video);
      return next;
    });
  };

  // Sync selected videos with latest page items so eligibility reflects live state
  const selectedVideos = useMemo(() => {
    const latestById = new Map(pageItems.map((v) => [v.id, v]));
    return Array.from(selectedVideosMap.values()).map(
      (v) => latestById.get(v.id) ?? v,
    );
  }, [selectedVideosMap, pageItems]);

  return (
    <PageContainer>
      {/* 1. Page heading and Discover Videos action */}
      <PageHeader
        eyebrow="WORKSPACE"
        title="Videos"
        actions={
          <>
            {channelIdFilter !== undefined && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => discoverChannelMutation.mutate(channelIdFilter)}
                disabled={isDiscovering}
                aria-busy={discoverChannelMutation.isPending}
              >
                <RefreshCw
                  size={14}
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
              size="sm"
              onClick={() => discoverMutation.mutate()}
              disabled={isDiscovering}
              aria-busy={discoverMutation.isPending}
            >
              <RefreshCw
                size={14}
                className={discoverMutation.isPending ? "animate-spin" : ""}
                aria-hidden="true"
              />
              {discoverMutation.isPending ? "Discovering…" : "Discover Videos"}
            </Button>
          </>
        }
      />

      {mutationError && (
        <NotificationAlert
          tone="error"
          summary={mutationError}
          onDismiss={() => setMutationError(null)}
        />
      )}

      {lastRun && (
        <NotificationAlert
          tone={lastRun.errors.length > 0 ? "warning" : "success"}
          summary={`Discovery complete — ${lastRun.new_videos_added} new video${lastRun.new_videos_added !== 1 ? "s" : ""} added`}
          onDismiss={() => setLastRun(null)}
          details={
            <div className="space-y-1.5">
              <p>
                Channels checked: {lastRun.channels_checked} · Found:{" "}
                {lastRun.videos_found} · Skipped:{" "}
                {lastRun.existing_videos_skipped} · Duration rejected:{" "}
                {lastRun.videos_rejected_duration} · Livestreams deferred:{" "}
                {lastRun.livestreams_deferred} · API requests:{" "}
                {lastRun.api_requests_made} (search:{" "}
                {lastRun.search_requests_made}) ·{" "}
                {lastRun.duration_seconds.toFixed(1)}s
              </p>
              {lastRun.errors.length > 0 && (
                <ul className="list-inside list-disc text-red-800">
                  {lastRun.errors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              )}
            </div>
          }
        />
      )}

      {/* 2. Compact summary statistics */}
      <section
        aria-label="Video summary"
        className="grid grid-cols-2 gap-3 sm:grid-cols-5"
      >
        <StatCard label="Total videos" value={summary?.total ?? "—"} />
        <StatCard
          label="Eligible"
          value={summary?.eligible ?? "—"}
          tone="success"
        />
        <StatCard
          label="Excluded"
          value={summary?.excluded ?? "—"}
          tone="muted"
        />
        <StatCard label="Pending" value={summary?.pending ?? "—"} />
        <StatCard
          label="Latest run"
          value={
            summary?.latest_discovery_at
              ? formatIST(summary.latest_discovery_at)
              : "—"
          }
        />
      </section>

      {/* 3. Search and filter toolbar */}
      <FilterToolbar ariaLabel="Filters">
        <div className="relative min-w-[180px] flex-1">
          <Search
            size={14}
            className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            aria-label="Search videos by title"
            placeholder="Search by title…"
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
          className="w-40"
        />

        <Select
          ariaLabel="Filter by processing status"
          value={statusFilter}
          options={PROCESSING_OPTIONS}
          onValueChange={(val) => {
            setStatusFilter(val);
            setPage(1);
          }}
          className="w-36"
        />

        <Select
          ariaLabel="Filter by download status"
          value={downloadStatusFilter}
          options={DOWNLOAD_OPTIONS}
          onValueChange={(val) => {
            setDownloadStatusFilter(val);
            setPage(1);
          }}
          className="w-40"
        />

        <Select
          ariaLabel="Filter by eligibility"
          value={eligibilityFilter}
          options={ELIGIBILITY_OPTIONS}
          onValueChange={(val) => {
            setEligibilityFilter(val);
            setPage(1);
          }}
          className="w-36"
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
          ariaLabel="Sort videos"
          value={`${sortBy}:${sortOrder}`}
          options={SORT_OPTIONS}
          onValueChange={(val) => {
            const [by, order] = val.split(":") as [SortBy, SortOrder];
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

      {/* 4. Unified bulk processing toolbar */}
      <UnifiedBulkToolbar
        selectedVideos={selectedVideos}
        interval={extractionInterval}
        onIntervalChange={setExtractionInterval}
        onClearSelection={() => setSelectedVideosMap(new Map())}
      />

      {/* 5. Video table */}
      {videosQuery.isLoading ? (
        <LoadingState message="Loading videos…" />
      ) : videosQuery.isError ? (
        <ErrorState
          message={getErrorMessage(videosQuery.error)}
          onRetry={() => videosQuery.refetch()}
        />
      ) : videoList && videoList.total > 0 ? (
        <div className="space-y-3">
          <DataTable>
            <thead>
              <tr className="border-b border-border bg-muted/40 text-xs text-muted-foreground uppercase">
                <th className="w-8 px-2 py-1.5 text-left">
                  <input
                    type="checkbox"
                    aria-label="Select all videos on page"
                    checked={allPageSelected}
                    disabled={eligiblePageItems.length === 0}
                    onChange={toggleSelectAllOnPage}
                    className="h-4 w-4 rounded border-border disabled:cursor-not-allowed disabled:opacity-50"
                  />
                </th>
                <th className="w-14 px-1.5 py-1.5 text-left font-semibold">
                  <span className="sr-only">Thumbnail</span>
                </th>
                <th className="px-2 py-1.5 text-left font-semibold">Title</th>
                <th className="px-2 py-1.5 text-left font-semibold">Channel</th>
                <th className="px-2 py-1.5 text-left font-semibold">
                  Duration
                </th>
                <th className="px-2 py-1.5 text-left font-semibold">
                  Published
                </th>
                <th className="px-2 py-1.5 text-left font-semibold">
                  Download
                </th>
                <th className="px-2 py-1.5 text-left font-semibold">Frames</th>
                <th className="px-2 py-1.5 text-left font-semibold">Slides</th>
                <th className="px-2 py-1.5 text-left font-semibold">PDF</th>
                <th className="px-2 py-1.5 text-right font-semibold">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {videoList.items.map((video) => {
                const channelLabel =
                  (video.channel_id !== null
                    ? channelNameById.get(video.channel_id)
                    : undefined) ??
                  video.channel_name ??
                  (video.channel_id !== null
                    ? `Channel #${video.channel_id}`
                    : "Unknown Channel");
                const live = liveProgressByVideoId.get(video.id);
                const dlStatus = live?.status ?? video.download_status;
                const progressPct =
                  live?.progress_percent ?? video.download_progress;

                return (
                  <tr
                    key={video.id}
                    data-excluded={video.is_excluded ? "true" : "false"}
                    className={
                      video.is_excluded
                        ? "align-top bg-muted/40 text-muted-foreground opacity-80"
                        : "align-top transition-colors hover:bg-muted/20"
                    }
                  >
                    <td className="px-2 py-1.5">
                      <input
                        type="checkbox"
                        aria-label={`Select ${video.title}`}
                        disabled={video.is_excluded}
                        checked={
                          !video.is_excluded && selectedVideosMap.has(video.id)
                        }
                        onChange={() => toggleSelectOne(video)}
                        className="mt-1 h-4 w-4 rounded border-border disabled:cursor-not-allowed disabled:opacity-50"
                      />
                    </td>
                    <td className="px-1.5 py-1.5">
                      {video.thumbnail_url ? (
                        <img
                          src={video.thumbnail_url}
                          alt={`Thumbnail for ${video.title}`}
                          className="h-8 w-14 rounded object-cover"
                          loading="lazy"
                        />
                      ) : (
                        <div
                          className="flex h-8 w-14 items-center justify-center rounded bg-muted"
                          aria-hidden="true"
                        >
                          <Play size={14} className="text-muted-foreground" />
                        </div>
                      )}
                    </td>
                    <td className="max-w-[200px] px-2 py-1.5">
                      <p className="line-clamp-2 text-xs font-medium leading-snug">
                        {video.title}
                      </p>
                      {video.is_excluded && (
                        <div
                          className="mt-1 flex flex-wrap items-center gap-1"
                          title={
                            video.excluded_keywords.length > 0
                              ? `Excluded by keyword(s): ${video.excluded_keywords.join(", ")}`
                              : "Excluded by keyword"
                          }
                        >
                          <StatusBadge label="Excluded" tone="warning" />
                          {video.excluded_keywords.length > 0 && (
                            <span className="truncate text-[11px] text-amber-800">
                              {video.excluded_keywords.join(", ")}
                            </span>
                          )}
                        </div>
                      )}
                      <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <span className="font-mono">
                          {video.youtube_video_id}
                        </span>
                        <a
                          href={video.video_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={`Watch ${video.title} on YouTube`}
                          className="inline-flex items-center gap-0.5 text-primary hover:underline"
                        >
                          <ExternalLink size={11} aria-hidden="true" />
                          Watch
                        </a>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-xs text-muted-foreground">
                      {channelLabel}
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-xs tabular-nums text-muted-foreground">
                      {formatDuration(video.duration_seconds)}
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-xs text-muted-foreground">
                      {formatIST(video.published_at)}
                    </td>
                    <td className="px-2 py-1.5">
                      <div className="space-y-1">
                        <div>
                          <StatusBadge
                            label={dlStatus}
                            tone={DOWNLOAD_STATUS_TONE[dlStatus] ?? "neutral"}
                          />
                        </div>
                        {dlStatus === "downloading" && (
                          <ProgressIndicator
                            className="w-32"
                            value={progressPct}
                            ariaLabel={`Download progress for ${video.title}`}
                            detail={`${progressPct.toFixed(1)}%${
                              live?.is_live && live.speed_bytes_per_sec != null
                                ? ` · ${formatSpeed(live.speed_bytes_per_sec)}`
                                : ""
                            }${
                              live?.is_live && live.eta_seconds != null
                                ? ` · ETA ${formatDuration(live.eta_seconds)}`
                                : ""
                            }`}
                          />
                        )}
                        {(dlStatus === "failed" || dlStatus === "cancelled") &&
                          video.download_error && (
                            <p
                              className="max-w-[160px] truncate text-[11px] text-red-700"
                              title={video.download_error}
                            >
                              {video.download_error}
                            </p>
                          )}
                        {(dlStatus === "downloaded" ||
                          video.actual_resolution ||
                          video.video_codec ||
                          video.file_size_bytes != null ||
                          video.download_retry_count > 0) && (
                          <div className="flex flex-nowrap items-center gap-1.5">
                            {dlStatus === "downloaded" &&
                              video.file_size_bytes != null && (
                                <span className="whitespace-nowrap text-[11px] tabular-nums text-muted-foreground">
                                  {formatBytes(video.file_size_bytes)}
                                </span>
                              )}
                            <DetailsPopover
                              title="Download metadata"
                              ariaLabel={`View download details for ${video.title}`}
                              items={[
                                {
                                  label: "Resolution",
                                  value: video.actual_resolution,
                                },
                                {
                                  label: "Duration",
                                  value:
                                    video.duration_seconds > 0
                                      ? formatDuration(video.duration_seconds)
                                      : null,
                                },
                                {
                                  label: "Codec",
                                  value: video.video_codec,
                                },
                                {
                                  label: "File size",
                                  value:
                                    video.file_size_bytes != null
                                      ? formatBytes(video.file_size_bytes)
                                      : null,
                                },
                                {
                                  label: "Retries",
                                  value:
                                    video.download_retry_count > 0
                                      ? video.download_retry_count
                                      : null,
                                },
                                {
                                  label: "Completed",
                                  value: video.download_completed_at
                                    ? formatIST(video.download_completed_at)
                                    : null,
                                },
                              ]}
                            />
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="px-2 py-1.5">
                      <ExtractionControls
                        videoId={video.id}
                        downloaded={dlStatus === "downloaded"}
                        interval={extractionInterval}
                        isExcluded={video.is_excluded}
                      />
                    </td>
                    <td className="px-2 py-1.5">
                      <SlideControls
                        videoId={video.id}
                        isExcluded={video.is_excluded}
                      />
                    </td>
                    <td className="px-2 py-1.5">
                      <PdfControls
                        videoId={video.id}
                        videoTitle={video.title}
                        isExcluded={video.is_excluded}
                      />
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <div className="inline-flex flex-nowrap items-center justify-end gap-1">
                        {dlStatus === "pending" && (
                          <ActionButton
                            size="icon"
                            tooltip={
                              video.is_excluded
                                ? "Excluded videos cannot be downloaded"
                                : `Download ${video.title}`
                            }
                            ariaLabel={`Download ${video.title}`}
                            onClick={() => downloadMutation.mutate(video.id)}
                            disabled={
                              downloadMutation.isPending || video.is_excluded
                            }
                          >
                            <Download size={14} aria-hidden="true" />
                          </ActionButton>
                        )}
                        {dlStatus === "downloading" && (
                          <ActionButton
                            size="icon"
                            tooltip={`Cancel download for ${video.title}`}
                            ariaLabel={`Cancel download for ${video.title}`}
                            onClick={() => cancelMutation.mutate(video.id)}
                            disabled={cancelMutation.isPending}
                          >
                            <XCircle size={14} aria-hidden="true" />
                          </ActionButton>
                        )}
                        {(dlStatus === "failed" ||
                          dlStatus === "cancelled") && (
                          <ActionButton
                            size="icon"
                            tooltip={
                              video.is_excluded
                                ? "Excluded videos cannot be retried"
                                : `Retry download for ${video.title}`
                            }
                            ariaLabel={`Retry download for ${video.title}`}
                            onClick={() => retryMutation.mutate(video.id)}
                            disabled={
                              retryMutation.isPending || video.is_excluded
                            }
                          >
                            <RotateCcw size={14} aria-hidden="true" />
                          </ActionButton>
                        )}
                        {dlStatus === "downloaded" && (
                          <ActionButton
                            size="icon"
                            variant="ghost"
                            tooltip={`Delete local video for ${video.title}`}
                            ariaLabel={`Delete local video for ${video.title}`}
                            onClick={() => setDeleteTarget(video)}
                            className="text-red-700 hover:bg-red-50 hover:text-red-800"
                          >
                            <Trash2 size={14} aria-hidden="true" />
                          </ActionButton>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </DataTable>

          {/* 6. Pagination */}
          {videoList.total_pages > 1 && (
            <div className="flex items-center justify-between pt-1 text-xs text-muted-foreground">
              <span>
                Page {videoList.page} of {videoList.total_pages} (
                {videoList.total} videos)
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

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete local video file"
        description={
          deleteTarget
            ? `Remove the downloaded file for "${deleteTarget.title}"? The video record will remain in your library and can be re-downloaded later.`
            : undefined
        }
        confirmLabel="Delete local file"
        pendingLabel="Deleting…"
        isPending={deleteLocalMutation.isPending}
        onConfirm={() => {
          if (deleteTarget) deleteLocalMutation.mutate(deleteTarget.id);
        }}
        onClose={() => setDeleteTarget(null)}
      />
    </PageContainer>
  );
}
