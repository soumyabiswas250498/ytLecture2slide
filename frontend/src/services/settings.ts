import { z } from "zod";
import { apiGet, apiPut } from "@/services/api";

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
