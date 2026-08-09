import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DocumentAnalysis, DocumentMetadata } from "../types/documents";
import { DocumentsPage } from "./DocumentsPage";

const document: DocumentMetadata = {
  file_name: "izin-talebi.pdf",
  storage_path: "documents/izin-talebi.pdf",
  upload_time: "2026-08-09T09:00:00Z",
  document_type: "petition",
  document_type_label: "Dilekçe",
  compliance_status: "compliant",
  summary: "Yıllık izin talebi",
};

const analysis: DocumentAnalysis = {
  ...document,
  extraction: {
    extractor: "pdfium",
    page_count: 1,
    char_count: 180,
    used_ocr: false,
  },
  fields: { konu: "Yıllık izin talebi" },
  missing_fields: [],
  mevzuat_references: [],
  guardrail: {
    sensitivity_level: "hizmete_ozel",
    pii_findings: [],
    requires_human_review: false,
    reasons: [],
  },
};

describe("DocumentsPage", () => {
  it("opens the compact uploader from the header action and omits the subtitle", () => {
    render(
      <DocumentsPage
        documents={[]}
        selected={null}
        analysis={null}
        loading={false}
        uploading={false}
        error={null}
        onUpload={vi.fn().mockResolvedValue(undefined)}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Evrak Kütüphanesi" })).toBeInTheDocument();
    expect(
      screen.queryByText(/Evrakları yükleyin, analiz sonuçlarını inceleyin/),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Yeni evrak yükle" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Evrak yükle" }));
    expect(screen.getByRole("heading", { name: "Yeni evrak yükle" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yüklemeyi kapat" })).toBeInTheDocument();
  });

  it("shows analysis below the selected document row and supports collapsing it", () => {
    const onCloseDocument = vi.fn();
    render(
      <DocumentsPage
        documents={[document]}
        selected={document}
        analysis={analysis}
        loading={false}
        uploading={false}
        error={null}
        onUpload={vi.fn().mockResolvedValue(undefined)}
        onSelect={vi.fn()}
        onCloseDocument={onCloseDocument}
      />,
    );

    const row = screen.getByRole("button", { name: /izin-talebi\.pdf/ });
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("heading", { name: "Analiz ayrıntıları" })).toBeInTheDocument();

    fireEvent.click(row);
    expect(onCloseDocument).toHaveBeenCalledTimes(1);
  });
});
