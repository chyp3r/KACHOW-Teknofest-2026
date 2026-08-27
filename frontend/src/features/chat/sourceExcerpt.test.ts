import { describe, expect, it } from "vitest";
import { findSourceExcerpt } from "./sourceExcerpt";

const PAGE = [
  "GÖKDENİZ KURUCA",
  "Hacettepe Üniversitesi Bilgisayar Mühendisliği",
  "Genel not ortalaması 3.83, sınıf sıralaması 144 öğrenci içinde 2.",
  "ACM Hacettepe kulübünde TEKNOFEST Teams Lead olarak görev aldı.",
].join("\n");

describe("findSourceExcerpt", () => {
  it("splits the page around the sentence the claim came from", () => {
    const excerpt = findSourceExcerpt(
      PAGE,
      "Gökdeniz Kuruca'nın not ortalaması 3.83'tür ve sınıfında 144 öğrenci arasında 2. sıradadır.",
    );

    expect(excerpt).not.toBeNull();
    expect(excerpt!.match).toContain("3.83");
    expect(excerpt!.match).toContain("144");
    // The rest of the page is preserved verbatim around it.
    expect(excerpt!.before).toContain("GÖKDENİZ KURUCA");
    expect(excerpt!.after).toContain("TEKNOFEST Teams Lead");
  });

  it("reassembles into exactly the original page text", () => {
    const excerpt = findSourceExcerpt(PAGE, "not ortalaması 3.83 sınıf sıralaması");

    expect(excerpt!.before + excerpt!.match + excerpt!.after).toBe(PAGE);
  });

  it("matches across casing and punctuation differences", () => {
    const excerpt = findSourceExcerpt(PAGE, "acm hacettepe kulubu teknofest teams lead");

    expect(excerpt!.match).toContain("TEKNOFEST Teams Lead");
  });

  it("picks the precise line over a longer one sharing a single word", () => {
    const page = [
      "Bu belge Hacettepe Üniversitesi tarafından pek çok farklı amaçla düzenlenmiş uzun bir paragraftır.",
      "Not ortalaması 3.83.",
    ].join("\n");

    const excerpt = findSourceExcerpt(page, "not ortalaması 3.83");

    expect(excerpt!.match).toBe("Not ortalaması 3.83.");
  });

  it("returns null when nothing on the page is a plausible source", () => {
    expect(findSourceExcerpt(PAGE, "ACM ICPC yarışmasında altın madalya kazandı")).toBeNull();
  });

  it("returns null for an empty page or a claim with no significant tokens", () => {
    expect(findSourceExcerpt("", "not ortalaması")).toBeNull();
    expect(findSourceExcerpt(PAGE, "ve bu bir")).toBeNull();
  });

  it("handles Turkish dotted/dotless i when folding", () => {
    const excerpt = findSourceExcerpt("SINIF SIRALAMASI İKİNCİ", "sınıf sıralaması ikinci");

    expect(excerpt).not.toBeNull();
    expect(excerpt!.match).toBe("SINIF SIRALAMASI İKİNCİ");
  });
});
