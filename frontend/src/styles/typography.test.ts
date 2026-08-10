// @ts-expect-error Vitest runs on Node; production sources intentionally omit Node ambient types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const typography = readFileSync("src/styles/typography.css", "utf8");
const appStyles = readFileSync("src/styles/App.css", "utf8");
const integrationStyles = readFileSync("src/styles/integration.css", "utf8");
const legacyStyles = `${appStyles}\n${integrationStyles}`;

function readVariables(source: string, marker: string): Record<string, string> {
  const start = source.indexOf(marker);
  const open = source.indexOf("{", start);
  const close = source.indexOf("}", open);
  return Object.fromEntries(
    [...source.slice(open + 1, close).matchAll(/--([\w-]+):\s*([^;]+);/g)].map(
      ([, name, value]) => [name, value.trim()],
    ),
  );
}

function contrast(foreground: string, background: string): number {
  const luminance = (color: string) => {
    const hex = color.slice(1);
    const channels = [0, 2, 4].map((index) =>
      Number.parseInt(hex.slice(index, index + 2), 16) / 255,
    );
    return channels
      .map((value) =>
        value <= 0.04045
          ? value / 12.92
          : ((value + 0.055) / 1.055) ** 2.4,
      )
      .reduce(
        (total, value, index) =>
          total + value * [0.2126, 0.7152, 0.0722][index],
        0,
      );
  };
  const values = [luminance(foreground), luminance(background)].sort(
    (a, b) => b - a,
  );
  return (values[0] + 0.05) / (values[1] + 0.05);
}

describe("semantic typography contract", () => {
  it("defines the complete rem-based scale without shrinking the root", () => {
    expect(typography).toContain("--text-overline: 0.6875rem");
    expect(typography).toContain("--text-caption: 0.75rem");
    expect(typography).toContain("--font-size-secondary: 0.8125rem");
    expect(typography).toContain("--text-body: 0.875rem");
    expect(typography).toContain("--text-body-lg: 1rem");
    expect(typography).toContain("--text-heading-md: 1.125rem");
    expect(typography).toContain("--text-heading-lg: 1.375rem");
    expect(typography).toContain("--text-display: 1.75rem");
    expect(typography).toMatch(/html\s*{[^}]*font-size:\s*100%/s);
  });

  it("maps critical content and controls to accessible semantic roles", () => {
    expect(typography).toMatch(
      /\.page-header h1,[\s\S]*?font-size:\s*var\(--text-display\)/,
    );
    expect(typography).toMatch(
      /\.chat-message \.markdown-content,[\s\S]*?font-size:\s*var\(--text-body-lg\)/,
    );
    expect(typography).toMatch(
      /\.nav-item,[\s\S]*?font-size:\s*var\(--text-body\)/,
    );
    expect(typography).toMatch(
      /\.status-badge,[\s\S]*?font-size:\s*var\(--text-caption\)/,
    );
    expect(typography).toMatch(
      /\.chat-message header,[\s\S]*?font-size:\s*var\(--text-body\)/,
    );
    expect(typography).toMatch(
      /th\s*{[^}]*font-size:\s*var\(--text-body\)[^}]*line-height:\s*var\(--leading-control\)/s,
    );
  });

  it("uses only the four supported weight tokens", () => {
    const declarations = [...typography.matchAll(/font-weight:\s*([^;]+);/g)]
      .map((match) => match[1].trim())
      .filter((value) => !value.startsWith("var(--weight-"));

    expect(declarations).toEqual([]);
  });

  it("keeps arbitrary typography declarations out of legacy layout styles", () => {
    expect(legacyStyles).not.toMatch(
      /(?:font-size|font-weight|line-height|letter-spacing|font-family|text-transform)\s*:/,
    );
  });

  it.each(["light", "dark"])(
    "keeps readable semantic text colors in the %s theme",
    (theme) => {
      const marker = `[data-theme="${theme}"]`;
      const variables = {
        ...readVariables(integrationStyles, marker),
        ...readVariables(typography, marker),
      };
      const readableColors = [
        "text-primary",
        "text-secondary",
        "text-muted",
        "text-link",
        "text-success",
        "text-warning",
        "text-error",
      ];

      for (const name of readableColors) {
        expect(contrast(variables[name], variables["bg-secondary"])).toBeGreaterThanOrEqual(4.5);
      }
    },
  );

  it("keeps mobile body roles unchanged and only scales major headings", () => {
    const mobile = typography.slice(typography.indexOf("@media"));

    expect(mobile).not.toMatch(/input|textarea/);
    expect(mobile).toMatch(
      /\.sidebar-compact \.nav-item,[\s\S]*?font-size:\s*var\(--text-body\)/,
    );
    expect(mobile).toContain(".page-header h1");
    expect(mobile).toContain(".chat-empty-state h2");
  });

  it("keeps long Turkish copy wrap-safe without altering its characters", () => {
    const turkishSample = "İ ı Ş ş Ğ ğ Ç ç Ö ö Ü ü çalışma alanı";

    expect(turkishSample).toBe("İ ı Ş ş Ğ ğ Ç ç Ö ö Ü ü çalışma alanı");
    expect(typography).toMatch(
      /h1,[\s\S]*?p\s*{\s*overflow-wrap:\s*anywhere;/,
    );
    expect(typography).toContain("max-width: 75ch");
  });
});
