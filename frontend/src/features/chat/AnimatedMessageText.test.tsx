import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnimatedMessageText } from "./AnimatedMessageText";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("AnimatedMessageText", () => {
  it("renders settled history messages immediately", () => {
    render(<AnimatedMessageText text="Tamamlanmış yanıt" />);

    expect(screen.getByText("Tamamlanmış yanıt")).toBeInTheDocument();
    expect(document.querySelector(".streaming-caret")).toBeNull();
  });

  it("reveals a new final reply locally without waiting for backend chunks", () => {
    vi.useFakeTimers();
    const onComplete = vi.fn();
    const { container } = render(
      <AnimatedMessageText
        text="Bu cevap frontend üzerinde kontrollü biçimde yazılıyor."
        animate
        onComplete={onComplete}
      />,
    );

    expect(container.querySelector("[aria-hidden='true']")).not.toHaveTextContent("Bu cevap frontend üzerinde kontrollü biçimde yazılıyor.");
    expect(document.querySelector(".streaming-caret")).not.toBeNull();
    expect(onComplete).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(10_000));

    expect(screen.getByText("Bu cevap frontend üzerinde kontrollü biçimde yazılıyor.")).toBeInTheDocument();
    expect(document.querySelector(".streaming-caret")).toBeNull();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("completes immediately when reduced motion is preferred", () => {
    const onComplete = vi.fn();
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));

    render(
      <AnimatedMessageText
        text="Animasyonsuz yanıt"
        animate
        onComplete={onComplete}
      />,
    );

    expect(screen.getByText("Animasyonsuz yanıt")).toBeInTheDocument();
    expect(document.querySelector(".streaming-caret")).toBeNull();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });
});
