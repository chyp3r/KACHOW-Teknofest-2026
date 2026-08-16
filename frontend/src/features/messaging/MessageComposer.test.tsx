import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MessageComposer } from "./MessageComposer";

describe("MessageComposer", () => {
  it("sends on Enter and clears the input", () => {
    const onSend = vi.fn().mockResolvedValue(undefined);
    render(<MessageComposer sending={false} onSend={onSend} />);
    const textarea = screen.getByLabelText("Mesaj") as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: "merhaba" } });
    fireEvent.keyDown(textarea, { key: "Enter" });

    expect(onSend).toHaveBeenCalledWith("merhaba");
    expect(textarea.value).toBe("");
  });

  it("inserts a newline instead of sending on Shift+Enter", () => {
    const onSend = vi.fn();
    render(<MessageComposer sending={false} onSend={onSend} />);
    const textarea = screen.getByLabelText("Mesaj");

    fireEvent.change(textarea, { target: { value: "satır 1" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });

    expect(onSend).not.toHaveBeenCalled();
  });

  it("never sends an empty or whitespace-only message", () => {
    const onSend = vi.fn();
    render(<MessageComposer sending={false} onSend={onSend} />);
    const textarea = screen.getByLabelText("Mesaj");

    fireEvent.change(textarea, { target: { value: "   " } });
    fireEvent.keyDown(textarea, { key: "Enter" });

    expect(onSend).not.toHaveBeenCalled();
  });

  it("disables the composer while the conversation cannot be written to", () => {
    render(<MessageComposer disabled sending={false} onSend={vi.fn()} />);
    expect(screen.getByLabelText("Mesaj")).toBeDisabled();
  });
});
