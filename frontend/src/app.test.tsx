import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { App } from "@/app";

function renderApp(path = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/channels")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [],
              total: 0,
              page: 1,
              page_size: 10,
              total_pages: 1,
              summary: { total: 0, active: 0, inactive: 0 },
            }),
          ),
        );
      }
      if (url.includes("/videos/summary")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              total: 0,
              pending: 0,
              today: 0,
              latest_discovery_at: null,
            }),
          ),
        );
      }
      if (url.includes("/videos")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [],
              total: 0,
              page: 1,
              page_size: 20,
              total_pages: 1,
            }),
          ),
        );
      }
      if (url.includes("/settings/pipeline")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
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
              updated_at: null,
            }),
          ),
        );
      }
      if (url.includes("/pipeline/scheduler")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              enabled: true,
              frequency: "daily",
              time: "03:00",
              timezone: "Asia/Kolkata",
              next_run_at: null,
              last_run_at: null,
              is_running: false,
            }),
          ),
        );
      }
      if (url.includes("/pipeline/runs/active")) {
        return Promise.resolve(new Response(JSON.stringify(null)));
      }
      if (url.includes("/pipeline/runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [],
              total: 0,
              page: 1,
              page_size: 15,
              total_pages: 1,
            }),
          ),
        );
      }
      if (url.includes("/settings/exclusion-keywords")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              keywords: [],
              suggested_keywords: ["Math", "Mathematics", "Reasoning"],
              updated_at: null,
              reevaluated_count: 0,
              excluded_video_count: 0,
              eligible_video_count: 0,
            }),
          ),
        );
      }
      if (url.includes("/pdfs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [],
              total: 0,
              page: 1,
              page_size: 20,
              total_pages: 1,
              total_bytes: 0,
              total_pages_sum: 0,
            }),
          ),
        );
      }
      return Promise.resolve(new Response(JSON.stringify({ status: "ok" })));
    }),
  );
});

it("renders the shell and actual backend health", async () => {
  renderApp();
  expect(
    screen.getByRole("heading", { name: "Dashboard", level: 1 }),
  ).toBeInTheDocument();
  expect(await screen.findByText("Backend is healthy")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/health",
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  );
});

it("navigates to Channels and every future section without fabricated data", async () => {
  const user = userEvent.setup();
  renderApp();

  await user.click(screen.getByRole("link", { name: "Channels" }));
  expect(
    await screen.findByRole("heading", { name: "Channels", level: 1 }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Channels" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  // Videos is now a live page — it should render its own heading.
  await user.click(screen.getByRole("link", { name: "Videos" }));
  expect(
    await screen.findByRole("heading", { name: "Videos", level: 1 }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Videos" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await user.click(screen.getByRole("link", { name: "PDF Library" }));
  expect(
    await screen.findByRole("heading", { name: "PDF Library", level: 1 }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "PDF Library" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await user.click(screen.getByRole("link", { name: "Processing Jobs" }));
  expect(
    await screen.findByRole("heading", { name: "Processing Jobs", level: 1 }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Processing Jobs" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await user.click(screen.getByRole("link", { name: "Settings" }));
  expect(
    await screen.findByRole("heading", { name: "Settings", level: 1 }),
  ).toBeInTheDocument();
  expect(
    await screen.findByRole("heading", { name: "Exclude Keywords" }),
  ).toBeInTheDocument();
});

it("collapses and expands the sidebar and persists preference in localStorage", async () => {
  window.localStorage.removeItem("ytl2s.sidebar.collapsed");
  const user = userEvent.setup();
  const { unmount } = renderApp();

  expect(screen.getByText("Local by design")).toBeInTheDocument();
  const collapseBtn = screen.getByRole("button", { name: "Collapse sidebar" });
  await user.click(collapseBtn);

  expect(window.localStorage.getItem("ytl2s.sidebar.collapsed")).toBe("true");
  expect(screen.queryByText("Local by design")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Expand sidebar" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Videos" })).toHaveAttribute(
    "title",
    "Videos",
  );

  // Remounting preserves collapsed preference
  unmount();
  renderApp();
  expect(screen.queryByText("Local by design")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
  expect(window.localStorage.getItem("ytl2s.sidebar.collapsed")).toBe("false");
  expect(screen.getByText("Local by design")).toBeInTheDocument();
});

it("reports a failed backend connection and supports retry", async () => {
  vi.mocked(fetch).mockRejectedValueOnce(new TypeError("offline"));
  renderApp();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Cannot reach the backend",
  );
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("Backend is healthy")).toBeInTheDocument();
});

it("shows a loading state while health is pending", () => {
  vi.mocked(fetch).mockImplementation(() => new Promise<Response>(() => {}));
  renderApp();
  expect(screen.getByRole("status")).toHaveTextContent(
    "Checking backend connection",
  );
});

it("handles unknown URLs", () => {
  renderApp("/unknown");
  expect(screen.getByText("Page not found")).toBeInTheDocument();
});
