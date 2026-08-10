import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../services/apiClient";
import { ApiErrorNotice } from "./ApiErrorNotice";

describe("ApiErrorNotice", () => {
  it("presents rate-limit and request correlation details without exposing payloads", () => {
    render(<ApiErrorNotice error={new ApiError("Çok fazla istek", 429, { secret: "hidden" }, "RATE_LIMIT", "request-42", 15)} />);

    expect(screen.getByRole("alert")).toHaveTextContent("İstek sınırına ulaşıldı");
    fireEvent.click(screen.getByText("Hata ayrıntıları"));
    expect(screen.getByText(/request-42/)).toBeInTheDocument();
    expect(screen.getByText(/15 saniye/)).toBeInTheDocument();
    expect(screen.queryByText(/hidden/)).not.toBeInTheDocument();
  });
});
