import { describe, expect, it } from "vitest";
import { diffWords, isTargetedDiff } from "./textDiff";

describe("diffWords", () => {
  it("marks nothing changed for identical text", () => {
    const segments = diffWords("Merhaba dünya", "Merhaba dünya");
    expect(segments.every((segment) => !segment.changed)).toBe(true);
    expect(segments.map((segment) => segment.text).join("")).toBe("Merhaba dünya");
  });

  it("highlights only the redacted span, not the whole message", () => {
    const previous = "Telefon numaram 0555 111 22 33, lütfen arayın.";
    const next = "Telefon numaram [GİZLENDİ], lütfen arayın.";
    const segments = diffWords(previous, next);

    expect(segments.map((segment) => segment.text).join("")).toBe(next);
    expect(segments.some((segment) => segment.changed && segment.text.includes("[GİZLENDİ]"))).toBe(
      true,
    );
    expect(segments.find((segment) => segment.text.includes("lütfen"))?.changed).toBe(false);
  });

  it("treats an empty previous text as nothing to diff against", () => {
    expect(diffWords("", "Yeni metin")).toEqual([{ text: "Yeni metin", changed: false }]);
  });
});

describe("isTargetedDiff", () => {
  it("accepts a small localized change", () => {
    const segments = diffWords("Bir iki üç dört beş", "Bir iki ÜÇ dört beş");
    expect(isTargetedDiff(segments)).toBe(true);
  });

  it("rejects a near-total rewrite", () => {
    const segments = diffWords("Bir iki üç", "Tamamen farklı bambaşka bir cümle oldu");
    expect(isTargetedDiff(segments)).toBe(false);
  });
});
