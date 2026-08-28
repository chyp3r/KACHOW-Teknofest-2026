import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LoginPage } from "./LoginPage";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
}));

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ login: mocks.login }),
}));

vi.mock("../hooks/useSessionNotice", () => ({
  useSessionNotice: () => null,
}));

function renderLoginPage(onSuccess = vi.fn()) {
  return render(<LoginPage onSuccess={onSuccess} />, { wrapper: MemoryRouter });
}

describe("LoginPage", () => {
  beforeEach(() => {
    mocks.login.mockReset().mockResolvedValue(undefined);
  });

  it("supports password visibility and the real login flow", async () => {
    const onSuccess = vi.fn();
    renderLoginPage(onSuccess);

    const password = screen.getByLabelText("Parola");
    expect(password).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Parolayı göster" }));
    expect(password).toHaveAttribute("type", "text");

    fireEvent.change(screen.getByLabelText("Kullanıcı adı veya e-posta"), { target: { value: "admin" } });
    fireEvent.change(password, { target: { value: "secret-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "Oturum aç" }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith("admin", "secret-pass"));
    expect(onSuccess).toHaveBeenCalled();
  });

  it("shows the institutional KACHOW identity", () => {
    renderLoginPage();
    expect(screen.getByText("KACHOW")).toBeInTheDocument();
    expect(screen.getByText("Karar Destek Sistemi")).toBeInTheDocument();
  });

  it("links to the register page for a user without an account", () => {
    renderLoginPage();
    expect(screen.getByRole("link", { name: "Kayıt ol" })).toHaveAttribute("href", "/register");
  });
});
