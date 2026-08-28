import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDocuments } from "./useDocuments";

const mocks = vi.hoisted(() => ({
  list: vi.fn(), analyze: vi.fn(), getAnalysis: vi.fn(), getText: vi.fn(),
  generateDetailedSummary: vi.fn(),
  generateDetailedAnalysis: vi.fn(),
  documentGraph: vi.fn(),
}));

vi.mock("../services/documentService", () => ({ documentService: mocks }));
vi.mock("../services/graphService", () => ({
  graphService: { documentGraph: mocks.documentGraph },
}));

const remoteDocument = {
  file_name: "remote.pdf",
  storage_path: "user/remote.pdf",
  upload_time: "2026-08-09T10:00:00Z",
  document_type: "dilekce",
  document_type_label: "Dilekçe",
  compliance_status: "compliant",
  summary: "Sunucudaki evrak",
};

describe("useDocuments", () => {
  function wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, {
      client: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    }, children);
  }

  beforeEach(() => {
    mocks.list.mockReset().mockResolvedValue([remoteDocument]);
    mocks.analyze.mockReset();
    mocks.getAnalysis.mockReset().mockResolvedValue({ ...remoteDocument });
    mocks.getText.mockReset().mockResolvedValue({
      pages: ["Belge metni"],
      extracted_text: "Belge metni",
      page_count: 1,
      extractor: "pdfium",
      used_ocr: false,
    });
    mocks.generateDetailedSummary.mockReset();
    mocks.generateDetailedAnalysis.mockReset();
    mocks.documentGraph.mockReset().mockResolvedValue(null);
  });

  it("clears a selected ghost document that is absent from the backend list", async () => {
    const { result } = renderHook(() => useDocuments("user-1"), { wrapper });
    await waitFor(() => expect(result.current.documents).toEqual([remoteDocument]));

    act(() => result.current.setSelectedDocument({
      ...remoteDocument,
      file_name: "ghost.pdf",
      storage_path: "user/ghost.pdf",
    }));

    await waitFor(() => expect(result.current.selectedDocument).toBeNull());
  });

  it("stages a selected file locally and analyzes it only on demand", async () => {
    const analyzed = {
      ...remoteDocument,
      file_name: "bekleyen.pdf",
      storage_path: "uploads/analyzed.pdf",
      extraction: { extractor: "pdfium", page_count: 1, char_count: 120, used_ocr: false },
      fields: {},
      missing_fields: [],
      mevzuat_references: [],
      guardrail: {
        sensitivity_level: "unmarked",
        pii_findings: [],
        requires_human_review: false,
        reasons: [],
      },
    };
    mocks.analyze.mockResolvedValue(analyzed);
    const { result } = renderHook(() => useDocuments("user-1"), { wrapper });
    await waitFor(() => expect(result.current.documents).toEqual([remoteDocument]));

    let pendingPath = "";
    await act(async () => {
      const pending = await result.current.upload(
        new File(["içerik"], "bekleyen.pdf", { type: "application/pdf" }),
      );
      pendingPath = pending.storage_path;
    });

    expect(result.current.documents[0]).toMatchObject({
      file_name: "bekleyen.pdf",
      analyzed: false,
    });
    expect(mocks.analyze).not.toHaveBeenCalled();
    expect(mocks.getText).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.analyze(pendingPath);
    });

    expect(mocks.analyze).toHaveBeenCalledTimes(1);
    expect(mocks.analyze.mock.calls[0][0]).toBeInstanceOf(File);
    expect(result.current.documents[0]).toMatchObject({
      storage_path: "uploads/analyzed.pdf",
      analyzed: true,
    });
    await waitFor(() =>
      expect(mocks.getText).toHaveBeenCalledWith("uploads/analyzed.pdf"),
    );
  });

  it("can analyze a file immediately after staging it for chat", async () => {
    mocks.analyze.mockResolvedValue({
      ...remoteDocument,
      storage_path: "uploads/chat.pdf",
      extraction: { extractor: "pdfium", page_count: 1, char_count: 120, used_ocr: false },
      fields: {},
      missing_fields: [],
      mevzuat_references: [],
      guardrail: {
        sensitivity_level: "unmarked",
        pii_findings: [],
        requires_human_review: false,
        reasons: [],
      },
    });
    const { result } = renderHook(() => useDocuments("user-1"), { wrapper });
    await waitFor(() => expect(result.current.documents).toEqual([remoteDocument]));
    const upload = result.current.upload;
    const analyze = result.current.analyze;

    await act(async () => {
      const pending = await upload(
        new File(["içerik"], "chat.pdf", { type: "application/pdf" }),
      );
      await analyze(pending.storage_path);
    });

    expect(mocks.analyze).toHaveBeenCalledTimes(1);
    expect(result.current.documents[0].storage_path).toBe("uploads/chat.pdf");
  });

  it("tracks detailed summary generation by storage path and publishes the result", async () => {
    let resolveSummary!: (analysis: typeof remoteDocument & { detailed_summary: string }) => void;
    const summaryPromise = new Promise<typeof remoteDocument & { detailed_summary: string }>((resolve) => {
      resolveSummary = resolve;
    });
    mocks.generateDetailedSummary.mockReturnValue(summaryPromise);
    const { result } = renderHook(() => useDocuments("user-1"), { wrapper });
    await waitFor(() => expect(result.current.documents).toEqual([remoteDocument]));

    act(() => result.current.setSelectedDocument(remoteDocument));
    await waitFor(() => expect(result.current.analysis).toMatchObject(remoteDocument));

    let generatePromise!: Promise<void>;
    act(() => {
      generatePromise = result.current.generateDetailedSummary(remoteDocument.storage_path);
    });

    await waitFor(() =>
      expect(result.current.generatingDetailedSummaryPath).toBe(remoteDocument.storage_path),
    );

    await act(async () => {
      resolveSummary({ ...remoteDocument, detailed_summary: "Detaylı özet metni." });
      await generatePromise;
    });

    await waitFor(() => expect(result.current.generatingDetailedSummaryPath).toBeNull());
    expect(result.current.analysis?.detailed_summary).toBe("Detaylı özet metni.");
  });

  it("tracks detailed analysis generation by storage path and publishes the result", async () => {
    let resolveAnalysis!: (analysis: typeof remoteDocument) => void;
    const analysisPromise = new Promise<typeof remoteDocument>((resolve) => {
      resolveAnalysis = resolve;
    });
    mocks.generateDetailedAnalysis.mockReturnValue(analysisPromise);
    const { result } = renderHook(() => useDocuments("user-1"), { wrapper });
    await waitFor(() => expect(result.current.documents).toEqual([remoteDocument]));

    act(() => result.current.setSelectedDocument(remoteDocument));
    await waitFor(() => expect(result.current.analysis).toMatchObject(remoteDocument));

    let generatePromise!: Promise<void>;
    act(() => {
      generatePromise = result.current.generateDetailedAnalysis(remoteDocument.storage_path);
    });

    await waitFor(() =>
      expect(result.current.generatingDetailedAnalysisPath).toBe(remoteDocument.storage_path),
    );

    await act(async () => {
      resolveAnalysis({ ...remoteDocument, summary: "Yeniden analiz edildi." });
      await generatePromise;
    });

    await waitFor(() => expect(result.current.generatingDetailedAnalysisPath).toBeNull());
    expect(result.current.analysis?.summary).toBe("Yeniden analiz edildi.");
  });
});
