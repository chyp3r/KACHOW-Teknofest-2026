import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { GraphNode } from "../../types/documents";
import { NodeInspector } from "./NodeInspector";

function baseNode(overrides: Partial<GraphNode>): GraphNode {
  return {
    id: "x", node_type: "document", label: "x",
    storage_path: null, file_name: null, document_type_label: null,
    compliance_status: null, has_analysis: null,
    kanun: null, madde: null, field_labels: [], document_count: null,
    entity_kind: null, surface_forms: [], attributes: {},
    ...overrides,
  };
}

describe("NodeInspector", () => {
  it("renders nothing when there is no selected node", () => {
    const { container } = render(<NodeInspector node={null} onClose={() => undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a document's attribute payload", () => {
    const node = baseNode({
      node_type: "document",
      label: "evrak.pdf",
      storage_path: "uploads/evrak.pdf",
      attributes: {
        sayi: "E-1-2", tarih: "18.03.2026", konu: "Test konusu",
        muhatap: "ÖRNEK KAYMAKAMLIĞINA", gonderen_kurum: "ÖRNEK BAKANLIĞI",
        ivedilik: "Acele", summary: "Kısa özet.", missing_field_count: 2,
      },
    });

    render(<NodeInspector node={node} onClose={() => undefined} />);

    expect(screen.getByText("E-1-2")).toBeInTheDocument();
    expect(screen.getByText("18.03.2026")).toBeInTheDocument();
    expect(screen.getByText("ÖRNEK KAYMAKAMLIĞINA")).toBeInTheDocument();
    expect(screen.getByText("Kısa özet.")).toBeInTheDocument();
  });

  it("calls onOpenDocument with the storage path when the open-document action is used", () => {
    const onOpenDocument = vi.fn();
    const node = baseNode({ node_type: "document", storage_path: "uploads/evrak.pdf" });

    render(<NodeInspector node={node} onClose={() => undefined} onOpenDocument={onOpenDocument} />);
    fireEvent.click(screen.getByRole("button", { name: /belgeyi aç/i }));

    expect(onOpenDocument).toHaveBeenCalledWith("uploads/evrak.pdf");
  });

  it("lists every merged surface form for an entity node, disclosing the OCR-variant merge", () => {
    const node = baseNode({
      node_type: "entity",
      label: "Türkiye Büyük Millet Meclisi Başkanlığı",
      entity_kind: "kurum",
      surface_forms: [
        "TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA",
        "TÜRKIYE BÜYÜK MILLET MECLISI BASKANLIÇINA",
      ],
      document_count: 11,
    });

    render(<NodeInspector node={node} onClose={() => undefined} />);

    expect(screen.getByText("TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA")).toBeInTheDocument();
    expect(screen.getByText("TÜRKIYE BÜYÜK MILLET MECLISI BASKANLIÇINA")).toBeInTheDocument();
    expect(screen.getByText(/11 belge/)).toBeInTheDocument();
  });

  it("renders a madde node's field labels and breach count", () => {
    const node = baseNode({
      node_type: "madde", label: "m.17", kanun: "2646", madde: "17",
      field_labels: ["İmza sahibi", "İmza sahibinin unvanı"], document_count: 7,
    });

    render(<NodeInspector node={node} onClose={() => undefined} />);

    expect(screen.getByText(/İmza sahibi/)).toBeInTheDocument();
    expect(screen.getByText(/7 evrakta ihlal/)).toBeInTheDocument();
  });

  it("calls onClose when the close action is used", () => {
    const onClose = vi.fn();
    render(<NodeInspector node={baseNode({})} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: /kapat/i }));

    expect(onClose).toHaveBeenCalled();
  });
});
