import { AlertCircle, AlertTriangle, CheckCircle2, ChevronDown, FileText, History } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { ConflictFinding, InterruptState } from "../../types/chat";
import { Button } from "../../components/Button";
import { Textarea } from "../../components/FormControls";
import { FormActions } from "../../components/LayoutPrimitives";
import { PromptQuestionCard, type PromptAnswers } from "./PromptQuestionCard";

const SEVERITY_LABEL: Record<ConflictFinding["severity"], string> = {
  critical: "Kritik",
  major: "Önemli",
  minor: "Küçük",
};

export function InterruptPanel({
  interrupt,
  loading,
  onResume,
}: {
  interrupt: InterruptState;
  loading: boolean;
  onResume: (
    action: "answer" | "approve" | "revise" | "reject",
    answers: PromptAnswers,
    instructions: string,
    reason?: string,
  ) => Promise<void>;
}) {
  const [instructions, setInstructions] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const questions = Array.isArray(interrupt.payload.questions)
    ? interrupt.payload.questions
    : [];
  const isMissingInformation = interrupt.kind === "missing_information";
  const isWritingBrief = interrupt.kind === "writing_brief";
  const autoValue = interrupt.payload.auto_value ?? "__auto__";

  const conflicts = Array.isArray(interrupt.payload.conflicts)
    ? interrupt.payload.conflicts
    : [];
  const changelog = interrupt.payload.changelog;
  const changelogEntries = Array.isArray(changelog?.entries) ? changelog.entries : [];
  const revisionRound = interrupt.payload.revision_round;
  const maxRevisionRounds = interrupt.payload.max_revision_rounds;
  const revisionExhausted = interrupt.payload.revision_exhausted ?? false;
  const combinedScore = interrupt.payload.combined_score;
  const requiresApproval = interrupt.payload.requires_human_approval;
  const evaluationNotes =
    typeof interrupt.payload.verification?.evaluation_notes === "string"
      ? interrupt.payload.verification.evaluation_notes
      : "";

  const submitReject = (event: FormEvent) => {
    event.preventDefault();
    if (!rejectReason.trim() || loading) return;
    void onResume("reject", {}, "", rejectReason.trim());
  };

  const acceptAllDefaults = () => {
    if (loading) return;
    const answers: PromptAnswers = {};
    for (const question of questions) answers[question.key] = autoValue;
    void onResume("answer", answers, "");
  };

  return (
    <section
      className={`interrupt-panel ${
        isMissingInformation
          ? "interrupt-information"
          : isWritingBrief
            ? "interrupt-brief"
            : "interrupt-approval"
      }`}
      aria-labelledby="interrupt-title"
    >
      <header className="interrupt-header">
        <span className="interrupt-icon">
          {isMissingInformation || isWritingBrief ? (
            <AlertCircle size={20} />
          ) : (
            <CheckCircle2 size={20} />
          )}
        </span>
        <div>
          <span className="eyebrow">İşlem sizden bilgi bekliyor</span>
          <h2 id="interrupt-title">
            {isWritingBrief
              ? (interrupt.payload.title ?? "Taslak öncesi birkaç nokta")
              : isMissingInformation
                ? "Devam etmek için birkaç bilgi gerekli"
                : "Hazırlanan taslak onayınızı bekliyor"}
          </h2>
          <p>
            {isWritingBrief
              ? (interrupt.payload.intro ??
                "Taslağı yazmadan önce netleştirmem gereken birkaç nokta var.")
              : isMissingInformation
                ? "Alanları tamamladığınızda çalışma kaldığı yerden devam edecek."
                : "Taslağı inceleyip onaylayabilir veya değişiklik isteyebilirsiniz."}
          </p>
        </div>
      </header>

      {!isMissingInformation && !isWritingBrief && (
        <>
          {typeof revisionRound === "number" && (
            <p className="interrupt-revision-round">
              <History size={14} />
              Revizyon turu {revisionRound + 1}
              {typeof maxRevisionRounds === "number" ? `/${maxRevisionRounds}` : ""}
            </p>
          )}
          {(typeof combinedScore === "number" || requiresApproval) && (
            <div className="draft-meta-strip">
              {typeof combinedScore === "number" && (
                <span className="draft-meta-chip">Güven skoru: {combinedScore}/100</span>
              )}
              {requiresApproval && (
                <span className="draft-meta-chip draft-meta-warning">
                  <AlertCircle size={13} />
                  İnsan onayı gerekiyor
                  {evaluationNotes ? `: ${evaluationNotes}` : ""}
                </span>
              )}
            </div>
          )}
        </>
      )}

      {conflicts.length > 0 && (
        <div className="interrupt-conflicts" role="alert">
          <p className="interrupt-conflicts-heading">
            <AlertTriangle size={16} />
            Talimatınız uygulandı, ancak mevzuat/kaynak ile şu noktalarda çelişiyor:
          </p>
          <ul>
            {conflicts.map((conflict, index) => (
              <li key={index} className={`conflict-severity-${conflict.severity}`}>
                <strong>[{SEVERITY_LABEL[conflict.severity]}]</strong> {conflict.detail}
                {conflict.evidence && (
                  <span className="conflict-evidence"> — dayanak: {conflict.evidence}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {interrupt.payload.draft && (
        <details className="interrupt-draft" open={!isMissingInformation}>
          <summary>
            <span>
              <FileText size={15} />
              Oluşturulan taslağı görüntüle
            </span>
            <ChevronDown size={15} />
          </summary>
          <pre className="draft-preview">{interrupt.payload.draft}</pre>
        </details>
      )}

      {changelogEntries.length > 0 && (
        <details className="interrupt-changelog">
          <summary>
            <span>
              <History size={15} />
              Değişiklik günlüğü ({changelog?.summary ?? "Değişiklikler"})
            </span>
            <ChevronDown size={15} />
          </summary>
          <ul className="changelog-entries">
            {changelogEntries.map((entry, index) => (
              <li key={index}>
                {entry.directive && <p className="changelog-directive">"{entry.directive}"</p>}
                <div className="changelog-diff">
                  {entry.before && <p className="changelog-before">- {entry.before}</p>}
                  {entry.after && <p className="changelog-after">+ {entry.after}</p>}
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}

      {isMissingInformation ? (
        <PromptQuestionCard
          questions={questions}
          loading={loading}
          submitLabel={loading ? "Gönderiliyor…" : "Bilgileri gönder ve devam et"}
          onSubmit={(answers) => void onResume("answer", answers, "")}
        />
      ) : isWritingBrief ? (
        <>
          <PromptQuestionCard
            questions={questions}
            resolved={interrupt.payload.resolved}
            loading={loading}
            submitLabel={loading ? "Gönderiliyor…" : "Bilgileri gönder ve devam et"}
            onSubmit={(answers) => void onResume("answer", answers, "")}
          />
          <FormActions className="interrupt-actions approval-actions">
            <Button variant="secondary" disabled={loading} onClick={acceptAllDefaults}>
              Sen karar ver, devam et
            </Button>
            <Button
              variant="destructive"
              disabled={loading}
              onClick={() => void onResume("reject", {}, "", "Kullanıcı taslağı iptal etti.")}
            >
              Vazgeç
            </Button>
          </FormActions>
        </>
      ) : showRejectForm ? (
        <form className="interrupt-form form-stack" onSubmit={submitReject}>
          <Textarea
              label="Red gerekçesi"
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              placeholder="Bu taslağı neden reddediyorsunuz?"
              required
            />
          <FormActions className="interrupt-actions approval-actions">
            <Button
              variant="secondary"
              disabled={loading}
              onClick={() => setShowRejectForm(false)}
            >
              Vazgeç
            </Button>
            <Button
              type="submit"
              variant="destructive"
              loading={loading}
              disabled={!rejectReason.trim()}
            >
              {loading ? "Gönderiliyor…" : "Reddi onayla"}
            </Button>
          </FormActions>
        </form>
      ) : (
        <div className="interrupt-form form-stack">
          <Textarea
              label="Revizyon notu"
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              placeholder="Revizyon istiyorsanız talimatınızı yazın."
              disabled={revisionExhausted}
            />
          {revisionExhausted && (
            <p className="interrupt-revision-exhausted">
              <AlertCircle size={14} />
              Revizyon turu sınırına ulaşıldı; onaylayın, reddedin veya yeni bir mesajla devam edin.
            </p>
          )}
          <FormActions className="interrupt-actions approval-actions">
            <Button
              disabled={loading}
              onClick={() => void onResume("approve", {}, "")}
            >
              Onayla
            </Button>
            <Button
              variant="secondary"
              disabled={loading || !instructions.trim() || revisionExhausted}
              onClick={() => void onResume("revise", {}, instructions)}
            >
              Revizyon iste
            </Button>
            <Button
              variant="destructive"
              disabled={loading}
              onClick={() => setShowRejectForm(true)}
            >
              Reddet
            </Button>
          </FormActions>
        </div>
      )}
    </section>
  );
}
