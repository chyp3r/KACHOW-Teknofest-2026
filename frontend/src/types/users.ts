import type { components } from "../api/generated";

export type UserRole = components["schemas"]["UserRole"];
export type User = components["schemas"]["UserResponse"];
export type TokenPair = components["schemas"]["TokenResponse"];

export const ROLE_LABELS: Record<UserRole, string> = {
  root: "Sistem yöneticisi",
  admin: "Yönetici",
  manager: "Yönetici yardımcısı",
  employee: "Çalışan",
};

//: Roles a company admin can assign through the UI (invite/role-change
//: dropdowns) -- "root" is a superuser role seeded outside any company's
//: own admin flow, never something to hand out from here.
export const ASSIGNABLE_ROLE_LABELS: Record<Exclude<UserRole, "root">, string> = {
  admin: ROLE_LABELS.admin,
  manager: ROLE_LABELS.manager,
  employee: ROLE_LABELS.employee,
};
