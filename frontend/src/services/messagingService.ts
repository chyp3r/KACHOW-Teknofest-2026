import { apiRequest } from "./apiClient";
import type { PaginatedResponse } from "../types/api";
import type { Conversation, Message, Participant } from "../types/messaging";

export const messagingService = {
  conversations: (page = 1, size = 50) =>
    apiRequest<PaginatedResponse<Conversation>>(
      `/api/v1/messaging/conversations?page=${page}&size=${size}`,
    ),
  conversation: (conversationId: string) =>
    apiRequest<Conversation>(
      `/api/v1/messaging/conversations/${encodeURIComponent(conversationId)}`,
    ),
  openDm: (participantId: string) =>
    apiRequest<Conversation>("/api/v1/messaging/conversations", {
      method: "POST",
      body: JSON.stringify({ kind: "dm", participant_id: participantId }),
    }),
  createGroup: (title: string, participantIds: string[]) =>
    apiRequest<Conversation>("/api/v1/messaging/conversations", {
      method: "POST",
      body: JSON.stringify({ kind: "group", title, participant_ids: participantIds }),
    }),
  updateConversation: (
    conversationId: string,
    changes: { title?: string; is_archived?: boolean },
  ) =>
    apiRequest<Conversation>(
      `/api/v1/messaging/conversations/${encodeURIComponent(conversationId)}`,
      { method: "PATCH", body: JSON.stringify(changes) },
    ),
  addParticipants: (conversationId: string, userIds: string[]) =>
    apiRequest<Participant[]>(
      `/api/v1/messaging/conversations/${encodeURIComponent(conversationId)}/participants`,
      { method: "POST", body: JSON.stringify({ user_ids: userIds }) },
    ),
  removeParticipant: (conversationId: string, userId: string) =>
    apiRequest<{ removed: boolean }>(
      `/api/v1/messaging/conversations/${encodeURIComponent(conversationId)}/participants/${encodeURIComponent(userId)}`,
      { method: "DELETE" },
    ),
  messages: (conversationId: string, beforeId?: string, limit = 50) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (beforeId) params.set("before_id", beforeId);
    return apiRequest<Message[]>(
      `/api/v1/messaging/conversations/${encodeURIComponent(conversationId)}/messages?${params.toString()}`,
    );
  },
  sendMessage: (conversationId: string, body: string) =>
    apiRequest<Message>(
      `/api/v1/messaging/conversations/${encodeURIComponent(conversationId)}/messages`,
      { method: "POST", body: JSON.stringify({ body }) },
    ),
  markRead: (conversationId: string, messageId?: string) =>
    apiRequest<{ last_read_message_id: string | null }>(
      `/api/v1/messaging/conversations/${encodeURIComponent(conversationId)}/read`,
      { method: "POST", body: JSON.stringify({ message_id: messageId ?? null }) },
    ),
  streamPath: "/api/v1/messaging/stream",
};
