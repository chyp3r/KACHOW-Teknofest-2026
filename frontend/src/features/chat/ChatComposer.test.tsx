import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ChatComposer } from "./ChatComposer";

const baseProps = {
  documents: [],
  selectedDocument: null,
  onSelectDocument: vi.fn(),
  onClearDocument: vi.fn(),
  onSend: vi.fn().mockResolvedValue(undefined),
};

describe("ChatComposer", () => {
  it("exposes a legible loading state without detaching the send action", () => {
    render(<MemoryRouter><ChatComposer {...baseProps} loading /></MemoryRouter>);
    const send = screen.getByRole("button", { name: "Mesaj gönderiliyor" });
    expect(send).toBeDisabled();
    expect(send).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("textbox", { name: "Sohbet mesajı" })).toBeDisabled();
  });

  it("preserves Enter submission behavior", () => {
    const onSend = vi.fn().mockResolvedValue(undefined);
    render(<MemoryRouter><ChatComposer {...baseProps} loading={false} onSend={onSend} /></MemoryRouter>);
    const input = screen.getByRole("textbox", { name: "Sohbet mesajı" });
    fireEvent.change(input, { target: { value: "Uzun Türkçe bir karar destek sorusu" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("Uzun Türkçe bir karar destek sorusu", "balanced", false);
  });

  it("keeps the document action and AI mode in the same compact control row", () => {
    render(<MemoryRouter><ChatComposer {...baseProps} loading={false} /></MemoryRouter>);

    expect(screen.getByRole("button", { name: "Evrak ekle" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "AI modu" })).toHaveValue("balanced");
  });
});
