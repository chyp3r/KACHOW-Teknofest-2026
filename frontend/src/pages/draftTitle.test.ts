import { describe, expect, it } from "vitest";
import type { PersistedDraft } from "../types/drafts";
import { correspondenceTypeLabel, documentName, draftSubject, draftTitle } from "./draftTitle";

function makeDraft(overrides: Partial<PersistedDraft> = {}): PersistedDraft {
  return {
    id: "draft-1",
    user_id: "user-1",
    session_id: "session-1",
    document_id: null,
    version: 1,
    parent_draft_id: null,
    content: "Sayın Makam,\n\nArz ederim.",
    correspondence_type: null,
    destination: null,
    status: "COMPLETED",
    confidence_score: 90,
    requires_human_approval: false,
    attempts: 1,
    verification: null,
    judge: null,
    missing_information: null,
    instructions: null,
    created_at: "2026-08-18T10:00:00Z",
    updated_at: "2026-08-18T10:00:00Z",
    ...overrides,
  };
}

describe("draftSubject", () => {
  it("extracts the draft's own Konu line", () => {
    const draft = makeDraft({
      content: "Konu: Yıllık İzin Talebi\nSayı: [Belge Sayısı]\n\nSayın Makam,",
    });
    expect(draftSubject(draft)).toBe("Yıllık İzin Talebi");
  });

  it("returns null when there is no Konu line at all", () => {
    expect(draftSubject(makeDraft({ content: "Sayın Makam,\n\nArz ederim." }))).toBeNull();
  });

  it("returns null for an unfilled [Konu] placeholder", () => {
    expect(draftSubject(makeDraft({ content: "Konu: [Konu]\n\nSayın Makam," }))).toBeNull();
  });

  it("never matches an İlgi line quoting a different document's subject", () => {
    // "İlgi" is a distinct label from "Konu" -- must not be swept in by a
    // loose match.
    const draft = makeDraft({ content: "İlgi: Konu: Eski bir yazı\n\nSayın Makam," });
    expect(draftSubject(draft)).toBeNull();
  });
});

describe("documentName", () => {
  it("returns the source document's file name when it matches", () => {
    const documents = [
      { file_name: "izin-talebi.pdf", storage_path: "doc-1" } as never,
    ];
    expect(documentName("doc-1", documents)).toBe("izin-talebi.pdf");
  });

  it("falls back to a fixed label when there is no attached document", () => {
    expect(documentName(null, [])).toBe("Kaynak yok");
  });
});

describe("correspondenceTypeLabel", () => {
  it("uses the catalog label when the type is known", () => {
    const types = [{ value: "response_letter", label: "Cevap Yazısı" }];
    expect(correspondenceTypeLabel(makeDraft({ correspondence_type: "response_letter" }), types)).toBe(
      "Cevap Yazısı",
    );
  });

  it("falls back to a generic label when correspondence_type is unset", () => {
    expect(correspondenceTypeLabel(makeDraft({ correspondence_type: null }), [])).toBe("Resmî taslak");
  });
});

// ==========================================
// draftTitle -- the actual bug report: every document-less draft of the
// same type rendered an identical, non-distinguishing "Kaynak yok -
// Bilgilendirme Metni" title.
// ==========================================
describe("draftTitle", () => {
  const types = [{ value: "information_notice", label: "Bilgilendirme Metni" }];

  it("prefers the draft's own subject when one can be extracted", () => {
    const draft = makeDraft({
      document_id: null,
      correspondence_type: "information_notice",
      content: "Konu: Yeni Personel Oryantasyonu\nSayı: [Belge Sayısı]\n\nSayın İK,",
    });
    expect(draftTitle(draft, [], types)).toBe("Yeni Personel Oryantasyonu · Bilgilendirme Metni");
  });

  it("two document-less drafts of the same type are no longer indistinguishable", () => {
    const first = makeDraft({
      correspondence_type: "information_notice",
      content: "Konu: Yıllık İzin Duyurusu\n\nSayın Personel,",
    });
    const second = makeDraft({
      correspondence_type: "information_notice",
      content: "Konu: Ofis Taşınma Duyurusu\n\nSayın Personel,",
    });
    expect(draftTitle(first, [], types)).not.toBe(draftTitle(second, [], types));
  });

  it("falls back to the source/type form when no subject can be extracted", () => {
    const draft = makeDraft({
      document_id: null,
      correspondence_type: "information_notice",
      content: "Sayın Personel,\n\nArz ederim.",
    });
    expect(draftTitle(draft, [], types)).toBe("Kaynak yok - Bilgilendirme Metni");
  });
});
