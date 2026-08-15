import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThinkingBubble } from "./ThinkingBubble";

const baseProps = {
  planSteps: ["draft"],
  nodeOrder: ["planning", "draft"],
  nodeLabels: {},
  nodeMeta: {},
  nodeResults: {},
  nodeStartedAt: {},
  turnStartedAt: null as number | null,
};

describe("ThinkingBubble", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the live step list derived from nodeOrder/nodeStatus, not a static line", () => {
    render(
      <ThinkingBubble
        {...baseProps}
        nodeStatus={{ planning: "completed", draft: "running" }}
      />,
    );
    expect(screen.getByText("Yönlendirici")).toBeInTheDocument();
    expect(screen.getByText("Taslak")).toBeInTheDocument();
    const steps = screen.getAllByRole("listitem");
    const draftStep = steps.find((item) => item.textContent?.includes("Taslak"));
    expect(draftStep).toHaveClass("is-running");
  });

  it("counts up the total elapsed time since the turn started", () => {
    const turnStartedAt = Date.now();
    render(
      <ThinkingBubble
        {...baseProps}
        nodeStatus={{ draft: "running" }}
        turnStartedAt={turnStartedAt}
      />,
    );
    expect(screen.getByText("0 sn")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByText("5 sn")).toBeInTheDocument();
  });

  it("shows a skeleton placeholder while the draft step is running with no preview text yet", () => {
    const { container } = render(
      <ThinkingBubble {...baseProps} nodeStatus={{ draft: "running" }} />,
    );
    expect(container.querySelector(".thinking-bubble-draft-skeleton")).not.toBeNull();
    expect(container.querySelector(".thinking-bubble-draft-preview")).toBeNull();
  });

  it("shows the streamed partial draft text once partial_result has arrived", () => {
    const { container } = render(
      <ThinkingBubble
        {...baseProps}
        nodeStatus={{ draft: "running" }}
        nodeResults={{ draft: { draft: "Sayın Muhatap,\n\nBu bir ön izlemedir..." } }}
      />,
    );
    expect(screen.getByText(/Bu bir ön izlemedir/)).toBeInTheDocument();
    expect(container.querySelector(".thinking-bubble-draft-skeleton")).toBeNull();
  });

  it("shows the attempt/reasoning-level subtext only while the draft step is actually running", () => {
    const { rerender } = render(
      <ThinkingBubble
        {...baseProps}
        nodeStatus={{ draft: "running" }}
        nodeMeta={{ draft: { attempt: 2, reasoning_level: "deep" } }}
      />,
    );
    expect(screen.getByText("2. deneme · deep mod")).toBeInTheDocument();

    rerender(
      <ThinkingBubble
        {...baseProps}
        nodeStatus={{ draft: "completed", verify: "running" }}
        nodeMeta={{ draft: { attempt: 2, reasoning_level: "deep" } }}
      />,
    );
    expect(screen.queryByText("2. deneme · deep mod")).not.toBeInTheDocument();
  });

  it("offers the long-wait hint and fast retry only after a step has run past the threshold", () => {
    const runningStartedAt = Date.now();
    const onRetryFast = vi.fn();
    render(
      <ThinkingBubble
        {...baseProps}
        nodeStatus={{ draft: "running" }}
        nodeStartedAt={{ draft: runningStartedAt }}
        onRetryFast={onRetryFast}
      />,
    );
    expect(screen.queryByText("Bu adım normalden uzun sürüyor.")).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(21_000);
    });
    expect(screen.getByText("Bu adım normalden uzun sürüyor.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hızlı modda tekrar dene" }));
    expect(onRetryFast).toHaveBeenCalledOnce();
  });

  it("moves the cancel action into the bubble", () => {
    const onCancel = vi.fn();
    render(<ThinkingBubble {...baseProps} nodeStatus={{ draft: "running" }} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: "İşlemi durdur" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
