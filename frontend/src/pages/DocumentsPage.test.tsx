import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
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

const renderPage = (page: ReactElement) => render(<MemoryRouter>{page}</MemoryRouter>);

describe("DocumentsPage", () => {
  it("opens the compact uploader from the header action and omits the subtitle", () => {
    renderPage(
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

  it("keeps the same draft-style master list before and after a document is opened", () => {
    const commonProps = {
      documents: [document],
      analysis: null,
      loading: false,
      uploading: false,
      error: null,
      onUpload: vi.fn().mockResolvedValue(undefined),
      onSelect: vi.fn(),
    };
    const view = renderPage(<DocumentsPage {...commonProps} selected={null} />);

    const closedList = screen.getByRole("list", { name: "Evrak listesi" });
    const closedRow = within(closedList).getByRole("button", { name: /izin-talebi\.pdf/ });
    expect(closedRow).toHaveClass("document-list-item");
    expect(screen.queryByRole("table", { name: "Evrak kütüphanesi" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Bir evrak seçin" })).toBeInTheDocument();

    view.rerender(
      <MemoryRouter>
        <DocumentsPage {...commonProps} selected={document} analysis={analysis} />
      </MemoryRouter>,
    );

    const openList = screen.getByRole("list", { name: "Evrak listesi" });
    const openRow = within(openList).getByRole("button", { name: /izin-talebi\.pdf/ });
    expect(openRow).toHaveClass("document-list-item");
    expect(openRow).toHaveAttribute("aria-expanded", "true");
  });

  it("shows analysis in the detail pane and supports closing it", () => {
    const onCloseDocument = vi.fn();
    renderPage(
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
    expect(within(screen.getByRole("list", { name: "Evrak listesi" })).getByText("Yıllık izin talebi")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Evrak Özeti" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Liste görünümüne dön" }));
    expect(onCloseDocument).toHaveBeenCalledTimes(1);
  });

  it("switches between the supported reference detail tabs", () => {
    renderPage(
      <DocumentsPage
        documents={[document]}
        selected={document}
        analysis={analysis}
        loading={false}
        uploading={false}
        error={null}
        onUpload={vi.fn().mockResolvedValue(undefined)}
        onSelect={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Ayrıntılar" }));
    expect(screen.getByText("Evrak adı")).toBeInTheDocument();
    expect(screen.getByText("Sayfa sayısı")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Analiz" }));
    expect(screen.getByRole("heading", { name: "Belge karar sürecine hazır" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Temel bilgiler" })).toBeInTheDocument();
    expect(screen.queryByText("Analiz alanlarını görüntüle veya düzenle")).not.toBeInTheDocument();
  });

  it("edits basic analysis fields in place without replacing the compact grid", async () => {
    const onUpdateFields = vi.fn().mockResolvedValue(undefined);
    const detailedAnalysis: DocumentAnalysis = {
      ...analysis,
      fields: {
        tarih: "14.04.2026",
        konu: "4982 sayılı Kanun Kapsamında Bilgi Talebi",
        muhatap: "ÖRNEK BAKANLIĞI BİLGİ EDİNME BİRİMİNE",
        imza_sahibi: "Fatma Öz",
        gizlilik_derecesi: null,
        ivedilik: null,
        basvuran_adi: "Fatma Öz",
        adres: "Deneme Cad. No:5 Kat:3 Örnek/Örnek",
        iletisim: "ornek@ornek.example",
      },
    };
    renderPage(
      <DocumentsPage
        documents={[document]}
        selected={document}
        analysis={detailedAnalysis}
        loading={false}
        uploading={false}
        error={null}
        onUpload={vi.fn().mockResolvedValue(undefined)}
        onSelect={vi.fn()}
        onUpdateFields={onUpdateFields}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Analiz" }));
    const compactPanel = screen.getByRole("region", { name: "Temel bilgiler" });
    expect(compactPanel).not.toHaveClass("is-editing");
    expect(screen.getAllByText("—")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Temel bilgileri düzenle" }));
    expect(compactPanel).toHaveClass("is-editing");
    fireEvent.change(screen.getByLabelText("Muhatap"), { target: { value: "Hukuk İşleri Birimi" } });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));

    await waitFor(() => expect(onUpdateFields).toHaveBeenCalledWith(
      document.storage_path,
      expect.objectContaining({ muhatap: "Hukuk İşleri Birimi", konu: "4982 sayılı Kanun Kapsamında Bilgi Talebi" }),
    ));
    expect(compactPanel).not.toHaveClass("is-editing");
  });

  it("deletes a document after confirmation and closes it if it was open", async () => {
    const onDeleteDocument = vi.fn().mockResolvedValue(undefined);
    const onCloseDocument = vi.fn();
    renderPage(
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
        onDeleteDocument={onDeleteDocument}
      />,
    );

    fireEvent.click(screen.getByLabelText("izin-talebi.pdf için işlemler"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sil" }));
    expect(screen.getByRole("alertdialog", { name: "Evrakı sil" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sil" }));

    await waitFor(() => expect(onDeleteDocument).toHaveBeenCalledWith(document.storage_path));
    expect(onCloseDocument).toHaveBeenCalled();
  });

  it("does not delete anything when the confirmation is cancelled", () => {
    const onDeleteDocument = vi.fn();
    renderPage(
      <DocumentsPage
        documents={[document]}
        selected={null}
        analysis={null}
        loading={false}
        uploading={false}
        error={null}
        onUpload={vi.fn().mockResolvedValue(undefined)}
        onSelect={vi.fn()}
        onDeleteDocument={onDeleteDocument}
      />,
    );

    fireEvent.click(screen.getByLabelText("izin-talebi.pdf için işlemler"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sil" }));
    fireEvent.click(screen.getByRole("button", { name: "Vazgeç" }));

    expect(onDeleteDocument).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("hides the delete button when no onDeleteDocument is wired", () => {
    renderPage(
      <DocumentsPage
        documents={[document]}
        selected={null}
        analysis={null}
        loading={false}
        uploading={false}
        error={null}
        onUpload={vi.fn().mockResolvedValue(undefined)}
        onSelect={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByLabelText("izin-talebi.pdf için işlemler"));
    expect(screen.queryByRole("menuitem", { name: "Sil" })).not.toBeInTheDocument();
  });

  it("shows a single analyze action for a pending document", () => {
    const pendingDocument: DocumentMetadata = {
      ...document,
      storage_path: "pending:test-document",
      document_type: "",
      document_type_label: "",
      compliance_status: "",
      summary: "",
      analyzed: false,
    };
    const onAnalyzeDocument = vi.fn().mockResolvedValue(undefined);

    renderPage(
      <DocumentsPage
        documents={[pendingDocument]}
        selected={null}
        analysis={null}
        loading={false}
        uploading={false}
        error={null}
        onUpload={vi.fn().mockResolvedValue(undefined)}
        onAnalyzeDocument={onAnalyzeDocument}
        onSelect={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByLabelText("izin-talebi.pdf için işlemler"));
    const analyzeButton = screen.getByRole("menuitem", { name: "Analiz et" });
    expect(analyzeButton).toBeInTheDocument();
    fireEvent.click(analyzeButton);
    expect(onAnalyzeDocument).toHaveBeenCalledWith("pending:test-document");
  });

  it("makes review the primary action and explains the number of issues", () => {
    const reviewDocument = { ...document, compliance_status: "partially_compliant" };
    const reviewAnalysis: DocumentAnalysis = {
      ...analysis,
      ...reviewDocument,
      missing_fields: [
        { key: "imza", label: "İmza", severity: "high", mevzuat: "", reason: "İmza alanı doğrulanmalı." },
        { key: "tarih", label: "Tarih", severity: "medium", mevzuat: "", reason: "Tarih okunamadı." },
      ],
    };

    renderPage(
      <DocumentsPage
        documents={[reviewDocument]}
        selected={reviewDocument}
        analysis={reviewAnalysis}
        loading={false}
        uploading={false}
        error={null}
        onUpload={vi.fn().mockResolvedValue(undefined)}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getAllByText("İnceleme gerekli · 2 konu")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Analizi incele" }));
    expect(screen.getByRole("heading", { name: "2 konu incelenmeli" })).toBeInTheDocument();
    expect(screen.getByText("İmza alanı doğrulanmalı.")).toBeInTheDocument();
  });

  it("shows active filters and clears them in one action", () => {
    renderPage(
      <DocumentsPage
        documents={[document]}
        selected={null}
        analysis={null}
        loading={false}
        uploading={false}
        error={null}
        onUpload={vi.fn().mockResolvedValue(undefined)}
        onSelect={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: "Evraklarda ara" }), { target: { value: "izin" } });
    expect(screen.getByText("Arama: izin")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Filtreleri temizle" }));
    expect(screen.getByRole("textbox", { name: "Evraklarda ara" })).toHaveValue("");
    expect(screen.queryByLabelText("Etkin filtreler")).not.toBeInTheDocument();
  });

  it("keeps the same ten-row page size after opening document details", () => {
    const manyDocuments = Array.from({ length: 11 }, (_, index) => ({
      ...document,
      file_name: `evrak-${index + 1}.pdf`,
      storage_path: `documents/evrak-${index + 1}.pdf`,
    }));

    renderPage(
      <DocumentsPage
        documents={manyDocuments}
        selected={manyDocuments[0]}
        analysis={{ ...analysis, ...manyDocuments[0] }}
        loading={false}
        uploading={false}
        error={null}
        onUpload={vi.fn().mockResolvedValue(undefined)}
        onSelect={vi.fn()}
      />,
    );

    expect(within(screen.getByRole("list", { name: "Evrak listesi" })).getAllByRole("button")).toHaveLength(10);
    expect(screen.getByText("1–10 / 11")).toBeInTheDocument();
  });

  it("edits extracted text page by page", async () => {
    const onSaveText = vi.fn().mockResolvedValue(undefined);
    renderPage(
      <DocumentsPage
        documents={[document]}
        selected={document}
        analysis={analysis}
        documentText={{ pages: ["İlk metin"], extracted_text: "İlk metin", page_count: 1, extractor: "pdfium", used_ocr: false }}
        loading={false}
        uploading={false}
        error={null}
        onUpload={vi.fn().mockResolvedValue(undefined)}
        onSelect={vi.fn()}
        onSaveText={onSaveText}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Belge Metni" }));
    expect(screen.getByRole("heading", { name: "Sayfa 1/1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Düzenle" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Sayfa 1/1" }), { target: { value: "Düzeltilmiş metin" } });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));

    await waitFor(() => expect(onSaveText).toHaveBeenCalledWith(document.storage_path, ["Düzeltilmiş metin"]));
  });
});
