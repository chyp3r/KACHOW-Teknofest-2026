import { afterEach, describe, expect, it, vi } from "vitest";
import { clearTokens, getAccessToken, getRefreshToken } from "./apiClient";
import { authService } from "./authService";

const response = (data: unknown) => new Response(JSON.stringify({ success: true, data }), {
  status: 200, headers: { "Content-Type": "application/json" },
});

afterEach(() => {
  clearTokens();
  vi.unstubAllGlobals();
});

describe("authService", () => {
  it("uses the verified login/logout bodies and clears the session", async () => {
    const user = {
      id: "user-1", username: "demo", email: "demo@example.test", role: "employee",
      clearance_level: "hizmete_ozel", is_active: true, is_deleted: false,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ access_token: "access", refresh_token: "refresh", token_type: "bearer" }))
      .mockResolvedValueOnce(response(user))
      .mockResolvedValueOnce(response(null));
    vi.stubGlobal("fetch", fetchMock);

    await expect(authService.login("demo", "password")).resolves.toEqual(user);
    expect(getAccessToken()).toBe("access");
    const loginBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(loginBody).toEqual({ username: "demo", password: "password" });

    await authService.logout();
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({ refresh_token: "refresh" });
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
  });
});
