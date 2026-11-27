import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as pipelineApi from "@/services/pipeline";
import { ProcessingJobsPage } from "./processing-jobs-page";

vi.mock("@/services/pipeline");

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      {children}
    </QueryClientProvider>
  );
}

const sampleRun: pipelineApi.PipelineRun = {
  id: 1,
  trigger_type: "manual",
  status: "completed_with_errors",
  current_stage: "completed",
  current_video_id: null,
  current_video_title: null,
  current_stage_progress: 100,
  total_videos: 2,
  completed_videos: 1,
  excluded_videos: 0,
  skipped_videos: 0,
  failed_videos: 1,
  cancelled_videos: 0,
  last_error: "Transient network timeout",
  reprocess_existing: false,
  target_video_ids: [],
  started_at: "2026-11-27T03:00:00Z",
  completed_at: "2026-11-27T03:05:00Z",
  created_at: "2026-11-27T03:00:00Z",
  updated_at: "2026-11-27T03:05:00Z",
  estimated_remaining_seconds: 0,
  videos: [
    {
      id: 10,
      run_id: 1,
      video_id: 5,
      video_title: "Lecture 1",
      youtube_video_id: "abc123",
      status: "completed",
      current_stage: "completed",
      stage_progress: 100,
      retry_count: 0,
      is_retryable: true,
      error: null,
      cleaned: true,
      started_at: "2026-11-27T03:00:00Z",
      completed_at: "2026-11-27T03:02:00Z",
    },
    {
      id: 11,
      run_id: 1,
      video_id: 6,
      video_title: "Lecture 2",
      youtube_video_id: "def456",
      status: "failed",
      current_stage: "downloading",
      stage_progress: 0,
      retry_count: 3,
      is_retryable: true,
      error: "Transient network timeout",
      cleaned: false,
      started_at: "2026-11-27T03:02:00Z",
      completed_at: "2026-11-27T03:05:00Z",
    },
  ],
  logs: [
    {
      timestamp: "2026-11-27T03:00:00Z",
      level: "INFO",
      video_id: null,
      stage: null,
      message: "Pipeline run #1 started.",
    },
  ],
};

describe("ProcessingJobsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(pipelineApi.getSchedulerStatus).mockResolvedValue({
      enabled: true,
      frequency: "daily",
      time: "03:00",
      timezone: "Asia/Kolkata",
      next_run_at: "2026-11-28T03:00:00+05:30",
      last_run_at: null,
      is_running: false,
    });
    vi.mocked(pipelineApi.getActivePipelineRun).mockResolvedValue(null);
    vi.mocked(pipelineApi.listPipelineRuns).mockResolvedValue({
      items: [sampleRun],
      total: 1,
      page: 1,
      page_size: 15,
      total_pages: 1,
    });
    vi.mocked(pipelineApi.triggerPipelineRun).mockResolvedValue({
      ...sampleRun,
      id: 2,
      status: "running",
      current_stage: "discovering",
    });
    vi.mocked(pipelineApi.retryFailedPipelineRun).mockResolvedValue({
      ...sampleRun,
      id: 3,
      status: "running",
      current_stage: "evaluating",
    });
  });

  it("displays scheduler status, run history, Run Now, Retry Failed, and logs modal", async () => {
    const user = userEvent.setup();
    render(<ProcessingJobsPage />, { wrapper });

    expect(await screen.findByText("03:00 IST")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();

    // Open logs modal
    await user.click(
      screen.getByRole("button", { name: "View logs for run #1" }),
    );
    expect(
      await screen.findByText("Run #1 Execution Logs"),
    ).toBeInTheDocument();
    expect(screen.getByText("Pipeline run #1 started.")).toBeInTheDocument();
    await user.keyboard("{Escape}");

    // Trigger Retry Failed
    await user.click(
      screen.getByRole("button", { name: "Retry failed videos in run #1" }),
    );
    await waitFor(() =>
      expect(pipelineApi.retryFailedPipelineRun).toHaveBeenCalledWith(1),
    );

    // Trigger Run Now
    await user.click(screen.getByRole("button", { name: "Run Now" }));
    await waitFor(() =>
      expect(pipelineApi.triggerPipelineRun).toHaveBeenCalledWith({}),
    );
  });
});
