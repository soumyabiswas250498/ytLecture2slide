import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as api from "@/services/extractions";
import { ExtractionControls, ExtractionToolbar } from "./extraction-controls";
import { FramePreview } from "./frame-preview";

vi.mock("@/services/extractions");
const state = {
  video_id: 1,
  status: "pending" as const,
  requested: false,
  progress: 0,
  interval_seconds: 60,
  frame_count: 0,
  expected_count: null,
  frame_directory: null,
  manifest_path: null,
  started_at: null,
  completed_at: null,
  retry_count: 0,
  error: null,
};
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
  vi.mocked(api.getExtraction).mockResolvedValue(state);
  vi.mocked(api.getExtractionConfig).mockResolvedValue({
    interval_seconds: 60,
  });
  vi.mocked(api.startExtraction).mockResolvedValue(state);
  vi.mocked(api.extractionAction).mockResolvedValue(state);
});
describe("Frame extraction controls", () => {
  it("starts extraction with the chosen interval", async () => {
    render(<ExtractionControls videoId={1} downloaded interval={30} />, {
      wrapper,
    });
    await userEvent.click(
      await screen.findByRole("button", { name: "Extract Frames" }),
    );
    expect(api.startExtraction).toHaveBeenCalledWith(1, 30);
  });
  it("shows real progress and cancels active extraction", async () => {
    vi.mocked(api.getExtraction).mockResolvedValue({
      ...state,
      status: "extracting",
      requested: true,
      frame_count: 2,
      expected_count: 5,
      progress: 40,
    });
    render(<ExtractionControls videoId={1} downloaded />, { wrapper });
    expect(await screen.findByText("2 / 5 frames")).toBeVisible();
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "40");
    await userEvent.click(
      screen.getByRole("button", { name: "Cancel extraction" }),
    );
    expect(api.extractionAction).toHaveBeenCalledWith(1, "cancel");
  });
  it("retries failure and confirms deletion", async () => {
    vi.mocked(api.getExtraction).mockResolvedValue({
      ...state,
      status: "failed",
      error: "Source is corrupted.",
    });
    render(<ExtractionControls videoId={1} downloaded />, { wrapper });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Source is corrupted.",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Retry extraction" }),
    );
    expect(api.extractionAction).toHaveBeenCalledWith(1, "retry");
    await userEvent.click(
      screen.getByRole("button", { name: "Delete frames" }),
    );
    expect(api.deleteFrames).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm delete frames" }),
    );
    expect(api.deleteFrames).toHaveBeenCalledWith(1);
  });
  it("uses configured defaults and reports bulk per-video failures", async () => {
    vi.mocked(api.extractSelected).mockResolvedValue({
      started_ids: [1],
      errors: [{ video_id: 2, reason: "Source unavailable" }],
    });
    render(
      <ExtractionToolbar
        selectedIds={[1, 2]}
        interval={undefined}
        setInterval={vi.fn()}
      />,
      { wrapper },
    );
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(60));
    await userEvent.click(
      screen.getByRole("button", { name: "Extract selected frames" }),
    );
    expect(api.extractSelected).toHaveBeenCalledWith([1, 2], undefined);
    expect(
      await screen.findByText("Video #2: Source unavailable"),
    ).toBeVisible();
  });
  it("paginates lazy images with source timestamps and full-resolution links", async () => {
    vi.mocked(api.frameUrl).mockReturnValue("/frame.png");
    vi.mocked(api.getFrames).mockResolvedValue({
      items: [
        {
          filename: "frame_000060000.png",
          requested_timestamp: 60,
          actual_timestamp: 60.04,
          width: 1280,
          height: 720,
        },
      ],
      total: 24,
      page: 1,
      page_size: 12,
      video_duration: 1400,
    });
    render(<FramePreview videoId={1} />, { wrapper });
    expect(await screen.findByRole("img")).toHaveAttribute("loading", "lazy");
    expect(screen.getByRole("link")).toHaveAttribute("target", "_blank");
    expect(screen.getByText(/60.040s/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Next frames" }));
    await waitFor(() =>
      expect(api.getFrames).toHaveBeenCalledWith(1, 2, expect.any(AbortSignal)),
    );
  });
});
