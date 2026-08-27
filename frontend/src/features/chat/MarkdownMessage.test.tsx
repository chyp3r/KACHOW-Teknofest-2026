import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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

  it("stays a plain label when no click handler is given", () => {
    const { container } = render(<MarkdownMessage text="Bir cümle. [s. 2]" />);

    expect(container.querySelector("button")).toBeNull();
    expect(container.querySelector(".page-citation")?.tagName).toBe("SPAN");
  });

  it("reports the page and the sentence the citation backs when clicked", () => {
    const onCitationClick = vi.fn();
    render(
      <MarkdownMessage
        text="Bu alakasız. Not ortalaması 3.83'tür. [s. 1]"
        onCitationClick={onCitationClick}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Sayfa 1/ }));

    expect(onCitationClick).toHaveBeenCalledTimes(1);
    const target = onCitationClick.mock.calls[0][0];
    expect(target.page).toBe(1);
    // The claim is the sentence the badge sits after, not the whole paragraph.
    expect(target.claim).toContain("Not ortalaması 3.83");
    expect(target.claim).not.toContain("Bu alakasız");
  });

  it("gives each citation in a paragraph its own page number", () => {
    const onCitationClick = vi.fn();
    render(
      <MarkdownMessage text="İlk [s. 2] ikinci [s. 5]" onCitationClick={onCitationClick} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Sayfa 5/ }));

    expect(onCitationClick.mock.calls[0][0].page).toBe(5);
  });

  it("does not invent badges where there is no citation", () => {
    const { container } = render(
      <MarkdownMessage text="Madde [5] ve dizi [s] burada atıf değil." />,
    );

    expect(container.querySelector(".page-citation")).toBeNull();
  });
});
