import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GraphFilters } from "./GraphFilters";

describe("GraphFilters", () => {
  it("checks a node-type box when that type is in the allowed set", () => {
    render(
      <GraphFilters
        mode="unified"
        nodeTypes={new Set(["document", "entity"])}
        edgeTypes={new Set(["ihlal", "atif", "muhatap", "gonderen", "bahseder", "konu"])}
        onToggleNodeType={() => undefined}
        onToggleEdgeType={() => undefined}
        onSelectPreset={() => undefined}
      />,
    );

    expect(screen.getByRole("checkbox", { name: /evrak/i })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /madde/i })).not.toBeChecked();
  });

  it("calls onToggleNodeType with the clicked type", () => {
    const onToggleNodeType = vi.fn();
    render(
      <GraphFilters
        mode="unified"
        nodeTypes={new Set(["document"])}
        edgeTypes={new Set(["ihlal"])}
        onToggleNodeType={onToggleNodeType}
        onToggleEdgeType={() => undefined}
        onSelectPreset={() => undefined}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: /^kurum\/kişi$/i }));

    expect(onToggleNodeType).toHaveBeenCalledWith("entity");
  });

  it("calls onToggleEdgeType with the clicked kind", () => {
    const onToggleEdgeType = vi.fn();
    render(
      <GraphFilters
        mode="unified"
        nodeTypes={new Set(["document"])}
        edgeTypes={new Set(["ihlal"])}
        onToggleNodeType={() => undefined}
        onToggleEdgeType={onToggleEdgeType}
        onSelectPreset={() => undefined}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: /^bahseder/i }));

    expect(onToggleEdgeType).toHaveBeenCalledWith("bahseder");
  });

  it("calls onSelectPreset('compliance') when the compliance-only preset is chosen", () => {
    const onSelectPreset = vi.fn();
    render(
      <GraphFilters
        mode="unified"
        nodeTypes={new Set(["document"])}
        edgeTypes={new Set(["ihlal"])}
        onToggleNodeType={() => undefined}
        onToggleEdgeType={() => undefined}
        onSelectPreset={onSelectPreset}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /sadece uyum/i }));

    expect(onSelectPreset).toHaveBeenCalledWith("compliance");
  });

  it("calls onSelectPreset('unified') when the full-graph preset is chosen", () => {
    const onSelectPreset = vi.fn();
    render(
      <GraphFilters
        mode="compliance"
        nodeTypes={new Set(["document"])}
        edgeTypes={new Set(["ihlal"])}
        onToggleNodeType={() => undefined}
        onToggleEdgeType={() => undefined}
        onSelectPreset={onSelectPreset}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /tüm graf/i }));

    expect(onSelectPreset).toHaveBeenCalledWith("unified");
  });
});
