import { expect, test } from "@playwright/test";

test("generates PDF from Videos page and manages PDFs in PDF Library", async ({
  page,
}) => {
  const video = {
    id: 888,
    channel_id: 1,
    youtube_video_id: "pdf_e2e_001",
    title: "WBPSC IDO Geography Lecture",
    description: "",
    video_url: "https://www.youtube.com/watch?v=pdf_e2e_001",
    thumbnail_url: null,
    duration_seconds: 2400,
    published_at: "2026-11-20T10:00:00Z",
    livestream_status: "none",
    discovered_at: "2026-11-20T12:00:00Z",
    processing_status: "pending",
    download_status: "downloaded",
    local_video_path: "/video.mp4",
    actual_resolution: "1280x720",
    file_size_bytes: 1000,
    video_codec: "av1",
    download_progress: 100,
    downloaded_bytes: 1000,
    total_bytes: 1000,
    download_requested: false,
    download_started_at: null,
    download_completed_at: null,
    download_retry_count: 0,
    download_error: null,
    is_excluded: false,
    excluded_keywords: [],
    created_at: "2026-11-20T12:00:00Z",
    updated_at: "2026-11-20T12:00:00Z",
  };

  let pdfGenerated = false;
  const pdfState = () => ({
    video_id: 888,
    source_slide_generation: pdfGenerated ? "gen1" : null,
    status: pdfGenerated ? "generated" : "pending",
    requested: false,
    progress: pdfGenerated ? 100 : 0,
    completed_pages: pdfGenerated ? 12 : 0,
    total_pages: pdfGenerated ? 12 : 0,
    pdf_path: pdfGenerated ? "/data/pdfs/lecture.pdf" : null,
    pdf_filename: pdfGenerated
      ? "2026-11-20_BSSEI_WBPSC-IDO-Geography-Lecture_pdf_e2e_001.pdf"
      : null,
    page_count: pdfGenerated ? 12 : 0,
    file_size_bytes: pdfGenerated ? 524288 : 0,
    started_at: null,
    completed_at: pdfGenerated ? "2026-11-27T08:00:00Z" : null,
    retry_count: 0,
    error: null,
  });

  await page.route(/\/api\/v1\/channels/, (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 1,
            name: "BSSEI Competitive",
            channel_url: "https://www.youtube.com/@bssei",
            youtube_channel_id: null,
            sample_video_url: null,
            search_keyword: "IDO",
            is_active: true,
            created_at: "2026-11-20T00:00:00Z",
            updated_at: "2026-11-20T00:00:00Z",
          },
        ],
        total: 1,
        page: 1,
        page_size: 100,
        total_pages: 1,
        summary: { total: 1, active: 1, inactive: 0 },
      },
    }),
  );

  await page.route(/\/api\/v1\/videos\/summary/, (route) =>
    route.fulfill({
      json: {
        total: 1,
        eligible: 1,
        excluded: 0,
        pending: 0,
        today: 0,
        latest_discovery_at: null,
      },
    }),
  );

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

  await page.route("**/api/v1/videos/888/extraction", (route) =>
    route.fulfill({
      json: {
        video_id: 888,
        status: "extracted",
        progress: 100,
        requested: false,
        interval_seconds: 60,
        frame_count: 12,
        expected_count: 12,
        frame_directory: "/frames",
        manifest_path: "/frames/manifest.json",
        started_at: null,
        completed_at: null,
        retry_count: 0,
        error: null,
      },
    }),
  );

  await page.route("**/api/v1/videos/888/slide-processing", (route) =>
    route.fulfill({
      json: {
        video_id: 888,
        status: "processed",
        requested: false,
        progress: 100,
        input_count: 12,
        completed_count: 12,
        additional_count: 0,
        output_count: 12,
        duplicate_count: 0,
        reconstructed_count: 0,
        review_count: 0,
        output_directory: "/slides/gen1",
        error: null,
      },
    }),
  );

  await page.route("**/api/v1/videos/888/pdf", (route) => {
    if (route.request().method() === "POST") {
      pdfGenerated = true;
      return route.fulfill({ status: 202, json: pdfState() });
    }
    if (route.request().method() === "DELETE") {
      pdfGenerated = false;
      return route.fulfill({ json: pdfState() });
    }
    return route.fulfill({ json: pdfState() });
  });

  await page.route(/\/api\/v1\/pdfs(\?.*)?$/, (route) => {
    const items = pdfGenerated
      ? [
          {
            video_id: 888,
            youtube_video_id: "pdf_e2e_001",
            video_title: "WBPSC IDO Geography Lecture",
            channel_id: 1,
            channel_name: "BSSEI Competitive",
            published_at: "2026-11-20T10:00:00Z",
            generated_at: "2026-11-27T08:00:00Z",
            page_count: 12,
            file_size_bytes: 524288,
            pdf_filename:
              "2026-11-20_BSSEI_WBPSC-IDO-Geography-Lecture_pdf_e2e_001.pdf",
            source_slide_generation: "gen1",
            is_excluded: false,
          },
        ]
      : [];
    return route.fulfill({
      json: {
        items,
        total: items.length,
        page: 1,
        page_size: 20,
        total_pages: 1,
        total_bytes: items.reduce((a, b) => a + b.file_size_bytes, 0),
        total_pages_sum: items.reduce((a, b) => a + b.page_count, 0),
      },
    });
  });

  await page.route("**/api/v1/pdfs/888/preview", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/pdf",
      body: "%PDF-1.4\n%%EOF\n",
    }),
  );

  await page.goto("/videos");
  await expect(page.getByText("WBPSC IDO Geography Lecture")).toBeVisible();

  await page
    .getByRole("button", {
      name: "Generate PDF for WBPSC IDO Geography Lecture",
    })
    .click();
  await expect(page.getByText(/12 pages/)).toBeVisible();

  // Navigate to PDF Library
  await page.getByRole("link", { name: "PDF Library" }).click();
  await expect(
    page.getByRole("heading", { name: "PDF Library", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("WBPSC IDO Geography Lecture")).toBeVisible();

  // Preview PDF in fullscreen modal
  await page
    .getByRole("button", { name: "Preview WBPSC IDO Geography Lecture" })
    .click();
  await expect(
    page.getByTitle("PDF preview for WBPSC IDO Geography Lecture"),
  ).toBeVisible();
});
