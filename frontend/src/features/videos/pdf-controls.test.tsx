import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PdfControls } from "./pdf-controls";

function renderControls(isExcluded = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PdfControls
        videoId={10}
        videoTitle="WBPSC IDO History Class"
        isExcluded={isExcluded}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

it("disables Generate when slides are not processed", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/slide-processing")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              video_id: 10,
              status: "pending",
              requested: false,
              progress: 0,
              input_count: 0,
              completed_count: 0,
              additional_count: 0,
              output_count: 0,
              duplicate_count: 0,
              reconstructed_count: 0,
              review_count: 0,
              output_directory: null,
              error: null,
            }),
          ),
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            video_id: 10,
            source_slide_generation: null,
            status: "pending",
            requested: false,
            progress: 0,
            completed_pages: 0,
            total_pages: 0,
            pdf_path: null,
            pdf_filename: null,
            page_count: 0,
            file_size_bytes: 0,
            started_at: null,
            completed_at: null,
            retry_count: 0,
            error: null,
          }),
        ),
      );
    }),
  );

  renderControls();
  const btn = await screen.findByRole("button", {
    name: "Generate PDF for WBPSC IDO History Class",
  });
  expect(btn).toBeDisabled();
});

it("generates, previews, and deletes a PDF with confirmation", async () => {
  const user = userEvent.setup();
  let status: "pending" | "generated" = "pending";

  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/slide-processing")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              video_id: 10,
              status: "processed",
              requested: false,
              progress: 100,
              input_count: 5,
              completed_count: 5,
              additional_count: 0,
              output_count: 4,
              duplicate_count: 1,
              reconstructed_count: 0,
              review_count: 0,
              output_directory: "/slides/abc",
              error: null,
            }),
          ),
        );
      }
      if (url.endsWith("/pdf") && init?.method === "POST") {
        status = "generated";
      }
      if (url.endsWith("/pdf") && init?.method === "DELETE") {
        status = "pending";
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            video_id: 10,
            source_slide_generation: status === "generated" ? "abc" : null,
            status,
            requested: false,
            progress: status === "generated" ? 100 : 0,
            completed_pages: status === "generated" ? 4 : 0,
            total_pages: status === "generated" ? 4 : 0,
            pdf_path: status === "generated" ? "/pdfs/lecture.pdf" : null,
            pdf_filename: status === "generated" ? "lecture.pdf" : null,
            page_count: status === "generated" ? 4 : 0,
            file_size_bytes: status === "generated" ? 204800 : 0,
            started_at: null,
            completed_at: null,
            retry_count: 0,
            error: null,
          }),
        ),
      );
    }),
  );

  renderControls();
  const genBtn = await screen.findByRole("button", {
    name: "Generate PDF for WBPSC IDO History Class",
  });
  await waitFor(() => expect(genBtn).toBeEnabled());
  expect(genBtn.className).toContain("h-8 w-8");
  expect(
    screen.queryByRole("combobox", {
      name: /Compression mode/i,
    }),
  ).not.toBeInTheDocument();
  await user.click(genBtn);

  expect(await screen.findByText(/4 pages/)).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", {
      name: "View PDF details for WBPSC IDO History Class",
    }),
  );
  expect(await screen.findByText("Compact (JPEG 85)")).toBeVisible();
  await user.keyboard("{Escape}");
  await user.click(
    screen.getByRole("button", {
      name: "Preview PDF for WBPSC IDO History Class",
    }),
  );
  expect(
    screen.getByTitle("PDF preview for WBPSC IDO History Class"),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Close dialog" }));

  await user.click(
    screen.getByRole("button", {
      name: "Delete PDF for WBPSC IDO History Class",
    }),
  );
  await user.click(screen.getByRole("button", { name: "Confirm delete PDF" }));
  await waitFor(() =>
    expect(screen.queryByText(/4 pages/)).not.toBeInTheDocument(),
  );
});
