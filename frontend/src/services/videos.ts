import { z } from "zod";
import { apiGet, apiPost, apiRequest } from "@/services/api";

// ------------------------------------------------------------------
// Schemas
// ------------------------------------------------------------------

export const LivestreamStatus = z.enum([
  "none",
  "upcoming",
  "live",
  "completed",
]);
export type LivestreamStatus = z.infer<typeof LivestreamStatus>;

export const ProcessingStatus = z.enum([
  "pending",
  "queued",
  "running",
  "succeeded",
  "failed",
  "skipped",
]);
export type ProcessingStatus = z.infer<typeof ProcessingStatus>;

export const DownloadStatus = z.enum([
  "pending",
  "downloading",
  "downloaded",
  "failed",
  "cancelled",
]);
export type DownloadStatus = z.infer<typeof DownloadStatus>;

export const videoSchema = z.object({
  id: z.number(),
  channel_id: z.number().nullable(),
  youtube_video_id: z.string(),
  title: z.string(),
  description: z.string(),
  video_url: z.string(),
  thumbnail_url: z.string().nullable(),
  duration_seconds: z.number(),
  published_at: z.string(),
  livestream_status: LivestreamStatus,
  discovered_at: z.string(),
  processing_status: ProcessingStatus,
  download_status: DownloadStatus,
  local_video_path: z.string().nullable(),
  actual_resolution: z.string().nullable(),
  file_size_bytes: z.number().nullable(),
  video_codec: z.string().nullable(),
  download_progress: z.number(),
  downloaded_bytes: z.number(),
  total_bytes: z.number().nullable(),
  download_requested: z.boolean(),
  download_started_at: z.string().nullable(),
  download_completed_at: z.string().nullable(),
  download_retry_count: z.number(),
  download_error: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Video = z.infer<typeof videoSchema>;

export const videoListSchema = z.object({
  items: z.array(videoSchema),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
  total_pages: z.number(),
});
export type VideoList = z.infer<typeof videoListSchema>;

export const videoSummarySchema = z.object({
  total: z.number(),
  pending: z.number(),
  today: z.number(),
  latest_discovery_at: z.string().nullable(),
});
export type VideoSummary = z.infer<typeof videoSummarySchema>;

export const discoveryRunSchema = z.object({
  channels_checked: z.number(),
  channels_skipped: z.number(),
  videos_found: z.number(),
  new_videos_added: z.number(),
  existing_videos_skipped: z.number(),
  videos_rejected_duration: z.number(),
  videos_rejected_filter: z.number(),
  livestreams_deferred: z.number(),
  failed_channels: z.array(z.string()),
  api_requests_made: z.number(),
  search_requests_made: z.number().optional().default(0),
  quota_reset_at: z.string().nullable().optional().default(null),
  duration_seconds: z.number(),
  errors: z.array(z.string()),
});
export type DiscoveryRun = z.infer<typeof discoveryRunSchema>;

export const downloadProgressSchema = z.object({
  video_id: z.number(),
  youtube_video_id: z.string(),
  status: DownloadStatus,
  progress_percent: z.number(),
  downloaded_bytes: z.number(),
  total_bytes: z.number().nullable(),
  speed_bytes_per_sec: z.number().nullable(),
  eta_seconds: z.number().nullable(),
  is_live: z.boolean().optional().default(false),
  error: z.string().nullable(),
});
export type DownloadProgress = z.infer<typeof downloadProgressSchema>;

export const activeDownloadsSchema = z.array(downloadProgressSchema);

export const bulkDownloadOutcomeSchema = z.object({
  video_id: z.number(),
  reason: z.string(),
});

export const bulkDownloadResponseSchema = z.object({
  started_ids: z.array(z.number()),
  skipped: z.array(bulkDownloadOutcomeSchema),
  errors: z.array(bulkDownloadOutcomeSchema),
});
export type BulkDownloadResponse = z.infer<typeof bulkDownloadResponseSchema>;

// ------------------------------------------------------------------
// Query params
// ------------------------------------------------------------------

export interface ListVideosParams {
  search?: string;
  channel_id?: number;
  processing_status?: ProcessingStatus;
  download_status?: DownloadStatus;
  published_after?: string;
  published_before?: string;
  sort_by?: "published_at" | "discovered_at" | "title" | "duration_seconds";
  sort_order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

// ------------------------------------------------------------------
// API functions
// ------------------------------------------------------------------

export function getVideoSummary(signal?: AbortSignal): Promise<VideoSummary> {
  return apiGet("videos/summary", videoSummarySchema, signal);
}

export function listVideos(
  params: ListVideosParams = {},
  signal?: AbortSignal,
): Promise<VideoList> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.channel_id !== undefined)
    query.set("channel_id", String(params.channel_id));
  if (params.processing_status)
    query.set("processing_status", params.processing_status);
  if (params.download_status)
    query.set("download_status", params.download_status);
  if (params.published_after)
    query.set("published_after", params.published_after);
  if (params.published_before)
    query.set("published_before", params.published_before);
  if (params.sort_by) query.set("sort_by", params.sort_by);
  if (params.sort_order) query.set("sort_order", params.sort_order);
  if (params.page !== undefined) query.set("page", String(params.page));
  if (params.page_size !== undefined)
    query.set("page_size", String(params.page_size));
  const qs = query.toString();
  return apiGet(qs ? `videos?${qs}` : "videos", videoListSchema, signal);
}

export function runDiscovery(): Promise<DiscoveryRun> {
  return apiPost("discovery/run", {}, discoveryRunSchema);
}

export function runChannelDiscovery(channelId: number): Promise<DiscoveryRun> {
  return apiPost(`discovery/channel/${channelId}`, {}, discoveryRunSchema);
}

export function startVideoDownload(videoId: number): Promise<Video> {
  return apiPost(`videos/${videoId}/download`, {}, videoSchema);
}

export function startBulkDownload(
  videoIds: number[],
): Promise<BulkDownloadResponse> {
  return apiPost(
    "videos/downloads/bulk",
    { video_ids: videoIds },
    bulkDownloadResponseSchema,
  );
}

export function getActiveDownloads(
  signal?: AbortSignal,
): Promise<DownloadProgress[]> {
  return apiGet("videos/downloads/active", activeDownloadsSchema, signal);
}

export function cancelVideoDownload(videoId: number): Promise<Video> {
  return apiPost(`videos/${videoId}/download/cancel`, {}, videoSchema);
}

export function retryVideoDownload(videoId: number): Promise<Video> {
  return apiPost(`videos/${videoId}/download/retry`, {}, videoSchema);
}

export function deleteLocalVideo(videoId: number): Promise<Video> {
  return apiRequest(`videos/${videoId}/download`, videoSchema, {
    method: "DELETE",
  });
}
