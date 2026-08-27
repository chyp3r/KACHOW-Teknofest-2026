import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ChatComposer } from "./ChatComposer";

const baseProps = {
  documents: [],
  drafts: [],
  selectedDocument: null,
  selectedDraft: null,
  onSelectDocument: vi.fn(),
  onSelectDraft: vi.fn(),
  onClearDocument: vi.fn(),
  onClearDraft: vi.fn(),
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

  it("keeps the document action and working mode in the same compact control row", () => {
    render(<MemoryRouter><ChatComposer {...baseProps} loading={false} /></MemoryRouter>);

    expect(screen.getByRole("button", { name: "Evrak veya taslak ekle" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Çalışma modu" })).toHaveAttribute("aria-valuetext", "Dengeli");
  });

  it("opens the working mode choices above the composer", () => {
    render(<MemoryRouter><ChatComposer {...baseProps} loading={false} /></MemoryRouter>);

    fireEvent.click(screen.getByRole("combobox", { name: "Çalışma modu" }));

    expect(screen.getByRole("listbox")).toHaveStyle({ top: "8px" });
  });

  it("keeps context compaction available beside the working mode", () => {
    const onCompact = vi.fn();
    render(
      <MemoryRouter>
        <ChatComposer
          {...baseProps}
          loading={false}
          onCompact={onCompact}
          contextUsage={{
            used: 4_096,
            total: 8_192,
            free: 4_096,
            segments: [{ key: "history", label: "Sohbet geçmişi", tokens: 4_096 }],
          }}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: /Bağlam penceresi/ }));
    fireEvent.click(screen.getByRole("button", { name: "Bağlamı sıkıştır" }));

    expect(onCompact).toHaveBeenCalledTimes(1);
  });
});
