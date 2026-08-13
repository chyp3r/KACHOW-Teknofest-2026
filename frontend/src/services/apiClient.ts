import type { ApiEnvelope } from "../types/api";
import type { TokenPair } from "../types/users";

const ACCESS_TOKEN_KEY = "kachow.accessToken";
const REFRESH_TOKEN_KEY = "kachow.refreshToken";
export const AUTH_EXPIRED_EVENT = "kachow:auth-expired";
const SESSION_NOTICE_KEY = "kachow.sessionNotice";

interface ApiFetchOptions {
  authenticated?: boolean;
  retryOnUnauthorized?: boolean;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly details?: unknown,
    public readonly code?: string,
    public readonly requestId?: string,
    public readonly retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isPermissionDenied(): boolean {
    return this.status === 403;
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

function notifyExpiredSession(path: string): void {
  // Any 401 anywhere logs the whole app out (see AuthProvider's listener),
  // so when that happens unexpectedly this is the fastest way to see which
  // request actually caused it.
  void path;
  sessionStorage.setItem(
    SESSION_NOTICE_KEY,
    "Oturumunuzun süresi doldu. Lütfen yeniden giriş yapın.",
  );
  clearTokens();
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
}

export function consumeSessionNotice(): string | null {
  const notice = sessionStorage.getItem(SESSION_NOTICE_KEY);
  sessionStorage.removeItem(SESSION_NOTICE_KEY);
  return notice;
}

function responseMessage(envelope: ApiEnvelope<unknown> | undefined): string {
  const message = envelope?.error?.message ?? envelope?.message;
  if (message === "An unexpected internal server error occurred.") {
    return "Sunucuda beklenmeyen bir hata oluştu.";
  }
  if (message) return message;
  if (typeof envelope?.detail === "string") return envelope.detail;
  if (
    envelope?.detail &&
    typeof envelope.detail === "object" &&
    "message" in envelope.detail &&
    typeof envelope.detail.message === "string"
  ) {
    return envelope.detail.message;
  }
  return "İşlem tamamlanamadı.";
}

async function parseEnvelope<T>(response: Response): Promise<ApiEnvelope<T> | undefined> {
  try {
    return (await response.json()) as ApiEnvelope<T>;
  } catch {
    return undefined;
  }
}

let refreshInFlight: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  try {
    const response = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    const envelope = await parseEnvelope<TokenPair>(response);
    if (!response.ok || !envelope?.data) return false;
    storeTokens(envelope.data.access_token, envelope.data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

async function ensureRefreshed(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = refreshSession().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function requestHeaders(init: RequestInit, authenticated: boolean): Headers {
  const headers = new Headers(init.headers);
  if (authenticated) {
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

export async function apiFetch(
  path: string,
  init: RequestInit = {},
  options: ApiFetchOptions = {},
): Promise<Response> {
  const authenticated = options.authenticated !== false;
  const retryOnUnauthorized = options.retryOnUnauthorized !== false;
  let response = await fetch(path, {
    ...init,
    headers: requestHeaders(init, authenticated),
  });

  if (response.status !== 401 || !authenticated || !retryOnUnauthorized) {
    return response;
  }

  if (!(await ensureRefreshed())) {
    notifyExpiredSession(path);
    return response;
  }

  response = await fetch(path, {
    ...init,
    headers: requestHeaders(init, authenticated),
  });
  if (response.status === 401) notifyExpiredSession(path);
  return response;
}

export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  const envelope = await parseEnvelope<unknown>(response);
  const retryAfterHeader = response.headers.get("Retry-After");
  const retryAfter = retryAfterHeader ? Number.parseInt(retryAfterHeader, 10) : undefined;
  return new ApiError(
    responseMessage(envelope),
    response.status,
    envelope?.error?.details ?? envelope?.detail,
    envelope?.error?.code,
    response.headers.get("X-Correlation-ID") ??
      response.headers.get("X-Request-ID") ??
      undefined,
    Number.isFinite(retryAfter) ? retryAfter : undefined,
  );
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: ApiFetchOptions = {},
): Promise<T> {
  const response = await apiFetch(path, init, options);
  const envelope = await parseEnvelope<T>(response);
  if (!envelope) {
    throw new ApiError("Sunucudan geçersiz bir yanıt alındı.", response.status);
  }
  if (!response.ok || envelope.success === false) {
    throw await apiErrorFromResponse(
      new Response(JSON.stringify(envelope), {
        status: response.status,
        headers: response.headers,
      }),
    );
  }
  return envelope.data;
}
