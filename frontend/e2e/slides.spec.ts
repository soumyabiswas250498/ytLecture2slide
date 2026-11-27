import { expect, test } from "@playwright/test";

test("processes slides and compares results in fullscreen modal without crop controls", async ({
  page,
}) => {
  const video = {
    id: 777,
    channel_id: null,
    youtube_video_id: "fixture001",
    title: "Frame extraction fixture",
    description: "",
    video_url: "https://www.youtube.com/watch?v=fixture001",
    thumbnail_url: null,
    duration_seconds: 130,
    published_at: "2026-11-20T00:00:00Z",
    livestream_status: "none",
    discovered_at: "2026-11-20T00:00:00Z",
    processing_status: "pending",
    download_status: "downloaded",
    local_video_path: "/fixture.mp4",
    actual_resolution: "1280x720",
    file_size_bytes: 100,
    video_codec: "h264",
    download_progress: 100,
    downloaded_bytes: 100,
    total_bytes: 100,
    download_requested: false,
    download_started_at: null,
    download_completed_at: null,
    download_retry_count: 0,
    download_error: null,
    created_at: "2026-11-20T00:00:00Z",
    updated_at: "2026-11-20T00:00:00Z",
  };

  let processed = false;
  const slideState = () => ({
    video_id: 777,
    status: processed ? "processed" : "pending",
    requested: false,
    progress: processed ? 100 : 0,
    input_count: 3,
    completed_count: processed ? 3 : 0,
    additional_count: 2,
    output_count: processed ? 2 : 0,
    duplicate_count: 1,
    reconstructed_count: 0,
    review_count: 2,
    output_directory: processed ? "/slides" : null,
    error: null,
  });
  await page.route(/\/api\/v1\/videos\?/, (route) =>
    route.fulfill({
      json: {
        items: [video],
        total: 1,
        page: 1,
        page_size: 20,
        total_pages: 1,
      },
    }),
  );
  await page.route("**/api/v1/videos/777/extraction", (route) =>
    route.fulfill({
      json: {
        video_id: 777,
        status: "extracted",
        progress: 100,
        requested: false,
        interval_seconds: 60,
        frame_count: 3,
        expected_count: 3,
        frame_directory: "/frames",
        manifest_path: "/frames/manifest.json",
        started_at: null,
        completed_at: null,
        retry_count: 0,
        error: null,
      },
    }),
  );
  await page.route("**/api/v1/videos/777/slide-processing", async (route) => {
    if (route.request().method() === "POST") processed = true;
    await route.fulfill({ json: slideState() });
  });
  await page.route("**/api/v1/videos/777/slides?**", (route) =>
    route.fulfill({
      json: {
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
              unresolved_fraction: 0.1,
              measurement_kind: "heuristic_not_accuracy",
              verified_accuracy: null,
            },
          },
        ],
        total: 1,
        page: 1,
        page_size: 6,
        generation: "abc",
        warnings: [],
      },
    }),
  );
  await page.route("**/api/v1/videos/777/slides/abc/*.png", (route) =>
    route.fulfill({
      contentType: "image/png",
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=",
        "base64",
      ),
    }),
  );
  await page.goto("/videos");
  await page
    .getByRole("button", { name: "Process Slides", exact: true })
    .click();
  await expect(page.getByText("2 slides")).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Adjust board crop/i }),
  ).toHaveCount(0);

  // Verify DetailsPopover does not change row height, is not clipped, and works at 1280/1440/1920px
  const row = page.locator("tbody tr").first();
  const initialRowBox = await row.boundingBox();
  expect(initialRowBox).not.toBeNull();

  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    const rowBefore = await row.boundingBox();
    const infoBtn = page.getByRole("button", {
      name: "View slide processing details",
    });
    await infoBtn.click();
    const popover = page.getByRole("dialog", { name: "Slide processing" });
    await expect(popover).toBeVisible();
    await expect(popover.getByText("Input frames")).toBeVisible();
    await expect(
      popover.getByText("Confirmed duplicates excluded"),
    ).toBeVisible();

    const rowAfter = await row.boundingBox();
    expect(rowAfter?.height).toBeCloseTo(rowBefore!.height, 1);

    const popoverBox = await popover.boundingBox();
    expect(popoverBox).not.toBeNull();
    expect(popoverBox!.x).toBeGreaterThanOrEqual(0);
    expect(popoverBox!.x + popoverBox!.width).toBeLessThanOrEqual(width);
    expect(popoverBox!.height).toBeGreaterThan(80);

    await page.keyboard.press("Escape");
    await expect(popover).toBeHidden();
  }

  await page.getByRole("button", { name: "Compare slides" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("img")).toHaveCount(2);
  await expect(dialog.getByText("Slide 1 of 1")).toBeVisible();
  await expect(dialog.getByText("00:01:00", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Technical diagnostics")).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
});
