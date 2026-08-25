import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { queryKeys } from "../query/queryKeys";
import { messagingService } from "../services/messagingService";
import { subscribeToRawStream } from "../services/sse";
import type { PaginatedResponse } from "../types/api";
import type { Conversation, Message } from "../types/messaging";

const NEW_CONVERSATION_REFRESH_DELAY_MS = 750;

function isMessage(value: unknown): value is Message {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return typeof record.id === "string" && typeof record.conversation_id === "string";
}

/**
 * Keeps every open message thread and the conversation list live via
 * `GET /messaging/stream`. Mounted once, at the top of the authenticated
 * app (see `AppShell`) -- not per-thread -- so a message arriving for a
 * conversation the user isn't currently looking at still updates its
 * `unread_count` in the sidebar.
 */
export function useMessagingStream(enabled: boolean): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return undefined;
    const seenMessageIds = new Set<string>();
    const refreshTimers = new Set<number>();
    const unsubscribe = subscribeToRawStream(messagingService.streamPath, (value) => {
      if (!isMessage(value)) return;
      if (seenMessageIds.has(value.id)) return;
      seenMessageIds.add(value.id);
      if (seenMessageIds.size > 500) {
        seenMessageIds.delete(seenMessageIds.values().next().value as string);
      }

      const key = queryKeys.conversationMessages(value.conversation_id);
      // Only append into a thread the user has already loaded -- an
      // unopened conversation's message cache doesn't exist yet, and
      // `loadOlder`'s own keyset pagination will pick this row up
      // naturally the first time that thread is opened.
      if (queryClient.getQueryData<Message[]>(key)) {
        queryClient.setQueryData<Message[]>(key, (existing = []) =>
          existing.some((item) => item.id === value.id) ? existing : [...existing, value],
        );
      }

      const conversations = queryClient.getQueryData<PaginatedResponse<Conversation>>(
        queryKeys.conversations,
      );
      const knownConversation = conversations?.items.some(
        (item) => item.id === value.conversation_id,
      );
      if (knownConversation) {
        // The SSE event is published just before the sender's request-scoped
        // transaction commits. Refetching here can therefore read the old
        // unread count and leave the sidebar stale until /messages mounts.
        // This recipient-only event represents exactly one unread message,
        // so update the already-loaded sidebar cache directly instead.
        queryClient.setQueryData<PaginatedResponse<Conversation>>(
          queryKeys.conversations,
          (current) => {
            if (!current) return current;
            const updated = current.items.find(
              (item) => item.id === value.conversation_id,
            );
            if (!updated) return current;
            return {
              ...current,
              items: [
                {
                  ...updated,
                  unread_count: updated.unread_count + 1,
                  last_message_at: value.created_at,
                },
                ...current.items.filter((item) => item.id !== value.conversation_id),
              ],
            };
          },
        );
        return;
      }

      // A newly-created DM/group is not in the current cache yet. Wait until
      // the sender transaction has committed before fetching that new row.
      const timer = window.setTimeout(() => {
        refreshTimers.delete(timer);
        void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
      }, NEW_CONVERSATION_REFRESH_DELAY_MS);
      refreshTimers.add(timer);
    });
    return () => {
      unsubscribe();
      refreshTimers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [enabled, queryClient]);
}
