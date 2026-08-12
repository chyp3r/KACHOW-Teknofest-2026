export interface RoutingSuggestionRequest {
  draft: string;
  confidence_score?: number;
  document_type?: string;
}

export interface RoutingSuggestion {
  routed_unit: string;
  priority: string;
  reasoning: string;
  justification: string;
}
