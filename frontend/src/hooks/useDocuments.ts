import { useCallback, useEffect, useState } from "react";
import { documentService } from "../services/documentService";
import type { DocumentAnalysis, DocumentMetadata } from "../types/documents";

const MAX_CACHED_DOCUMENTS = 50;

function documentCacheKey(userId: string): string {
  return `kachow.documents.${userId}`;
}

function readCachedDocuments(key: string): DocumentMetadata[] {
  try {
    const stored = JSON.parse(localStorage.getItem(key) ?? "[]") as unknown;
    if (!Array.isArray(stored)) return [];
    return stored
      .filter(
        (item): item is DocumentMetadata =>
          typeof item === "object" &&
          item !== null &&
          "storage_path" in item &&
          typeof item.storage_path === "string" &&
          "file_name" in item &&
          typeof item.file_name === "string",
      )
      .slice(0, MAX_CACHED_DOCUMENTS);
  } catch {
    return [];
  }
}

function mergeDocuments(
  preferred: DocumentMetadata[],
  fallback: DocumentMetadata[],
): DocumentMetadata[] {
  const seen = new Set<string>();
  return [...preferred, ...fallback]
    .filter((document) => {
      if (seen.has(document.storage_path)) return false;
      seen.add(document.storage_path);
      return true;
    })
    .slice(0, MAX_CACHED_DOCUMENTS);
}

export function useDocuments(
  userId: string,
  onUploaded?: (analysis: DocumentAnalysis) => void,
) {
  const storageKey = documentCacheKey(userId);
  const [documents, setDocuments] = useState<DocumentMetadata[]>(() =>
    readCachedDocuments(storageKey),
  );
  const [selectedDocument, setSelectedDocument] =
    useState<DocumentMetadata | null>(null);
  const [analysis, setAnalysis] = useState<DocumentAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const remoteDocuments = await documentService.list();
      setDocuments((cachedDocuments) =>
        mergeDocuments(remoteDocuments, cachedDocuments),
      );
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Evraklar yüklenemedi.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(documents));
    } catch {
      /* The live state remains usable when browser storage is unavailable. */
    }
  }, [documents, storageKey]);
  useEffect(() => {
    if (!selectedDocument) {
      setAnalysis(null);
      return;
    }
    setAnalysis(null);
    setError(null);
    let active = true;
    documentService
      .getAnalysis(selectedDocument.storage_path)
      .then((result) => active && setAnalysis(result))
      .catch(
        (caught) =>
          active &&
          setError(
            caught instanceof Error
              ? caught.message
              : "Evrak analizi yüklenemedi.",
          ),
      );
    return () => {
      active = false;
    };
  }, [selectedDocument]);

  const upload = useCallback(
    async (file: File) => {
      setUploading(true);
      setError(null);
      try {
        const result = await documentService.analyze(file);
        setDocuments((current) => mergeDocuments([result], current));
        setSelectedDocument(result);
        setAnalysis(result);
        setError(null);
        onUploaded?.(result);
      } catch (caught) {
        setError(
          caught instanceof Error ? caught.message : "Evrak yüklenemedi.",
        );
        throw caught;
      } finally {
        setUploading(false);
      }
    },
    [onUploaded],
  );

  return {
    documents,
    selectedDocument,
    setSelectedDocument,
    analysis,
    loading,
    uploading,
    error,
    refresh,
    upload,
  };
}
