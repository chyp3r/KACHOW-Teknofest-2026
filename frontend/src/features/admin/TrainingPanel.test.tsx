import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TrainingPanel } from "./TrainingPanel";

const mocks = vi.hoisted(() => ({
  compileSamples: vi.fn(),
  listSamples: vi.fn(),
  stats: vi.fn(),
  deleteSample: vi.fn(),
  triggerRun: vi.fn(),
  listRuns: vi.fn(),
}));

vi.mock("../../services/trainingService", () => ({ trainingService: mocks }));

function renderWithQueryClient(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const STATS = { total: 12, by_source: { explicit_feedback: 12 }, min_samples_required: 50, samples_remaining_to_threshold: 38 };
const SAMPLE = {
  id: "sample-1", source: "explicit_feedback", chosen: "Sayın Makam, arz ederim.",
  rejected: null, weight: 1, created_at: "2026-08-15T00:00:00Z", updated_at: "2026-08-15T00:00:00Z",
};
const RUN = {
  id: "run-1", kind: "style_adapter", status: "succeeded" as const, trigger: "manual",
  sample_count: 60, metrics: {}, error: null, created_at: "2026-08-15T00:00:00Z",
};

beforeEach(() => {
  mocks.compileSamples.mockReset();
  mocks.listSamples.mockReset().mockResolvedValue({ items: [SAMPLE], total: 1, page: 1, size: 20, pages: 1 });
  mocks.stats.mockReset().mockResolvedValue(STATS);
  mocks.deleteSample.mockReset();
  mocks.triggerRun.mockReset();
  mocks.listRuns.mockReset().mockResolvedValue({ items: [RUN], total: 1, page: 1, size: 20, pages: 1 });
});

describe("TrainingPanel", () => {
  it("renders sample-remaining-to-threshold stats once loaded", async () => {
    renderWithQueryClient(<TrainingPanel companyId="company-1" canManage />);

    await waitFor(() => expect(screen.getByText("38")).toBeInTheDocument());
  });

  it("lists compiled samples and expands a chosen/rejected diff on click", async () => {
    renderWithQueryClient(<TrainingPanel companyId="company-1" canManage />);

    await waitFor(() => expect(screen.getByText("explicit_feedback")).toBeInTheDocument());
    expect(screen.queryByText("Sayın Makam, arz ederim.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("explicit_feedback"));

    expect(screen.getByText("Sayın Makam, arz ederim.")).toBeInTheDocument();
  });

  it("compiles samples and shows a confirmation notice", async () => {
    mocks.compileSamples.mockResolvedValue({ items: [], total: 5, page: 1, size: 5, pages: 1 });

    renderWithQueryClient(<TrainingPanel companyId="company-1" canManage />);
    await waitFor(() => expect(screen.getByText("explicit_feedback")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Örnekleri derle" }));

    await waitFor(() => expect(mocks.compileSamples).toHaveBeenCalledWith("company-1"));
    await waitFor(() => expect(screen.getByText("5 örnek derlendi.")).toBeInTheDocument());
  });

  it("triggers a training run", async () => {
    mocks.triggerRun.mockResolvedValue(RUN);

    renderWithQueryClient(<TrainingPanel companyId="company-1" canManage />);
    await waitFor(() => expect(screen.getByText("explicit_feedback")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Eğitimi başlat" }));

    await waitFor(() => expect(mocks.triggerRun).toHaveBeenCalledWith("company-1"));
    await waitFor(() => expect(screen.getByText("Üslup adaptörü güncellendi.")).toBeInTheDocument());
  });

  it("shows a skip message without treating it as a failure", async () => {
    mocks.triggerRun.mockResolvedValue({ ...RUN, status: "skipped" });

    renderWithQueryClient(<TrainingPanel companyId="company-1" canManage />);
    await waitFor(() => expect(screen.getByText("explicit_feedback")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Eğitimi başlat" }));

    await waitFor(() =>
      expect(screen.getByText("Eğitim atlandı -- eşiği geçecek kadar örnek yok.")).toBeInTheDocument(),
    );
  });

  it("hides compile/train/delete controls for a non-managing viewer", async () => {
    renderWithQueryClient(<TrainingPanel companyId="company-1" canManage={false} />);

    await waitFor(() => expect(screen.getByText("explicit_feedback")).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: "Örnekleri derle" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Eğitimi başlat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kaldır" })).not.toBeInTheDocument();
  });

  it("deletes a sample without navigating into its expanded diff", async () => {
    mocks.deleteSample.mockResolvedValue({ deleted: true });

    renderWithQueryClient(<TrainingPanel companyId="company-1" canManage />);
    await waitFor(() => expect(screen.getByText("explicit_feedback")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Kaldır" }));

    await waitFor(() => expect(mocks.deleteSample).toHaveBeenCalledWith("sample-1"));
    expect(screen.queryByText("Sayın Makam, arz ederim.")).not.toBeInTheDocument();
  });

  it("renders training run history with a status badge", async () => {
    renderWithQueryClient(<TrainingPanel companyId="company-1" canManage />);

    await waitFor(() => expect(screen.getByText("Başarılı")).toBeInTheDocument());
  });
});
