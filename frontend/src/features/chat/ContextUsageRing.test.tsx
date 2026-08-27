import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ContextUsageRing } from "./ContextUsageRing";
import type { ContextUsage } from "../../types/chat";

const usage: ContextUsage = {
  total: 8192,
  used: 4096,
  free: 4096,
  segments: [
    { key: "system", label: "Sistem yönergesi", tokens: 2048 },
    { key: "history", label: "Sohbet geçmişi", tokens: 1024 },
    { key: "input", label: "Güncel mesaj", tokens: 0 },
    { key: "reserved", label: "Yanıt için ayrılan", tokens: 1024 },
  ],
};

describe("ContextUsageRing", () => {
  it("renders nothing without usage data", () => {
    const { container } = render(<ContextUsageRing usage={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("exposes the used percentage on the trigger and stays collapsed by default", async () => {
    render(<ContextUsageRing usage={usage} />);
    expect(await screen.findByRole("button", { name: /%50 dolu/ })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens a popup with the breakdown and a compact button on click", () => {
    const onCompact = vi.fn();
    render(<ContextUsageRing usage={usage} onCompact={onCompact} />);

    fireEvent.click(screen.getByRole("button", { name: /Bağlam penceresi/ }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Sistem yönergesi")).toBeInTheDocument();
    expect(screen.getByText("Boş")).toBeInTheDocument();
    expect(screen.queryByText("Güncel mesaj")).not.toBeInTheDocument(); // 0 token -> gizli
    expect(screen.getByText(/4\.096 \/ 8\.192 token/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Bağlamı sıkıştır" }));
    expect(onCompact).toHaveBeenCalledTimes(1);
  });

  it("shows a locked label while compacting", () => {
    render(<ContextUsageRing usage={usage} onCompact={vi.fn()} compacting />);
    fireEvent.click(screen.getByRole("button", { name: /Bağlam penceresi/ }));
    expect(screen.getByRole("button", { name: /Sıkıştırılıyor/ })).toBeDisabled();
  });
});
