import { useCallback, useEffect, useState } from "react";

export type AppRoute =
  | "/chats"
  | "/drafts"
  | "/documents"
  | "/admin"
  | "/login";
const ROUTES = new Set<AppRoute>([
  "/chats",
  "/drafts",
  "/documents",
  "/admin",
  "/login",
]);

function currentRoute(): AppRoute {
  return ROUTES.has(window.location.pathname as AppRoute)
    ? (window.location.pathname as AppRoute)
    : "/chats";
}

export function useAppRoute() {
  const [route, setRoute] = useState<AppRoute>(currentRoute);
  useEffect(() => {
    if (!ROUTES.has(window.location.pathname as AppRoute))
      window.history.replaceState({}, "", "/chats");
    const onPopState = () => setRoute(currentRoute());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  const navigate = useCallback((next: AppRoute) => {
    if (window.location.pathname !== next)
      window.history.pushState({}, "", next);
    setRoute(next);
  }, []);
  return { route, navigate };
}
