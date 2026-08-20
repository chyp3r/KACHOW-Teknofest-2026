import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DraftsPage } from "./DraftsPage";

// UnitPicker (rendered inside the expanded draft detail) fetches units via
// a live useQuery -- every render here now needs a real QueryClient in
// scope, same as MessageList.test.tsx's own wrapper.
vi.mock("../services/unitsService", () => ({
  unitsService: { list: vi.fn().mockResolvedValue([]), suggestedRecipients: vi.fn().mockResolvedValue([]) },
}));
vi.mock("../services/transferService", () => ({ transferService: { recommendations: vi.fn().mockResolvedValue([]) } }));
vi.mock("../features/messaging/PersonPickerBody", () => ({
  PersonPickerBody: ({ onToggleSelect }: { onToggleSelect: (userId: string) => void }) => (
    <button type="button" onClick={() => onToggleSelect("recipient-1")}>Alıcı seç</button>
  ),
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
const sendDraft = vi.fn().mockResolvedValue(undefined);
const respondToShare = vi.fn().mockResolvedValue(undefined);
const markShareRead = vi.fn().mockResolvedValue(undefined);
const revokeShare = vi.fn().mockResolvedValue(undefined);
const suggestRouting = vi.fn().mockResolvedValue(undefined);
let inboxShares: Array<Record<string, unknown>> = [];
let outboxShares: Array<Record<string, unknown>> = [];
vi.mock("../hooks/useDrafts", () => ({ useDrafts: () => ({
  drafts: [draft], total: 1, activeDraft: draft,
  versions: [{ ...draft, id: "draft-1", version: 1, content: "İlk sürüm" }, draft],
  inbox: inboxShares, inboxTotal: inboxShares.length, outbox: outboxShares, outboxTotal: outboxShares.length,
  loading: false, detailLoading: false, refreshing: false, error: null,
  deleteDraft, deleting: false,
  updateDestination, updatingDestination: false,
  sendDraft, sending: false, respondToShare, responding: false,
  markShareRead, markingShareRead: false, revokeShare, revokingShare: false,
}) }));
vi.mock("../hooks/useDraftCreation", () => ({ useDraftCreation: () => ({
  correspondenceTypes: [], typesLoading: false, draft: null, creating: false,
  error: null, create: vi.fn(), reset: vi.fn(),
}) }));
vi.mock("../hooks/useRoutingSuggestion", () => ({ useRoutingSuggestion: () => ({
  suggestion: {
    routed_unit: "Strateji Geliştirme Birimi",
    priority: "yüksek",
    reasoning: "Taslağın mali ve stratejik değerlendirme gerektirmesi.",
    justification: "",
  },
  loading: false,
  error: null,
  errorObject: null,
  suggest: suggestRouting,
  reset: vi.fn(),
}) }));

describe("DraftsPage", () => {
  beforeEach(() => {
    inboxShares = [];
    outboxShares = [];
    sendDraft.mockClear();
    respondToShare.mockClear();
    suggestRouting.mockClear();
  });

  it("shows the source document in a stable workspace and keeps versions in their own tab", () => {
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

    expect(screen.getByLabelText("Taslaklarım")).toBeInTheDocument();
    expect(screen.getByLabelText("Resmî yazı önizlemesi")).toHaveTextContent("İkinci sürüm taslak içeriği.");
    expect(screen.getByRole("link", { name: "izin-talebi.pdf" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Revize et" })).toHaveAttribute(
      "href",
      "/chats/session-1?draft=draft-2&mode=revise",
    );
    fireEvent.click(screen.getByRole("tab", { name: "Sürümler (2)" }));
    const historyHeading = screen.getByRole("heading", { name: "Sürüm geçmişi" });
    expect(historyHeading).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Görüntüle" })).toHaveLength(2);
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

    fireEvent.click(screen.getByRole("tab", { name: "Ayrıntılar" }));
    fireEvent.click(screen.getByRole("button", { name: "Birimi değiştir" }));
    const select = await screen.findByLabelText("Hedef birim");
    fireEvent.change(select, { target: { value: "__custom__" } });
    fireEvent.change(screen.getByLabelText("Birim adı"), { target: { value: "Basın Birimi" } });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));

    expect(updateDestination).toHaveBeenCalledWith("draft-2", "Basın Birimi");
  });

  it("runs and applies routing from the selected draft detail", () => {
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
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Yönlendirme" }));
    expect(screen.getByRole("heading", { name: "Birim yönlendirme" })).toBeInTheDocument();
    expect(screen.getByText("Strateji Geliştirme Birimi")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Öneriyi yenile" }));
    expect(suggestRouting).toHaveBeenCalledWith({
      draft: longDraftContent,
      confidence_score: 92,
      document_type: "resmi_yazi",
    });

    fireEvent.click(screen.getByRole("button", { name: "Öneriyi hedef birim yap" }));
    expect(updateDestination).toHaveBeenCalledWith("draft-2", "Strateji Geliştirme Birimi");
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

    expect(screen.queryByRole("heading", { name: "Yazışma bilgileri" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Yeni taslak" }));
    expect(screen.getByRole("heading", { name: "Yazışma bilgileri" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Hukuk Birimi/ }));
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

    fireEvent.click(screen.getByLabelText("Taslak işlemleri"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sil" }));
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
          activeDraftId="draft-2"
          onSelect={vi.fn()}
          onOpenDraft={vi.fn()}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByLabelText("Taslak işlemleri"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sil" }));
    fireEvent.click(screen.getByRole("button", { name: "Vazgeç" }));

    expect(deleteDraft).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("shows incoming drafts in the real inbox and lets the recipient respond", async () => {
    inboxShares = [{
      id: "share-1", draft_id: "draft-2", sender_id: "sender-1", recipient_id: "user-1",
      suggested_unit_id: null, message: "Hukuki yönden inceleyin.", status: "sent",
      responded_at: null, response_note: null, created_at: "2026-08-10T09:00:00Z",
      content: "Konu: Gelen taslak içeriği\n\nİncelenmek üzere iletilmiştir.", correspondence_type: "resmi_yazi", destination: "Hukuk Birimi",
    }];
    renderWithQueryClient(
      <MemoryRouter>
        <DraftsPage documents={[sourceDocument]} selected={null} analysis={null} onSelect={vi.fn()} onOpenDraft={vi.fn()} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("tab", { name: /Gelenler/ }));
    fireEvent.click(screen.getByRole("button", { name: /Gelen taslak içeriği/ }));
    expect(screen.getByLabelText("Resmî yazı önizlemesi")).toHaveTextContent("Gelen taslak içeriği");
    expect(screen.getByText("Hukuki yönden inceleyin.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Kabul et" }));

    await waitFor(() => expect(respondToShare).toHaveBeenCalledWith("share-1", "accept"));
  });

  it("sends a draft to the selected recipient from the primary action", async () => {
    renderWithQueryClient(
      <MemoryRouter>
        <DraftsPage documents={[sourceDocument]} selected={null} analysis={null} activeDraftId="draft-2" onSelect={vi.fn()} onOpenDraft={vi.fn()} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Gönder" }));
    expect(screen.getByRole("dialog", { name: "Taslağı gönder" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Alıcı seç" }));
    fireEvent.click(screen.getByRole("button", { name: "Seçilenlere gönder" }));

    await waitFor(() => expect(sendDraft).toHaveBeenCalledWith("draft-2", ["recipient-1"], ""));
  });
});
