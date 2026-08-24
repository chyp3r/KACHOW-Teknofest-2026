import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatDropZone } from "./ChatDropZone";

function dragEvent(fileNames: string[] = ["evrak.pdf"]) {
  return {
    dataTransfer: {
      types: fileNames.length > 0 ? ["Files"] : [],
      files: fileNames.map((name) => new File(["içerik"], name, { type: "application/pdf" })),
    },
  };
}

describe("ChatDropZone", () => {
  it("renders children and shows nothing extra when idle", () => {
    render(
      <ChatDropZone onUpload={vi.fn()}>
        <p>Sohbet içeriği</p>
      </ChatDropZone>,
    );

    expect(screen.getByText("Sohbet içeriği")).toBeInTheDocument();
    expect(screen.queryByText("Dosyanızı buraya bırakın")).not.toBeInTheDocument();
  });

  it("shows the drop overlay while a file is dragged over it, and hides it when the drag leaves", () => {
    render(
      <ChatDropZone onUpload={vi.fn()}>
        <p>Sohbet içeriği</p>
      </ChatDropZone>,
    );

    const wrapper = screen.getByText("Sohbet içeriği").closest(".chat-dropzone-wrapper")!;
    fireEvent.dragEnter(wrapper, dragEvent());
    expect(screen.getByText("Dosyanızı buraya bırakın")).toBeInTheDocument();

    fireEvent.dragLeave(wrapper, dragEvent());
    expect(screen.queryByText("Dosyanızı buraya bırakın")).not.toBeInTheDocument();
  });

  it("does not open the overlay for a plain text drag (no files)", () => {
    render(
      <ChatDropZone onUpload={vi.fn()}>
        <p>Sohbet içeriği</p>
      </ChatDropZone>,
    );

    const wrapper = screen.getByText("Sohbet içeriği").closest(".chat-dropzone-wrapper")!;
    fireEvent.dragEnter(wrapper, dragEvent([]));
    expect(screen.queryByText("Dosyanızı buraya bırakın")).not.toBeInTheDocument();
  });

  it("uploads a valid dropped file and starts document analysis", async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined);
    render(
      <ChatDropZone onUpload={onUpload}>
        <p>Sohbet içeriği</p>
      </ChatDropZone>,
    );

    const wrapper = screen.getByText("Sohbet içeriği").closest(".chat-dropzone-wrapper")!;
    fireEvent.drop(wrapper, dragEvent(["dilekce.pdf"]));

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));
    expect(onUpload.mock.calls[0][0].name).toBe("dilekce.pdf");
  });

  it("rejects an unsupported file type in the overlay without ever calling onUpload", () => {
    const onUpload = vi.fn();
    render(
      <ChatDropZone onUpload={onUpload}>
        <p>Sohbet içeriği</p>
      </ChatDropZone>,
    );

    const wrapper = screen.getByText("Sohbet içeriği").closest(".chat-dropzone-wrapper")!;
    fireEvent.drop(wrapper, dragEvent(["virus.exe"]));

    expect(screen.getByText("Bu dosya türü desteklenmiyor.")).toBeInTheDocument();
    expect(onUpload).not.toHaveBeenCalled();
  });

});
