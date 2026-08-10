import type { components } from "../api/generated";

export type UserRole = components["schemas"]["UserRole"];
export type User = components["schemas"]["UserResponse"];
export type TokenPair = components["schemas"]["TokenResponse"];

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Yönetici",
  manager: "Yönetici yardımcısı",
  employee: "Çalışan",
};
