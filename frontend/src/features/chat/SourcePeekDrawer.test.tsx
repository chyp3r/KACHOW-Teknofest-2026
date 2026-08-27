import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SourcePeekDrawer } from "./SourcePeekDrawer";

const PAGES = [
  "GÖKDENİZ KURUCA\nGenel not ortalaması 3.83, sınıf sıralaması 144 öğrenci içinde 2.",
  "İkinci sayfanın içeriği burada.",
];

describe("SourcePeekDrawer", () => {
  it("renders nothing until a citation is opened", () => {
    const { container } = render(
      <SourcePeekDrawer target={null} pages={PAGES} onClose={vi.fn()} />,
    );

    expect(container.querySelector(".source-peek-drawer")).toBeNull();
  });

  it("shows the cited page with the claim highlighted in its surroundings", () => {
    const { container } = render(
      <SourcePeekDrawer
        target={{ page: 1, claim: "Not ortalaması 3.83 ve sınıf sıralaması 144 öğrenci içinde." }}
        pages={PAGES}
        documentName="cv.pdf"
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Kaynak — Sayfa 1")).toBeTruthy();
    expect(screen.getByText("cv.pdf")).toBeTruthy();

    const mark = container.querySelector("mark");
    expect(mark?.textContent).toContain("3.83");
    // The rest of the page is present around the highlight, not cropped away.
    expect(container.querySelector(".source-peek-page")?.textContent).toContain(
      "GÖKDENİZ KURUCA",
    );
  });

  it("opens the page the citation names, not the first one", () => {
    const { container } = render(
      <SourcePeekDrawer
        target={{ page: 2, claim: "ikinci sayfanın içeriği" }}
        pages={PAGES}
        onClose={vi.fn()}
      />,
    );

    expect(container.querySelector(".source-peek-page")?.textContent).toContain(
      "İkinci sayfanın içeriği",
    );
  });

  it("falls back to the whole page, with a note, when the claim cannot be located", () => {
    const { container } = render(
      <SourcePeekDrawer
        target={{ page: 1, claim: "ACM ICPC altın madalya kazandı" }}
        pages={PAGES}
        onClose={vi.fn()}
      />,
    );

    expect(container.querySelector("mark")).toBeNull();
    expect(screen.getByText(/eşleştirilemedi/)).toBeTruthy();
    expect(container.querySelector(".source-peek-page")?.textContent).toContain(
      "GÖKDENİZ KURUCA",
    );
  });

  it("explains itself when the page text is missing", () => {
    render(
      <SourcePeekDrawer
        target={{ page: 9, claim: "bir iddia" }}
        pages={PAGES}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Sayfa metni bulunamadı")).toBeTruthy();
  });

  it("shows a loading state while the document text is still being fetched", () => {
    render(
      <SourcePeekDrawer
        target={{ page: 1, claim: "bir iddia" }}
        pages={null}
        loading
        onClose={vi.fn()}
      />,
    );

    // The visible line, not the Spinner's own sr-only label.
    expect(screen.getByText("Belge metni yükleniyor…")).toBeTruthy();
  });
});
