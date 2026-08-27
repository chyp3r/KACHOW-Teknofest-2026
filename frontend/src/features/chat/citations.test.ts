import { describe, expect, it } from "vitest";
import { parseReplyCitations } from "./citations";

const REPLY = [
  "Not ortalaması 3.83'tür [1] ve sınıfında 2. sıradadır [2].",
  "",
  "KAYNAKLAR:",
  "[1] (s. 1) Genel not ortalaması 3.83.",
  "[2] (s. 1) Sınıf sıralaması 144 öğrenci içinde 2.",
].join("\n");

describe("parseReplyCitations", () => {
  it("keeps the prose and hides the sources block", () => {
    const { body } = parseReplyCitations(REPLY);

    expect(body).toBe("Not ortalaması 3.83'tür [1] ve sınıfında 2. sıradadır [2].");
    expect(body).not.toContain("KAYNAKLAR");
  });

  it("parses each citation's number, page and quote", () => {
    const { citations } = parseReplyCitations(REPLY);

    expect(citations.size).toBe(2);
    expect(citations.get(1)).toEqual({
      index: 1,
      page: 1,
      quote: "Genel not ortalaması 3.83.",
    });
    expect(citations.get(2)?.quote).toBe("Sınıf sıralaması 144 öğrenci içinde 2.");
  });

  it("leaves a reply with no sources block untouched", () => {
    const { body, citations } = parseReplyCitations("Merhaba, nasıl yardımcı olabilirim?");

    expect(body).toBe("Merhaba, nasıl yardımcı olabilirim?");
    expect(citations.size).toBe(0);
  });

  it("tolerates the decorations a model adds to the header", () => {
    for (const header of ["## Kaynaklar", "**KAYNAKLAR**", "KAYNAKLAR:", "### KAYNAKLAR :"]) {
      const { body, citations } = parseReplyCitations(
        `Cevap [1].\n\n${header}\n[1] (s. 2) Kaynak cümlesi.`,
      );
      expect(body).toBe("Cevap [1].");
      expect(citations.get(1)?.quote).toBe("Kaynak cümlesi.");
    }
  });

  it("accepts an entry without a page", () => {
    const { citations } = parseReplyCitations("Cevap [1].\n\nKAYNAKLAR:\n[1] Kaynak cümlesi.");

    expect(citations.get(1)).toEqual({ index: 1, page: undefined, quote: "Kaynak cümlesi." });
  });

  it("accepts list-marker and separator variations", () => {
    const { citations } = parseReplyCitations(
      "Cevap [1] ve [2].\n\nKAYNAKLAR:\n- [1] (s. 3) - İlk kaynak.\n* [2] s. 4 : İkinci kaynak.",
    );

    expect(citations.get(1)?.quote).toBe("İlk kaynak.");
    expect(citations.get(2)).toEqual({ index: 2, page: 4, quote: "İkinci kaynak." });
  });

  it("strips surrounding quote marks from the source sentence", () => {
    const { citations } = parseReplyCitations(
      'Cevap [1].\n\nKAYNAKLAR:\n[1] (s. 1) "Alıntılanan cümle."',
    );

    expect(citations.get(1)?.quote).toBe("Alıntılanan cümle.");
  });

  it("hides a half-streamed block instead of flashing it up", () => {
    const { body, citations } = parseReplyCitations("Cevap [1].\n\nKAYNAKLAR:\n[1] (s. 1");

    expect(body).toBe("Cevap [1].");
    expect(citations.size).toBe(0);
  });

  it("ignores a repeated number rather than letting it overwrite the first", () => {
    const { citations } = parseReplyCitations(
      "Cevap [1].\n\nKAYNAKLAR:\n[1] (s. 1) İlk tanım.\n[1] (s. 9) Tekrar.",
    );

    expect(citations.get(1)?.quote).toBe("İlk tanım.");
  });
});
