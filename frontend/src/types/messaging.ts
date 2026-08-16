//: Mirrors the backend's `MESSAGE_BODY_MAX_LENGTH`
//: (`app.domains.messaging.schema.message_schema`).
export const MESSAGE_BODY_MAX_LENGTH = 4000;

export type ConversationKind = "dm" | "group";
export type MessageKind = "text" | "artifact" | "system";
export type ParticipantRole = "owner" | "member";

export interface Participant {
  user_id: string;
  username: string;
  role_in_conversation: ParticipantRole;
  joined_at: string;
  left_at: string | null;
}

export interface Conversation {
  id: string;
  kind: ConversationKind;
  title: string | null;
  last_message_at: string | null;
  is_archived: boolean;
  created_at: string;
  participants: Participant[];
  unread_count: number;
  role_in_conversation: ParticipantRole;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string | null;
  sender_username: string | null;
  kind: MessageKind;
  body: string;
  artifact_transfer_id: string | null;
  created_at: string;
}
