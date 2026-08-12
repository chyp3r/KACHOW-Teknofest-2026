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
  it("keeps destination, version, and date in separate labeled cells, without a status column", () => {
    render(<DraftTable drafts={[draft]} titleFor={() => "dilekce.pdf - Cevap yazısı"} onToggle={vi.fn()} renderDetail={() => null} />);

    expect(screen.queryByRole("columnheader", { name: "Durum / onay" })).not.toBeInTheDocument();
    expect(screen.queryByText("İnsan onayı")).not.toBeInTheDocument();
    expect(screen.getByText("dilekce.pdf - Cevap yazısı")).toBeInTheDocument();
    expect(screen.getByText("İnsan Kaynakları")).toBeInTheDocument();
    expect(screen.getByText("v3")).toBeInTheDocument();
    expect(screen.getAllByText("Hedef birim").length).toBeGreaterThan(0);
  });

  it("supports keyboard activation of the record", () => {
    const onToggle = vi.fn();
    render(<DraftTable drafts={[draft]} titleFor={() => "Cevap yazısı"} onToggle={onToggle} renderDetail={() => null} />);
    fireEvent.keyDown(screen.getByRole("row", { name: /Cevap yazısı/ }), { key: "Enter" });
    expect(onToggle).toHaveBeenCalledWith(draft, false);
  });

  it("renders row actions passed via renderRowActions without triggering row toggle", () => {
    const onToggle = vi.fn();
    render(
      <DraftTable
        drafts={[draft]}
        titleFor={() => "Cevap yazısı"}
        onToggle={onToggle}
        renderDetail={() => null}
        renderRowActions={() => <button type="button" aria-label="Sil">Sil</button>}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Sil" }));
    expect(onToggle).not.toHaveBeenCalled();
  });
});
