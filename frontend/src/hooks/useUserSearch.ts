import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { queryKeys } from "../query/queryKeys";
import { userService } from "../services/userService";
import type { UserRole } from "../types/users";

//: Mirrors the backend's own minimum (`GET /users/search`'s `q` field,
//: `min_length=2`) -- querying below it would just 422 on every keystroke.
const MIN_QUERY_LENGTH = 2;
const DEBOUNCE_MS = 300;

export function useUserSearch(unitId = "", role: UserRole | "" = "") {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [query]);

  const enabled = debouncedQuery.length >= MIN_QUERY_LENGTH;
  const searchQuery = useQuery({
    queryKey: queryKeys.userSearch(debouncedQuery, unitId, role),
    queryFn: () => userService.search({ q: debouncedQuery, unitId: unitId || undefined, role: role || undefined }),
    enabled,
    staleTime: 15_000,
  });

  return {
    query,
    setQuery,
    isSearching: query.trim().length > 0 && query.trim().length < MIN_QUERY_LENGTH,
    results: enabled ? searchQuery.data?.items ?? [] : [],
    loading: enabled && searchQuery.isLoading,
    error: searchQuery.error instanceof Error ? searchQuery.error.message : null,
    minLength: MIN_QUERY_LENGTH,
  };
}
