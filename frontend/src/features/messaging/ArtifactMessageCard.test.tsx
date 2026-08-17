import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ArtifactMessageCard } from "./ArtifactMessageCard";
import type { ArtifactTransfer } from "../../types/transfers";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../../services/transferService", () => ({ transferService: mocks }));

function transfer(overrides: Partial<ArtifactTransfer> = {}): ArtifactTransfer {
  return {
    id: "transfer-1",
    artifact_kind: "draft",
    source_artifact_id: "draft-1",
    source_version: 2,
    snapshot_ref: "draft-2",
    sender_id: "me",
    recipient_id: "other",
    conversation_id: "conv-1",
    message_id: "msg-1",
    channel: "chat",
    ai_suggested: false,
    cross_unit: false,
    policy_decision: "permit",
    policy_reason: null,
    status: "executed",
    created_at: "2026-08-16T10:00:00Z",
    ...overrides,
  };
}

function renderCard(transferId: string, currentUserId = "me") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function wrapper({ children }: { children: ReactNode }) {
    return createElement(
      QueryClientProvider,
      { client },
      createElement(MemoryRouter, null, children),
    );
  }
  return render(<ArtifactMessageCard transferId={transferId} currentUserId={currentUserId} />, { wrapper });
}

describe("ArtifactMessageCard", () => {
  it("shows the draft's version and an executed status badge", async () => {
    mocks.get.mockResolvedValue(transfer());
    renderCard("transfer-1");
    await waitFor(() => expect(screen.getByText(/v2/)).toBeInTheDocument());
    expect(screen.getByText("Gönderildi")).toBeInTheDocument();
  });

  it("shows a cross-unit indicator only when the transfer crossed units", async () => {
    mocks.get.mockResolvedValue(transfer({ cross_unit: true }));
    renderCard("transfer-1");
    await waitFor(() => expect(screen.getByText("Farklı birim")).toBeInTheDocument());
  });

  it("does not show the cross-unit indicator for a same-unit transfer", async () => {
    mocks.get.mockResolvedValue(transfer({ cross_unit: false }));
    renderCard("transfer-1");
    await waitFor(() => expect(screen.getByText("Gönderildi")).toBeInTheDocument());
    expect(screen.queryByText("Farklı birim")).not.toBeInTheDocument();
  });

  it("offers no Aç button for a failed transfer", async () => {
    mocks.get.mockResolvedValue(transfer({ status: "failed" }));
    renderCard("transfer-1");
    await waitFor(() => expect(screen.getByText("Başarısız")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Aç" })).not.toBeInTheDocument();
  });

  it("offers no Aç button for a document transfer", async () => {
    mocks.get.mockResolvedValue(transfer({ artifact_kind: "document" }));
    renderCard("transfer-1");
    await waitFor(() => expect(screen.getByText(/Evrak/)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Aç" })).not.toBeInTheDocument();
  });

  it("shows an error state when the transfer fails to load", async () => {
    mocks.get.mockRejectedValue(new Error("boom"));
    renderCard("transfer-1");
    await waitFor(() => expect(screen.getByText("Gönderi yüklenemedi.")).toBeInTheDocument());
  });
});
