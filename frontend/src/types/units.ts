export interface Unit {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
}

export interface UnitMember {
  user_id: string;
  username: string;
  email: string;
  is_primary: boolean;
  role_in_unit: string | null;
}
