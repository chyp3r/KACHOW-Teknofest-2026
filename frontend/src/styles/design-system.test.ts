// @ts-expect-error Vitest runs on Node; production sources intentionally omit Node ambient types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/styles/design-system.css", "utf8");
const appCss = readFileSync("src/styles/App.css", "utf8");
const integrationCss = readFileSync("src/styles/integration.css", "utf8");
const referenceCss = readFileSync("src/styles/reference-ui.css", "utf8");
const messagingCss = readFileSync("src/styles/messaging.css", "utf8");

describe("design-system tokens", () => {
  it("keeps live chat timers inline without shifting at double digits", () => {
    expect(appCss).toMatch(
      /\.thinking-bubble-header\s*{[^}]*justify-content: flex-start;/,
    );
    expect(appCss).toMatch(
      /\.thinking-bubble-elapsed,[\s\S]*?\.thinking-bubble-step-time\s*{[^}]*flex: 0 0 5ch;[^}]*white-space: nowrap;[^}]*font-variant-numeric: tabular-nums;/,
    );
    expect(appCss).not.toMatch(
      /\.thinking-bubble-step-time\s*{[^}]*margin-left: auto;/,
    );
  });

  it("keeps drawers out of page flow with stable padded person results", () => {
    expect(css).toContain("position: fixed");
    expect(css).toContain("height: 100dvh");
    expect(css).toContain(".overlay-backdrop");
    expect(messagingCss).toContain(".people-drawer-body");
    expect(messagingCss).toContain("scrollbar-gutter: stable");
  });

  it("keeps the document picker above its blur backdrop", () => {
    expect(integrationCss).toMatch(
      /\.document-picker-layer \.document-picker-backdrop\s*{[^}]*z-index: 0;/,
    );
    expect(integrationCss).toMatch(
      /\.document-picker-layer \.document-picker\s*{[\s\S]*?z-index: 1;/,
    );
  });

  it("preserves the dashboard title hierarchy and status-safe document master rows", () => {
    expect(referenceCss).toContain("line-height: 1.05");
    expect(referenceCss).toContain(".home-activity-panel > header > .select { width: 10rem; flex: 0 0 10rem; }");
    expect(referenceCss).toMatch(/\.draft-master li > button \{[\s\S]*?min-height: 7rem;[\s\S]*?padding: var\(--space-4\);/);
    expect(referenceCss).toMatch(/\.document-master-list \.document-list-item \{[\s\S]*?height: auto;[\s\S]*?min-height: 8rem;/);
    expect(referenceCss).toMatch(/\.document-master-list \.document-list-item \{[\s\S]*?align-items: start;[\s\S]*?gap: 0\.75rem;[\s\S]*?padding: var\(--space-4\) var\(--space-2\) var\(--space-5\) var\(--space-4\);/);
  });

  it("keeps document and draft master lists padded, scrollable, and inside the viewport", () => {
    expect(referenceCss).toMatch(
      /\.documents-page,[\s\S]*?\.drafts-page\s*\{[^}]*height: 100%;[^}]*min-height: 0;[^}]*padding-inline: var\(--page-gutter\);[^}]*overflow: hidden;/,
    );
    expect(referenceCss).toMatch(
      /\.document-master-column \.document-result-count\s*\{[^}]*padding: var\(--space-3\) var\(--space-4\);/,
    );
    expect(referenceCss).toMatch(
      /\.draft-master > header\s*\{[^}]*padding: var\(--space-3\) var\(--space-4\);/,
    );
    expect(referenceCss).toMatch(
      /\.draft-master\s*\{[^}]*display: flex;[^}]*min-height: 0;[^}]*flex-direction: column;/,
    );
    expect(referenceCss).toMatch(
      /\.draft-master > ul\s*\{[^}]*min-height: 0;[^}]*flex: 1;[^}]*overflow-y: auto;/,
    );
    expect(referenceCss).toMatch(
      /\.document-master-pagination\s*\{[^}]*min-height: calc\(var\(--touch-target\) \+ var\(--space-4\)\);[^}]*flex: 0 0 auto;/,
    );
    expect(referenceCss).toMatch(
      /@media \(max-width: 47\.5rem\)[\s\S]*?\.document-library-layout\s*\{[^}]*width: 100%;[^}]*margin-inline: 0;/,
    );
    expect(referenceCss).toMatch(
      /@media \(max-width: 47\.5rem\)[\s\S]*?\.document-master-list\s*\{[^}]*max-height: none;[^}]*overflow-y: visible;[^}]*scrollbar-gutter: auto;/,
    );
    expect(referenceCss).toMatch(
      /@media \(max-width: 30rem\)[\s\S]*?\.document-master-list \.document-item-metadata\s*\{[^}]*display: grid;[^}]*grid-template-columns: 1fr;[^}]*justify-items: start;/,
    );
  });

  it("lets the legislation graph fill its page without losing mobile page scrolling", () => {
    expect(integrationCss).toMatch(
      /\.graph-page\s*\{[^}]*display: flex;[^}]*height: 100%;[^}]*min-height: 0;[^}]*overflow: hidden;/,
    );
    expect(integrationCss).toMatch(
      /\.graph-page > \.entity-graph-view\s*\{[^}]*display: flex;[^}]*min-height: 0;[^}]*flex: 1;/,
    );
    expect(integrationCss).toMatch(
      /\.graph-page \.interactive-graph\s*\{[^}]*grid-template-rows: auto minmax\(0, 1fr\) auto;/,
    );
    expect(integrationCss).toMatch(
      /@media \(max-width: 47\.5rem\)[\s\S]*?\.graph-page\s*\{[^}]*overflow-y: auto;/,
    );
  });

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

  it("defines the shared loading rotation used by spinners and loading icons", () => {
    expect(css).toMatch(/@keyframes spin\s*{[^}]*transform: rotate\(360deg\);/);
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

  it("reserves the full profile avatar width before the account identity", () => {
    expect(referenceCss).toMatch(
      /\.profile-summary-heading\s*\{[^}]*--profile-avatar-size: 4\.25rem;[^}]*grid-template-columns: var\(--profile-avatar-size\) minmax\(0, 1fr\) auto;[^}]*column-gap: var\(--space-5\);/,
    );
    expect(referenceCss).toMatch(
      /\.profile-avatar\s*\{[^}]*width: var\(--profile-avatar-size\);[^}]*height: var\(--profile-avatar-size\);/,
    );
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
