import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { VideosPage } from "./videos-page";
import * as videosService from "@/services/videos";
import * as channelsService from "@/services/channels";

vi.mock("@/services/extractions", () => ({
  getExtractionConfig: vi.fn().mockResolvedValue({ interval_seconds: 60 }),
  getExtraction: vi.fn().mockResolvedValue({
    video_id: 1,
    status: "pending",
    requested: false,
    frame_count: 0,
    expected_count: null,
  }),
}));
vi.mock("@/services/videos");
vi.mock("@/services/channels");

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

const emptyChannels: channelsService.ChannelListResponse = {
  items: [
    {
      id: 1,
      name: "WBPSC Academy",
      channel_url: "https://www.youtube.com/@wbpsc",
      youtube_channel_id: "UC123",
      sample_video_url: null,
      search_keyword: "IDO",
      is_active: true,
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  page_size: 100,
  total_pages: 1,
  summary: { total: 1, active: 1, inactive: 0 },
};

const emptySummary: videosService.VideoSummary = {
  total: 0,
  pending: 0,
  today: 0,
  latest_discovery_at: null,
};

const emptyList: videosService.VideoList = {
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  total_pages: 1,
};

const sampleVideo: videosService.Video = {
  id: 1,
  channel_id: 1,
  youtube_video_id: "abc123",
  title: "IDO Lecture — Chapter 1",
  description: "Full description here",
  video_url: "https://www.youtube.com/watch?v=abc123",
  thumbnail_url: "https://img.youtube.com/vi/abc123/hqdefault.jpg",
  duration_seconds: 7200,
  published_at: "2025-01-15T10:00:00Z",
  livestream_status: "none",
  discovered_at: "2025-01-15T12:00:00Z",
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
  created_at: "2025-01-15T12:00:00Z",
  updated_at: "2025-01-15T12:00:00Z",
};

const videoList: videosService.VideoList = {
  items: [sampleVideo],
  total: 1,
  page: 1,
  page_size: 20,
  total_pages: 1,
};

const discoveryResult: videosService.DiscoveryRun = {
  channels_checked: 2,
  channels_skipped: 0,
  videos_found: 3,
  new_videos_added: 1,
  existing_videos_skipped: 2,
  videos_rejected_duration: 0,
  videos_rejected_filter: 0,
  livestreams_deferred: 0,
  failed_channels: [],
  api_requests_made: 5,
  search_requests_made: 2,
  quota_reset_at: null,
  duration_seconds: 1.2,
  errors: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(channelsService.listChannels).mockResolvedValue(emptyChannels);
  vi.mocked(videosService.getActiveDownloads).mockResolvedValue([]);
});

describe("VideosPage", () => {
  it("renders loading state initially", () => {
    vi.mocked(videosService.getVideoSummary).mockReturnValue(
      new Promise(() => {}),
    );
    vi.mocked(videosService.listVideos).mockReturnValue(new Promise(() => {}));
    render(<VideosPage />, { wrapper });
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders empty state when no videos exist", async () => {
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(emptySummary);
    vi.mocked(videosService.listVideos).mockResolvedValue(emptyList);
    render(<VideosPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getByText(/No videos discovered yet/i)).toBeInTheDocument(),
    );
  });

  it("renders summary cards", async () => {
    const summary: videosService.VideoSummary = {
      total: 42,
      pending: 10,
      today: 5,
      latest_discovery_at: "2025-01-15T12:00:00Z",
    };
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(summary);
    vi.mocked(videosService.listVideos).mockResolvedValue(emptyList);
    render(<VideosPage />, { wrapper });
    await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("renders video table with channel name and video data", async () => {
    vi.mocked(videosService.getVideoSummary).mockResolvedValue({
      total: 1,
      pending: 1,
      today: 1,
      latest_discovery_at: null,
    });
    vi.mocked(videosService.listVideos).mockResolvedValue(videoList);
    render(<VideosPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getByText("IDO Lecture — Chapter 1")).toBeInTheDocument(),
    );
    expect(screen.getByText("2h 0m")).toBeInTheDocument();
    expect(
      screen.getByRole("cell", { name: "WBPSC Academy" }),
    ).toBeInTheDocument();
    const watchLink = screen.getByRole("link", { name: /watch/i });
    expect(watchLink).toHaveAttribute(
      "href",
      "https://www.youtube.com/watch?v=abc123",
    );
  });

  it("filters by channel and triggers individual channel discovery", async () => {
    const user = userEvent.setup();
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(emptySummary);
    vi.mocked(videosService.listVideos).mockResolvedValue(emptyList);
    vi.mocked(videosService.runChannelDiscovery).mockResolvedValue(
      discoveryResult,
    );
    render(<VideosPage />, { wrapper });

    const channelSelect = await screen.findByLabelText("Filter by channel");
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: "WBPSC Academy" }),
      ).toBeInTheDocument(),
    );
    await user.selectOptions(channelSelect, "1");

    await waitFor(() =>
      expect(videosService.listVideos).toHaveBeenLastCalledWith(
        expect.objectContaining({ channel_id: 1 }),
        expect.any(AbortSignal),
      ),
    );

    const discoverChannelBtn = screen.getByRole("button", {
      name: /Discover WBPSC Academy/i,
    });
    await user.click(discoverChannelBtn);
    await waitFor(() =>
      expect(videosService.runChannelDiscovery).toHaveBeenCalledWith(1),
    );
  });

  it("filters by publication date range", async () => {
    const user = userEvent.setup();
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(emptySummary);
    vi.mocked(videosService.listVideos).mockResolvedValue(emptyList);
    render(<VideosPage />, { wrapper });

    const afterInput = await screen.findByLabelText("Published after");
    await user.type(afterInput, "2025-01-10");

    await waitFor(() =>
      expect(videosService.listVideos).toHaveBeenLastCalledWith(
        expect.objectContaining({
          published_after: "2025-01-10T00:00:00+05:30",
        }),
        expect.any(AbortSignal),
      ),
    );
  });

  it("triggers discovery and shows result banner", async () => {
    const user = userEvent.setup();
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(emptySummary);
    vi.mocked(videosService.listVideos).mockResolvedValue(emptyList);
    vi.mocked(videosService.runDiscovery).mockResolvedValue(discoveryResult);
    render(<VideosPage />, { wrapper });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /discover videos/i }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /discover videos/i }));
    await waitFor(() =>
      expect(screen.getByText(/Discovery complete/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/1 new video/i)).toBeInTheDocument();
  });

  it("shows error message when discovery fails", async () => {
    const user = userEvent.setup();
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(emptySummary);
    vi.mocked(videosService.listVideos).mockResolvedValue(emptyList);
    vi.mocked(videosService.runDiscovery).mockRejectedValue(
      new Error("YOUTUBE_API_KEY is not configured."),
    );
    render(<VideosPage />, { wrapper });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /discover videos/i }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /discover videos/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(
      screen.getByText(/YOUTUBE_API_KEY is not configured/i),
    ).toBeInTheDocument();
  });

  it("shows error state on list fetch failure", async () => {
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(emptySummary);
    vi.mocked(videosService.listVideos).mockRejectedValue(
      new Error("Cannot reach the backend."),
    );
    render(<VideosPage />, { wrapper });
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });

  it("renders thumbnail image when available", async () => {
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(emptySummary);
    vi.mocked(videosService.listVideos).mockResolvedValue(videoList);
    render(<VideosPage />, { wrapper });
    await waitFor(() =>
      expect(
        screen.getByRole("img", { name: /Thumbnail for/i }),
      ).toBeInTheDocument(),
    );
  });

  it("triggers individual video download", async () => {
    const user = userEvent.setup();
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(emptySummary);
    vi.mocked(videosService.listVideos).mockResolvedValue(videoList);
    vi.mocked(videosService.startVideoDownload).mockResolvedValue({
      ...sampleVideo,
      download_status: "downloading",
    });

    render(<VideosPage />, { wrapper });
    const dlBtn = await screen.findByRole("button", {
      name: /Download IDO Lecture/i,
    });
    await user.click(dlBtn);
    await waitFor(() =>
      expect(videosService.startVideoDownload).toHaveBeenCalledWith(1),
    );
  });

  it("supports selecting videos and triggering bulk download", async () => {
    const user = userEvent.setup();
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(emptySummary);
    vi.mocked(videosService.listVideos).mockResolvedValue(videoList);
    vi.mocked(videosService.startBulkDownload).mockResolvedValue({
      started_ids: [1],
      skipped: [],
      errors: [],
    });

    render(<VideosPage />, { wrapper });
    const checkbox = await screen.findByLabelText(/Select IDO Lecture/i);
    await user.click(checkbox);

    const bulkBtn = screen.getByRole("button", {
      name: /Download Selected \(1\)/i,
    });
    await user.click(bulkBtn);

    await waitFor(() =>
      expect(videosService.startBulkDownload).toHaveBeenCalledWith([1]),
    );
    expect(
      await screen.findByText(/Bulk download requested: 1 started/i),
    ).toBeInTheDocument();
  });

  it("displays live download progress, speed, ETA, and cancel action", async () => {
    const user = userEvent.setup();
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(emptySummary);
    vi.mocked(videosService.listVideos).mockResolvedValue({
      ...videoList,
      items: [{ ...sampleVideo, download_status: "downloading" }],
    });
    vi.mocked(videosService.getActiveDownloads).mockResolvedValue([
      {
        video_id: 1,
        youtube_video_id: "abc123",
        status: "downloading",
        progress_percent: 62.5,
        downloaded_bytes: 5_000_000,
        total_bytes: 8_000_000,
        speed_bytes_per_sec: 1_048_576,
        eta_seconds: 90,
        is_live: true,
        error: null,
      },
    ]);
    vi.mocked(videosService.cancelVideoDownload).mockResolvedValue({
      ...sampleVideo,
      download_status: "cancelled",
    });

    render(<VideosPage />, { wrapper });
    expect(await screen.findByText(/62\.5%/)).toBeInTheDocument();
    expect(screen.getByText(/1\.0 MB\/s/)).toBeInTheDocument();
    expect(screen.getByText(/ETA 1m 30s/)).toBeInTheDocument();

    const cancelBtn = screen.getByRole("button", {
      name: /Cancel download for IDO Lecture/i,
    });
    await user.click(cancelBtn);
    await waitFor(() =>
      expect(videosService.cancelVideoDownload).toHaveBeenCalledWith(1),
    );
  });

  it("displays error and retry action for failed download, and delete confirmation for downloaded", async () => {
    const user = userEvent.setup();
    vi.mocked(videosService.getVideoSummary).mockResolvedValue(emptySummary);
    vi.mocked(videosService.listVideos).mockResolvedValue({
      ...videoList,
      items: [
        {
          ...sampleVideo,
          id: 1,
          title: "Failed Lecture",
          download_status: "failed",
          download_error: "Network timeout",
        },
        {
          ...sampleVideo,
          id: 2,
          youtube_video_id: "xyz789",
          title: "Downloaded Lecture",
          download_status: "downloaded",
          actual_resolution: "1280x720",
          file_size_bytes: 10_485_760,
        },
      ],
      total: 2,
    });
    vi.mocked(videosService.retryVideoDownload).mockResolvedValue({
      ...sampleVideo,
      download_status: "downloading",
    });
    vi.mocked(videosService.deleteLocalVideo).mockResolvedValue({
      ...sampleVideo,
      id: 2,
      download_status: "pending",
    });

    render(<VideosPage />, { wrapper });
    expect(await screen.findByText("Network timeout")).toBeInTheDocument();
    expect(screen.getByText(/1280x720 · 10\.0 MB/)).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: /Retry download for Failed Lecture/i,
      }),
    );
    await waitFor(() =>
      expect(videosService.retryVideoDownload).toHaveBeenCalledWith(1),
    );

    await user.click(
      screen.getByRole("button", {
        name: /Delete local video for Downloaded Lecture/i,
      }),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Delete local file/i }),
    );
    await waitFor(() =>
      expect(videosService.deleteLocalVideo).toHaveBeenCalledWith(2),
    );
  });
});
