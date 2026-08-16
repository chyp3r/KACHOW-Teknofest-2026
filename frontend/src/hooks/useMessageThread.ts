import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { queryKeys } from "../query/queryKeys";
import { messagingService } from "../services/messagingService";
import type { Message } from "../types/messaging";

const PAGE_SIZE = 50;

export function useMessageThread(conversationId: string | null) {
  const queryClient = useQueryClient();
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasMore, setHasMore] = useState(true);

  const messagesQuery = useQuery({
    queryKey: queryKeys.conversationMessages(conversationId ?? ""),
    // The backend returns newest-first; reversed here so the thread renders
    // top-to-bottom like every other chronological list in this app.
    queryFn: async () => {
      const page = await messagingService.messages(conversationId!, undefined, PAGE_SIZE);
      setHasMore(page.length === PAGE_SIZE);
      return [...page].reverse();
    },
    enabled: Boolean(conversationId),
    staleTime: 10_000,
  });

  const loadOlder = async () => {
    if (!conversationId || loadingOlder || !hasMore) return;
    const current = queryClient.getQueryData<Message[]>(queryKeys.conversationMessages(conversationId)) ?? [];
    const oldest = current[0];
    if (!oldest) return;
    setLoadingOlder(true);
    try {
      const older = await messagingService.messages(conversationId, oldest.id, PAGE_SIZE);
      setHasMore(older.length === PAGE_SIZE);
      if (older.length > 0) {
        queryClient.setQueryData<Message[]>(queryKeys.conversationMessages(conversationId), (existing = []) => [
          ...[...older].reverse(),
          ...existing,
        ]);
      }
    } finally {
      setLoadingOlder(false);
    }
  };

  const sendMutation = useMutation({
    mutationFn: (body: string) => messagingService.sendMessage(conversationId!, body),
    onSuccess: (message) => {
      queryClient.setQueryData<Message[]>(queryKeys.conversationMessages(message.conversation_id), (existing = []) => [
        ...existing,
        message,
      ]);
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
    },
  });

  const markReadMutation = useMutation({
    mutationFn: () => messagingService.markRead(conversationId!),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
  });

  return {
    messages: messagesQuery.data ?? [],
    loading: messagesQuery.isLoading,
    loadingOlder,
    hasMore,
    error: messagesQuery.error instanceof Error ? messagesQuery.error.message : null,
    errorObject: messagesQuery.error ?? sendMutation.error,
    loadOlder,
    send: (body: string) => sendMutation.mutateAsync(body),
    sending: sendMutation.isPending,
    markRead: () => markReadMutation.mutateAsync(),
  };
}
