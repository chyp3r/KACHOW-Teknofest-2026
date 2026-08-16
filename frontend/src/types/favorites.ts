import type { UserRole } from "./users";

export interface Favorite {
  id: string;
  favorite_user_id: string;
  username: string;
  email: string;
  note: string | null;
  created_at: string;
}

export interface UserSearchResult {
  id: string;
  username: string;
  email: string;
  role: UserRole;
  unit_name: string | null;
  is_favorite: boolean;
}
