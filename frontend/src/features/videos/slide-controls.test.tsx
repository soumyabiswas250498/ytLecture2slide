import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as api from "@/services/slides";
import * as frames from "@/services/extractions";
import { Modal } from "@/components/ui/modal";
import { SlideControls } from "./slide-controls";
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

it("processes available frames without crop controls", async () => {
  render(<SlideControls videoId={1} />, { wrapper });
  await userEvent.click(
    await screen.findByRole("button", { name: /^Process Slides$/ }),
  );
  expect(api.processSlides).toHaveBeenCalledWith(1, undefined, false);
  expect(
    screen.queryByRole("button", { name: /Adjust board crop/i }),
  ).not.toBeInTheDocument();
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
  expect(screen.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow",
    "66.7",
  );
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
    screen.getByRole("button", { name: "Confirm delete slides" }),
  );
  expect(api.deleteSlides).toHaveBeenCalledWith(1);
});

it("moves detailed slide statistics and warnings into DetailsPopover without inline expansion", async () => {
  const user = userEvent.setup();
  vi.mocked(api.getSlideState).mockResolvedValue({
    ...state,
    status: "processed",
    input_count: 5,
    additional_count: 2,
    duplicate_count: 1,
    output_count: 4,
    reconstructed_count: 2,
    review_count: 1,
    output_directory: "/slides",
  });
  render(<SlideControls videoId={1} />, { wrapper });
  expect(await screen.findByText("4 slides")).toBeVisible();
  expect(screen.queryByText(/Details/i)).not.toBeInTheDocument();
  expect(screen.queryByText("Input frames")).not.toBeInTheDocument();

  const infoBtn = screen.getByRole("button", {
    name: "View slide processing details",
  });
  expect(infoBtn).toHaveAttribute("title", "View details");
  expect(infoBtn.className).toContain("h-8 w-8");

  await user.click(infoBtn);
  expect(await screen.findByText("Slide processing")).toBeVisible();
  expect(screen.getByText("Input frames")).toBeVisible();
  expect(screen.getByText("5")).toBeVisible();
  expect(screen.getByText("Additional frames")).toBeVisible();
  expect(screen.getByText("Confirmed duplicates excluded")).toBeVisible();
  expect(screen.getByText("Output slides")).toBeVisible();
  expect(screen.getByText("Reconstructed slides")).toBeVisible();
  expect(screen.getByText("Potentially obstructed slides")).toBeVisible();
  expect(
    screen.getByText(
      /1 potentially obstructed slide retained for manual review\./,
    ),
  ).toBeVisible();

  await user.keyboard("{Escape}");
  await waitFor(() =>
    expect(screen.queryByText("Slide processing")).not.toBeInTheDocument(),
  );
});

it("displays single large image when original and processed match, and supports keyboard/jump navigation", async () => {
  vi.mocked(api.slideUrl).mockReturnValue("/image.png");
  vi.mocked(api.getSlides).mockResolvedValue({
    items: [
      {
        slide_id: "slide_00001",
        source_frame_ids: ["frame_000000000.png"],
        source_timestamps: [185],
        additional_sampled_timestamps: [],
        processed_image_path: "frame_000000000.png",
        cropped_image_path: "frame_000000000.png",
        original_image_path: "frame_000000000.png",
        obstruction_mask_path: null,
        reconstruction_method: "original",
        fallback: false,
        incomplete: false,
        manual_review: false,
        warnings: ["Board boundary uncertain; full frame retained."],
        board_coordinates: [
          [0, 0],
          [1, 0],
          [1, 1],
          [0, 1],
        ],
        quality: {
          obstruction_fraction: 0.01,
          unresolved_fraction: 0,
          measurement_kind: "heuristic_not_accuracy",
          verified_accuracy: null,
        },
      },
    ],
    generation: "abc",
    total: 7,
    page: 1,
    page_size: 1,
    warnings: [],
  });
  render(<SlidePreview videoId={1} />, { wrapper });
  expect(await screen.findByText("Slide 1 of 7")).toBeVisible();
  expect(screen.getByText("00:03:05")).toBeVisible();
  expect(screen.getAllByRole("img")).toHaveLength(1);
  expect(screen.queryByText(/Cropped smartboard/i)).not.toBeInTheDocument();
  expect(
    screen.queryByText(/Board boundary uncertain/i),
  ).not.toBeInTheDocument();

  // Keyboard right arrow advances to slide 2
  fireEvent.keyDown(window, { key: "ArrowRight" });
  await waitFor(() =>
    expect(api.getSlides).toHaveBeenCalledWith(
      1,
      2,
      expect.any(AbortSignal),
      1,
    ),
  );

  // Jump directly to slide 5
  const jumpInput = await screen.findByLabelText("Go to");
  await userEvent.clear(jumpInput);
  await userEvent.type(jumpInput, "5");
  await userEvent.click(screen.getByRole("button", { name: "Go" }));
  await waitFor(() =>
    expect(api.getSlides).toHaveBeenCalledWith(
      1,
      5,
      expect.any(AbortSignal),
      1,
    ),
  );
});

it("displays side-by-side comparison when original and processed differ", async () => {
  vi.mocked(api.slideUrl).mockReturnValue("/image.png");
  vi.mocked(api.getSlides).mockResolvedValue({
    items: [
      {
        slide_id: "slide_00001",
        source_frame_ids: ["frame_000000000.png"],
        source_timestamps: [60],
        additional_sampled_timestamps: [],
        processed_image_path: "slide_00001.png",
        cropped_image_path: "original_00001.png",
        original_image_path: "original_00001.png",
        obstruction_mask_path: null,
        reconstruction_method: "masked_pixel_fusion",
        fallback: false,
        incomplete: true,
        manual_review: true,
        warnings: [],
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
    total: 3,
    page: 1,
    page_size: 1,
    warnings: [],
  });
  render(<SlidePreview videoId={1} />, { wrapper });
  expect(await screen.findByText("Original screenshot")).toBeVisible();
  expect(screen.getByText("Processed screenshot")).toBeVisible();
  expect(screen.getAllByRole("img")).toHaveLength(2);
});

it("renders shared Modal with configurable sizes", () => {
  const { rerender } = render(
    <Modal open title="Test" size="fullscreen" onClose={() => undefined}>
      <div>Body</div>
    </Modal>,
  );
  expect(screen.getByRole("dialog").className).toContain("w-[95vw]");
  rerender(
    <Modal open title="Test" size="xl" onClose={() => undefined}>
      <div>Body</div>
    </Modal>,
  );
  expect(screen.getByRole("dialog").className).toContain("max-w-6xl");
});
