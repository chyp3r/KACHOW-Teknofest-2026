import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../hooks/useAuth";
import { AuthProvider } from "./AuthProvider";

function SessionProbe() {
  const { user, loading } = useAuth();
  return <span>{loading ? "loading" : user?.username ?? "anonymous"}</span>;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("AuthProvider development bypass", () => {
  it("opens a local session without calling the login API", async () => {
    vi.stubEnv("VITE_DEV_AUTH_BYPASS", "true");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AuthProvider>
        <SessionProbe />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByText("Yerel geliştirici")).toBeInTheDocument(),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
