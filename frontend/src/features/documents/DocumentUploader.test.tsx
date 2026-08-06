import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DocumentUploader } from "./DocumentUploader";

describe("DocumentUploader", () => {
  it("rejects unsupported files before upload", () => {
    const upload = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <DocumentUploader uploading={false} onUpload={upload} />,
    );
    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["test"], "belge.exe")] },
    });
    expect(
      screen.getByText("Bu dosya türü desteklenmiyor."),
    ).toBeInTheDocument();
    expect(upload).not.toHaveBeenCalled();
  });

  it("uploads a supported document", async () => {
    const upload = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <DocumentUploader uploading={false} onUpload={upload} />,
    );
    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [new File(["metin"], "evrak.pdf", { type: "application/pdf" })],
      },
    });
    expect(
      await screen.findByText("Evrak başarıyla yüklendi ve analiz edildi."),
    ).toBeInTheDocument();
    expect(upload).toHaveBeenCalledTimes(1);
  });
});
