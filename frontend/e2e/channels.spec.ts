import { expect, test } from "@playwright/test";

test("channel creation, editing, CSV import, and cleanup persist via real backend", async ({
  page,
}, testInfo) => {
  const runId = Date.now();
  const handle = `@e2echannel_${runId}`;
  const createdName = `E2E Lecture ${runId}`;
  const editedName = `E2E Edited ${runId}`;
  const csvBengaliName = `বাংলা লেকচার ${runId}`;
  const csvHandle = `@e2ebangla_${runId}`;

  await page.goto("/channels");
  await expect(
    page.getByRole("heading", { name: "Channels", level: 1 }),
  ).toBeVisible();

  // 1. Create channel via modal
  await page.getByRole("button", { name: "Add channel" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Channel name").fill(createdName);
  await dialog
    .getByLabel("Channel URL")
    .fill(`https://www.youtube.com/${handle}/videos?si=e2e`);
  await dialog
    .getByLabel("Sample video URL")
    .fill("https://youtu.be/e2evid12345?t=15");
  await dialog.getByLabel("Search keyword").fill("IDO");
  await dialog.getByRole("button", { name: "Add channel" }).click();

  const table = page.getByRole("table");
  await expect(table.getByText(createdName, { exact: true })).toBeVisible();
  await expect(
    table.getByRole("link", { name: `Visit ${createdName} channel` }),
  ).toBeVisible();
  await expect(
    table.getByText(`https://www.youtube.com/${handle}`),
  ).not.toBeVisible();

  // Reload to prove database persistence
  await page.reload();
  await expect(table.getByText(createdName, { exact: true })).toBeVisible();

  // 2. Edit channel
  await page.getByRole("button", { name: `Edit ${createdName}` }).click();
  const editDialog = page.getByRole("dialog");
  await editDialog.getByLabel("Channel name").fill(editedName);
  await editDialog.getByLabel("Search keyword").fill("WBPSC");
  await editDialog.getByRole("button", { name: "Save changes" }).click();

  await expect(table.getByText(editedName, { exact: true })).toBeVisible();
  await expect(table.getByText("WBPSC", { exact: true })).toBeVisible();

  // 3. Import CSV with valid UTF-8 Bengali row, duplicate row, and invalid missing-URL row
  await page.getByRole("button", { name: "Import CSV" }).click();
  const importDialog = page.getByRole("dialog");
  const csvContent = [
    "channel_name,channel_url,sample_video_url,search_keyword,is_active",
    `${csvBengaliName},https://m.youtube.com/${csvHandle}/featured,,IDO,true`,
    `Duplicate Row,https://www.youtube.com/${handle},,,true`,
    `Missing URL ${runId},,https://youtu.be/e2evid12345,,`,
  ].join("\n");

  await importDialog.getByLabel("CSV file").setInputFiles({
    name: "channels.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csvContent, "utf-8"),
  });
  await importDialog.getByRole("button", { name: "Import CSV" }).click();

  await expect(
    importDialog.getByText(
      /Channel URL is missing and requires manual correction/,
    ),
  ).toBeVisible();
  await expect(
    importDialog.getByText(/Channel URL already exists in the database/),
  ).toBeVisible();
  await importDialog
    .getByRole("button", { name: "Close", exact: true })
    .click();

  await expect(table.getByText(csvBengaliName, { exact: true })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("channels-page.png"),
    fullPage: true,
  });

  // 4. Clean up created E2E channels via delete confirmation
  for (const name of [editedName, csvBengaliName]) {
    await page.getByRole("button", { name: `Delete ${name}` }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Confirm delete" })
      .click();
    await expect(table.getByText(name, { exact: true })).not.toBeVisible();
  }
});
