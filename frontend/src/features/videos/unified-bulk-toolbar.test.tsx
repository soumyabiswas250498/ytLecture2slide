import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as extractionsApi from "@/services/extractions";
import * as slidesApi from "@/services/slides";
import type { Video } from "@/services/videos";
import { UnifiedBulkToolbar } from "./unified-bulk-toolbar";

vi.mock("@/services/videos");
vi.mock("@/services/extractions");
vi.mock("@/services/slides");

function makeVideo(id: number, overrides: Partial<Video> = {}): Video {
  return {
    id,
    channel_id: 1,
    youtube_video_id: `yt_${id}`,
    title: `Lecture ${id}`,
    description: "",
    video_url: `https://www.youtube.com/watch?v=yt_${id}`,
    thumbnail_url: null,
    duration_seconds: 1200,
    published_at: "2026-11-26T10:00:00Z",
    livestream_status: "none",
    discovered_at: "2026-11-26T10:00:00Z",
    processing_status: "pending",
    download_status: "pending",
    local_video_path: null,
    actual_resolution: null,
    file_size_bytes: null,
    video_codec: null,
    download_progress: 0,
    downloaded_bytes: 0,
    total_bytes: null,
    download_requested: false,
    download_started_at: null,
    download_completed_at: null,
    download_retry_count: 0,
    download_error: null,
    created_at: "2026-11-26T10:00:00Z",
    updated_at: "2026-11-26T10:00:00Z",
    is_excluded: false,
    excluded_keywords: [],
    ...overrides,
  };
}

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

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(extractionsApi.getExtractionConfig).mockResolvedValue({
    interval_seconds: 60,
  });
});

describe("UnifiedBulkToolbar", () => {
  it("disables all actions when no videos are selected", () => {
    render(
      <UnifiedBulkToolbar
        selectedVideos={[]}
        interval={undefined}
        onIntervalChange={vi.fn()}
        onClearSelection={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.getByText("0 selected")).toBeVisible();
    expect(screen.getByRole("button", { name: "Download (0)" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Extract Frames (0)" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Process Slides (0)" }),
    ).toBeDisabled();
  });

  it("computes mixed eligibility, processes only eligible videos, and shows video-title details with dismissal", async () => {
    const user = userEvent.setup();
    const pendingVideo = makeVideo(1, {
      title: "Polity Class 1",
      download_status: "pending",
    });
    const downloadedVideo = makeVideo(2, {
      title: "History Class 2",
      download_status: "downloaded",
    });
    const extractedVideo = makeVideo(3, {
      title: "Geography Class 3",
      download_status: "downloaded",
    });

    vi.mocked(extractionsApi.getExtraction).mockImplementation(async (id) => ({
      video_id: id,
      status: id === 3 ? "extracted" : "pending",
      progress: id === 3 ? 100 : 0,
      requested: false,
      interval_seconds: 60,
      frame_count: id === 3 ? 10 : 0,
      expected_count: id === 3 ? 10 : null,
      frame_directory: id === 3 ? "/frames/3" : null,
      manifest_path: id === 3 ? "/frames/3/manifest.json" : null,
      started_at: null,
      completed_at: null,
      retry_count: 0,
      error: null,
    }));

    vi.mocked(slidesApi.getSlideState).mockImplementation(async (id) => ({
      video_id: id,
      status: "pending",
      requested: false,
      progress: 0,
      input_count: 0,
      completed_count: 0,
      additional_count: 0,
      output_count: 0,
      duplicate_count: 0,
      reconstructed_count: 0,
      review_count: 0,
      output_directory: null,
      error: null,
    }));

    vi.mocked(extractionsApi.extractSelected).mockResolvedValue({
      started_ids: [2],
      errors: [],
    });

    vi.mocked(slidesApi.processSelected).mockResolvedValue({
      started_ids: [],
      errors: [{ video_id: 3, reason: "Insufficient disk space" }],
    });

    render(
      <UnifiedBulkToolbar
        selectedVideos={[pendingVideo, downloadedVideo, extractedVideo]}
        interval={undefined}
        onIntervalChange={vi.fn()}
        onClearSelection={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Download (1)" }),
      ).toBeEnabled();
      expect(
        screen.getByRole("button", { name: "Extract Frames (1)" }),
      ).toBeEnabled();
      expect(
        screen.getByRole("button", { name: "Process Slides (1)" }),
      ).toBeEnabled();
    });

    // Extract Frames on mixed selection -> sends only [2], explains why 1 and 3 excluded using titles
    await user.click(
      screen.getByRole("button", { name: "Extract Frames (1)" }),
    );
    expect(extractionsApi.extractSelected).toHaveBeenCalledWith([2], undefined);
    expect(
      await screen.findByText("Frame extraction: 1 video started · 2 excluded"),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Details/i }));
    expect(
      screen.getByText(
        "Polity Class 1: Excluded — Source video not downloaded yet",
      ),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Geography Class 3: Excluded — Frames already extracted",
      ),
    ).toBeVisible();

    await user.click(
      screen.getByRole("button", { name: "Dismiss notification" }),
    );
    expect(
      screen.queryByText("Frame extraction: 1 video started · 2 excluded"),
    ).not.toBeInTheDocument();

    // Process Slides -> API error uses video title instead of Video #3
    await user.click(
      screen.getByRole("button", { name: "Process Slides (1)" }),
    );
    expect(
      await screen.findByText(
        "Slide processing: 0 videos started · 2 excluded · 1 failed",
      ),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: /Details/i }));
    expect(
      screen.getByText("Geography Class 3: Failed — Insufficient disk space"),
    ).toBeVisible();
  });
});
