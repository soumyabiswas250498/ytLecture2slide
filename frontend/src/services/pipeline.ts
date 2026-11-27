import { z } from "zod";
import { apiGet, apiPost } from "@/services/api";

export const pipelineTriggerTypeSchema = z.enum(["manual", "scheduled"]);
export const pipelineRunStatusSchema = z.enum([
  "queued",
  "running",
  "completed",
  "completed_with_errors",
  "failed",
  "cancelled",
]);
export const pipelineStageSchema = z.enum([
  "idle",
  "discovering",
  "evaluating",
  "downloading",
  "extracting",
  "processing_slides",
  "generating_pdf",
  "validating_pdf",
  "cleaning",
  "completed",
]);
export const pipelineVideoStatusSchema = z.enum([
  "pending",
  "running",
  "completed",
  "skipped",
  "excluded",
  "failed",
  "cancelled",
]);

export const pipelineLogEntrySchema = z.object({
  timestamp: z.string(),
  level: z.enum(["INFO", "WARNING", "ERROR"]),
  video_id: z.number().int().nullable().optional(),
  stage: z.string().nullable().optional(),
  message: z.string(),
});

export const pipelineRunVideoSchema = z.object({
  id: z.number().int(),
  run_id: z.number().int(),
  video_id: z.number().int(),
  video_title: z.string(),
  youtube_video_id: z.string(),
  status: pipelineVideoStatusSchema,
  current_stage: pipelineStageSchema,
  stage_progress: z.number(),
  retry_count: z.number().int(),
  is_retryable: z.boolean(),
  error: z.string().nullable().optional(),
  cleaned: z.boolean(),
  started_at: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
});

export const pipelineRunSchema = z.object({
  id: z.number().int(),
  trigger_type: pipelineTriggerTypeSchema,
  status: pipelineRunStatusSchema,
  current_stage: pipelineStageSchema,
  current_video_id: z.number().int().nullable().optional(),
  current_video_title: z.string().nullable().optional(),
  current_stage_progress: z.number(),
  total_videos: z.number().int(),
  completed_videos: z.number().int(),
  excluded_videos: z.number().int(),
  skipped_videos: z.number().int(),
  failed_videos: z.number().int(),
  cancelled_videos: z.number().int(),
  last_error: z.string().nullable().optional(),
  reprocess_existing: z.boolean(),
  target_video_ids: z.array(z.number().int()),
  started_at: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  estimated_remaining_seconds: z.number().nullable().optional(),
  videos: z.array(pipelineRunVideoSchema),
  logs: z.array(pipelineLogEntrySchema),
});

export const pipelineRunPageSchema = z.object({
  items: z.array(pipelineRunSchema),
  total: z.number().int(),
  page: z.number().int(),
  page_size: z.number().int(),
  total_pages: z.number().int(),
});

export const schedulerStatusSchema = z.object({
  enabled: z.boolean(),
  frequency: z.literal("daily"),
  time: z.string(),
  timezone: z.string(),
  next_run_at: z.string().nullable().optional(),
  last_run_at: z.string().nullable().optional(),
  is_running: z.boolean(),
});

export type PipelineRun = z.infer<typeof pipelineRunSchema>;
export type PipelineRunPage = z.infer<typeof pipelineRunPageSchema>;
export type SchedulerStatus = z.infer<typeof schedulerStatusSchema>;

export function getSchedulerStatus(
  signal?: AbortSignal,
): Promise<SchedulerStatus> {
  return apiGet("pipeline/scheduler", schedulerStatusSchema, signal);
}

export function listPipelineRuns(
  page = 1,
  pageSize = 20,
  signal?: AbortSignal,
): Promise<PipelineRunPage> {
  return apiGet(
    `pipeline/runs?page=${page}&page_size=${pageSize}`,
    pipelineRunPageSchema,
    signal,
  );
}

export function getActivePipelineRun(
  signal?: AbortSignal,
): Promise<PipelineRun | null> {
  return apiGet("pipeline/runs/active", pipelineRunSchema.nullable(), signal);
}

export function getPipelineRun(
  runId: number,
  signal?: AbortSignal,
): Promise<PipelineRun> {
  return apiGet(`pipeline/runs/${runId}`, pipelineRunSchema, signal);
}

export function triggerPipelineRun(params?: {
  video_ids?: number[];
  reprocess_existing?: boolean;
}): Promise<PipelineRun> {
  return apiPost("pipeline/runs", params ?? {}, pipelineRunSchema);
}

export function cancelPipelineRun(runId: number): Promise<PipelineRun> {
  return apiPost(`pipeline/runs/${runId}/cancel`, {}, pipelineRunSchema);
}

export function retryFailedPipelineRun(runId: number): Promise<PipelineRun> {
  return apiPost(`pipeline/runs/${runId}/retry-failed`, {}, pipelineRunSchema);
}
