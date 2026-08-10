import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RoutingPage } from "./RoutingPage";

const suggest = vi.fn().mockResolvedValue(undefined);
vi.mock("../hooks/useDrafts", () => ({ useDrafts: () => ({
  drafts: [], total: 0, loading: false, refreshing: false, error: null,
}) }));
vi.mock("../hooks/useRoutingSuggestion", () => ({ useRoutingSuggestion: () => ({
  suggestion: { routed_unit: "Hukuk Birimi", priority: "yüksek", reasoning: "Mevzuat incelemesi gerekli", justification: "" },
  loading: false, error: null, suggest, reset: vi.fn(),
}) }));

describe("RoutingPage", () => {
  it("submits only the real stateless routing contract and labels the result as a recommendation", async () => {
    render(<RoutingPage />);
    fireEvent.change(screen.getByLabelText(/^Taslak veya evrak metni/), { target: { value: "İncelenecek taslak" } });
    fireEvent.click(screen.getByRole("button", { name: "Yönlendirme önerisi al" }));

    expect(suggest).toHaveBeenCalledWith({ draft: "İncelenecek taslak", confidence_score: 100 });
    expect(screen.getByText("Hukuk Birimi")).toBeInTheDocument();
    expect(screen.getByText(/nihai karar değildir/i)).toBeInTheDocument();
  });
});
