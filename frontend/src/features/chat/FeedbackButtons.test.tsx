import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FeedbackButtons } from "./FeedbackButtons";

const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("../../services/feedbackService", () => ({ feedbackService: mocks }));

function renderWithQueryClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  mocks.submit.mockReset();
  mocks.remove.mockReset();
});

describe("FeedbackButtons", () => {
  it("casts a like vote immediately, without a comment step", async () => {
    mocks.submit.mockResolvedValue({ id: "fb-1", signal: "like" });

    renderWithQueryClient(<FeedbackButtons targetKind="draft" content="İşte taslağınız." />);
    fireEvent.click(screen.getByRole("button", { name: "Beğendim" }));

    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    expect(mocks.submit).toHaveBeenCalledWith(
      expect.objectContaining({ target_kind: "draft", signal: "like", content: "İşte taslağınız." }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Beğendim" })).toHaveClass("is-active"),
    );
  });

  it("withdraws an already-cast vote on a second click instead of re-submitting", async () => {
    mocks.submit.mockResolvedValue({ id: "fb-1", signal: "like" });
    mocks.remove.mockResolvedValue({ deleted: true });

    renderWithQueryClient(<FeedbackButtons targetKind="draft" content="İşte taslağınız." />);
    fireEvent.click(screen.getByRole("button", { name: "Beğendim" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Beğendim" })).toHaveClass("is-active"),
    );

    fireEvent.click(screen.getByRole("button", { name: "Beğendim" }));

    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith("fb-1"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Beğendim" })).not.toHaveClass("is-active"),
    );
  });

  it("opens a comment box on dislike instead of submitting blind", () => {
    renderWithQueryClient(<FeedbackButtons targetKind="assist_reply" content="Cevap metni." />);

    fireEvent.click(screen.getByRole("button", { name: "Beğenmedim" }));

    expect(screen.getByLabelText("Ne iyileştirilebilir? (opsiyonel)")).toBeInTheDocument();
    expect(mocks.submit).not.toHaveBeenCalled();
  });

  it("submits the dislike with the typed comment", async () => {
    mocks.submit.mockResolvedValue({ id: "fb-2", signal: "dislike" });

    renderWithQueryClient(<FeedbackButtons targetKind="assist_reply" content="Cevap metni." />);
    fireEvent.click(screen.getByRole("button", { name: "Beğenmedim" }));
    fireEvent.change(screen.getByLabelText("Ne iyileştirilebilir? (opsiyonel)"), {
      target: { value: "Dayanak eksik." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Gönder" }));

    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    expect(mocks.submit).toHaveBeenCalledWith(
      expect.objectContaining({ signal: "dislike", comment: "Dayanak eksik." }),
    );
    await waitFor(() =>
      expect(screen.queryByLabelText("Ne iyileştirilebilir? (opsiyonel)")).not.toBeInTheDocument(),
    );
  });

  it("shows an inline error instead of an unhandled rejection when the vote fails", async () => {
    mocks.submit.mockRejectedValue(new Error("network down"));

    renderWithQueryClient(<FeedbackButtons targetKind="draft" content="İşte taslağınız." />);
    fireEvent.click(screen.getByRole("button", { name: "Beğendim" }));

    await waitFor(() =>
      expect(screen.getByText("Oy gönderilemedi. Lütfen tekrar deneyin.")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Beğendim" })).not.toHaveClass("is-active");
  });

  it("closes the comment box on vazgeç without submitting anything", () => {
    renderWithQueryClient(<FeedbackButtons targetKind="assist_reply" content="Cevap metni." />);
    fireEvent.click(screen.getByRole("button", { name: "Beğenmedim" }));

    fireEvent.click(screen.getByRole("button", { name: "Vazgeç" }));

    expect(screen.queryByLabelText("Ne iyileştirilebilir? (opsiyonel)")).not.toBeInTheDocument();
    expect(mocks.submit).not.toHaveBeenCalled();
  });
});
