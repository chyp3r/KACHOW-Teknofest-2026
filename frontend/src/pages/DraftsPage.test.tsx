import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { DraftsPage } from "./DraftsPage";

const longDraftContent = "İkinci sürüm taslak içeriği. ".repeat(24);
const draft = {
  id: "draft-2", user_id: "user-1", session_id: "session-1", document_id: "doc-1",
  version: 2, parent_draft_id: "draft-1", content: longDraftContent, correspondence_type: "resmi_yazi",
  destination: "Hukuk Birimi", status: "ready", confidence_score: 92,
  requires_human_approval: true, attempts: 2, verification: null, judge: null,
  missing_information: null, instructions: null,
  created_at: "2026-08-09T10:00:00Z", updated_at: "2026-08-09T11:00:00Z",
};

const sourceDocument = {
  file_name: "izin-talebi.pdf",
  storage_path: "doc-1",
  upload_time: "2026-08-09T09:00:00Z",
  document_type: "petition",
  document_type_label: "Dilekçe",
  compliance_status: "compliant",
  summary: "İzin talebi",
};

vi.mock("../hooks/useDrafts", () => ({ useDrafts: () => ({
  drafts: [draft], total: 1, activeDraft: draft,
  versions: [{ ...draft, id: "draft-1", version: 1, content: "İlk sürüm" }, draft],
  loading: false, detailLoading: false, refreshing: false, error: null,
}) }));
vi.mock("../hooks/useDraftCreation", () => ({ useDraftCreation: () => ({
  correspondenceTypes: [], typesLoading: false, draft: null, creating: false,
  error: null, create: vi.fn(), reset: vi.fn(),
}) }));

describe("DraftsPage", () => {
  it("shows the source document and expands version history below the selected row", () => {
    render(
      <MemoryRouter>
        <DraftsPage
          documents={[sourceDocument]}
          selected={null}
          analysis={null}
          activeDraftId="draft-2"
          onSelect={vi.fn()}
          onOpenDraft={vi.fn()}
          onCloseDraft={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText("Oluşturulan taslaklar")).toBeInTheDocument();
    expect(screen.getByText("izin-talebi.pdf - resmi yazi")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sürüm geçmişi" })).toBeInTheDocument();
    expect(screen.getByText("İlk sürüm")).toBeInTheDocument();

    const showAllButton = screen.getByRole("button", { name: "Tümünü gör" });
    const contentId = showAllButton.getAttribute("aria-controls");
    fireEvent.click(showAllButton);
    expect(document.getElementById(contentId!)?.textContent).toBe(longDraftContent);
    expect(screen.getByRole("button", { name: "Daha az göster" })).toBeInTheDocument();
  });

  it("keeps the creation form hidden until the header action is used", () => {
    const onOpenDraft = vi.fn();
    render(
      <MemoryRouter>
        <DraftsPage
          documents={[sourceDocument]}
          selected={null}
          analysis={null}
          onSelect={vi.fn()}
          onOpenDraft={onOpenDraft}
        />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("heading", { name: "Yeni taslak oluştur" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Yeni taslak" }));
    expect(screen.getByRole("heading", { name: "Yeni taslak oluştur" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("row", { name: /Hukuk Birimi/ }));
    expect(onOpenDraft).toHaveBeenCalledWith("draft-2");
  });
});
