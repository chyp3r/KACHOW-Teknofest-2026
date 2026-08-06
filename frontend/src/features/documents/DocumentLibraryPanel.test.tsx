import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DocumentMetadata } from "../../types/documents";
import { DocumentLibraryPanel } from "./DocumentLibraryPanel";

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

function renderPanel(
  overrides: Partial<React.ComponentProps<typeof DocumentLibraryPanel>> = {},
) {
  const props: React.ComponentProps<typeof DocumentLibraryPanel> = {
    documents,
    selected: null,
    loading: false,
    uploading: false,
    error: null,
    onUpload: vi.fn().mockResolvedValue(undefined),
    onSelect: vi.fn(),
    onViewDetails: vi.fn(),
    ...overrides,
  };

  render(<DocumentLibraryPanel {...props} />);
  return props;
}

describe("DocumentLibraryPanel", () => {
  it("filters documents and selects a result", () => {
    const props = renderPanel();

    fireEvent.change(screen.getByRole("textbox", { name: "Evraklarda ara" }), {
      target: { value: "genelge" },
    });

    expect(screen.queryByText("Başvuru.pdf")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Genelge.pdf"));
    expect(props.onSelect).toHaveBeenCalledWith(documents[1]);
  });

  it("opens the detailed documents page", () => {
    const onViewDetails = vi.fn();
    renderPanel({ onViewDetails });

    fireEvent.click(
      screen.getByRole("button", { name: /detaylı görüntüle/i }),
    );
    expect(onViewDetails).toHaveBeenCalledTimes(1);
  });
});
