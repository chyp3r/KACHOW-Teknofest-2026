import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PersistedDraft } from "../../types/drafts";
import { DraftTable } from "./DraftTable";

const draft: PersistedDraft = {
  id: "draft-1", user_id: null, session_id: null, document_id: null, version: 3,
  parent_draft_id: null, content: "İçerik", correspondence_type: "cevap_yazisi",
  destination: "İnsan Kaynakları", status: "ready", confidence_score: 90,
  requires_human_approval: true, attempts: 1, verification: null, judge: null,
  missing_information: null, instructions: null,
  created_at: "2026-08-09T10:00:00Z", updated_at: "2026-08-09T11:00:00Z",
};

describe("DraftTable", () => {
  it("keeps status, destination, source, version, and date in separate labeled cells", () => {
    render(<DraftTable drafts={[draft]} titleFor={() => "Cevap yazısı"} sourceFor={() => "Kaynak yok"} onToggle={vi.fn()} renderDetail={() => null} />);

    expect(screen.getByRole("columnheader", { name: "Durum / onay" })).toBeInTheDocument();
    expect(screen.getByText("İnsan onayı")).toBeInTheDocument();
    expect(screen.getByText("İnsan Kaynakları")).toBeInTheDocument();
    expect(screen.getByText("Kaynak yok")).toBeInTheDocument();
    expect(screen.getByText("v3")).toBeInTheDocument();
    expect(screen.getAllByText("Hedef birim").length).toBeGreaterThan(0);
  });

  it("supports keyboard activation of the record", () => {
    const onToggle = vi.fn();
    render(<DraftTable drafts={[draft]} titleFor={() => "Cevap yazısı"} sourceFor={() => "Kaynak yok"} onToggle={onToggle} renderDetail={() => null} />);
    fireEvent.keyDown(screen.getByRole("row", { name: /Cevap yazısı/ }), { key: "Enter" });
    expect(onToggle).toHaveBeenCalledWith(draft, false);
  });

  it("normalizes persisted status casing into a readable label", () => {
    render(<DraftTable drafts={[{ ...draft, status: "COMPLETED", requires_human_approval: false }]} titleFor={() => "Cevap yazısı"} sourceFor={() => "Kaynak yok"} onToggle={vi.fn()} renderDetail={() => null} />);

    expect(screen.getByText("Hazır")).toBeInTheDocument();
    expect(screen.queryByText("COMPLETED")).not.toBeInTheDocument();
  });
});
