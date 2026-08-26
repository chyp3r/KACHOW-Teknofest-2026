import type { components } from "../api/generated";

export type RoutingDocumentType = components["schemas"]["DocumentType"];

const ROUTING_DOCUMENT_TYPES: readonly RoutingDocumentType[] = [
  "official_letter",
  "petition",
  "information_request",
  "complaint",
  "circular",
  "directive",
  "report",
  "minutes",
  "leave_request",
  "other",
];

export function isRoutingDocumentType(
  value: string | null | undefined,
): value is RoutingDocumentType {
  return Boolean(value && ROUTING_DOCUMENT_TYPES.includes(value as RoutingDocumentType));
}

export interface RoutingSuggestionRequest {
  draft: string;
  confidence_score?: number;
  document_type?: RoutingDocumentType;
}

export interface RoutingSuggestion {
  routed_unit: string;
  priority: string;
  reasoning: string;
  justification: string;
}
