import { z } from "zod";
import { apiDelete, apiGet, apiPost } from "@/services/api";
import { config } from "@/lib/config";

export const extractionSchema = z.object({
  video_id: z.number(),
  status: z.enum(["pending", "extracting", "extracted", "failed", "cancelled"]),
  progress: z.number(),
  requested: z.boolean(),
  interval_seconds: z.number(),
  frame_count: z.number(),
  expected_count: z.number().nullable(),
  frame_directory: z.string().nullable(),
  manifest_path: z.string().nullable(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  retry_count: z.number(),
  error: z.string().nullable(),
});
export const framePageSchema = z.object({
  items: z.array(
    z.object({
      filename: z.string(),
      requested_timestamp: z.number(),
      actual_timestamp: z.number(),
      width: z.number(),
      height: z.number(),
    }),
  ),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
  video_duration: z.number(),
});
const bulkSchema = z.object({
  started_ids: z.array(z.number()),
  errors: z.array(z.object({ video_id: z.number(), reason: z.string() })),
});
export function getExtraction(videoId: number, signal?: AbortSignal) {
  return apiGet(`videos/${videoId}/extraction`, extractionSchema, signal);
}
export function startExtraction(videoId: number, interval?: number) {
  return apiPost(
    `videos/${videoId}/extraction`,
    { interval_seconds: interval },
    extractionSchema,
  );
}
export function extractionAction(videoId: number, action: "cancel" | "retry") {
  return apiPost(
    `videos/${videoId}/extraction/${action}`,
    {},
    extractionSchema,
  );
}
export function deleteFrames(videoId: number) {
  return apiDelete(`videos/${videoId}/extraction`);
}
export function extractSelected(videoIds: number[], interval?: number) {
  return apiPost(
    "videos/extractions/bulk",
    { video_ids: videoIds, interval_seconds: interval },
    bulkSchema,
  );
}
export function getFrames(videoId: number, page: number, signal?: AbortSignal) {
  return apiGet(
    `videos/${videoId}/frames?page=${page}&page_size=12`,
    framePageSchema,
    signal,
  );
}
export function frameUrl(videoId: number, filename: string) {
  return `${config.apiUrl.replace(/\/$/, "")}/videos/${videoId}/frames/${encodeURIComponent(filename)}`;
}
export function getExtractionConfig(signal?: AbortSignal) {
  return apiGet(
    "videos/extractions/config",
    z.object({ interval_seconds: z.number() }),
    signal,
  );
}
