import { z } from "zod";
import { apiDelete, apiGet, apiPost, ApiError } from "@/services/api";
import { config } from "@/lib/config";

export const pdfStatusSchema = z.enum([
  "pending",
  "generating",
  "generated",
  "failed",
  "cancelled",
]);
export type PdfStatus = z.infer<typeof pdfStatusSchema>;

export const pdfCompressionModeSchema = z.enum([
  "lossless",
  "maximum_quality",
  "high_quality",
  "compact",
]);
export type PdfCompressionMode = z.infer<typeof pdfCompressionModeSchema>;

export const PDF_COMPRESSION_LABELS: Record<PdfCompressionMode, string> = {
  lossless: "Lossless (Original PNG)",
  maximum_quality: "Maximum quality (JPEG 95)",
  high_quality: "High quality (JPEG 90)",
  compact: "Compact (JPEG 85)",
};

export const pdfStateSchema = z.object({
  video_id: z.number(),
  source_slide_generation: z.string().nullable(),
  status: pdfStatusSchema,
  requested: z.boolean(),
  progress: z.number(),
  completed_pages: z.number(),
  total_pages: z.number(),
  pdf_path: z.string().nullable(),
  pdf_filename: z.string().nullable(),
  page_count: z.number(),
  file_size_bytes: z.number(),
  compression: pdfCompressionModeSchema.optional().default("lossless"),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  retry_count: z.number(),
  error: z.string().nullable(),
});
export type PdfState = z.infer<typeof pdfStateSchema>;

export const pdfLibraryItemSchema = z.object({
  video_id: z.number(),
  youtube_video_id: z.string(),
  video_title: z.string(),
  channel_id: z.number().nullable(),
  channel_name: z.string(),
  published_at: z.string(),
  generated_at: z.string(),
  page_count: z.number(),
  file_size_bytes: z.number(),
  pdf_filename: z.string(),
  compression: pdfCompressionModeSchema.optional().default("lossless"),
  source_slide_generation: z.string().nullable(),
  is_excluded: z.boolean().optional().default(false),
});
export type PdfLibraryItem = z.infer<typeof pdfLibraryItemSchema>;

export const pdfLibraryPageSchema = z.object({
  items: z.array(pdfLibraryItemSchema),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
  total_pages: z.number(),
  total_bytes: z.number(),
  total_pages_sum: z.number(),
});
export type PdfLibraryPage = z.infer<typeof pdfLibraryPageSchema>;

export type PdfSortBy =
  "generated_at" | "published_at" | "title" | "page_count" | "file_size_bytes";
export type PdfSortOrder = "asc" | "desc";

export interface PdfListParams {
  search?: string;
  channel_id?: number;
  published_after?: string;
  published_before?: string;
  sort_by?: PdfSortBy;
  sort_order?: PdfSortOrder;
  page?: number;
  page_size?: number;
}

export function getPdfState(videoId: number, signal?: AbortSignal) {
  return apiGet(`videos/${videoId}/pdf`, pdfStateSchema, signal);
}

export function generatePdf(
  videoId: number,
  regenerate = false,
  compression?: PdfCompressionMode,
) {
  return apiPost(
    `videos/${videoId}/pdf`,
    {
      regenerate,
      ...(compression ? { configuration: { compression } } : {}),
    },
    pdfStateSchema,
  );
}

export function pdfAction(videoId: number, action: "retry" | "cancel") {
  return apiPost(`videos/${videoId}/pdf/${action}`, {}, pdfStateSchema);
}

export function deletePdf(videoId: number) {
  return apiDelete(`videos/${videoId}/pdf`);
}

export function generateSelectedPdfs(
  ids: number[],
  regenerate = false,
  compression?: PdfCompressionMode,
) {
  return apiPost(
    "pdfs/bulk",
    {
      video_ids: ids,
      regenerate,
      ...(compression ? { configuration: { compression } } : {}),
    },
    z.object({
      started_ids: z.array(z.number()),
      errors: z.array(z.object({ video_id: z.number(), reason: z.string() })),
    }),
  );
}

export function listPdfs(params: PdfListParams, signal?: AbortSignal) {
  const qs = new URLSearchParams();
  if (params.search) qs.set("search", params.search);
  if (params.channel_id !== undefined) {
    qs.set("channel_id", String(params.channel_id));
  }
  if (params.published_after) qs.set("published_after", params.published_after);
  if (params.published_before) {
    qs.set("published_before", params.published_before);
  }
  if (params.sort_by) qs.set("sort_by", params.sort_by);
  if (params.sort_order) qs.set("sort_order", params.sort_order);
  if (params.page !== undefined) qs.set("page", String(params.page));
  if (params.page_size !== undefined) {
    qs.set("page_size", String(params.page_size));
  }
  const query = qs.toString();
  return apiGet(query ? `pdfs?${query}` : "pdfs", pdfLibraryPageSchema, signal);
}

export function pdfPreviewUrl(videoId: number): string {
  return `${config.apiUrl.replace(/\/$/, "")}/pdfs/${videoId}/preview`;
}

export function pdfDownloadUrl(videoId: number): string {
  return `${config.apiUrl.replace(/\/$/, "")}/pdfs/${videoId}/download`;
}

export async function downloadPdfsZip(
  videoIds: number[],
): Promise<{ blob: Blob; filename: string; unavailableCount: number }> {
  const base = config.apiUrl.replace(/\/$/, "");
  const response = await fetch(`${base}/pdfs/download-zip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_ids: videoIds }),
  });
  if (!response.ok) {
    let message = `ZIP download failed (${response.status})`;
    try {
      const data = (await response.json()) as {
        error?: { code?: string; message?: string };
      };
      if (data?.error?.message) {
        message = data.error.message;
      }
    } catch {
      // Ignore JSON parse failure
    }
    throw new ApiError(message, response.status);
  }
  const blob = await response.blob();
  const unavailableHeader = response.headers.get("X-Unavailable-Count");
  const unavailableCount = unavailableHeader
    ? Number(unavailableHeader) || 0
    : 0;
  return {
    blob,
    filename: "lecture-slides.zip",
    unavailableCount,
  };
}
