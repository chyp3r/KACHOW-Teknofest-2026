import { apiRequest } from "./apiClient";
import type { RoutingSuggestion, RoutingSuggestionRequest } from "../types/routing";

export const routingService = {
  suggest: (request: RoutingSuggestionRequest) =>
    apiRequest<RoutingSuggestion>("/api/v1/routing/suggest", {
      method: "POST",
      body: JSON.stringify(request),
    }),
};
