import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as settingsApi from "@/services/settings";
import { SettingsPage } from "./settings-page";

vi.mock("@/services/settings");

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      {children}
    </QueryClientProvider>
  );
}

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(settingsApi.getExclusionKeywords).mockResolvedValue({
      keywords: ["Math", "গণিত"],
      suggested_keywords: [
        "Math",
        "Mathematics",
        "Reasoning",
        "অঙ্ক",
        "গণিত",
        "রিজনিং",
      ],
      updated_at: null,
      reevaluated_count: 0,
      excluded_video_count: 1,
      eligible_video_count: 3,
    });
    vi.mocked(settingsApi.getPdfSettings).mockResolvedValue({
      compression: "lossless",
      default_compression: "lossless",
      options: [
        {
          mode: "lossless",
          label: "Lossless (Original PNG)",
          description:
            "Original PNG — zero compression artifacts, largest file size.",
        },
        {
          mode: "maximum_quality",
          label: "Maximum quality (JPEG 95)",
          description: "JPEG quality 95 — near-lossless visual fidelity.",
        },
        {
          mode: "high_quality",
          label: "High quality (JPEG 90)",
          description: "JPEG quality 90 — crisp text and annotations.",
        },
        {
          mode: "compact",
          label: "Compact (JPEG 85)",
          description: "JPEG quality 85 — smallest file size.",
        },
      ],
      updated_at: null,
    });
    vi.mocked(settingsApi.updatePdfSettings).mockImplementation(
      async (compression) => ({
        compression,
        default_compression: "lossless",
        options: [
          {
            mode: "lossless",
            label: "Lossless (Original PNG)",
            description:
              "Original PNG — zero compression artifacts, largest file size.",
          },
          {
            mode: "maximum_quality",
            label: "Maximum quality (JPEG 95)",
            description: "JPEG quality 95 — near-lossless visual fidelity.",
          },
          {
            mode: "high_quality",
            label: "High quality (JPEG 90)",
            description: "JPEG quality 90 — crisp text and annotations.",
          },
          {
            mode: "compact",
            label: "Compact (JPEG 85)",
            description: "JPEG quality 85 — smallest file size.",
          },
        ],
        updated_at: "2026-11-27T07:00:00Z",
      }),
    );
    vi.mocked(settingsApi.updateExclusionKeywords).mockImplementation(
      async (keywords) => ({
        keywords,
        suggested_keywords: [
          "Math",
          "Mathematics",
          "Reasoning",
          "অঙ্ক",
          "গণিত",
          "রিজনিং",
        ],
        updated_at: "2026-11-27T07:00:00Z",
        reevaluated_count: 4,
        excluded_video_count: 2,
        eligible_video_count: 2,
      }),
    );
  });

  it("loads keywords, validates empty/duplicates, supports add/edit/remove/examples, and saves", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />, { wrapper });

    expect(await screen.findByText("Math")).toBeInTheDocument();
    expect(screen.getByText("গণিত")).toBeInTheDocument();

    const input = screen.getByLabelText("Add exclusion keyword");
    const addBtn = screen.getByRole("button", { name: /Add keyword/i });

    // Reject empty keyword
    await user.click(addBtn);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Keyword cannot be empty.",
    );

    // Reject case-insensitive duplicate
    await user.type(input, "math");
    await user.click(addBtn);
    expect(screen.getByRole("alert")).toHaveTextContent(
      '"math" is already in the exclusion list.',
    );

    // Add valid Bengali phrase
    await user.clear(input);
    await user.type(input, "রিজনিং");
    await user.click(addBtn);
    expect(screen.getByText("রিজনিং")).toBeInTheDocument();

    // Edit Math -> Mathematics
    await user.click(screen.getByRole("button", { name: "Edit Math" }));
    const editInput = screen.getByLabelText("Edit keyword Math");
    await user.clear(editInput);
    await user.type(editInput, "Mathematics");
    await user.click(screen.getByRole("button", { name: "Save keyword Math" }));
    expect(screen.getByText("Mathematics")).toBeInTheDocument();

    // Remove গণিত
    await user.click(screen.getByRole("button", { name: "Remove গণিত" }));
    expect(
      screen.queryByRole("button", { name: "Remove গণিত" }),
    ).not.toBeInTheDocument();

    // Click suggested example Reasoning
    await user.click(screen.getByRole("button", { name: "Reasoning" }));

    // Save changes
    await user.click(screen.getByRole("button", { name: /Save changes/i }));
    await waitFor(() =>
      expect(settingsApi.updateExclusionKeywords).toHaveBeenCalledWith([
        "Mathematics",
        "রিজনিং",
        "Reasoning",
      ]),
    );
    expect(
      await screen.findByText(/Saved 3 exclusion keywords/i),
    ).toBeInTheDocument();
  });

  it("renders PDF Generation compression settings and saves selection", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />, { wrapper });

    expect(await screen.findByText("PDF Generation")).toBeInTheDocument();
    expect(screen.getByText(/Default: Lossless/i)).toBeInTheDocument();

    const trigger = screen.getByRole("combobox", {
      name: /PDF compression mode/i,
    });
    await user.click(trigger);
    await user.click(
      screen.getByRole("option", { name: "High quality (JPEG 90)" }),
    );
    await user.click(
      screen.getByRole("button", { name: /Save PDF settings/i }),
    );

    await waitFor(() => {
      expect(settingsApi.updatePdfSettings).toHaveBeenCalledWith(
        "high_quality",
      );
    });
    expect(
      await screen.findByText(/Saved PDF compression mode: High quality/i),
    ).toBeInTheDocument();
  });
});
