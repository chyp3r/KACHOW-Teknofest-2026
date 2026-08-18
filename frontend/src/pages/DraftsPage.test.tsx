import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { DraftsPage } from "./DraftsPage";

// UnitPicker (rendered inside the expanded draft detail) fetches units via
// a live useQuery -- every render here now needs a real QueryClient in
// scope, same as MessageList.test.tsx's own wrapper.
vi.mock("../services/unitsService", () => ({
  unitsService: { list: vi.fn().mockResolvedValue([]) },
}));

function renderWithQueryClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

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

const deleteDraft = vi.fn().mockResolvedValue(undefined);
const updateDestination = vi.fn().mockResolvedValue(undefined);
vi.mock("../hooks/useDrafts", () => ({ useDrafts: () => ({
  drafts: [draft], total: 1, activeDraft: draft,
  versions: [{ ...draft, id: "draft-1", version: 1, content: "İlk sürüm" }, draft],
  loading: false, detailLoading: false, refreshing: false, error: null,
  deleteDraft, deleting: false,
  updateDestination, updatingDestination: false,
}) }));
vi.mock("../hooks/useDraftCreation", () => ({ useDraftCreation: () => ({
  correspondenceTypes: [], typesLoading: false, draft: null, creating: false,
  error: null, create: vi.fn(), reset: vi.fn(),
}) }));

describe("DraftsPage", () => {
  it("shows the source document and expands version history below the selected row", () => {
    renderWithQueryClient(
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

  it("lets the user override the routed unit from the draft detail", async () => {
    updateDestination.mockClear();
    renderWithQueryClient(
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

    fireEvent.click(screen.getByRole("button", { name: "Birimi değiştir" }));
    const select = await screen.findByLabelText("Hedef birim");
    fireEvent.change(select, { target: { value: "__custom__" } });
    fireEvent.change(screen.getByLabelText("Birim adı"), { target: { value: "Basın Birimi" } });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));

    expect(updateDestination).toHaveBeenCalledWith("draft-2", "Basın Birimi");
  });

  it("keeps the creation form hidden until the header action is used", () => {
    const onOpenDraft = vi.fn();
    renderWithQueryClient(
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

  it("deletes a draft after confirmation and closes it if it was open", async () => {
    deleteDraft.mockClear();
    const onCloseDraft = vi.fn();
    renderWithQueryClient(
      <MemoryRouter>
        <DraftsPage
          documents={[sourceDocument]}
          selected={null}
          analysis={null}
          activeDraftId="draft-2"
          onSelect={vi.fn()}
          onOpenDraft={vi.fn()}
          onCloseDraft={onCloseDraft}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Taslağı sil" }));
    expect(screen.getByRole("alertdialog", { name: "Taslağı sil" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sil" }));

    await waitFor(() => expect(onCloseDraft).toHaveBeenCalled());
    expect(deleteDraft).toHaveBeenCalledWith("draft-2");
  });

  it("does not delete anything when the confirmation is cancelled", () => {
    deleteDraft.mockClear();
    renderWithQueryClient(
      <MemoryRouter>
        <DraftsPage
          documents={[sourceDocument]}
          selected={null}
          analysis={null}
          onSelect={vi.fn()}
          onOpenDraft={vi.fn()}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Taslağı sil" }));
    fireEvent.click(screen.getByRole("button", { name: "Vazgeç" }));

    expect(deleteDraft).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
