import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DetailsPopover } from "./details-popover";

describe("DetailsPopover", () => {
  it("opens on click, renders key-value details and warnings, and closes on Escape or outside click", async () => {
    const user = userEvent.setup();
    render(
      <div>
        <button type="button">Outside target</button>
        <DetailsPopover
          title="Slide statistics"
          ariaLabel="View slide details"
          items={[
            { label: "Input frames", value: 12 },
            { label: "Output slides", value: 8 },
            { label: "Empty field", value: null },
          ]}
          warnings={["1 potentially obstructed slide retained."]}
        />
      </div>,
    );

    const trigger = screen.getByRole("button", { name: "View slide details" });
    expect(trigger).toHaveAttribute("title", "View details");
    expect(trigger.className).toContain("h-8 w-8");
    expect(screen.queryByText("Slide statistics")).not.toBeInTheDocument();

    await user.click(trigger);
    expect(await screen.findByText("Slide statistics")).toBeVisible();
    expect(screen.getByText("Input frames")).toBeVisible();
    expect(screen.getByText("12")).toBeVisible();
    expect(screen.getByText("Output slides")).toBeVisible();
    expect(screen.getByText("8")).toBeVisible();
    expect(screen.queryByText("Empty field")).not.toBeInTheDocument();
    expect(
      screen.getByText("1 potentially obstructed slide retained."),
    ).toBeVisible();

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByText("Slide statistics")).not.toBeInTheDocument(),
    );
    expect(trigger).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(await screen.findByText("Slide statistics")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Outside target" }));
    await waitFor(() =>
      expect(screen.queryByText("Slide statistics")).not.toBeInTheDocument(),
    );
  });

  it("renders nothing when all items and warnings are empty", () => {
    const { container } = render(
      <DetailsPopover
        title="Empty"
        items={[{ label: "None", value: null }]}
        warnings={[]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
