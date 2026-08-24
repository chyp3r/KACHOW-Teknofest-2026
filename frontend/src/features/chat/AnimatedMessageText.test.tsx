import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnimatedMessageText } from "./AnimatedMessageText";

afterEach(() => {
  vi.useRealTimers();
});

describe("AnimatedMessageText", () => {
  it("renders settled history messages immediately", () => {
    render(<AnimatedMessageText text="Tamamlanmış yanıt" />);

    expect(screen.getByText("Tamamlanmış yanıt")).toBeInTheDocument();
    expect(document.querySelector(".streaming-caret")).toBeNull();
  });

  it("reveals a new final reply locally without waiting for backend chunks", () => {
    vi.useFakeTimers();
    const { container } = render(<AnimatedMessageText text="Bu cevap frontend üzerinde kontrollü biçimde yazılıyor." animate />);

    expect(container.querySelector("[aria-hidden='true']")).not.toHaveTextContent("Bu cevap frontend üzerinde kontrollü biçimde yazılıyor.");
    expect(document.querySelector(".streaming-caret")).not.toBeNull();

    act(() => vi.advanceTimersByTime(10_000));

    expect(screen.getByText("Bu cevap frontend üzerinde kontrollü biçimde yazılıyor.")).toBeInTheDocument();
    expect(document.querySelector(".streaming-caret")).toBeNull();
  });
});
