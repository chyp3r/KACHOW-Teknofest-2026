import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { InterruptState } from "../../types/chat";
import { TransferConfirmCard } from "./TransferConfirmCard";

function confirmInterrupt(overrides: Partial<InterruptState["payload"]> = {}): InterruptState {
  return {
    kind: "artifact_transfer_confirm",
    interruptId: "interrupt-1",
    payload: {
      artifact_kind: "draft",
      source_artifact_id: "draft-1",
      source_version: 2,
      cross_unit: false,
      ...overrides,
    },
  };
}

function disambiguateInterrupt(overrides: Partial<InterruptState["payload"]> = {}): InterruptState {
  return {
    kind: "artifact_transfer_disambiguate",
    interruptId: "interrupt-2",
    payload: {
      artifact_kind: "draft",
      candidates: [
        { user_id: "u-1", username: "ahmet", unit_name: "İK" },
        { user_id: "u-2", username: "mehmet", unit_name: "Hukuk" },
      ],
      ...overrides,
    },
  };
}

describe("TransferConfirmCard", () => {
  it("always renders the cross-unit warning when payload.cross_unit is true", () => {
    render(
      <TransferConfirmCard
        interrupt={confirmInterrupt({ cross_unit: true })}
        loading={false}
        onSelect={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/farklı bir birimde/i);
  });

  it("never renders the cross-unit warning when payload.cross_unit is false", () => {
    render(
      <TransferConfirmCard
        interrupt={confirmInterrupt({ cross_unit: false })}
        loading={false}
        onSelect={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows the draft version in the confirmation question", () => {
    render(
      <TransferConfirmCard
        interrupt={confirmInterrupt({ source_version: 3 })}
        loading={false}
        onSelect={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.getByText(/v3/)).toBeInTheDocument();
  });

  it("approve calls onApprove, vazgeç calls onReject", () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    render(
      <TransferConfirmCard
        interrupt={confirmInterrupt()}
        loading={false}
        onSelect={vi.fn()}
        onApprove={onApprove}
        onReject={onReject}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /onayla ve gönder/i }));
    expect(onApprove).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /vazgeç/i }));
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  it("renders every candidate and never lets the model choose -- only a click resolves it", () => {
    const onSelect = vi.fn();
    render(
      <TransferConfirmCard
        interrupt={disambiguateInterrupt()}
        loading={false}
        onSelect={onSelect}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.getByText("ahmet")).toBeInTheDocument();
    expect(screen.getByText("mehmet")).toBeInTheDocument();

    const selectButtons = screen.getAllByRole("button", { name: "Seç" });
    expect(selectButtons).toHaveLength(2);
    fireEvent.click(selectButtons[0]);
    expect(onSelect).toHaveBeenCalledWith("u-1");
  });

  it("disambiguation offers a vazgeç but no approve/reject-send action", () => {
    render(
      <TransferConfirmCard
        interrupt={disambiguateInterrupt()}
        loading={false}
        onSelect={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /onayla ve gönder/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /vazgeç/i })).toBeInTheDocument();
  });
});
