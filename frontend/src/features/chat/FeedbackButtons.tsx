import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { Button, IconButton } from "../../components/Button";
import { Textarea } from "../../components/FormControls";
import { FormActions } from "../../components/LayoutPrimitives";
import { useFeedback } from "../../hooks/useFeedback";
import type { FeedbackTargetKind } from "../../types/feedback";

// 👍/👎 on one piece of AI-generated output -- the one write path in the
// RLHF-style data-collection layer (Faz C1) every user reaches, not just
// admins. Clicking an already-active vote withdraws it; clicking 👎 opens
// an optional comment box first (what's on screen is often obvious from
// the vote alone, the comment is for *why*) rather than submitting blind.
export function FeedbackButtons({
  targetKind,
  content,
  sessionId,
  messageId,
  draftId,
  context,
}: {
  targetKind: FeedbackTargetKind;
  content: string;
  sessionId?: string;
  messageId?: string;
  draftId?: string;
  context?: Record<string, unknown>;
}) {
  const { vote, withdraw, voteFor, isPending } = useFeedback();
  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState("");
  // A failed vote must never surface as an unhandled promise rejection --
  // every async trigger below catches into this instead, so a network
  // hiccup reads as "oy gönderilemedi," not a crash the console screams
  // about with no visible UI change at all.
  const [error, setError] = useState<string | null>(null);
  const current = voteFor(targetKind, content);

  const castVote = (signal: "like" | "dislike", withComment?: string) =>
    vote({
      targetKind,
      content,
      signal,
      comment: withComment,
      sessionId,
      messageId,
      draftId,
      context,
    });

  const handleLike = () => {
    setError(null);
    const action =
      current === "like" ? withdraw(targetKind, content) : castVote("like");
    if (current !== "like") setCommentOpen(false);
    action.catch(() => setError("Oy gönderilemedi. Lütfen tekrar deneyin."));
  };

  const handleDislikeClick = () => {
    if (current === "dislike") {
      setError(null);
      withdraw(targetKind, content).catch(() =>
        setError("Oy gönderilemedi. Lütfen tekrar deneyin."),
      );
      return;
    }
    setError(null);
    setCommentOpen(true);
  };

  const submitDislike = async () => {
    setError(null);
    try {
      await castVote("dislike", comment.trim() || undefined);
      setCommentOpen(false);
    } catch {
      setError("Oy gönderilemedi. Lütfen tekrar deneyin.");
    }
  };

  return (
    <div className="feedback-buttons">
      <div className="feedback-buttons-row">
        <IconButton
          icon={<ThumbsUp size={15} />}
          aria-label="Beğendim"
          aria-pressed={current === "like"}
          className={current === "like" ? "is-active" : ""}
          disabled={isPending}
          onClick={handleLike}
        />
        <IconButton
          icon={<ThumbsDown size={15} />}
          aria-label="Beğenmedim"
          aria-pressed={current === "dislike"}
          className={current === "dislike" ? "is-active" : ""}
          disabled={isPending}
          onClick={handleDislikeClick}
        />
      </div>
      {error && <p className="feedback-error">{error}</p>}
      {commentOpen && (
        <div className="feedback-comment-box">
          <Textarea
            label="Ne iyileştirilebilir? (opsiyonel)"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder="Örn. Üslup çok resmi değil, dayanak eksik…"
          />
          <FormActions>
            <Button variant="secondary" size="sm" disabled={isPending} onClick={() => setCommentOpen(false)}>
              Vazgeç
            </Button>
            <Button size="sm" disabled={isPending} onClick={() => void submitDislike()}>
              Gönder
            </Button>
          </FormActions>
        </div>
      )}
    </div>
  );
}
