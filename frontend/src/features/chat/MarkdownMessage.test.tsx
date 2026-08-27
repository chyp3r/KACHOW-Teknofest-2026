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

  it("drops a stray page anchor when the reply uses numbered citations", () => {
    const { container } = render(
      <MarkdownMessage text={"Bilgi [s. 3] burada [1].\n\nKAYNAKLAR:\n[1] (s. 3) Kaynak."} />,
    );

    // Mixing a "Sayfa 3" badge into a numbered reply is what looked
    // inconsistent; the page still reaches the reader via the block.
    expect(proseBadges(container)).toEqual(["1"]);
    expect(container.textContent).not.toContain("Sayfa 3");
    expect(container.textContent).not.toContain("[s. 3]");
    // No gap left where the anchor was.
    expect(container.textContent).toContain("Bilgi burada");
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

describe("MarkdownMessage during the typewriter reveal", () => {
  // The sources block is the last thing in the reply, so a partially revealed
  // `text` contains no citations at all -- markers already on screen used to
  // sit as bare "[1]" until the animation finished, then snap into badges.
  const FULL = [
    "Staj yapmıştır [1]. Mezuniyeti 2027'dir [2].",
    "",
    "KAYNAKLAR:",
    "[1] (s. 1) ASELSAN, Turkcell, OBSS Technology",
    "[2] (s. 2) June 2027 (Expected)",
  ].join("\n");

  it("badges a marker that is already visible, before the block is revealed", () => {
    const { container } = render(
      <MarkdownMessage text="Staj yapmıştır [1]." citationSource={FULL} />,
    );

    expect(proseBadges(container)).toEqual(["1"]);
    expect(container.textContent).not.toContain("[1]");
  });

  it("does not trail a citation whose marker has not been reached yet", () => {
    const { container } = render(
      <MarkdownMessage text="Staj yapmıştır [1]." citationSource={FULL} />,
    );

    // [2] is referenced by the finished answer, so it must not flash at the
    // bottom as an unreferenced source mid-animation.
    expect(container.querySelector(".citation-trailing")).toBeNull();
  });

  it("renders only the revealed slice, never the rest of the reply", () => {
    const { container } = render(
      <MarkdownMessage text="Staj yapmıştır [1]." citationSource={FULL} />,
    );

    expect(container.textContent).not.toContain("Mezuniyeti");
    expect(container.textContent).not.toContain("KAYNAKLAR");
  });

  it("behaves exactly as before when no separate source is given", () => {
    const { container } = render(<MarkdownMessage text={FULL} />);

    expect(proseBadges(container)).toEqual(["1", "2"]);
  });
});

describe("MarkdownMessage reveal ordering", () => {
  const FULL = "Cevap metni.\n\nKAYNAKLAR:\n[1] (s. 1) Kaynak cümlesi.";

  it("withholds trailing sources while the text is still revealing", () => {
    const { container } = render(
      <MarkdownMessage text="Cevap" citationSource={FULL} />,
    );

    // Arriving before the answer is exactly the out-of-order flash reported.
    expect(container.querySelector(".citation-trailing")).toBeNull();
  });

  it("shows them once the reveal has caught up", () => {
    const { container } = render(
      <MarkdownMessage text={FULL} citationSource={FULL} />,
    );

    expect(container.querySelector(".citation-trailing")).not.toBeNull();
  });
});
