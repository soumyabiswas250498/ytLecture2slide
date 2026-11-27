import { expect, test } from "@playwright/test";

test("renders Processing Jobs page and persists Scheduling/Processing/Storage settings", async ({
  page,
}) => {
  let currentSettings = {
    scheduler_enabled: true,
    scheduler_frequency: "daily",
    scheduler_time: "03:00",
    timezone: "Asia/Kolkata",
    discovery_lookback_days: 7,
    extraction_interval_seconds: 60,
    pipeline_concurrent_limit: 1,
    pipeline_retry_attempts: 3,
    auto_cleanup_enabled: true,
    min_free_disk_mb: 500,
    updated_at: null as string | null,
  };

  let runs: unknown[] = [];

  await page.route("**/api/v1/pipeline/scheduler", async (route) => {
    await route.fulfill({
      json: {
        enabled: currentSettings.scheduler_enabled,
        frequency: currentSettings.scheduler_frequency,
        time: currentSettings.scheduler_time,
        timezone: currentSettings.timezone,
        next_run_at: "2026-11-28T03:00:00+05:30",
        last_run_at: null,
        is_running: false,
      },
    });
  });

  await page.route("**/api/v1/pipeline/runs/active", async (route) => {
    await route.fulfill({ json: null });
  });

  await page.route("**/api/v1/pipeline/runs?**", async (route) => {
    await route.fulfill({
      json: {
        items: runs,
        total: runs.length,
        page: 1,
        page_size: 15,
        total_pages: 1,
      },
    });
  });

  await page.route("**/api/v1/pipeline/runs", async (route) => {
    if (route.request().method() === "POST") {
      const created = {
        id: 1,
        trigger_type: "manual",
        status: "completed",
        current_stage: "completed",
        current_video_id: null,
        current_video_title: null,
        current_stage_progress: 100,
        total_videos: 1,
        completed_videos: 1,
        excluded_videos: 0,
        skipped_videos: 0,
        failed_videos: 0,
        cancelled_videos: 0,
        last_error: null,
        reprocess_existing: false,
        target_video_ids: [],
        started_at: "2026-11-27T10:00:00Z",
        completed_at: "2026-11-27T10:01:00Z",
        created_at: "2026-11-27T10:00:00Z",
        updated_at: "2026-11-27T10:01:00Z",
        estimated_remaining_seconds: 0,
        videos: [],
        logs: [
          {
            timestamp: "2026-11-27T10:00:00Z",
            level: "INFO",
            video_id: null,
            stage: null,
            message: "Pipeline run #1 completed.",
          },
        ],
      };
      runs = [created];
      await route.fulfill({ status: 202, json: created });
      return;
    }
    await route.continue();
  });

  await page.route("**/api/v1/settings/exclusion-keywords", async (route) => {
    await route.fulfill({
      json: {
        keywords: [],
        suggested_keywords: ["Math", "Reasoning"],
        updated_at: null,
        reevaluated_count: 0,
        excluded_video_count: 0,
        eligible_video_count: 0,
      },
    });
  });

  await page.route("**/api/v1/settings/pipeline", async (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      currentSettings = {
        ...currentSettings,
        ...body,
        updated_at: "2026-11-27T10:05:00Z",
      };
      await route.fulfill({ json: currentSettings });
      return;
    }
    await route.fulfill({ json: currentSettings });
  });

  // 1. Processing Jobs page
  await page.goto("/jobs");
  await expect(
    page.getByRole("heading", { name: "Processing Jobs", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("03:00 IST")).toBeVisible();
  await page.getByRole("button", { name: "Run Now" }).click();
  await expect(page.getByText("#1", { exact: true })).toBeVisible();

  // 2. Settings page
  await page.goto("/settings");
  await expect(
    page.getByText("Automation, Processing & Storage"),
  ).toBeVisible();
  const timeInput = page.getByLabel("Daily execution time");
  await timeInput.fill("04:30");
  await page.getByRole("button", { name: /Save Pipeline Settings/i }).click();
  await expect(
    page.getByText("Scheduling, processing, and storage settings saved."),
  ).toBeVisible();
});
