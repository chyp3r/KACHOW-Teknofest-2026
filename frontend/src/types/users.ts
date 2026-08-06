import type { SensitivityLevel } from "./security";

export type UserRole = "admin" | "manager" | "employee";

export interface User {
  id: string;
  username: string;
  email: string;
  role: UserRole;
  clearance_level: SensitivityLevel;
  is_active: boolean;
  is_deleted: boolean;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}
