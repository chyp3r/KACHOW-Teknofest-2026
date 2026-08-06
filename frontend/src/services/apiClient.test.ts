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
});
