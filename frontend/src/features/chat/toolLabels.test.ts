import { describe, expect, it } from "vitest";
import { toolLabel } from "./toolLabels";

describe("toolLabel", () => {
  it("maps every known assistant tool name to Turkish", () => {
    expect(toolLabel("suggest_unit")).toBe("Birim önerisi");
    expect(toolLabel("search_document")).toBe("Belgede arama");
    expect(toolLabel("get_document_details")).toBe("Belge özeti ve üst verisi");
    expect(toolLabel("search_legislation")).toBe("Mevzuat araması");
    expect(toolLabel("request_handoff")).toBe("İlgili akışa devretme");
    expect(toolLabel("propose_transfer")).toBe("Aktarım önerisi");
  });

  it("degrades an unknown name to a readable form instead of dropping it", () => {
    expect(toolLabel("some_new_tool")).toBe("some new tool");
  });
});
