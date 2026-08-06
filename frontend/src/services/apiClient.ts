import type { ApiEnvelope } from "../types/api";

const ACCESS_TOKEN_KEY = "kachow.accessToken";
const REFRESH_TOKEN_KEY = "kachow.refreshToken";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS_TOKEN_KEY);
}

export function storeTokens(accessToken: string, refreshToken: string): void {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  sessionStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearTokens(): void {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return sessionStorage.getItem(REFRESH_TOKEN_KEY);
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, { ...init, headers });
  let envelope: ApiEnvelope<T> | undefined;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    throw new ApiError("Sunucudan geçersiz bir yanıt alındı.", response.status);
  }
  if (!response.ok) {
    throw new ApiError(
      envelope.error?.message ?? envelope.message ?? "İşlem tamamlanamadı.",
      response.status,
    );
  }
  return envelope.data;
}

export function authorizedHeaders(headers?: HeadersInit): Headers {
  const result = new Headers(headers);
  const token = getAccessToken();
  if (token) result.set("Authorization", `Bearer ${token}`);
  return result;
}
