import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { documentService } from "../services/documentService";
import type { DocumentAnalysis, DocumentMetadata } from "../types/documents";

export function useDocuments(
  _userId: string,
  onUploaded?: (analysis: DocumentAnalysis) => void,
) {
  const queryClient = useQueryClient();
  const [selectedDocument, setSelectedDocument] =
    useState<DocumentMetadata | null>(null);
  const documentsQuery = useQuery({
    queryKey: queryKeys.documents(),
    queryFn: () => documentService.list(),
    staleTime: 30_000,
  });
  const analysisQuery = useQuery({
    queryKey: queryKeys.documentAnalysis(selectedDocument?.storage_path ?? ""),
    queryFn: () => documentService.getAnalysis(selectedDocument!.storage_path),
    enabled: Boolean(selectedDocument),
    staleTime: 60_000,
  });
  const uploadMutation = useMutation({
    mutationFn: (file: File) => documentService.analyze(file),
    onSuccess: (analysis) => {
      queryClient.setQueryData<DocumentMetadata[]>(queryKeys.documents(), (current = []) => [
        analysis,
        ...current.filter((item) => item.storage_path !== analysis.storage_path),
      ]);
      queryClient.setQueryData(
        queryKeys.documentAnalysis(analysis.storage_path),
        analysis,
      );
      setSelectedDocument(analysis);
      onUploaded?.(analysis);
    },
  });

  useEffect(() => {
    if (
      selectedDocument &&
      documentsQuery.data &&
      !documentsQuery.data.some(
        (document) => document.storage_path === selectedDocument.storage_path,
      )
    ) {
      setSelectedDocument(null);
    }
  }, [documentsQuery.data, selectedDocument]);

  const error =
    uploadMutation.error ?? analysisQuery.error ?? documentsQuery.error;

  return {
    documents: documentsQuery.data ?? [],
    selectedDocument,
    setSelectedDocument,
    analysis: analysisQuery.data ?? null,
    loading: documentsQuery.isLoading || analysisQuery.isLoading,
    refreshing: documentsQuery.isFetching && !documentsQuery.isLoading,
    uploading: uploadMutation.isPending,
    error: error instanceof Error ? error.message : null,
    refresh: async () => {
      await documentsQuery.refetch();
    },
    upload: async (file: File) => {
      await uploadMutation.mutateAsync(file);
    },
  };
}
