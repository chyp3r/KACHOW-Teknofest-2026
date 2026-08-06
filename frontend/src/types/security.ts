export type SensitivityLevel =
  | "unmarked"
  | "tasnif_disi"
  | "hizmete_ozel"
  | "ozel"
  | "gizli"
  | "cok_gizli";

export const SENSITIVITY_LABELS: Record<SensitivityLevel, string> = {
  unmarked: "İşaretlenmemiş",
  tasnif_disi: "Tasnif dışı",
  hizmete_ozel: "Hizmete özel",
  ozel: "Özel",
  gizli: "Gizli",
  cok_gizli: "Çok gizli",
};
