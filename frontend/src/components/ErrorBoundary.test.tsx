import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function BrokenScreen(): never {
  throw new Error("render failed");
}

afterEach(() => vi.restoreAllMocks());

describe("ErrorBoundary", () => {
  it("replaces a crashed route with an accessible recovery screen", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<ErrorBoundary><BrokenScreen /></ErrorBoundary>);

    expect(screen.getByRole("alert")).toHaveTextContent("Bu ekran yüklenemedi");
    expect(screen.getByRole("button", { name: "Sayfayı yenile" })).toBeInTheDocument();
  });
});
