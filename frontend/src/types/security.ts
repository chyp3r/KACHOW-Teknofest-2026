import type { components } from "../api/generated";

export type SensitivityLevel = components["schemas"]["SensitivityLevel"];

export const SENSITIVITY_LABELS: Record<SensitivityLevel, string> = {
  unmarked: "İşaretlenmemiş",
  tasnif_disi: "Tasnif dışı",
  hizmete_ozel: "Hizmete özel",
  ozel: "Özel",
  gizli: "Gizli",
  cok_gizli: "Çok gizli",
};
