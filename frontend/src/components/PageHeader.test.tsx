import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "./Button";
import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("keeps secondary and primary actions in semantic groups", () => {
    render(
      <PageHeader
        title="Taslaklar"
        description="Taslak kayıtlarını inceleyin."
        secondaryActions={<Button variant="secondary">Geçmiş</Button>}
        primaryAction={<Button>Yeni taslak</Button>}
      />,
    );

    expect(screen.getByRole("heading", { name: "Taslaklar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Geçmiş" }).parentElement).toHaveClass("page-secondary-actions");
    expect(screen.getByRole("button", { name: "Yeni taslak" }).parentElement).toHaveClass("page-primary-action");
  });
});
