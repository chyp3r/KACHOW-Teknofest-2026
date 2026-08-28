import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RegisterPage } from "./RegisterPage";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn(),
}));

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ login: mocks.login }),
}));

vi.mock("../services/userService", () => ({ userService: { register: mocks.register } }));

function renderRegisterPage() {
  return render(<RegisterPage />, { wrapper: MemoryRouter });
}

function fillForm({
  username = "yeni.kullanici",
  email = "yeni@kurum.gov.tr",
  password = "secret-pass",
  confirmPassword = password,
}: { username?: string; email?: string; password?: string; confirmPassword?: string } = {}) {
  fireEvent.change(screen.getByLabelText("Kullanıcı adı"), { target: { value: username } });
  fireEvent.change(screen.getByLabelText("E-posta"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Parola"), { target: { value: password } });
  fireEvent.change(screen.getByLabelText("Parola (Tekrar)"), { target: { value: confirmPassword } });
  fireEvent.click(screen.getByRole("button", { name: "Kayıt ol" }));
}

describe("RegisterPage", () => {
  beforeEach(() => {
    mocks.login.mockReset().mockResolvedValue(undefined);
    mocks.register.mockReset().mockResolvedValue({ id: "user-1" });
  });

  it("registers then logs in with the same credentials", async () => {
    renderRegisterPage();

    fillForm({ username: "yeni.kullanici", email: "yeni@kurum.gov.tr", password: "secret-pass" });

    await waitFor(() =>
      expect(mocks.register).toHaveBeenCalledWith("yeni.kullanici", "yeni@kurum.gov.tr", "secret-pass"),
    );
    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith("yeni.kullanici", "secret-pass"));
  });

  it("rejects a submit without ever calling the backend when passwords don't match", () => {
    renderRegisterPage();

    fillForm({ password: "secret-pass", confirmPassword: "different" });

    expect(screen.getByText("Parolalar eşleşmiyor.")).toBeInTheDocument();
    expect(mocks.register).not.toHaveBeenCalled();
  });

  it("translates the invite-gate error into Turkish", async () => {
    mocks.register.mockRejectedValue(
      new Error("This email address has not been invited by a system administrator."),
    );
    renderRegisterPage();

    fillForm();

    await waitFor(() =>
      expect(
        screen.getByText(
          "Bu e-posta adresi bir yöneticiniz tarafından davet edilmedi. Lütfen kurumunuzun yöneticisiyle iletişime geçin.",
        ),
      ).toBeInTheDocument(),
    );
    expect(mocks.login).not.toHaveBeenCalled();
  });

  it("links back to the login page", () => {
    renderRegisterPage();
    expect(screen.getByRole("link", { name: "Oturum aç" })).toHaveAttribute("href", "/login");
  });
});
