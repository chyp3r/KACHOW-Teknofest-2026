import { AlertCircle, AlertTriangle, ChevronDown, FileText, History } from "lucide-react";
import { useState } from "react";
import type { ConflictFinding, InterruptState } from "../../types/chat";
import { Button } from "../../components/Button";
import { Textarea } from "../../components/FormControls";
import { FormActions } from "../../components/LayoutPrimitives";
import { PromptQuestionCard, type PromptAnswers } from "./PromptQuestionCard";
import { TransferConfirmCard } from "./TransferConfirmCard";

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
    action: "answer" | "approve" | "revise" | "reject" | "select",
    answers: PromptAnswers,
    instructions: string,
    reason?: string,
  ) => Promise<void>;
}) {
  const [showRevisionEscapeHatch, setShowRevisionEscapeHatch] = useState(false);
  const [revisionNote, setRevisionNote] = useState("");
  const questions = Array.isArray(interrupt.payload.questions)
    ? interrupt.payload.questions
    : [];
  // The only two gate shapes this panel ever renders now -- a low-scoring
  // or guessed-type draft no longer opens a separate approve/reject/revise
  // gate of its own (see planning_graph.human_gate_node's own docstring on
  // why: there is no "İnsan onayı gerekiyor" surface anywhere in this
  // system, only a question about a specific missing field).
  const isMissingInformation = interrupt.kind === "missing_information";
  const isWritingBrief = interrupt.kind === "writing_brief";
  const autoValue = interrupt.payload.auto_value ?? "__auto__";

  const conflicts = Array.isArray(interrupt.payload.conflicts)
    ? interrupt.payload.conflicts
    : [];
  const changelog = interrupt.payload.changelog;
  const changelogEntries = Array.isArray(changelog?.entries) ? changelog.entries : [];

  const acceptAllDefaults = () => {
    if (loading) return;
    const answers: PromptAnswers = {};
    for (const question of questions) answers[question.key] = autoValue;
    void onResume("answer", answers, "");
  };

  // Faz 4 (#201) -- a distinct gate shape, not a draft-approval variant:
  // no draft preview, no revision quick-picks, no changelog. Short-circuits
  // before the shared JSX below rather than threading a third branch
  // through every section of it.
  if (interrupt.kind === "artifact_transfer_confirm" || interrupt.kind === "artifact_transfer_disambiguate") {
    return (
      <section className="interrupt-panel interrupt-transfer" aria-labelledby="interrupt-title">
        <header className="interrupt-header">
          <span className="interrupt-icon">
            <AlertCircle size={15} />
          </span>
          <h2 id="interrupt-title">
            {interrupt.kind === "artifact_transfer_disambiguate" ? "Alıcı seçimi bekleniyor" : "Gönderim onayınız bekleniyor"}
          </h2>
        </header>
        <TransferConfirmCard
          interrupt={interrupt}
          loading={loading}
          onSelect={(recipientId) => void onResume("select", { recipient_id: recipientId }, "")}
          onApprove={() => void onResume("approve", {}, "")}
          onReject={() => void onResume("reject", {}, "", "Kullanıcı transferi iptal etti.")}
        />
      </section>
    );
  }

  return (
    <section
      className={`interrupt-panel ${
        isMissingInformation ? "interrupt-information" : "interrupt-brief"
      }`}
      aria-labelledby="interrupt-title"
    >
      <header className="interrupt-header">
        <span className="interrupt-icon">
          <AlertCircle size={15} />
        </span>
        <h2 id="interrupt-title">
          {isWritingBrief
            ? (interrupt.payload.title ?? "Taslak öncesi birkaç nokta")
            : "Birkaç bilgi daha gerekiyor"}
        </h2>
      </header>
      {isWritingBrief && interrupt.payload.intro && (
        <p className="interrupt-subtext">{interrupt.payload.intro}</p>
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
        <>
          <PromptQuestionCard
            questions={questions}
            loading={loading}
            submitLabel={loading ? "Gönderiliyor…" : "Bilgileri gönder ve devam et"}
            onSubmit={(answers) => void onResume("answer", answers, "")}
          />
          {/* Escape hatch: a revision instruction typed into an answer box
              used to be substituted verbatim into the placeholder it was
              answering, producing a nonsense draft -- this routes it
              through a real revision instead (see planning_graph.
              human_gate_node's own "missing_information" + action="revise"
              branch). */}
          {!showRevisionEscapeHatch ? (
            <button
              type="button"
              className="interrupt-escape-hatch-toggle"
              disabled={loading}
              onClick={() => setShowRevisionEscapeHatch(true)}
            >
              Bilgi vermek yerine taslağı revize etmek mi istiyorsunuz?
            </button>
          ) : (
            <div className="interrupt-form form-stack interrupt-revision-escape-hatch">
              <Textarea
                label="Revizyon talimatı"
                value={revisionNote}
                onChange={(event) => setRevisionNote(event.target.value)}
                placeholder="Örn. Unvanı Daire Başkanı olarak değiştir."
              />
              <FormActions className="interrupt-actions approval-actions">
                <Button
                  variant="secondary"
                  disabled={loading}
                  onClick={() => setShowRevisionEscapeHatch(false)}
                >
                  Vazgeç
                </Button>
                <Button
                  disabled={loading || !revisionNote.trim()}
                  onClick={() => void onResume("revise", {}, revisionNote.trim())}
                >
                  Bunun yerine revizyon iste
                </Button>
              </FormActions>
            </div>
          )}
        </>
      ) : (
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
      )}
    </section>
  );
}
