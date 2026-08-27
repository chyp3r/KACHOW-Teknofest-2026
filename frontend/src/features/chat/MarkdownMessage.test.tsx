import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarkdownMessage } from "./MarkdownMessage";

/** Badges in the answer itself, excluding any that trail it. */
function proseBadges(container: HTMLElement): (string | null)[] {
  return [...container.querySelectorAll(".page-citation")]
    .filter((node) => !node.closest(".citation-trailing"))
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
    // The quote backs the badge; it is never printed into the answer.
    expect(container.textContent).not.toContain("Genel not ortalaması");
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

describe("MarkdownMessage trailing sources", () => {
  it("renders several citations on one sentence side by side", () => {
    const { container } = render(
      <MarkdownMessage
        text={"Bilgi bilgi bilgi [1][2].\n\nKAYNAKLAR:\n[1] (s. 1) Bir.\n[2] (s. 1) İki."}
      />,
    );

    expect(proseBadges(container)).toEqual(["1", "2"]);
    // Everything is referenced, so nothing trails the answer.
    expect(container.querySelector(".citation-trailing")).toBeNull();
  });

  it("keeps spaced markers on one sentence as separate badges", () => {
    const { container } = render(
      <MarkdownMessage
        text={"Bilgi bilgi [4] [5].\n\nKAYNAKLAR:\n[4] (s. 2) Dört.\n[5] (s. 2) Beş."}
      />,
    );

    expect(proseBadges(container)).toEqual(["4", "5"]);
  });

  it("no longer lists sources under the answer", () => {
    const { container } = render(
      <MarkdownMessage text={"Cevap [1].\n\nKAYNAKLAR:\n[1] (s. 1) Kaynak cümlesi."} />,
    );

    expect(container.querySelector(".citation-list")).toBeNull();
    // The quote itself is not printed under the answer either.
    expect(container.textContent).not.toContain("Kaynak cümlesi.");
  });

  it("trails a source the model defined but never referenced", () => {
    const { container } = render(
      <MarkdownMessage text={"Ortalama 3.83.\n\nKAYNAKLAR:\n[1] (s. 1) GPA: 3.83"} />,
    );

    const trailing = container.querySelector(".citation-trailing");
    expect(trailing?.querySelector(".page-citation")?.textContent).toBe("1");
    expect(container.textContent).not.toContain("KAYNAKLAR:");
  });

  it("trails only the ones that were missed", () => {
    const { container } = render(
      <MarkdownMessage
        text={"Yalnızca ilki [1].\n\nKAYNAKLAR:\n[1] (s. 1) Bir.\n[2] (s. 2) İki."}
      />,
    );

    const trailing = [
      ...(container.querySelector(".citation-trailing")?.querySelectorAll(".page-citation") ?? []),
    ].map((node) => node.textContent);
    expect(trailing).toEqual(["2"]);
  });

  it("keeps a trailing source clickable", () => {
    const onCitationClick = vi.fn();
    render(
      <MarkdownMessage
        text={"Ortalama 3.83.\n\nKAYNAKLAR:\n[1] (s. 1) GPA: 3.83"}
        onCitationClick={onCitationClick}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Kaynak 1/ }));

    expect(onCitationClick).toHaveBeenCalledWith({
      index: 1,
      page: 1,
      quote: "GPA: 3.83",
    });
  });

  it("renders nothing extra for a reply with no citations", () => {
    const { container } = render(<MarkdownMessage text="Merhaba." />);

    expect(container.querySelector(".citation-trailing")).toBeNull();
  });
});
