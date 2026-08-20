import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../query/queryKeys";
import { messagingService } from "../services/messagingService";
import { collectPages } from "../services/pagination";
import type { Conversation } from "../types/messaging";

function upsertConversation(current: Conversation[] | undefined, updated: Conversation): Conversation[] {
  const withoutUpdated = (current ?? []).filter((item) => item.id !== updated.id);
  return [updated, ...withoutUpdated].sort((left, right) => {
    const leftTime = left.last_message_at ? new Date(left.last_message_at).getTime() : 0;
    const rightTime = right.last_message_at ? new Date(right.last_message_at).getTime() : 0;
    return rightTime - leftTime;
  });
}

export function useConversations(enabled = true) {
  const queryClient = useQueryClient();
  const listQuery = useQuery({
    queryKey: queryKeys.conversations,
    queryFn: () => collectPages((page) => messagingService.conversations(page)),
    staleTime: 15_000,
    enabled,
  });

  const setList = (updater: (current: Conversation[] | undefined) => Conversation[]) => {
    queryClient.setQueryData<{ items: Conversation[]; total: number; page: number; size: number; pages: number }>(
      queryKeys.conversations,
      (current) => {
        if (!current) return current;
        const items = updater(current.items);
        return { ...current, items, total: items.length };
      },
    );
  };

  const openDmMutation = useMutation({
    mutationFn: (participantId: string) => messagingService.openDm(participantId),
    onSuccess: (conversation) => setList((current) => upsertConversation(current, conversation)),
  });

  const createGroupMutation = useMutation({
    mutationFn: ({ title, participantIds }: { title: string; participantIds: string[] }) =>
      messagingService.createGroup(title, participantIds),
    onSuccess: (conversation) => setList((current) => upsertConversation(current, conversation)),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      conversationId,
      changes,
    }: {
      conversationId: string;
      changes: { title?: string; is_archived?: boolean };
    }) => messagingService.updateConversation(conversationId, changes),
    onSuccess: (conversation) => setList((current) => upsertConversation(current, conversation)),
  });

  const addParticipantsMutation = useMutation({
    mutationFn: ({ conversationId, userIds }: { conversationId: string; userIds: string[] }) =>
      messagingService.addParticipants(conversationId, userIds),
    onSuccess: (_result, { conversationId }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
      return messagingService.conversation(conversationId).then((conversation) =>
        setList((current) => upsertConversation(current, conversation)),
      );
    },
  });

  const removeParticipantMutation = useMutation({
    mutationFn: ({ conversationId, userId }: { conversationId: string; userId: string }) =>
      messagingService.removeParticipant(conversationId, userId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
  });

  const conversations = listQuery.data?.items ?? [];
  const unreadTotal = conversations.reduce((sum, item) => sum + item.unread_count, 0);

  return {
    conversations,
    unreadTotal,
    loading: listQuery.isLoading,
    refreshing: listQuery.isFetching && !listQuery.isLoading,
    error: listQuery.error instanceof Error ? listQuery.error.message : null,
    errorObject: listQuery.error,
    refresh: () => listQuery.refetch(),
    openDm: (participantId: string) => openDmMutation.mutateAsync(participantId),
    openingDm: openDmMutation.isPending,
    createGroup: (title: string, participantIds: string[]) =>
      createGroupMutation.mutateAsync({ title, participantIds }),
    creatingGroup: createGroupMutation.isPending,
    updateConversation: (conversationId: string, changes: { title?: string; is_archived?: boolean }) =>
      updateMutation.mutateAsync({ conversationId, changes }),
    addParticipants: (conversationId: string, userIds: string[]) =>
      addParticipantsMutation.mutateAsync({ conversationId, userIds }),
    addingParticipants: addParticipantsMutation.isPending,
    removeParticipant: (conversationId: string, userId: string) =>
      removeParticipantMutation.mutateAsync({ conversationId, userId }),
    removingParticipant: removeParticipantMutation.isPending,
  };
}
