import { afterEach, describe, expect, it, vi } from "vitest";
import {
  apiRequest,
  clearTokens,
  getAccessToken,
  getRefreshToken,
  storeTokens,
} from "./apiClient";

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

afterEach(() => {
  clearTokens();
  vi.unstubAllGlobals();
});

describe("apiClient", () => {
  it("adds the access token to authenticated requests", async () => {
    storeTokens("access-1", "refresh-1");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ success: true, data: { ok: true } }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest<{ ok: boolean }>("/api/v1/example");

    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer access-1");
  });

  it("refreshes once and retries a request after a 401", async () => {
    storeTokens("expired", "refresh-1");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          { success: false, data: null, error: { message: "expired" } },
          401,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          success: true,
          data: {
            access_token: "access-2",
            refresh_token: "refresh-2",
            token_type: "bearer",
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ success: true, data: { ok: true } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiRequest<{ ok: boolean }>("/api/v1/example"),
    ).resolves.toEqual({ ok: true });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/auth/refresh");
    expect(getAccessToken()).toBe("access-2");
    expect(getRefreshToken()).toBe("refresh-2");
    const retryHeaders = new Headers(fetchMock.mock.calls[2][1]?.headers);
    expect(retryHeaders.get("Authorization")).toBe("Bearer access-2");
  });

  it("coalesces concurrent 401 responses into one refresh request", async () => {
    storeTokens("expired", "refresh-1");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (input === "/api/v1/auth/refresh") {
        return jsonResponse({
          success: true,
          data: {
            access_token: "access-2",
            refresh_token: "refresh-2",
            token_type: "bearer",
          },
        });
      }
      const authorization = new Headers(init?.headers).get("Authorization");
      return authorization === "Bearer access-2"
        ? jsonResponse({ success: true, data: { ok: true } })
        : jsonResponse({ success: false, data: null, error: { message: "expired" } }, 401);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      Promise.all([
        apiRequest<{ ok: boolean }>("/api/v1/one"),
        apiRequest<{ ok: boolean }>("/api/v1/two"),
      ]),
    ).resolves.toEqual([{ ok: true }, { ok: true }]);

    expect(
      fetchMock.mock.calls.filter(([input]) => input === "/api/v1/auth/refresh"),
    ).toHaveLength(1);
  });

  it("clears credentials and emits an expiry signal when refresh fails", async () => {
    storeTokens("expired", "refresh-1");
    const onExpired = vi.fn();
    window.addEventListener("kachow:auth-expired", onExpired, { once: true });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ success: false, error: { message: "expired" } }, 401))
      .mockResolvedValueOnce(jsonResponse({ success: false, error: { message: "invalid refresh" } }, 401));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/api/v1/example")).rejects.toMatchObject({ status: 401 });

    expect(onExpired).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
  });
});
