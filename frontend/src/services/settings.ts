import { z } from "zod";
import { apiGet, apiPut } from "@/services/api";
import {
  pdfCompressionModeSchema,
  type PdfCompressionMode,
} from "@/services/pdfs";

export const exclusionKeywordsSchema = z.object({
  keywords: z.array(z.string()),
  suggested_keywords: z.array(z.string()),
  updated_at: z.string().nullable().optional(),
  reevaluated_count: z.number().int().optional().default(0),
  excluded_video_count: z.number().int().optional().default(0),
  eligible_video_count: z.number().int().optional().default(0),
});

export type ExclusionKeywordsResponse = z.infer<typeof exclusionKeywordsSchema>;

export function getExclusionKeywords(
  signal?: AbortSignal,
): Promise<ExclusionKeywordsResponse> {
  return apiGet("settings/exclusion-keywords", exclusionKeywordsSchema, signal);
}

export function updateExclusionKeywords(
  keywords: string[],
): Promise<ExclusionKeywordsResponse> {
  return apiPut(
    "settings/exclusion-keywords",
    { keywords },
    exclusionKeywordsSchema,
  );
}

export const pdfCompressionOptionSchema = z.object({
  mode: pdfCompressionModeSchema,
  label: z.string(),
  description: z.string(),
});

export const pdfSettingsSchema = z.object({
  compression: pdfCompressionModeSchema,
  default_compression: pdfCompressionModeSchema,
  options: z.array(pdfCompressionOptionSchema),
  updated_at: z.string().nullable().optional(),
});

export type PdfSettingsResponse = z.infer<typeof pdfSettingsSchema>;

export function getPdfSettings(
  signal?: AbortSignal,
): Promise<PdfSettingsResponse> {
  return apiGet("settings/pdf", pdfSettingsSchema, signal);
}

export function updatePdfSettings(
  compression: PdfCompressionMode,
): Promise<PdfSettingsResponse> {
  return apiPut("settings/pdf", { compression }, pdfSettingsSchema);
}

export const pipelineSettingsSchema = z.object({
  scheduler_enabled: z.boolean(),
  scheduler_frequency: z.literal("daily"),
  scheduler_time: z.string(),
  timezone: z.string(),
  discovery_lookback_days: z.number().int().min(1).max(30),
  extraction_interval_seconds: z.number().min(1).max(3600),
  pipeline_concurrent_limit: z.number().int().min(1).max(3),
  pipeline_retry_attempts: z.number().int().min(0).max(10),
  auto_cleanup_enabled: z.boolean(),
  min_free_disk_mb: z.number().int().min(50).max(102400),
  updated_at: z.string().nullable().optional(),
});

export type PipelineSettings = z.infer<typeof pipelineSettingsSchema>;

export function getPipelineSettings(
  signal?: AbortSignal,
): Promise<PipelineSettings> {
  return apiGet("settings/pipeline", pipelineSettingsSchema, signal);
}

export function updatePipelineSettings(
  payload: Omit<PipelineSettings, "updated_at">,
): Promise<PipelineSettings> {
  return apiPut("settings/pipeline", payload, pipelineSettingsSchema);
}
