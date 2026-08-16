import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { queryKeys } from "../query/queryKeys";
import { messagingService } from "../services/messagingService";
import { subscribeToRawStream } from "../services/sse";
import type { Message } from "../types/messaging";

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
    const unsubscribe = subscribeToRawStream(messagingService.streamPath, (value) => {
      if (!isMessage(value)) return;
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
    });
    return unsubscribe;
  }, [enabled, queryClient]);
}
