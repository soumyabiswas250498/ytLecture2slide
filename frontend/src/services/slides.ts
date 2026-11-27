import { z } from "zod";
import { apiDelete, apiGet, apiPost } from "@/services/api";
import { config } from "@/lib/config";

const stateSchema = z.object({
  video_id: z.number(),
  status: z.enum([
    "pending",
    "processing",
    "processed",
    "failed",
    "cancelled",
    "cleaned",
  ]),
  requested: z.boolean(),
  progress: z.number(),
  input_count: z.number(),
  completed_count: z.number(),
  additional_count: z.number(),
  output_count: z.number(),
  duplicate_count: z.number(),
  reconstructed_count: z.number(),
  review_count: z.number(),
  output_directory: z.string().nullable(),
  error: z.string().nullable(),
});
const slideSchema = z.object({
  slide_id: z.string(),
  source_frame_ids: z.array(z.string()),
  source_timestamps: z.array(z.number()),
  additional_sampled_timestamps: z.array(z.number()),
  processed_image_path: z.string(),
  cropped_image_path: z.string(),
  original_image_path: z.string(),
  obstruction_mask_path: z.string().nullable().optional(),
  reconstruction_method: z.string(),
  quality_category: z
    .enum([
      "clear_original",
      "improved_original",
      "reconstructed",
      "incomplete",
      "uncertain",
    ])
    .optional(),
  selection_reason: z.string().optional(),
  fallback: z.boolean(),
  incomplete: z.boolean(),
  manual_review: z.boolean(),
  warnings: z.array(z.string()),
  board_coordinates: z.array(z.tuple([z.number(), z.number()])),
  quality: z.object({
    obstruction_fraction: z.number(),
    unresolved_fraction: z.number(),
    visible_coverage: z.number().optional(),
    crop_reliability: z.string().optional(),
    grouping_confidence: z.string().optional(),
    measurement_kind: z.literal("heuristic_not_accuracy"),
    verified_accuracy: z.null(),
  }),
});
export const slidePageSchema = z.object({
  items: z.array(slideSchema),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
  generation: z.string(),
  warnings: z.array(z.string()),
});
export type Crop = { left: number; top: number; right: number; bottom: number };
export function getSlideState(id: number, signal?: AbortSignal) {
  return apiGet(`videos/${id}/slide-processing`, stateSchema, signal);
}
export function processSlides(id: number, crop?: Crop, reprocess = false) {
  return apiPost(
    `videos/${id}/slide-processing`,
    {
      ...(crop ? { configuration: { crop } } : {}),
      reprocess,
    },
    stateSchema,
  );
}
export function slideAction(id: number, action: "retry" | "cancel") {
  return apiPost(`videos/${id}/slide-processing/${action}`, {}, stateSchema);
}
export function deleteSlides(id: number) {
  return apiDelete(`videos/${id}/slide-processing`);
}
export function processSelected(ids: number[]) {
  return apiPost(
    "videos/slides/bulk",
    { video_ids: ids },
    z.object({
      started_ids: z.array(z.number()),
      errors: z.array(z.object({ video_id: z.number(), reason: z.string() })),
    }),
  );
}
export function getSlides(
  id: number,
  page: number,
  signal?: AbortSignal,
  pageSize = 6,
) {
  return apiGet(
    `videos/${id}/slides?page=${page}&page_size=${pageSize}`,
    slidePageSchema,
    signal,
  );
}
export function slideUrl(id: number, generation: string, filename: string) {
  return `${config.apiUrl.replace(/\/$/, "")}/videos/${id}/slides/${encodeURIComponent(generation)}/${encodeURIComponent(filename)}`;
}
