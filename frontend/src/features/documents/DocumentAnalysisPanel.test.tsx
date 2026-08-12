import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DocumentAnalysis } from "../../types/documents";
import { DocumentAnalysisPanel } from "./DocumentAnalysisPanel";

const analysis: DocumentAnalysis = {
  file_name: "evrak.pdf",
  storage_path: "uploads/evrak.pdf",
  upload_time: "2026-08-06T00:00:00Z",
  document_type: "OTHER",
  document_type_label: "Diğer",
  compliance_status: "REVIEW_REQUIRED",
  summary: "Özet",
  extraction: {
    extractor: "pdfium",
    page_count: 1,
    char_count: 100,
    used_ocr: false,
  },
  fields: {},
  missing_fields: [],
  mevzuat_references: [],
  guardrail: {
    sensitivity_level: "gizli",
    pii_findings: [{ kind: "tckn", preview: "12*******90" }],
    requires_human_review: true,
    reasons: ["Gizlilik derecesi insan incelemesi gerektiriyor."],
  },
};

describe("DocumentAnalysisPanel", () => {
  it("shows sensitivity and only the masked PII preview", () => {
    render(<DocumentAnalysisPanel analysis={analysis} />);

    expect(screen.getByText("Gizli")).toBeInTheDocument();
    expect(screen.getByText("12*******90")).toBeInTheDocument();
    expect(
      screen.getAllByText(/insan incelemesi gerektiriyor/i).length,
    ).toBeGreaterThan(0);
  });

  it("stays read-only when no onSave is wired", () => {
    render(<DocumentAnalysisPanel analysis={analysis} />);
    expect(screen.queryByRole("button", { name: "Düzenle" })).not.toBeInTheDocument();
  });

  it("lets a missing field be filled in and saved, including list fields", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <DocumentAnalysisPanel
        analysis={{ ...analysis, fields: { konu: "İzin Talebi", ilgi: ["önceki yazı"] } }}
        onSave={onSave}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Düzenle" }));
    fireEvent.change(screen.getByLabelText("Muhatap"), { target: { value: "İlgili Makama" } });
    fireEvent.change(screen.getByLabelText("İlgi"), {
      target: { value: "önceki yazı\nikinci ilgi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));

    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          konu: "İzin Talebi",
          muhatap: "İlgili Makama",
          ilgi: ["önceki yazı", "ikinci ilgi"],
        }),
      ),
    );
  });

  it("discards edits on cancel without calling onSave", () => {
    const onSave = vi.fn();
    render(<DocumentAnalysisPanel analysis={analysis} onSave={onSave} />);

    fireEvent.click(screen.getByRole("button", { name: "Düzenle" }));
    fireEvent.change(screen.getByLabelText("Konu"), { target: { value: "Değişecek ama iptal edilecek" } });
    fireEvent.click(screen.getByRole("button", { name: "Vazgeç" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Konu")).not.toBeInTheDocument();
  });
});
