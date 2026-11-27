import { expect, test } from "@playwright/test";

test("frontend connects to the real backend and navigation works", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await expect(page.getByText("Backend is healthy")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("workspace.png"),
    fullPage: true,
  });

  await page.getByRole("link", { name: "Channels", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Channels", level: 1 }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Videos", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Videos", level: 1 }),
  ).toBeVisible();

  await page.getByRole("link", { name: "PDF Library", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "PDF Library", level: 1 }),
  ).toBeVisible();

  for (const name of ["Processing Jobs"]) {
    await page.getByRole("link", { name, exact: true }).click();
    await expect(
      page.getByRole("heading", { name: `${name} is not available yet` }),
    ).toBeVisible();
  }
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Exclude Keywords" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Exclude Keywords" }),
  ).toBeVisible();
});

test("mobile shell fits the viewport", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await expect(page.getByText("Backend is healthy")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("workspace.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
