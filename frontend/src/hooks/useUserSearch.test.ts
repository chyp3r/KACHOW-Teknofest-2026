import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUserSearch } from "./useUserSearch";

const mocks = vi.hoisted(() => ({ search: vi.fn() }));

vi.mock("../services/userService", () => ({ userService: mocks }));

describe("useUserSearch", () => {
  function wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, {
      client: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    }, children);
  }

  beforeEach(() => {
    vi.useFakeTimers();
    mocks.search.mockReset().mockResolvedValue({ items: [], total: 0, page: 1, size: 20, pages: 0 });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("never calls the backend for a query below the minimum length", async () => {
    const { result } = renderHook(() => useUserSearch(), { wrapper });

    act(() => result.current.setQuery("a"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(mocks.search).not.toHaveBeenCalled();
    expect(result.current.isSearching).toBe(true);
  });

  it("debounces before calling the backend once the minimum length is met", async () => {
    const { result } = renderHook(() => useUserSearch(), { wrapper });

    act(() => result.current.setQuery("ah"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(mocks.search).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(mocks.search).toHaveBeenCalledWith({ q: "ah", unitId: undefined, role: undefined });
  });

  it("only fires the latest query when the user keeps typing within the debounce window", async () => {
    const { result } = renderHook(() => useUserSearch(), { wrapper });

    act(() => result.current.setQuery("ah"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    act(() => result.current.setQuery("ahmet"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });

    expect(mocks.search).toHaveBeenCalledTimes(1);
    expect(mocks.search).toHaveBeenCalledWith({ q: "ahmet", unitId: undefined, role: undefined });
  });
});
