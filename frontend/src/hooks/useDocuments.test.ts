import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDocuments } from "./useDocuments";

const mocks = vi.hoisted(() => ({
  list: vi.fn(), analyze: vi.fn(), getAnalysis: vi.fn(),
}));

vi.mock("../services/documentService", () => ({ documentService: mocks }));

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
    mocks.getAnalysis.mockReset().mockResolvedValue({ ...remoteDocument });
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
});
