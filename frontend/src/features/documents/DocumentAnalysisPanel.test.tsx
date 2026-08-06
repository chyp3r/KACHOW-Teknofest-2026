import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
});
