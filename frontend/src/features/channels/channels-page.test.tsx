import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChannelsPage } from "@/features/channels/channels-page";
import type { Channel, ChannelListResponse } from "@/services/channels";

function makeChannel(overrides: Partial<Channel> = {}): Channel {
  return {
    id: 1,
    name: "WBPSC Study Hub",
    channel_url: "https://www.youtube.com/@wbpscstudyhub",
    youtube_channel_id: null,
    sample_video_url: "https://www.youtube.com/watch?v=sample12345",
    search_keyword: "IDO",
    is_active: true,
    created_at: "2026-11-26T10:00:00Z",
    updated_at: "2026-11-26T10:00:00Z",
    ...overrides,
  };
}

function renderChannelsPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ChannelsPage />
    </QueryClientProvider>,
  );
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChannelsPage", () => {
  it("lists channels and displays summary counts", async () => {
    const payload: ChannelListResponse = {
      items: [
        makeChannel(),
        makeChannel({
          id: 2,
          name: "ইতিহাস ক্লাস",
          channel_url: "https://www.youtube.com/@itihasclass",
          sample_video_url: null,
          search_keyword: "WBCS",
          is_active: false,
        }),
      ],
      total: 2,
      page: 1,
      page_size: 10,
      total_pages: 1,
      summary: { total: 2, active: 1, inactive: 1 },
    };

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(payload)));
    renderChannelsPage();

    expect(await screen.findByText("WBPSC Study Hub")).toBeInTheDocument();
    expect(screen.getByText("ইতিহাস ক্লাস")).toBeInTheDocument();

    const summary = screen.getByLabelText("Channel summary");
    expect(within(summary).getByText("2")).toBeInTheDocument();
    expect(within(summary).getAllByText("1")).toHaveLength(2);
    const table = screen.getByRole("table");
    expect(within(table).getByText("WBCS")).toBeInTheDocument();
    expect(within(table).getByText("Inactive")).toBeInTheDocument();
  });

  it("validates add channel form and creates a channel", async () => {
    const user = userEvent.setup();
    let channels: Channel[] = [];

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/channels") && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as {
          name: string;
          channel_url: string;
          search_keyword: string;
          is_active: boolean;
        };
        const created = makeChannel({
          id: 10,
          name: body.name,
          channel_url: "https://www.youtube.com/@newchannel",
          search_keyword: body.search_keyword,
          is_active: body.is_active,
        });
        channels = [created];
        return Promise.resolve(jsonResponse(created, 201));
      }
      return Promise.resolve(
        jsonResponse({
          items: channels,
          total: channels.length,
          page: 1,
          page_size: 10,
          total_pages: 1,
          summary: {
            total: channels.length,
            active: channels.filter((c) => c.is_active).length,
            inactive: channels.filter((c) => !c.is_active).length,
          },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    renderChannelsPage();
    expect(
      await screen.findByText("No channels registered yet"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add channel" }));
    const dialog = screen.getByRole("dialog");

    // Submit empty form -> client validation error
    await user.click(
      within(dialog).getByRole("button", { name: "Add channel" }),
    );
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "Channel name is required.",
    );

    // Invalid channel URL
    await user.type(within(dialog).getByLabelText("Channel name"), "New Hub");
    await user.type(
      within(dialog).getByLabelText("Channel URL"),
      "https://vimeo.com/123",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Add channel" }),
    );
    expect(within(dialog).getByRole("alert")).toHaveTextContent("youtube.com");

    // Valid submission
    const urlInput = within(dialog).getByLabelText("Channel URL");
    await user.clear(urlInput);
    await user.type(urlInput, "https://www.youtube.com/@NewChannel");
    await user.click(
      within(dialog).getByRole("button", { name: "Add channel" }),
    );

    expect(await screen.findByText("New Hub")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      'Added channel "New Hub".',
    );
  });

  it("supports editing, status toggle, and delete confirmation", async () => {
    const user = userEvent.setup();
    let channels: Channel[] = [makeChannel()];

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/channels/1") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as Partial<Channel>;
        channels = [{ ...channels[0], ...body }];
        return Promise.resolve(jsonResponse(channels[0]));
      }
      if (url.endsWith("/channels/1") && init?.method === "DELETE") {
        channels = [];
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return Promise.resolve(
        jsonResponse({
          items: channels,
          total: channels.length,
          page: 1,
          page_size: 10,
          total_pages: 1,
          summary: {
            total: channels.length,
            active: channels.filter((c) => c.is_active).length,
            inactive: channels.filter((c) => !c.is_active).length,
          },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    renderChannelsPage();
    expect(await screen.findByText("WBPSC Study Hub")).toBeInTheDocument();

    // Toggle status
    await user.click(screen.getByRole("button", { name: "Disable" }));
    expect(await screen.findByText("Enable")).toBeInTheDocument();

    // Edit channel
    await user.click(
      screen.getByRole("button", { name: "Edit WBPSC Study Hub" }),
    );
    const editDialog = screen.getByRole("dialog");
    const keywordInput = within(editDialog).getByLabelText("Search keyword");
    await user.clear(keywordInput);
    await user.type(keywordInput, "WBCS");
    await user.click(
      within(editDialog).getByRole("button", { name: "Save changes" }),
    );
    expect(await screen.findByText("WBCS")).toBeInTheDocument();

    // Delete with confirmation (cancel first, then confirm)
    await user.click(
      screen.getByRole("button", { name: "Delete WBPSC Study Hub" }),
    );
    const deleteDialog = screen.getByRole("dialog");
    await user.click(
      within(deleteDialog).getByRole("button", { name: "Cancel" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("WBPSC Study Hub")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Delete WBPSC Study Hub" }),
    );
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Confirm delete",
      }),
    );
    expect(
      await screen.findByText("No channels registered yet"),
    ).toBeInTheDocument();
  });

  it("displays CSV import counts and row-specific errors", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/channels/import") && init?.method === "POST") {
          return Promise.resolve(
            jsonResponse({
              total_rows: 3,
              imported_count: 1,
              skipped_count: 1,
              invalid_count: 1,
              imported: [makeChannel({ id: 5, name: "বাংলা একাডেমি" })],
              skipped: [
                {
                  row_number: 3,
                  channel_name: "Dup",
                  channel_url: "https://www.youtube.com/@dup",
                  reason: "Channel URL already exists in the database.",
                },
              ],
              errors: [
                {
                  row_number: 4,
                  channel_name: "Missing URL",
                  channel_url: null,
                  reason:
                    "Channel URL is missing and requires manual correction.",
                },
              ],
            }),
          );
        }
        return Promise.resolve(
          jsonResponse({
            items: [],
            total: 0,
            page: 1,
            page_size: 10,
            total_pages: 1,
            summary: { total: 0, active: 0, inactive: 0 },
          }),
        );
      }),
    );

    renderChannelsPage();
    await screen.findByText("No channels registered yet");

    await user.click(screen.getByRole("button", { name: "Import CSV" }));
    const dialog = screen.getByRole("dialog");

    const file = new File(
      [
        "channel_name,channel_url,sample_video_url\nTest,https://www.youtube.com/@test,\n",
      ],
      "channels.csv",
      { type: "text/csv" },
    );
    await user.upload(within(dialog).getByLabelText("CSV file"), file);
    await user.click(
      within(dialog).getByRole("button", { name: "Import CSV" }),
    );

    expect(
      await within(dialog).findByText(/Channel URL is missing/),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(/Channel URL already exists/),
    ).toBeInTheDocument();
  });

  it("handles API errors on initial load and form submission", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ error: { message: "Database is unavailable." } }, 503),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          items: [],
          total: 0,
          page: 1,
          page_size: 10,
          total_pages: 1,
          summary: { total: 0, active: 0, inactive: 0 },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          {
            error: {
              message: "A channel with this normalized URL already exists.",
            },
          },
          409,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    renderChannelsPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Database is unavailable.",
    );

    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByText("No channels registered yet"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add channel" }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Channel name"), "Dup");
    await user.type(
      within(dialog).getByLabelText("Channel URL"),
      "https://www.youtube.com/@dup",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Add channel" }),
    );

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "already exists",
    );
  });
});
