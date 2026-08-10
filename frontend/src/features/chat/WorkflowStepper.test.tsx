import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkflowStepper, type WorkflowStageItem } from "./WorkflowStepper";

const stages: WorkflowStageItem[] = [
  { id: "analysis", label: "Evrak analizi", description: "Uzun Türkçe belge açıklaması güvenli biçimde sarılır.", status: "todo", target: "classification" },
  { id: "approval", label: "İnsan onayı", description: "Kullanıcı kararı bekleniyor.", status: "interrupted", target: "human_gate" },
  { id: "routing", label: "Yönlendirme", description: "Hedef birim önerisi.", status: "completed", target: "routing" },
];

describe("WorkflowStepper", () => {
  it("renders each state once and keeps interrupted state distinct", () => {
    render(<WorkflowStepper stages={stages} onSelect={vi.fn()} />);

    expect(screen.getAllByText("Bekliyor")).toHaveLength(1);
    expect(screen.getByText("Yanıtınız bekleniyor")).toBeInTheDocument();
    expect(screen.getByText("Tamamlandı")).toBeInTheDocument();
  });

  it("activates the selected stage through its full-size button", () => {
    const onSelect = vi.fn();
    render(<WorkflowStepper stages={stages} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /İnsan onayı/ }));
    expect(onSelect).toHaveBeenCalledWith("human_gate");
  });
});
