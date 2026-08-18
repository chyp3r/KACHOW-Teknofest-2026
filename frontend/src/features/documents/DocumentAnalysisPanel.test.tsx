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
  it("renders the document summary", () => {
    render(<DocumentAnalysisPanel analysis={analysis} />);
    expect(screen.getByText("Özet")).toBeInTheDocument();
  });

  it("does not render a summary section when the summary is empty", () => {
    render(<DocumentAnalysisPanel analysis={{ ...analysis, summary: "" }} />);
    expect(screen.queryByText("Özet")).not.toBeInTheDocument();
  });

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

  it("does not render the signature section when the field is absent", () => {
    // `signature` is optional (see types/documents.ts) specifically so a
    // pre-existing analysis object, like this suite's own base fixture,
    // still type-checks and renders without it.
    render(<DocumentAnalysisPanel analysis={analysis} />);
    expect(screen.queryByText("İmza ve mühür")).not.toBeInTheDocument();
  });

  it("shows a signed badge and detected marks when signature is present", () => {
    render(
      <DocumentAnalysisPanel
        analysis={{
          ...analysis,
          signature: {
            is_signed: true,
            has_stamp: true,
            marks: [
              { kind: "signature", page: 1, bbox: [10, 900, 200, 950], confidence: 0.8 },
              { kind: "stamp", page: 1, bbox: [600, 100, 700, 200], confidence: 0.7 },
            ],
          },
        }}
      />,
    );

    fireEvent.click(screen.getByText("İmza ve mühür"));

    expect(screen.getByText("İmzalı")).toBeInTheDocument();
    expect(screen.getByText("Mühür/damga")).toBeInTheDocument();
  });

  it("shows an unsigned badge and empty state when no marks were detected", () => {
    render(
      <DocumentAnalysisPanel
        analysis={{
          ...analysis,
          signature: { is_signed: false, has_stamp: false, marks: [] },
        }}
      />,
    );

    fireEvent.click(screen.getByText("İmza ve mühür"));

    expect(screen.getByText("İmza tespit edilmedi")).toBeInTheDocument();
    expect(
      screen.getByText("Sayfada imza, mühür veya el yazısı bölgesi tespit edilmedi."),
    ).toBeInTheDocument();
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

  it("does not render the detailed summary section when not wired", () => {
    render(<DocumentAnalysisPanel analysis={analysis} />);
    expect(screen.queryByText("Detaylı özet")).not.toBeInTheDocument();
  });

  it("offers a generate button when detailed_summary is absent", () => {
    render(
      <DocumentAnalysisPanel analysis={analysis} onGenerateDetailedSummary={vi.fn()} />,
    );

    fireEvent.click(screen.getByText("Detaylı özet"));

    expect(
      screen.getByRole("button", { name: "Detaylı özet oluştur" }),
    ).toBeInTheDocument();
  });

  it("triggers generation and surfaces a failure without losing the short summary", async () => {
    const onGenerateDetailedSummary = vi.fn().mockRejectedValue(new Error("zaman aşımı"));
    render(
      <DocumentAnalysisPanel
        analysis={analysis}
        onGenerateDetailedSummary={onGenerateDetailedSummary}
      />,
    );

    fireEvent.click(screen.getByText("Detaylı özet"));
    fireEvent.click(screen.getByRole("button", { name: "Detaylı özet oluştur" }));

    await waitFor(() => expect(onGenerateDetailedSummary).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText("zaman aşımı")).toBeInTheDocument());
    // The short summary above must still be intact -- a detailed-summary
    // failure is scoped to its own section, never the whole panel.
    expect(screen.getByText("Özet")).toBeInTheDocument();
  });

  it("shows the detailed summary text instead of the button once generated", () => {
    render(
      <DocumentAnalysisPanel
        analysis={{ ...analysis, detailed_summary: "Çok paragraflı ayrıntılı özet." }}
        onGenerateDetailedSummary={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByText("Detaylı özet"));

    expect(screen.getByText("Çok paragraflı ayrıntılı özet.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Detaylı özet oluştur" }),
    ).not.toBeInTheDocument();
  });

  it("does not render the document graph section when documentGraph is not wired", () => {
    render(<DocumentAnalysisPanel analysis={analysis} />);
    expect(screen.queryByText("Belge ilişkileri")).not.toBeInTheDocument();
  });

  it("renders the document graph section once documentGraph data arrives", () => {
    render(
      <DocumentAnalysisPanel
        analysis={analysis}
        documentGraph={{
          nodes: [
            {
              id: "madde:2646:17", node_type: "madde", label: "m.17",
              storage_path: null, file_name: null, document_type_label: null,
              compliance_status: null, has_analysis: null,
              kanun: "2646", madde: "17", field_labels: ["İmza sahibi"], document_count: 1,
            },
          ],
          edges: [],
          insights: {
            document_count: 1, madde_count: 1, kanun_count: 0,
            rule_edge_count: 0, llm_edge_count: 0, unresolved_reference_count: 0,
            top_breached_madde: null,
          },
        }}
      />,
    );

    fireEvent.click(screen.getByText("Belge ilişkileri"));

    expect(screen.getByText(/m\.17/)).toBeInTheDocument();
  });
});
