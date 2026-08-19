import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { DocumentMetadata } from "../../types/documents";
import type { PersistedDraft } from "../../types/drafts";
import { DocumentSelector } from "./DocumentSelector";

const documents: DocumentMetadata[] = [
  {
    file_name: "Başvuru.pdf",
    storage_path: "documents/basvuru.pdf",
    upload_time: "2026-08-01T10:00:00Z",
    document_type: "petition",
    document_type_label: "Dilekçe",
    compliance_status: "COMPLIANT",
    summary: "İzin başvurusu",
  },
  {
    file_name: "Genelge.pdf",
    storage_path: "documents/genelge.pdf",
    upload_time: "2026-08-02T10:00:00Z",
    document_type: "circular",
    document_type_label: "Genelge",
    compliance_status: "REVIEW",
    summary: "Kurum içi düzenleme",
  },
];

const draft: PersistedDraft = {
  id: "draft-1",
  user_id: "user-1",
  session_id: null,
  document_id: null,
  version: 1,
  parent_draft_id: null,
  content: "Konu: Yıllık izin talebi\n\nTaslak içeriği",
  correspondence_type: "response_letter",
  destination: "İnsan Kaynakları",
  status: "COMPLETED",
  confidence_score: 90,
  requires_human_approval: false,
  attempts: 1,
  verification: null,
  judge: null,
  missing_information: null,
  instructions: null,
  created_at: "2026-08-02T10:00:00Z",
  updated_at: "2026-08-02T10:00:00Z",
};

function renderSelector(selected: DocumentMetadata | null = null) {
  const onSelect = vi.fn();
  const onClear = vi.fn();
  render(
    <MemoryRouter>
      <DocumentSelector
        documents={documents}
        selected={selected}
        onSelect={onSelect}
        onClear={onClear}
      />
    </MemoryRouter>,
  );
  return { onSelect, onClear };
}

describe("DocumentSelector", () => {
  it("keeps the library hidden until the attach action is opened", () => {
    const { onSelect } = renderSelector();

    expect(screen.queryByRole("dialog", { name: "Sohbet bağlamı seç" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Evrak veya taslak ekle" }));
    expect(screen.getByRole("dialog", { name: "Sohbet bağlamı seç" })).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Evraklarda ara" }), {
      target: { value: "genelge" },
    });
    expect(screen.queryByText("Başvuru.pdf")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Genelge.pdf/i }));

    expect(onSelect).toHaveBeenCalledWith(documents[1]);
    expect(screen.queryByRole("dialog", { name: "Sohbet bağlamı seç" })).not.toBeInTheDocument();
  });

  it("renders a compact removable chip for the selected document", () => {
    const { onClear } = renderSelector(documents[0]);

    expect(screen.getByText("Başvuru.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Evrak veya taslak ekle" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Evrak seçimini kaldır" }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("allows a saved draft to be selected from the draft tab", () => {
    const onSelectDraft = vi.fn();
    render(
      <MemoryRouter>
        <DocumentSelector
          documents={documents}
          drafts={[draft]}
          selected={null}
          selectedDraft={null}
          onSelect={vi.fn()}
          onSelectDraft={onSelectDraft}
          onClear={vi.fn()}
          onClearDraft={vi.fn()}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Evrak veya taslak ekle" }));
    fireEvent.click(screen.getByRole("tab", { name: "Taslaklar" }));
    fireEvent.click(screen.getByRole("button", { name: /Yıllık izin talebi/i }));

    expect(onSelectDraft).toHaveBeenCalledWith(draft);
  });
});
