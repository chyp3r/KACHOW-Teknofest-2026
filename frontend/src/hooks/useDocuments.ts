import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { documentService } from "../services/documentService";
import { graphService } from "../services/graphService";
import type { DocumentAnalysis, DocumentMetadata, DocumentText, EvrakFields } from "../types/documents";

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
  const documentGraphQuery = useQuery({
    queryKey: queryKeys.documentGraph(selectedDocument?.storage_path ?? ""),
    queryFn: () => graphService.documentGraph(selectedDocument!.storage_path),
    enabled: Boolean(selectedDocument),
    staleTime: 60_000,
  });
  const textQuery = useQuery({
    queryKey: queryKeys.documentText(selectedDocument?.storage_path ?? ""),
    queryFn: () => documentService.getText(selectedDocument!.storage_path),
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
  const updateFieldsMutation = useMutation({
    mutationFn: ({ storagePath, fields }: { storagePath: string; fields: EvrakFields }) =>
      documentService.updateFields(storagePath, fields),
    onSuccess: (analysis) => {
      queryClient.setQueryData<DocumentMetadata[]>(queryKeys.documents(), (current = []) =>
        (current ?? []).map((item) =>
          item.storage_path === analysis.storage_path
            ? { ...item, compliance_status: analysis.compliance_status, summary: analysis.summary }
            : item,
        ),
      );
      queryClient.setQueryData(queryKeys.documentAnalysis(analysis.storage_path), analysis);
      setSelectedDocument((current) =>
        current && current.storage_path === analysis.storage_path
          ? { ...current, compliance_status: analysis.compliance_status }
          : current,
      );
    },
  });
  const detailedSummaryMutation = useMutation({
    mutationFn: (storagePath: string) => documentService.generateDetailedSummary(storagePath),
    onSuccess: (analysis) => {
      // No documents-list update, unlike updateFieldsMutation above --
      // detailed_summary is a detail-panel-only field, never shown in the
      // row preview (DocumentTable/DocumentListItem read `summary`, not
      // this), so the list cache has nothing to change.
      queryClient.setQueryData(queryKeys.documentAnalysis(analysis.storage_path), analysis);
    },
  });
  const updateTextMutation = useMutation({
    mutationFn: ({ storagePath, pages }: { storagePath: string; pages: string[] }) =>
      documentService.updateText(storagePath, pages),
    onSuccess: (analysis, variables) => {
      // The client already knows the exact pages it just sent -- no need to
      // refetch documentText, just write it straight into the cache the
      // same way uploadMutation seeds documentAnalysis above.
      queryClient.setQueryData<DocumentText>(
        queryKeys.documentText(variables.storagePath),
        (current) =>
          current
            ? {
                ...current,
                pages: variables.pages,
                extracted_text: variables.pages.join("\n\n"),
              }
            : current,
      );
      queryClient.setQueryData<DocumentMetadata[]>(queryKeys.documents(), (current = []) =>
        current.map((item) =>
          item.storage_path === analysis.storage_path
            ? { ...item, compliance_status: analysis.compliance_status, summary: analysis.summary }
            : item,
        ),
      );
      queryClient.setQueryData(queryKeys.documentAnalysis(analysis.storage_path), analysis);
    },
  });
  const reextractTextMutation = useMutation({
    mutationFn: (storagePath: string) => documentService.reextractText(storagePath),
    onSuccess: (analysis) => {
      // Unlike updateTextMutation, the client has no idea what the vision
      // model actually transcribed -- documentText must be refetched, not
      // guessed at.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documentText(analysis.storage_path),
      });
      queryClient.setQueryData<DocumentMetadata[]>(queryKeys.documents(), (current = []) =>
        current.map((item) =>
          item.storage_path === analysis.storage_path
            ? { ...item, compliance_status: analysis.compliance_status, summary: analysis.summary }
            : item,
        ),
      );
      queryClient.setQueryData(queryKeys.documentAnalysis(analysis.storage_path), analysis);
    },
  });
  const removeMutation = useMutation({
    mutationFn: (storagePath: string) => documentService.remove(storagePath),
    onSuccess: (_result, storagePath) => {
      queryClient.setQueryData<DocumentMetadata[]>(queryKeys.documents(), (current = []) =>
        current.filter((item) => item.storage_path !== storagePath),
      );
      queryClient.removeQueries({ queryKey: queryKeys.documentAnalysis(storagePath) });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
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
    // undefined (query not yet enabled/no document selected) is preserved
    // as-is -- DocumentAnalysisPanel's documentGraph prop treats undefined
    // as "not wired" and null as "wired, no data yet" (see its own
    // docstring), so collapsing this to `?? null` would hide the section
    // entirely whenever a document is selected but its graph hasn't loaded.
    documentGraph: documentGraphQuery.data ?? (selectedDocument ? null : undefined),
    loadingDocumentGraph: documentGraphQuery.isLoading,
    documentText: textQuery.data ?? null,
    loading: documentsQuery.isLoading || analysisQuery.isLoading,
    refreshing: documentsQuery.isFetching && !documentsQuery.isLoading,
    uploading: uploadMutation.isPending,
    updatingFields: updateFieldsMutation.isPending,
    generatingDetailedSummary: detailedSummaryMutation.isPending,
    savingText: updateTextMutation.isPending,
    reextracting: reextractTextMutation.isPending,
    deleting: removeMutation.isPending,
    error: error instanceof Error ? error.message : null,
    refresh: async () => {
      await documentsQuery.refetch();
    },
    upload: async (file: File) => {
      await uploadMutation.mutateAsync(file);
    },
    updateFields: async (storagePath: string, fields: EvrakFields) => {
      await updateFieldsMutation.mutateAsync({ storagePath, fields });
    },
    generateDetailedSummary: async (storagePath: string) => {
      await detailedSummaryMutation.mutateAsync(storagePath);
    },
    saveText: async (storagePath: string, pages: string[]) => {
      await updateTextMutation.mutateAsync({ storagePath, pages });
    },
    reextractText: async (storagePath: string) => {
      await reextractTextMutation.mutateAsync(storagePath);
    },
    deleteDocument: async (storagePath: string) => {
      await removeMutation.mutateAsync(storagePath);
    },
  };
}
