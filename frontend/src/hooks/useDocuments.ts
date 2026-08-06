import { useCallback, useEffect, useState } from "react";
import { documentService } from "../services/documentService";
import type { DocumentAnalysis, DocumentMetadata } from "../types/documents";

export function useDocuments(
  onUploaded?: (analysis: DocumentAnalysis) => void,
) {
  const [documents, setDocuments] = useState<DocumentMetadata[]>([]);
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
      setDocuments(await documentService.list());
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
    if (!selectedDocument) {
      setAnalysis(null);
      return;
    }
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
        setSelectedDocument(result);
        setAnalysis(result);
        await refresh();
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
    [onUploaded, refresh],
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
