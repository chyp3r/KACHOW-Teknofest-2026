import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarkdownMessage } from "./MarkdownMessage";

/** Badges in the answer itself, excluding the sources list at the end. */
function proseBadges(container: HTMLElement): (string | null)[] {
  return [...container.querySelectorAll(".page-citation")]
    .filter((node) => !node.closest(".citation-list"))
    .map((node) => node.textContent);
}

const CITED = [
  "Not ortalaması 3.83'tür [1].",
  "",
  "KAYNAKLAR:",
  "[1] (s. 1) Genel not ortalaması 3.83.",
].join("\n");

describe("MarkdownMessage", () => {
  it("renders a numbered citation as a badge and hides the sources block", () => {
    const { container } = render(<MarkdownMessage text={CITED} />);

    expect(proseBadges(container)).toEqual(["1"]);
    expect(container.textContent).not.toContain("KAYNAKLAR:");
    expect(container.textContent).toContain("Not ortalaması 3.83'tür");
    // The quote belongs to the sources list, never to the prose.
    expect(container.querySelector("p")?.textContent).not.toContain("Genel not ortalaması");
  });

  it("hands over the quoted source sentence when a badge is clicked", () => {
    const onCitationClick = vi.fn();
    render(<MarkdownMessage text={CITED} onCitationClick={onCitationClick} />);

    // The inline badge specifically -- the sources-list row for the same
    // citation carries its own, differently-worded label.
    fireEvent.click(screen.getByRole("button", { name: /Kaynak 1\. Bu bilginin/ }));

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

    expect(proseBadges(container)).toEqual(["1", "2"]);
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

    // The legacy anchor is `[s. 3]`, not `[3]`, so citation 3 is never read
    // as a marker in the prose -- it only appears in the sources list.
    expect(proseBadges(container)).toEqual(["Sayfa 3"]);
  });

  it("stays a plain label when no click handler is given", () => {
    const { container } = render(<MarkdownMessage text={CITED} />);

    expect(container.querySelector("button")).toBeNull();
    expect(container.querySelector("p .page-citation")?.tagName).toBe("SPAN");
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

describe("MarkdownMessage sources list", () => {
  const TWO = [
    "Staj yapmıştır [1]. Mezuniyeti 2027'dir [2].",
    "",
    "KAYNAKLAR:",
    "[1] (s. 1) ASELSAN, Turkcell, OBSS Technology",
    "[2] (s. 2) June 2027 (Expected)",
  ].join("\n");

  it("lists every source at the end, not only the unreferenced ones", () => {
    const { container } = render(<MarkdownMessage text={TWO} />);

    const rows = [...container.querySelectorAll(".citation-list li")];
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("ASELSAN");
    expect(rows[1].textContent).toContain("June 2027");
  });

  it("shows each source's number and page alongside its quote", () => {
    const { container } = render(<MarkdownMessage text={TWO} />);

    const first = container.querySelector(".citation-list li");
    expect(first?.querySelector(".page-citation")?.textContent).toBe("1");
    expect(first?.querySelector(".citation-list-page")?.textContent).toBe("s. 1");
    expect(first?.querySelector(".citation-list-quote")?.textContent).toBe(
      "ASELSAN, Turkcell, OBSS Technology",
    );
  });

  it("orders the list by citation number even when the block does not", () => {
    const { container } = render(
      <MarkdownMessage text={"A [2] B [1].\n\nKAYNAKLAR:\n[2] (s. 9) İkinci.\n[1] (s. 1) Birinci."} />,
    );

    const quotes = [...container.querySelectorAll(".citation-list-quote")].map(
      (n) => n.textContent,
    );
    expect(quotes).toEqual(["Birinci.", "İkinci."]);
  });

  it("opens the source when a row is clicked", () => {
    const onCitationClick = vi.fn();
    render(<MarkdownMessage text={TWO} onCitationClick={onCitationClick} />);

    fireEvent.click(screen.getByRole("button", { name: /Kaynak 2, s\. 2/ }));

    expect(onCitationClick).toHaveBeenCalledWith({
      index: 2,
      page: 2,
      quote: "June 2027 (Expected)",
    });
  });

  it("still lists a source the model never referenced inline", () => {
    const { container } = render(
      <MarkdownMessage
        text={"Ortalama 3.83.\n\nKAYNAKLAR:\n[1] (s. 1) GPA: 3.83"} />,
    );

    expect(container.querySelector(".citation-list-quote")?.textContent).toBe("GPA: 3.83");
    expect(container.textContent).not.toContain("KAYNAKLAR:");
  });

  it("renders no list for a reply with no citations", () => {
    const { container } = render(<MarkdownMessage text="Merhaba." />);

    expect(container.querySelector(".citation-list")).toBeNull();
  });
});
