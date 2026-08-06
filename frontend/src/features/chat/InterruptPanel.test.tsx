import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { InterruptState } from "../../types/chat";
import { InterruptPanel } from "./InterruptPanel";

const missingInformation: InterruptState = {
  kind: "missing_information",
  interruptId: "interrupt-1",
  payload: {
    draft: "Hazırlanan resmî yazı taslağı",
    questions: [
      { key: "organization", label: "Kurum adı", required: true },
      { key: "document_count", label: "Belge sayısı", required: true },
    ],
  },
};

describe("InterruptPanel", () => {
  it("keeps the draft collapsed and requires missing information", () => {
    const onResume = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <InterruptPanel
        interrupt={missingInformation}
        loading={false}
        onResume={onResume}
      />,
    );

    expect(container.querySelector("details")).not.toHaveAttribute("open");
    const submit = screen.getByRole("button", {
      name: "Bilgileri gönder ve devam et",
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/kurum adı/i), {
      target: { value: "KACHOW" },
    });
    fireEvent.change(screen.getByLabelText(/belge sayısı/i), {
      target: { value: "24" },
    });
    expect(submit).toBeEnabled();

    fireEvent.click(submit);
    expect(onResume).toHaveBeenCalledWith(
      "answer",
      { organization: "KACHOW", document_count: "24" },
      "",
    );
  });

  it("shows explicit approval actions for a completed draft", () => {
    const onResume = vi.fn().mockResolvedValue(undefined);
    render(
      <InterruptPanel
        interrupt={{
          kind: "draft_approval",
          interruptId: "interrupt-2",
          payload: { draft: "Onaylanacak taslak" },
        }}
        loading={false}
        onResume={onResume}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Onayla" }));
    expect(onResume).toHaveBeenCalledWith("approve", {}, "");
  });
});
