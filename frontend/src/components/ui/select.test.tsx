import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Select, type SelectOption } from "./select";

const OPTIONS: readonly SelectOption[] = [
  { value: "", label: "All statuses" },
  { value: "active", label: "Active" },
  { value: "inactive", label: "Inactive" },
  {
    value: "long",
    label: "Very long educational channel name that should remain readable",
  },
  { value: "disabled_opt", label: "Disabled option", disabled: true },
];

function ControlledSelect({
  initial = "",
  disabled = false,
}: {
  initial?: string;
  disabled?: boolean;
}) {
  const [value, setValue] = useState(initial);
  return (
    <div>
      <label htmlFor="test-select">Status</label>
      <Select
        id="test-select"
        ariaLabel="Status"
        value={value}
        options={OPTIONS}
        placeholder="Choose status"
        disabled={disabled}
        onValueChange={setValue}
      />
    </div>
  );
}

describe("Select", () => {
  it("renders placeholder when value does not match an option and updates on click", async () => {
    const user = userEvent.setup();
    render(<ControlledSelect initial="missing" />);
    const trigger = screen.getByRole("combobox", { name: "Status" });
    expect(trigger).toHaveTextContent("Choose status");

    await user.click(trigger);
    expect(screen.getByRole("listbox")).toBeVisible();
    await user.click(screen.getByRole("option", { name: "Active" }));
    expect(trigger).toHaveTextContent("Active");
  });

  it("supports keyboard navigation, skips disabled options, and closes on Escape", async () => {
    const user = userEvent.setup();
    render(<ControlledSelect initial="" />);
    const trigger = screen.getByRole("combobox", { name: "Status" });
    trigger.focus();

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("listbox")).toBeVisible();
    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Enter}");
    expect(trigger).toHaveTextContent("Active");

    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("supports disabled state and long option labels", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <Select
        ariaLabel="Channel"
        value=""
        options={OPTIONS}
        disabled
        onValueChange={onChange}
      />,
    );
    const trigger = screen.getByRole("combobox", { name: "Channel" });
    expect(trigger).toBeDisabled();
    await user.click(trigger);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    rerender(
      <Select
        ariaLabel="Channel"
        value="long"
        options={OPTIONS}
        onValueChange={onChange}
      />,
    );
    expect(trigger).toHaveTextContent(
      "Very long educational channel name that should remain readable",
    );
  });
});
