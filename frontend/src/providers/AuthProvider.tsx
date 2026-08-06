import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { AuthContext } from "../contexts/AuthContext";
import { authService } from "../services/authService";
import {
  ApiError,
  AUTH_EXPIRED_EVENT,
  clearTokens,
  getAccessToken,
} from "../services/apiClient";
import type { User } from "../types/users";

const DEVELOPMENT_USER: User = {
  id: "local-development-user",
  username: "Yerel geliştirici",
  email: "dev@localhost",
  role: "employee",
  clearance_level: "hizmete_ozel",
  is_active: true,
  is_deleted: false,
};

function isDevelopmentBypassEnabled(): boolean {
  return (
    import.meta.env.DEV &&
    import.meta.env.VITE_DEV_AUTH_BYPASS === "true"
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const developmentBypass = isDevelopmentBypassEnabled();

  useEffect(() => {
    const expire = () =>
      setUser((current) => {
        if (current)
          localStorage.removeItem(`kachow.chat.session.${current.id}`);
        return null;
      });
    window.addEventListener(AUTH_EXPIRED_EVENT, expire);
    if (developmentBypass) {
      clearTokens();
      setUser(DEVELOPMENT_USER);
      setLoading(false);
      return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expire);
    }
    if (!getAccessToken()) {
      setLoading(false);
      return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expire);
    }
    authService
      .me()
      .then(setUser)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) clearTokens();
        else
          console.error(error);
      })
      .finally(() => setLoading(false));
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, expire);
  }, [developmentBypass]);

  const login = useCallback(async (username: string, password: string) => {
    setUser(await authService.login(username, password));
  }, []);
  const logout = useCallback(async () => {
    if (developmentBypass) {
      setUser(DEVELOPMENT_USER);
      return;
    }
    try {
      await authService.logout();
    } finally {
      setUser((current) => {
        if (current)
          localStorage.removeItem(`kachow.chat.session.${current.id}`);
        return null;
      });
    }
  }, [developmentBypass]);
  const value = useMemo(
    () => ({ user, loading, login, logout }),
    [user, loading, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
