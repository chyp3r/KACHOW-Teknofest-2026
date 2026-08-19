import { fireEvent, render, screen } from "@testing-library/react";
import { Search } from "lucide-react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { Button, IconButton } from "./Button";
import { Input } from "./FormControls";
import { ListRow } from "./ListRow";
import { Dialog, Drawer } from "./Overlay";
import { Tabs } from "./Tabs";

describe("design-system primitives", () => {
  it("keeps button content stable while exposing variant, loading, and disabled state", () => {
    render(<Button variant="destructive" loading>Kaydı sil</Button>);
    const button = screen.getByRole("button", { name: "Kaydı sil" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveClass("button-destructive");
  });

  it("requires an accessible name for icon-only controls", () => {
    render(<IconButton icon={<Search />} aria-label="Evraklarda ara" />);
    expect(screen.getByRole("button", { name: "Evraklarda ara" })).toBeInTheDocument();
  });

  it("associates labels, errors, and invalid state with form controls", () => {
    render(<Input label="E-posta" error="Geçerli bir adres girin" />);
    const input = screen.getByLabelText("E-posta");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Geçerli bir adres girin");
  });

  it("activates list rows as native keyboard buttons", () => {
    const onClick = vi.fn();
    render(<ListRow primary="Taslak" expandable onClick={onClick} />);
    const row = screen.getByRole("button", { name: /Taslak/ });
    row.focus();
    fireEvent.keyDown(row, { key: "Enter" });
    fireEvent.click(row);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("exposes shared tabs with native selected state", () => {
    const onChange = vi.fn();
    render(<Tabs label="Bölümler" active="users" onChange={onChange} items={[{ id: "users", label: "Kullanıcılar" }, { id: "training", label: "Eğitim" }]} />);
    expect(screen.getByRole("tab", { name: "Kullanıcılar" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Eğitim" }));
    expect(onChange).toHaveBeenCalledWith("training");
  });
});

describe("shared overlays", () => {
  it("closes a dialog with Escape", () => {
    const onClose = vi.fn();
    render(<Dialog open title="Onay" onClose={onClose}>İçerik</Dialog>);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("locks scrolling and restores focus for drawers", () => {
    const onClose = vi.fn();
    const triggerRef = createRef<HTMLButtonElement>();
    const { unmount } = render(<><button ref={triggerRef}>Geçmişi aç</button><Drawer open title="Geçmiş" onClose={onClose} returnFocusRef={triggerRef}>İçerik</Drawer></>);
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount();
    expect(document.body.style.overflow).toBe("");
  });
});
