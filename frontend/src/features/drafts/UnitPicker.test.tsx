import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { UnitPicker } from "./UnitPicker";

vi.mock("../../services/unitsService", () => ({
  unitsService: {
    list: vi.fn().mockResolvedValue([
      { id: "unit-1", name: "Mali İşler", description: "Bütçe ve ödemeler.", is_active: true },
      { id: "unit-2", name: "İnsan Kaynakları", description: "Personel işleri.", is_active: true },
      { id: "unit-3", name: "Arşivlenmiş Birim", description: "Artık aktif değil.", is_active: false },
    ]),
  },
}));

function renderWithQueryClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("UnitPicker", () => {
  it("starts collapsed behind a single toggle button", () => {
    renderWithQueryClient(<UnitPicker currentDestination="Mali İşler" saving={false} onSave={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Birimi değiştir" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Hedef birim")).not.toBeInTheDocument();
  });

  it("lists only active units and lets the user save a different one", async () => {
    const onSave = vi.fn();
    renderWithQueryClient(<UnitPicker currentDestination="Mali İşler" saving={false} onSave={onSave} />);

    fireEvent.click(screen.getByRole("button", { name: "Birimi değiştir" }));
    const select = await screen.findByLabelText("Hedef birim");
    await waitFor(() => expect(screen.getByRole("option", { name: "İnsan Kaynakları" })).toBeInTheDocument());
    expect(screen.queryByText("Arşivlenmiş Birim")).not.toBeInTheDocument();

    fireEvent.change(select, { target: { value: "İnsan Kaynakları" } });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));

    expect(onSave).toHaveBeenCalledWith("İnsan Kaynakları");
  });

  it("accepts a custom, unlisted unit name", async () => {
    const onSave = vi.fn();
    renderWithQueryClient(<UnitPicker currentDestination="Mali İşler" saving={false} onSave={onSave} />);

    fireEvent.click(screen.getByRole("button", { name: "Birimi değiştir" }));
    const select = await screen.findByLabelText("Hedef birim");
    fireEvent.change(select, { target: { value: "__custom__" } });
    fireEvent.change(screen.getByLabelText("Birim adı"), { target: { value: "Basın ve Halkla İlişkiler" } });
    fireEvent.click(screen.getByRole("button", { name: "Kaydet" }));

    expect(onSave).toHaveBeenCalledWith("Basın ve Halkla İlişkiler");
  });

  it("disables saving when the picked value is unchanged from the current destination", async () => {
    renderWithQueryClient(<UnitPicker currentDestination="Mali İşler" saving={false} onSave={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Birimi değiştir" }));
    await screen.findByLabelText("Hedef birim");

    expect(screen.getByRole("button", { name: "Kaydet" })).toBeDisabled();
  });
});
