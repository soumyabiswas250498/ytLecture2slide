import { expect, test } from "@playwright/test";

test("configures sampling and previews frames through extraction controls", async ({
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
  let extracted = false;
  const state = () => ({
    video_id: 777,
    status: extracted ? "extracted" : "pending",
    progress: extracted ? 100 : 0,
    requested: false,
    interval_seconds: 30,
    frame_count: extracted ? 5 : 0,
    expected_count: extracted ? 5 : null,
    frame_directory: extracted ? "/frames" : null,
    manifest_path: extracted ? "/frames/manifest.json" : null,
    started_at: null,
    completed_at: null,
    retry_count: 0,
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
  await page.route("**/api/v1/videos/777/extraction", async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({ interval_seconds: 30 });
      extracted = true;
    }
    if (route.request().method() === "DELETE") extracted = false;
    await route.fulfill({ json: state() });
  });
  await page.route("**/api/v1/videos/777/frames?**", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            filename: "frame_000000000.png",
            requested_timestamp: 0,
            actual_timestamp: 0,
            width: 1280,
            height: 720,
          },
        ],
        total: 1,
        page: 1,
        page_size: 12,
        video_duration: 130,
      },
    }),
  );
  await page.route("**/api/v1/videos/777/frames/*.png", (route) =>
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
    .getByRole("spinbutton", { name: "Screenshot interval (seconds)" })
    .fill("30");
  await page
    .getByRole("button", { name: "Extract Frames", exact: true })
    .click();
  await expect(page.getByText("5 / 5 frames")).toBeVisible();
  await page.getByRole("button", { name: "Preview frames" }).click();
  await expect(page.getByRole("dialog").getByRole("img")).toBeVisible();
  await expect(page.getByRole("dialog").getByText(/1280×720/)).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page
    .getByRole("button", { name: "Delete frames", exact: true })
    .click();
  await page.getByRole("button", { name: "Confirm delete frames" }).click();
  await expect(
    page.getByRole("button", { name: "Extract Frames", exact: true }),
  ).toBeVisible();
});
