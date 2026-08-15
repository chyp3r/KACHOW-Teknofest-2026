import { useCallback, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { feedbackService } from "../services/feedbackService";
import type { FeedbackSignal, FeedbackTargetKind, FeedbackVoteRequest } from "../types/feedback";

// Keyed by target kind + the rated text itself, mirroring the backend's own
// vote identity (`content_hash`, see FeedbackModel's docstring) rather than
// a message id -- a freshly streamed chat reply has no durable id yet
// (chat_recorder persists it asynchronously after the turn), so keying on
// text is the one identity available immediately, both here and server-side.
function voteKey(targetKind: FeedbackTargetKind, content: string): string {
  return `${targetKind}::${content}`;
}

export interface CastVoteParams {
  targetKind: FeedbackTargetKind;
  content: string;
  signal: FeedbackSignal;
  comment?: string;
  dimensions?: Record<string, boolean>;
  sessionId?: string;
  messageId?: string;
  draftId?: string;
  context?: Record<string, unknown>;
}

export function useFeedback() {
  // Local, session-only cache of "what did I just vote" -- there is no
  // GET endpoint for "my votes on these specific in-flight messages" (and
  // building one would be over-engineering for what is otherwise a plain
  // optimistic click state), so this resets on reload. The server-side
  // `feedback` table remains the durable record either way.
  const [votes, setVotes] = useState<Record<string, { id: string; signal: FeedbackSignal }>>({});

  const submitMutation = useMutation({
    mutationFn: (request: FeedbackVoteRequest) => feedbackService.submit(request),
  });
  const removeMutation = useMutation({
    mutationFn: (feedbackId: string) => feedbackService.remove(feedbackId),
  });

  const vote = useCallback(
    async (params: CastVoteParams) => {
      const key = voteKey(params.targetKind, params.content);
      const entry = await submitMutation.mutateAsync({
        target_kind: params.targetKind,
        signal: params.signal,
        content: params.content,
        comment: params.comment,
        dimensions: params.dimensions,
        session_id: params.sessionId,
        message_id: params.messageId,
        draft_id: params.draftId,
        context: params.context,
      });
      setVotes((previous) => ({ ...previous, [key]: { id: entry.id, signal: entry.signal } }));
      return entry;
    },
    [submitMutation],
  );

  const withdraw = useCallback(
    async (targetKind: FeedbackTargetKind, content: string) => {
      const key = voteKey(targetKind, content);
      const existing = votes[key];
      if (!existing) return;
      await removeMutation.mutateAsync(existing.id);
      setVotes((previous) => {
        const next = { ...previous };
        delete next[key];
        return next;
      });
    },
    [removeMutation, votes],
  );

  const voteFor = useCallback(
    (targetKind: FeedbackTargetKind, content: string): FeedbackSignal | null =>
      votes[voteKey(targetKind, content)]?.signal ?? null,
    [votes],
  );

  const isPending = submitMutation.isPending || removeMutation.isPending;

  return { vote, withdraw, voteFor, isPending };
}
