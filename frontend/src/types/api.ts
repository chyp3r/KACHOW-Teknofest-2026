export interface ApiEnvelope<T> {
  success?: boolean;
  data: T;
  error?: { code?: string; message?: string; details?: unknown } | null;
  message?: string;
  detail?: unknown;
  meta?: Record<string, unknown>;
}

export interface ApiValidationError {
  field: string;
  type?: string;
  msg: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };
