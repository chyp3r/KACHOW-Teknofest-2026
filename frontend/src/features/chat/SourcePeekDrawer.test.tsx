import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SourcePeekDrawer } from "./SourcePeekDrawer";

const PAGES = [
  "GÖKDENİZ KURUCA\nGenel not ortalaması 3.83.\nSınıf sıralaması 144 öğrenci içinde 2.",
  "İkinci sayfanın içeriği burada.",
];

describe("SourcePeekDrawer", () => {
  it("renders nothing until a citation is opened", () => {
    const { container } = render(
      <SourcePeekDrawer target={null} pages={PAGES} onClose={vi.fn()} />,
    );

    expect(container.querySelector(".source-peek-drawer")).toBeNull();
  });

  it("shows the quoted sentence and highlights it in the page", () => {
    const { container } = render(
      <SourcePeekDrawer
        target={{ index: 1, page: 1, quote: "Genel not ortalaması 3.83." }}
        pages={PAGES}
        documentName="cv.pdf"
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Kaynak 1 — Sayfa 1")).toBeTruthy();
    expect(screen.getByText("cv.pdf")).toBeTruthy();
    expect(container.querySelector(".source-peek-quote")?.textContent).toBe(
      "Genel not ortalaması 3.83.",
    );

    // Exact quote -> exact highlight, and the rest of the page around it.
    expect(container.querySelector("mark")?.textContent).toBe("Genel not ortalaması 3.83.");
    expect(container.querySelector(".source-peek-page")?.textContent).toContain(
      "GÖKDENİZ KURUCA",
    );
    expect(screen.queryByText(/birebir bulunamadı/)).toBeNull();
  });

  it("opens the page the citation names, not the first one", () => {
    const { container } = render(
      <SourcePeekDrawer
        target={{ index: 2, page: 2, quote: "İkinci sayfanın içeriği burada." }}
        pages={PAGES}
        onClose={vi.fn()}
      />,
    );

    expect(container.querySelector("mark")?.textContent).toBe("İkinci sayfanın içeriği burada.");
  });

  it("falls back to the fuzzy match when the quote was lightly reflowed", () => {
    const { container } = render(
      <SourcePeekDrawer
        target={{ index: 1, page: 1, quote: "Sınıf sıralaması 144 öğrenci içinde ikinci" }}
        pages={PAGES}
        onClose={vi.fn()}
      />,
    );

    expect(container.querySelector("mark")?.textContent).toContain("144 öğrenci");
  });

  it("still shows the quote when the page cannot be resolved", () => {
    const { container } = render(
      <SourcePeekDrawer
        target={{ index: 1, quote: "Sayfası bilinmeyen bir kaynak cümlesi." }}
        pages={PAGES}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Kaynak 1")).toBeTruthy();
    expect(container.querySelector(".source-peek-quote")?.textContent).toBe(
      "Sayfası bilinmeyen bir kaynak cümlesi.",
    );
  });

  it("notes when the quote is not found verbatim on the cited page", () => {
    render(
      <SourcePeekDrawer
        target={{ index: 1, page: 2, quote: "Bambaşka bir cümle, hiç alakasız." }}
        pages={PAGES}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/birebir bulunamadı/)).toBeTruthy();
  });

  it("shows a loading state while the document text is still being fetched", () => {
    render(
      <SourcePeekDrawer
        target={{ index: 1, page: 1, quote: "bir alıntı" }}
        pages={null}
        loading
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Belge metni yükleniyor…")).toBeTruthy();
  });
});
