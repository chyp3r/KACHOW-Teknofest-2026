import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Dropdown } from "./FormControls";

function DropdownExample() {
  const [value, setValue] = useState("all");
  return (
    <Dropdown label="Durum" value={value} onChange={(event) => setValue(event.target.value)}>
      <option value="all">Tüm durumlar</option>
      <option value="ready">Hazır</option>
    </Dropdown>
  );
}

describe("Dropdown", () => {
  it("opens a custom listbox and updates the controlled value", () => {
    render(<DropdownExample />);

    const trigger = screen.getByRole("combobox", { name: "Durum" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    expect(screen.getByRole("listbox", { name: "Durum" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "Hazır" }));

    expect(trigger).toHaveTextContent("Hazır");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });
});
