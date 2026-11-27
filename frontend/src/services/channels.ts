import { z } from "zod";
import {
  apiDelete,
  apiDownloadText,
  apiGet,
  apiPatch,
  apiPost,
  apiUpload,
} from "@/services/api";

export const channelSchema = z.object({
  id: z.number(),
  name: z.string(),
  channel_url: z.string(),
  youtube_channel_id: z.string().nullable(),
  sample_video_url: z.string().nullable(),
  search_keyword: z.string(),
  is_active: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const channelSummarySchema = z.object({
  total: z.number(),
  active: z.number(),
  inactive: z.number(),
});

export const channelListResponseSchema = z.object({
  items: z.array(channelSchema),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
  total_pages: z.number(),
  summary: channelSummarySchema,
});

export const csvRowIssueSchema = z.object({
  row_number: z.number(),
  channel_name: z.string().nullable(),
  channel_url: z.string().nullable(),
  reason: z.string(),
});

export const csvImportResponseSchema = z.object({
  total_rows: z.number(),
  imported_count: z.number(),
  skipped_count: z.number(),
  invalid_count: z.number(),
  imported: z.array(channelSchema),
  skipped: z.array(csvRowIssueSchema),
  errors: z.array(csvRowIssueSchema),
});

export type Channel = z.infer<typeof channelSchema>;
export type ChannelSummary = z.infer<typeof channelSummarySchema>;
export type ChannelListResponse = z.infer<typeof channelListResponseSchema>;
export type CsvRowIssue = z.infer<typeof csvRowIssueSchema>;
export type CsvImportResponse = z.infer<typeof csvImportResponseSchema>;

export interface ListChannelsParams {
  search?: string;
  isActive?: boolean | null;
  page?: number;
  pageSize?: number;
}

export interface ChannelCreatePayload {
  name: string;
  channel_url: string;
  youtube_channel_id?: string | null;
  sample_video_url?: string | null;
  search_keyword?: string | null;
  is_active: boolean;
}

export interface ChannelUpdatePayload {
  name?: string;
  channel_url?: string;
  youtube_channel_id?: string | null;
  sample_video_url?: string | null;
  search_keyword?: string;
  is_active?: boolean;
}

function buildFilterQuery(params: ListChannelsParams): string {
  const searchParams = new URLSearchParams();
  if (params.search?.trim()) {
    searchParams.set("search", params.search.trim());
  }
  if (params.isActive !== undefined && params.isActive !== null) {
    searchParams.set("is_active", String(params.isActive));
  }
  if (params.page !== undefined) {
    searchParams.set("page", String(params.page));
  }
  if (params.pageSize !== undefined) {
    searchParams.set("page_size", String(params.pageSize));
  }
  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

export function listChannels(
  params: ListChannelsParams,
  signal?: AbortSignal,
): Promise<ChannelListResponse> {
  return apiGet(
    `channels${buildFilterQuery(params)}`,
    channelListResponseSchema,
    signal,
  );
}

export function createChannel(payload: ChannelCreatePayload): Promise<Channel> {
  return apiPost("channels", payload, channelSchema);
}

export function updateChannel(
  channelId: number,
  payload: ChannelUpdatePayload,
): Promise<Channel> {
  return apiPatch(`channels/${channelId}`, payload, channelSchema);
}

export function deleteChannel(channelId: number): Promise<void> {
  return apiDelete(`channels/${channelId}`);
}

export function importChannelsCsv(file: File): Promise<CsvImportResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiUpload("channels/import", formData, csvImportResponseSchema);
}

export function exportChannelsCsv(
  params: Omit<ListChannelsParams, "page" | "pageSize"> = {},
): Promise<string> {
  return apiDownloadText(`channels/export${buildFilterQuery(params)}`);
}

export function downloadChannelsTemplate(): Promise<string> {
  return apiDownloadText("channels/template");
}
