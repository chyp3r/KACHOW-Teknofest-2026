import { describe, expect, it } from "vitest";
import { formatGuardrailReason, guardrailDecisionLabel } from "./guardrailLabels";

describe("guardrailDecisionLabel", () => {
  it("maps the English decision codes to Turkish", () => {
    expect(guardrailDecisionLabel("redacted")).toBe("Maskelendi");
    expect(guardrailDecisionLabel("blocked")).toBe("Engellendi");
    expect(guardrailDecisionLabel("flagged")).toBe("İşaretlendi");
    expect(guardrailDecisionLabel("needs_review")).toBe("İnceleme gerekli");
  });

  it("falls back to a readable form for an unknown code", () => {
    expect(guardrailDecisionLabel("some_new_code")).toBe("some new code");
  });
});

describe("formatGuardrailReason", () => {
  it("uppercases the PII acronym and capitalizes the first letter", () => {
    expect(formatGuardrailReason("1 pii bulgusu maskelendi (EMAIL)")).toBe(
      "1 PII bulgusu maskelendi (EMAIL)",
    );
    expect(formatGuardrailReason("doğrulanamayan ifade kaldırıldı")).toBe(
      "Doğrulanamayan ifade kaldırıldı",
    );
  });
});
