import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminPage } from "./AdminPage";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  invite: vi.fn(),
  update: vi.fn(),
  removeAccess: vi.fn(),
}));

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      id: "manager-1",
      username: "manager",
      email: "manager@kurum.gov.tr",
      role: "manager",
      clearance_level: "hizmete_ozel",
      is_active: true,
      is_deleted: false,
    },
    loading: false,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

vi.mock("../services/userService", () => ({ userService: mocks }));

describe("AdminPage manager permissions", () => {
  beforeEach(() => {
    mocks.list.mockReset().mockResolvedValue([
      {
        id: "employee-1",
        username: "employee",
        email: "employee@kurum.gov.tr",
        role: "employee",
        clearance_level: "hizmete_ozel",
        is_active: true,
        is_deleted: false,
      },
    ]);
  });

  it("allows listing and invitations but disables admin-only controls", async () => {
    render(<AdminPage onLogin={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("employee")).toBeInTheDocument());
    expect(screen.getByText("Erişim daveti oluştur")).toBeInTheDocument();
    expect(screen.getByLabelText("employee rolü")).toBeDisabled();
    expect(screen.getByLabelText("employee gizlilik yetkisi")).toBeDisabled();
    expect(screen.getByText("Yalnızca admin değiştirebilir")).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Denetçi" })).not.toBeInTheDocument();
  });
});
