import { test, expect } from "@playwright/test";

test.describe("Videos page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/videos");
  });

  test("renders the Videos page heading", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: "Videos", exact: true }),
    ).toBeVisible();
  });

  test("renders summary cards", async ({ page }) => {
    const summary = page.getByRole("region", { name: "Video summary" });
    await expect(summary.getByText("Total videos")).toBeVisible();
    await expect(summary.getByText("Pending")).toBeVisible();
    await expect(summary.getByText("Discovered today")).toBeVisible();
  });

  test("renders Discover Videos button", async ({ page }) => {
    await expect(
      page.getByRole("button", { name: /Discover Videos/i }),
    ).toBeVisible();
  });

  test("renders empty state when no videos exist", async ({ page }) => {
    // Explicitly model an empty library even when a Docker volume retains real videos.
    await page.route(/\/api\/v1\/videos\?/, (route) =>
      route.fulfill({
        json: {
          items: [],
          total: 0,
          page: 1,
          page_size: 20,
          total_pages: 1,
        },
      }),
    );
    await page.reload();
    await expect(page.getByText(/No videos discovered yet/i)).toBeVisible();
  });

  test("shows search and filter controls", async ({ page }) => {
    await expect(
      page.getByRole("searchbox", { name: /search/i }),
    ).toBeVisible();
    await expect(page.getByLabel("Filter by channel")).toBeVisible();
    await expect(page.getByLabel("Filter by processing status")).toBeVisible();
    await expect(page.getByLabel("Filter by download status")).toBeVisible();
    await expect(page.getByLabel("Published after")).toBeVisible();
    await expect(page.getByLabel("Published before")).toBeVisible();
    await expect(page.getByLabel("Sort videos")).toBeVisible();
  });

  test("navigates to Videos from sidebar", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Videos" }).click();
    await expect(page).toHaveURL(/\/videos/);
    await expect(
      page.getByRole("heading", { name: "Videos", exact: true }),
    ).toBeVisible();
  });
});
