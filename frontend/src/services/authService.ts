import {
  apiRequest,
  clearTokens,
  getRefreshToken,
  storeTokens,
} from "./apiClient";
import type { TokenPair, User } from "../types/users";

export const authService = {
  me: () => apiRequest<User>("/api/v1/users/me"),
  async login(username: string, password: string): Promise<User> {
    const tokens = await apiRequest<TokenPair>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    storeTokens(tokens.access_token, tokens.refresh_token);
    return apiRequest<User>("/api/v1/users/me");
  },
  async logout(): Promise<void> {
    const refreshToken = getRefreshToken();
    try {
      await apiRequest<null>("/api/v1/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } finally {
      clearTokens();
    }
  },
};
