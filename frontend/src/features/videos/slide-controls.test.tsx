import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as api from "@/services/slides";
import * as frames from "@/services/extractions";
import { SlideControls, SlideToolbar } from "./slide-controls";
import { SlidePreview } from "./slide-preview";

vi.mock("@/services/slides");
vi.mock("@/services/extractions");
const state = {
  video_id: 1,
  status: "pending" as const,
  requested: false,
  progress: 0,
  input_count: 3,
  completed_count: 0,
  additional_count: 0,
  output_count: 0,
  duplicate_count: 0,
  reconstructed_count: 0,
  review_count: 0,
  output_directory: null,
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
  vi.mocked(api.getSlideState).mockResolvedValue(state);
  vi.mocked(api.processSlides).mockResolvedValue(state);
  vi.mocked(api.slideAction).mockResolvedValue(state);
  vi.mocked(frames.getExtraction).mockResolvedValue({
    video_id: 1,
    status: "extracted",
    requested: false,
    progress: 100,
    interval_seconds: 60,
    frame_count: 3,
    expected_count: 3,
    frame_directory: "/frames",
    manifest_path: "/frames/manifest.json",
    started_at: null,
    completed_at: null,
    retry_count: 0,
    error: null,
  });
});
it("processes available frames and applies a validated crop", async () => {
  render(<SlideControls videoId={1} />, { wrapper });
  await userEvent.click(
    await screen.findByRole("button", { name: /^Process Slides$/ }),
  );
  expect(api.processSlides).toHaveBeenCalledWith(1, undefined, false);
  await userEvent.click(
    screen.getByRole("button", { name: "Adjust board crop" }),
  );
  const input = screen.getByRole("spinbutton", { name: "Crop bottom" });
  await userEvent.clear(input);
  await userEvent.type(input, "0.9");
  await userEvent.click(
    screen.getByRole("button", { name: "Apply crop and reprocess" }),
  );
  expect(api.processSlides).toHaveBeenLastCalledWith(
    1,
    { left: 0, top: 0, right: 1, bottom: 0.9 },
    false,
  );
});
it("shows measured progress and cancels", async () => {
  vi.mocked(api.getSlideState).mockResolvedValue({
    ...state,
    status: "processing",
    requested: true,
    completed_count: 2,
    progress: 66.7,
    additional_count: 4,
  });
  render(<SlideControls videoId={1} />, { wrapper });
  expect(
    await screen.findByText("2 / 3 primary screenshots examined"),
  ).toBeVisible();
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "66.7");
  await userEvent.click(screen.getByRole("button", { name: "Cancel slides" }));
  expect(api.slideAction).toHaveBeenCalledWith(1, "cancel");
});
it("retries failure and confirms deletion", async () => {
  vi.mocked(api.getSlideState).mockResolvedValue({
    ...state,
    status: "failed",
    error: "Cannot decode",
    output_directory: "/slides",
  });
  render(<SlideControls videoId={1} />, { wrapper });
  expect(await screen.findByRole("alert")).toHaveTextContent("Cannot decode");
  await userEvent.click(screen.getByRole("button", { name: "Retry slides" }));
  expect(api.slideAction).toHaveBeenCalledWith(1, "retry");
  await userEvent.click(
    screen.getByRole("button", { name: "Delete processed slides" }),
  );
  expect(api.deleteSlides).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "Confirm delete processed slides" }),
  );
  expect(api.deleteSlides).toHaveBeenCalledWith(1);
});
it("reports bulk per-video outcomes", async () => {
  vi.mocked(api.processSelected).mockResolvedValue({
    started_ids: [1],
    errors: [{ video_id: 2, reason: "No frames" }],
  });
  render(<SlideToolbar selectedIds={[1, 2]} />, { wrapper });
  await userEvent.click(
    screen.getByRole("button", { name: "Process selected slides" }),
  );
  expect(await screen.findByText("Video #2: No frames")).toBeVisible();
});
it("compares four images, marks incomplete fallback and paginates", async () => {
  vi.mocked(api.slideUrl).mockReturnValue("/image.png");
  vi.mocked(api.getSlides).mockResolvedValue({
    items: [
      {
        slide_id: "slide_00001",
        source_frame_ids: ["frame.png"],
        source_timestamps: [60],
        additional_sampled_timestamps: [],
        processed_image_path: "slide_00001.png",
        cropped_image_path: "crop_00001.png",
        original_image_path: "original_00001.png",
        obstruction_mask_path: "mask_00001.png",
        reconstruction_method: "original",
        fallback: true,
        incomplete: true,
        manual_review: true,
        warnings: ["Visibility uncertain"],
        board_coordinates: [
          [0, 0],
          [1, 0],
          [1, 1],
          [0, 1],
        ],
        quality: {
          obstruction_fraction: 0.1,
          unresolved_fraction: 0.05,
          measurement_kind: "heuristic_not_accuracy",
          verified_accuracy: null,
        },
      },
    ],
    generation: "abc",
    total: 7,
    page: 1,
    page_size: 6,
    warnings: [],
  });
  render(<SlidePreview videoId={1} />, { wrapper });
  expect(
    await screen.findByText("Fallback · Incomplete · Manual review required"),
  ).toBeVisible();
  expect(screen.getAllByRole("img")).toHaveLength(4);
  for (const link of screen.getAllByRole("link"))
    expect(link).toHaveAttribute("target", "_blank");
  await userEvent.click(screen.getByRole("button", { name: "Next slides" }));
  await waitFor(() =>
    expect(api.getSlides).toHaveBeenCalledWith(1, 2, expect.any(AbortSignal)),
  );
});
