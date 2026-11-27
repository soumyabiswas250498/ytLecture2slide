import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PdfLibraryPage } from "./pdf-library-page";

function renderLibrary() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PdfLibraryPage />
    </QueryClientProvider>,
  );
}

const sampleItems = [
  {
    video_id: 1,
    youtube_video_id: "vid1",
    video_title: "Indian History Part 1",
    channel_id: 1,
    channel_name: "BSSEI Competitive",
    published_at: "2026-11-20T10:00:00Z",
    generated_at: "2026-11-27T08:00:00Z",
    page_count: 77,
    file_size_bytes: 15_728_640,
    pdf_filename: "2026-11-20_BSSEI-Competitive_Indian-History_vid1.pdf",
    source_slide_generation: "abc",
    is_excluded: false,
  },
  {
    video_id: 2,
    youtube_video_id: "vid2",
    video_title: "General Science MCQs",
    channel_id: 2,
    channel_name: "VSCE Academy",
    published_at: "2026-11-21T10:00:00Z",
    generated_at: "2026-11-27T09:00:00Z",
    page_count: 45,
    file_size_bytes: 9_437_184,
    pdf_filename: "2026-11-21_VSCE-Academy_General-Science_vid2.pdf",
    source_slide_generation: "def",
    is_excluded: false,
  },
];

beforeEach(() => {
  vi.restoreAllMocks();
});

it("renders PDF library, filters by search, selects PDFs, and triggers bulk ZIP download", async () => {
  const user = userEvent.setup();
  let zipCalled = false;

  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/channels")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [
                {
                  id: 1,
                  name: "BSSEI Competitive",
                  channel_url: "https://youtube.com/@bssei",
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
            }),
          ),
        );
      }
      if (url.includes("/pdfs/download-zip") && init?.method === "POST") {
        zipCalled = true;
        return Promise.resolve(
          new Response(
            new Blob(["PK\x03\x04zipdata"], { type: "application/zip" }),
            {
              status: 200,
              headers: { "X-Unavailable-Count": "0" },
            },
          ),
        );
      }
      const parsedUrl = new URL(url, "http://localhost");
      const search = parsedUrl.searchParams.get("search") ?? "";
      const filtered = search
        ? sampleItems.filter((item) =>
            item.video_title.toLowerCase().includes(search.toLowerCase()),
          )
        : sampleItems;
      return Promise.resolve(
        new Response(
          JSON.stringify({
            items: filtered,
            total: filtered.length,
            page: 1,
            page_size: 20,
            total_pages: 1,
            total_bytes: filtered.reduce(
              (acc, i) => acc + i.file_size_bytes,
              0,
            ),
            total_pages_sum: filtered.reduce((acc, i) => acc + i.page_count, 0),
          }),
        ),
      );
    }),
  );

  // Spy on URL.createObjectURL / revokeObjectURL without breaking `new URL()`
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-zip");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

  renderLibrary();

  expect(await screen.findByText("Indian History Part 1")).toBeInTheDocument();
  expect(screen.getByText("General Science MCQs")).toBeInTheDocument();

  // Select all and trigger bulk ZIP download
  await user.click(
    screen.getByRole("checkbox", { name: "Select all PDFs on page" }),
  );
  const zipBtn = screen.getByRole("button", { name: "Download ZIP (2)" });
  expect(zipBtn).toBeEnabled();
  await user.click(zipBtn);

  await waitFor(() => expect(zipCalled).toBe(true));
  expect(
    await screen.findByText("ZIP archive downloaded."),
  ).toBeInTheDocument();

  // Search filter
  const searchInput = screen.getByRole("searchbox", {
    name: "Search PDFs by video title",
  });
  await user.type(searchInput, "Science");
  await waitFor(() => {
    expect(screen.queryByText("Indian History Part 1")).not.toBeInTheDocument();
    expect(screen.getByText("General Science MCQs")).toBeInTheDocument();
  });
});
