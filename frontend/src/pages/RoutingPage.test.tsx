import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RoutingPage } from "./RoutingPage";

const suggest = vi.fn().mockResolvedValue(undefined);
const persistedDraft = {
  id: "draft-9", user_id: null, session_id: null, document_id: null, version: 2,
  parent_draft_id: null, content: "Kalıcı taslak metni", correspondence_type: "cevap_yazisi",
  destination: "Hukuk Birimi", status: "ready", confidence_score: 42,
  requires_human_approval: true, attempts: 1, verification: null, judge: null,
  missing_information: null, instructions: null,
  created_at: "2026-08-09T10:00:00Z", updated_at: "2026-08-09T11:00:00Z",
};
vi.mock("../hooks/useDrafts", () => ({ useDrafts: () => ({
  drafts: [persistedDraft], total: 1, loading: false, refreshing: false, error: null,
}) }));
vi.mock("../hooks/useRoutingSuggestion", () => ({ useRoutingSuggestion: () => ({
  suggestion: { routed_unit: "Hukuk Birimi", priority: "yüksek", reasoning: "Mevzuat incelemesi gerekli", justification: "" },
  loading: false, error: null, suggest, reset: vi.fn(),
}) }));

describe("RoutingPage", () => {
  it("does not show a confidence slider and submits free text without a confidence score", async () => {
    render(<RoutingPage />);
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Taslak veya evrak metni/), { target: { value: "İncelenecek taslak" } });
    fireEvent.click(screen.getByRole("button", { name: "Yönlendirme önerisi al" }));

    expect(suggest).toHaveBeenCalledWith({ draft: "İncelenecek taslak" });
    expect(screen.getByText("Hukuk Birimi")).toBeInTheDocument();
    expect(screen.getByText(/nihai karar değildir/i)).toBeInTheDocument();
  });

  it("still forwards a persisted draft's real confidence score when one is picked", async () => {
    render(<RoutingPage />);
    fireEvent.change(screen.getByLabelText(/Kalıcı taslaktan seç/), { target: { value: "draft-9" } });
    fireEvent.click(screen.getByRole("button", { name: "Yönlendirme önerisi al" }));

    expect(suggest).toHaveBeenCalledWith({ draft: "Kalıcı taslak metni", confidence_score: 42 });
  });
});
