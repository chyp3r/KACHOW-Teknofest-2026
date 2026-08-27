import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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

  it("shows the used percentage and the token caption", async () => {
    render(<ContextUsageRing usage={usage} />);
    // Yüzde 0'dan hedefe doğru animasyonla sayar; nihai değeri bekle.
    expect(await screen.findByText("%50")).toBeInTheDocument();
    expect(
      screen.getByText(/4\.096 \/ 8\.192 token/),
    ).toBeInTheDocument();
  });

  it("lists only non-zero segments plus the free remainder in the breakdown", () => {
    render(<ContextUsageRing usage={usage} />);
    expect(screen.getByText("Sistem yönergesi")).toBeInTheDocument();
    expect(screen.getByText("Sohbet geçmişi")).toBeInTheDocument();
    expect(screen.getByText("Boş")).toBeInTheDocument();
    // "Güncel mesaj" has 0 tokens -> hidden
    expect(screen.queryByText("Güncel mesaj")).not.toBeInTheDocument();
  });
});
