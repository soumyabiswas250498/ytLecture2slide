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
