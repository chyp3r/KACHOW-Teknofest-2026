import { useCallback, useState } from "react";
import type { DocumentMetadata, DraftResult } from "../types/documents";

const MAX_DRAFT_HISTORY = 20;

export interface DraftHistoryEntry {
  id: string;
  createdAt: string;
  source: DocumentMetadata;
  result: DraftResult;
}

function historyKey(userId: string): string {
  return `kachow.drafts.${userId}`;
}

function readHistory(key: string): DraftHistoryEntry[] {
  try {
    const stored = JSON.parse(localStorage.getItem(key) ?? "[]") as unknown;
    if (!Array.isArray(stored)) return [];
    return stored
      .filter(
        (entry): entry is DraftHistoryEntry =>
          typeof entry === "object" &&
          entry !== null &&
          "id" in entry &&
          typeof entry.id === "string" &&
          "createdAt" in entry &&
          typeof entry.createdAt === "string" &&
          "source" in entry &&
          "result" in entry,
      )
      .slice(0, MAX_DRAFT_HISTORY);
  } catch {
    return [];
  }
}

export function useDraftHistory(userId: string) {
  const storageKey = historyKey(userId);
  const [entries, setEntries] = useState<DraftHistoryEntry[]>(() =>
    readHistory(storageKey),
  );

  const addDraft = useCallback(
    (result: DraftResult, source: DocumentMetadata): DraftHistoryEntry => {
      const entry: DraftHistoryEntry = {
        id: result.draft_id || crypto.randomUUID(),
        createdAt: new Date().toISOString(),
        source,
        result,
      };
      setEntries((current) => {
        const next = [
          entry,
          ...current.filter((item) => item.id !== entry.id),
        ].slice(0, MAX_DRAFT_HISTORY);
        try {
          localStorage.setItem(storageKey, JSON.stringify(next));
        } catch {
          /* Keep the in-memory history when browser storage is unavailable. */
        }
        return next;
      });
      return entry;
    },
    [storageKey],
  );

  return { entries, addDraft };
}
