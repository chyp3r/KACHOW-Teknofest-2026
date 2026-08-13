// @ts-expect-error Vitest runs on Node; production sources intentionally omit Node ambient types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/styles/design-system.css", "utf8");

describe("design-system tokens", () => {
  it.each([
    ["--space-1", "0.25rem"],
    ["--space-16", "4rem"],
    ["--control-md", "2.5rem"],
    ["--touch-target", "2.75rem"],
    ["--icon-md", "1.25rem"],
    ["--radius-lg", "0.75rem"],
  ])("defines %s centrally", (token, value) => {
    expect(css).toContain(`${token}: ${value}`);
  });

  it("uses the shared two-pixel focus ring", () => {
    expect(css).toMatch(/focus-visible[\s\S]*outline: 2px solid var\(--focus-ring\);[\s\S]*outline-offset: 2px;/);
  });

  it("keeps mobile, tablet, and desktop page gutters token-based", () => {
    expect(css).toContain("--page-gutter: var(--space-8)");
    expect(css).toContain("--page-gutter: var(--space-6)");
    expect(css).toContain("--page-gutter: var(--space-4)");
  });
});
