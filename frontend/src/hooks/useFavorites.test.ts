import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useFavorites } from "./useFavorites";
import type { Favorite } from "../types/favorites";

const mocks = vi.hoisted(() => ({ list: vi.fn(), add: vi.fn(), remove: vi.fn() }));

vi.mock("../services/favoritesService", () => ({ favoritesService: mocks }));

function favorite(userId: string): Favorite {
  return {
    id: `fav-${userId}`,
    favorite_user_id: userId,
    username: userId,
    email: `${userId}@example.test`,
    note: null,
    created_at: "2026-08-16T10:00:00Z",
  };
}

describe("useFavorites", () => {
  function wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, {
      client: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    }, children);
  }

  beforeEach(() => {
    mocks.list.mockReset().mockResolvedValue([favorite("ahmet")]);
    mocks.add.mockReset();
    mocks.remove.mockReset();
  });

  it("exposes favorite ids for a quick membership check", async () => {
    const { result } = renderHook(() => useFavorites(), { wrapper });
    await waitFor(() => expect(result.current.favorites).toHaveLength(1));
    expect(result.current.favoriteIds.has("ahmet")).toBe(true);
    expect(result.current.favoriteIds.has("berk")).toBe(false);
  });

  it("adding a favorite inserts it without duplicating an existing row", async () => {
    const { result } = renderHook(() => useFavorites(), { wrapper });
    await waitFor(() => expect(result.current.favorites).toHaveLength(1));

    mocks.add.mockResolvedValue(favorite("berk"));
    await act(async () => {
      await result.current.add("berk");
    });

    await waitFor(() =>
      expect(result.current.favorites.map((item) => item.favorite_user_id)).toEqual(["berk", "ahmet"]),
    );
  });

  it("removing a favorite drops it from the list", async () => {
    const { result } = renderHook(() => useFavorites(), { wrapper });
    await waitFor(() => expect(result.current.favorites).toHaveLength(1));

    mocks.remove.mockResolvedValue({ removed: true });
    await act(async () => {
      await result.current.remove("ahmet");
    });

    await waitFor(() => expect(result.current.favorites).toHaveLength(0));
  });
});
