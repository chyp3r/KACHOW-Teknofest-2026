import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarkdownMessage } from "./MarkdownMessage";

const CITED = [
  "Not ortalaması 3.83'tür [1].",
  "",
  "KAYNAKLAR:",
  "[1] (s. 1) Genel not ortalaması 3.83.",
].join("\n");

describe("MarkdownMessage", () => {
  it("renders a numbered citation as a badge and hides the sources block", () => {
    const { container } = render(<MarkdownMessage text={CITED} />);

    expect(container.querySelector(".page-citation")?.textContent).toBe("1");
    expect(container.textContent).not.toContain("KAYNAKLAR");
    expect(container.textContent).not.toContain("Genel not ortalaması");
    expect(container.textContent).toContain("Not ortalaması 3.83'tür");
  });

  it("hands over the quoted source sentence when a badge is clicked", () => {
    const onCitationClick = vi.fn();
    render(<MarkdownMessage text={CITED} onCitationClick={onCitationClick} />);

    fireEvent.click(screen.getByRole("button", { name: /Kaynak 1/ }));

    expect(onCitationClick).toHaveBeenCalledWith({
      index: 1,
      page: 1,
      quote: "Genel not ortalaması 3.83.",
    });
  });

  it("numbers several citations independently", () => {
    const { container } = render(
      <MarkdownMessage
        text={"İlk [1] ve ikinci [2].\n\nKAYNAKLAR:\n[1] (s. 1) Bir.\n[2] (s. 4) İki."}
      />,
    );

    expect([...container.querySelectorAll(".page-citation")].map((n) => n.textContent)).toEqual([
      "1",
      "2",
    ]);
  });

  it("leaves a bracketed number alone when the sources block does not define it", () => {
    const { container } = render(
      <MarkdownMessage text={"Madde [5] uyarınca işlem yapılır."} />,
    );

    expect(container.querySelector(".page-citation")).toBeNull();
    expect(container.textContent).toContain("Madde [5]");
  });

  it("still renders the legacy page anchor as a readable badge", () => {
    const { container } = render(<MarkdownMessage text="Eski biçim. [s. 3]" />);

    expect(container.querySelector(".page-citation")?.textContent).toBe("Sayfa 3");
    expect(container.textContent).not.toContain("[s. 3]");
  });

  it("does not read a legacy page anchor as the number marker too", () => {
    const { container } = render(
      <MarkdownMessage text={"Eski [s. 3] biçim.\n\nKAYNAKLAR:\n[3] (s. 9) Alakasız."} />,
    );

    // Scoped to the prose: citation 3 is genuinely unreferenced there (the
    // legacy anchor is `[s. 3]`, not `[3]`), so it legitimately shows up in
    // the unreferenced-sources footer below.
    const inProse = [...container.querySelectorAll("p:not(.citation-footer) .page-citation")].map(
      (n) => n.textContent,
    );
    expect(inProse).toEqual(["Sayfa 3"]);
  });

  it("stays a plain label when no click handler is given", () => {
    const { container } = render(<MarkdownMessage text={CITED} />);

    expect(container.querySelector("button")).toBeNull();
    expect(container.querySelector(".page-citation")?.tagName).toBe("SPAN");
  });

  it("catches a citation nested inside inline formatting", () => {
    const { container } = render(
      <MarkdownMessage text={"**Sonuç [1]** böyle.\n\nKAYNAKLAR:\n[1] (s. 4) Kaynak."} />,
    );

    expect(container.querySelector("strong .page-citation")?.textContent).toBe("1");
  });

  it("badges citations inside list items too", () => {
    const { container } = render(
      <MarkdownMessage text={"- ilk madde [1]\n\nKAYNAKLAR:\n[1] (s. 7) Kaynak."} />,
    );

    expect(container.querySelector("li .page-citation")?.textContent).toBe("1");
  });

  it("leaves ordinary markdown alone", () => {
    render(<MarkdownMessage text="**kalın** ve düz metin" />);

    expect(screen.getByText("kalın").tagName).toBe("STRONG");
  });
});

describe("MarkdownMessage citation fallback", () => {
  // Observed on a real reply: the model wrote the sources block but never
  // placed [1] in its prose, so there was nothing to badge and the citation
  // vanished entirely.
  const NO_MARKERS = [
    "Ortalama notu 3.83 olarak belirtilmiştir.",
    "",
    "KAYNAKLAR:",
    "[1] (s. 1) GPA: 3.83 - Ranked 2nd out of 144 students",
  ].join("\n");

  it("offers a source the model listed but never referenced inline", () => {
    const { container } = render(<MarkdownMessage text={NO_MARKERS} />);

    const footer = container.querySelector(".citation-footer");
    expect(footer).not.toBeNull();
    expect(footer?.querySelector(".page-citation")?.textContent).toBe("1");
    // The block itself still never reaches the reader as raw text.
    expect(container.textContent).not.toContain("KAYNAKLAR:");
  });

  it("keeps the unreferenced source clickable", () => {
    const onCitationClick = vi.fn();
    render(<MarkdownMessage text={NO_MARKERS} onCitationClick={onCitationClick} />);

    fireEvent.click(screen.getByRole("button", { name: /Kaynak 1/ }));

    expect(onCitationClick).toHaveBeenCalledWith(
      expect.objectContaining({ index: 1, page: 1 }),
    );
  });

  it("does not repeat a source that is already referenced inline", () => {
    const { container } = render(
      <MarkdownMessage text={"Cevap [1].\n\nKAYNAKLAR:\n[1] (s. 1) Kaynak."} />,
    );

    expect(container.querySelector(".citation-footer")).toBeNull();
  });

  it("lists only the sources that were missed", () => {
    const { container } = render(
      <MarkdownMessage
        text={"Yalnızca ilki [1].\n\nKAYNAKLAR:\n[1] (s. 1) Bir.\n[2] (s. 2) İki."}
      />,
    );

    const footerBadges = [
      ...(container.querySelector(".citation-footer")?.querySelectorAll(".page-citation") ?? []),
    ].map((node) => node.textContent);
    expect(footerBadges).toEqual(["2"]);
  });

  it("shows no footer for a reply with no citations at all", () => {
    const { container } = render(<MarkdownMessage text="Merhaba." />);

    expect(container.querySelector(".citation-footer")).toBeNull();
  });
});
