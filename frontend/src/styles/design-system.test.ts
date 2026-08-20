// @ts-expect-error Vitest runs on Node; production sources intentionally omit Node ambient types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/styles/design-system.css", "utf8");
const integrationCss = readFileSync("src/styles/integration.css", "utf8");
const referenceCss = readFileSync("src/styles/reference-ui.css", "utf8");
const messagingCss = readFileSync("src/styles/messaging.css", "utf8");

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

  it("keeps desktop document metadata and action columns fixed", () => {
    expect(integrationCss).toContain(
      "grid-template-columns: var(--icon-container-md) minmax(16rem, 1fr) 31rem",
    );
    expect(integrationCss).toContain(
      "grid-template-columns: 9rem 7rem 9.5rem var(--touch-target)",
    );
    expect(integrationCss).toContain(
      "grid-template-columns: minmax(0, 1fr) 8rem var(--touch-target)",
    );
  });

  it("keeps the user access header padded and flush with its table", () => {
    expect(referenceCss).toMatch(/\.users-panel > \.section-header \{[^}]*margin: 0;[^}]*padding: 1rem 1\.25rem;/);
  });

  it("neutralizes persisted compact navigation at the mobile breakpoint", () => {
    const mobileLayer = referenceCss.slice(referenceCss.indexOf("Canonical narrow-viewport layer"));

    expect(mobileLayer).toMatch(
      /\.app-shell\.sidebar-compact,[\s\S]*?grid-template-columns: minmax\(0, 1fr\);/,
    );
    expect(mobileLayer).toMatch(
      /\.sidebar-compact \.app-sidebar[\s\S]*?width: min\(20rem, 88vw\);/,
    );
    expect(mobileLayer).toMatch(
      /\.sidebar-compact \.brand-lockup-compact \.brand-lockup-copy\s*{[^}]*display: grid;/,
    );
  });

  it("reserves mobile menu space and collapses narrow dashboard grids", () => {
    const mobileLayer = referenceCss.slice(referenceCss.indexOf("Canonical narrow-viewport layer"));

    expect(mobileLayer).toMatch(
      /\.page,[\s\S]*?padding: calc\(var\(--touch-target\) \+ var\(--space-5\) \+ env\(safe-area-inset-top\)\)/,
    );
    expect(mobileLayer).toMatch(
      /\.appearance-options,[\s\S]*?\.admin-overview-grid\s*{[^}]*grid-template-columns: 1fr;/,
    );
    expect(referenceCss).toMatch(
      /\.home-page\s*{[^}]*grid-auto-rows: max-content;[^}]*overflow-y: auto;/,
    );
    expect(referenceCss).toMatch(
      /@media \(max-width: 47\.5rem\)[\s\S]*?\.home-hero\s*{[^}]*min-height: auto;/,
    );
    expect(referenceCss).toMatch(
      /@media \(max-width: 40rem\)[\s\S]*?\.home-hero\s*{[^}]*grid-template-columns: 1fr;/,
    );
  });

  it("keeps mobile messaging navigable without overflowing artifact cards", () => {
    const mobileLayer = messagingCss.slice(messagingCss.indexOf("@media (max-width: 47.5rem)"));

    expect(mobileLayer).toMatch(
      /\.messages-layout\.has-active-conversation \.conversation-list-panel\s*{[^}]*display: none;/,
    );
    expect(mobileLayer).toMatch(
      /\.messages-layout\.has-active-conversation \.message-thread-panel\s*{[^}]*display: flex;/,
    );
    expect(mobileLayer).toMatch(/\.artifact-card\s*{[^}]*min-width: 0;/);
  });
});
