import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownMessage } from "./MarkdownMessage";

describe("MarkdownMessage", () => {
  it("renders a page citation as a labelled badge, not raw [s. N]", () => {
    const { container } = render(
      <MarkdownMessage text="Not ortalaması 3.83'tür. [s. 1]" />,
    );

    const badge = container.querySelector(".page-citation");
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toBe("Sayfa 1");
    expect(container.textContent).not.toContain("[s. 1]");
    // The surrounding sentence survives untouched.
    expect(container.textContent).toContain("Not ortalaması 3.83'tür.");
  });

  it("badges every citation in a paragraph, keeping the text between them", () => {
    const { container } = render(
      <MarkdownMessage text="Önce şu [s. 2] sonra bu [s. 5] geliyor." />,
    );

    const badges = [...container.querySelectorAll(".page-citation")].map(
      (node) => node.textContent,
    );
    expect(badges).toEqual(["Sayfa 2", "Sayfa 5"]);
    expect(container.textContent).toContain("sonra bu");
  });

  it("catches a citation nested inside inline formatting", () => {
    const { container } = render(<MarkdownMessage text="**Sonuç [s. 4]** böyle." />);

    expect(container.querySelector(".page-citation")?.textContent).toBe("Sayfa 4");
  });

  it("badges citations inside list items too", () => {
    const { container } = render(<MarkdownMessage text={"- ilk madde [s. 7]\n"} />);

    expect(container.querySelector("li .page-citation")?.textContent).toBe("Sayfa 7");
  });

  it("leaves ordinary markdown alone", () => {
    render(<MarkdownMessage text="**kalın** ve düz metin" />);

    expect(screen.getByText("kalın").tagName).toBe("STRONG");
  });

  it("does not invent badges where there is no citation", () => {
    const { container } = render(
      <MarkdownMessage text="Madde [5] ve dizi [s] burada atıf değil." />,
    );

    expect(container.querySelector(".page-citation")).toBeNull();
  });
});
