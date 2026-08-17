import { AlertCircle, AlertTriangle, CheckCircle2, ChevronDown, FileText, History } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { ConflictFinding, InterruptState, PromptQuestion } from "../../types/chat";
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

// Quick-pick revision shortcuts shown above the free-text note. Each
// option's label is itself a complete Turkish instruction fragment, so
// compiling a selection is just joining the chosen labels -- these ride
// the existing free-text `instructions` field of onResume("revise", ...),
// not a new resume contract.
const REVISION_QUICK_PICKS: PromptQuestion[] = [
  {
    key: "uslup",
    header: "Üslup",
    question: "Üslupta hazır bir değişiklik ister misiniz?",
    options: [
      { value: "daha_resmi", label: "Daha resmi bir üslup kullan" },
      { value: "daha_samimi", label: "Daha sıcak/samimi bir üslup kullan" },
    ],
    multi_select: true,
    allow_free_text: false,
    required: false,
  },
  {
    key: "hitap",
    header: "Hitap / Yön",
    question: "Hitap veya yönle ilgili hazır bir değişiklik ister misiniz?",
    options: [
      { value: "yazan_taraf", label: "Yazan tarafı (göndereni) değiştir" },
      { value: "muhatap", label: "Muhatabı değiştir" },
    ],
    multi_select: true,
    allow_free_text: false,
    required: false,
  },
  {
    key: "kapanis",
    header: "Kapanış",
    question: "Kapanış ifadesini değiştirmek ister misiniz?",
    options: [
      { value: "arz", label: "Kapanışı 'Arz ederim' yap" },
      { value: "rica", label: "Kapanışı 'Rica ederim' yap" },
      { value: "bilgi", label: "Kapanışı 'Bilgilerinize sunulur' yap" },
    ],
    multi_select: true,
    allow_free_text: false,
    required: false,
  },
  {
    key: "kapsam",
    header: "Kapsam",
    question: "Metnin kapsamında hazır bir değişiklik ister misiniz?",
    options: [
      { value: "kisalt", label: "Metni kısalt" },
      { value: "detaylandir", label: "Metni detaylandır" },
    ],
    multi_select: true,
    allow_free_text: false,
    required: false,
  },
];

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
  const [instructions, setInstructions] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [quickPicks, setQuickPicks] = useState<PromptAnswers>({});
  const [showRevisionEscapeHatch, setShowRevisionEscapeHatch] = useState(false);
  const [revisionNote, setRevisionNote] = useState("");
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

  // Turns the quick-pick selections back into the Turkish instruction
  // fragments they're labeled with, combined with anything typed by hand --
  // both ride the same free-text `instructions` field gate_revise_node
  // already runs through, so no resume-contract change was needed for this.
  const compiledInstructions = (() => {
    const picked = REVISION_QUICK_PICKS.flatMap((question) => {
      const selected = quickPicks[question.key];
      const values = Array.isArray(selected) ? selected : [];
      return question.options
        .filter((option) => values.includes(option.value))
        .map((option) => option.label);
    });
    return [...picked, instructions.trim()].filter(Boolean).join(". ");
  })();

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
            <AlertCircle size={15} />
          ) : (
            <CheckCircle2 size={15} />
          )}
        </span>
        <h2 id="interrupt-title">
          {isWritingBrief
            ? (interrupt.payload.title ?? "Taslak öncesi birkaç nokta")
            : isMissingInformation
              ? "Birkaç bilgi daha gerekiyor"
              : "Taslak onayınızı bekliyor"}
        </h2>
      </header>
      {isWritingBrief && interrupt.payload.intro && (
        <p className="interrupt-subtext">{interrupt.payload.intro}</p>
      )}

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
          <div className="prompt-question-list quick-pick-list">
            {REVISION_QUICK_PICKS.map((question) => {
              const selected = Array.isArray(quickPicks[question.key])
                ? (quickPicks[question.key] as string[])
                : [];
              return (
                <div className="prompt-question" key={question.key}>
                  <span className="prompt-question-chip">{question.header}</span>
                  <div className="prompt-question-options" role="group">
                    {question.options.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className={`prompt-question-option ${
                          selected.includes(option.value) ? "is-selected" : ""
                        }`}
                        disabled={revisionExhausted}
                        onClick={() =>
                          setQuickPicks((previous) => {
                            const current = Array.isArray(previous[question.key])
                              ? (previous[question.key] as string[])
                              : [];
                            const next = current.includes(option.value)
                              ? current.filter((value) => value !== option.value)
                              : [...current, option.value];
                            return { ...previous, [question.key]: next };
                          })
                        }
                      >
                        <span className="prompt-question-option-label">{option.label}</span>
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
          <Textarea
              label="Revizyon notu"
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              placeholder="Yukarıdaki hazır seçeneklere ek olarak, isterseniz talimatınızı yazın."
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
              disabled={loading || !compiledInstructions.trim() || revisionExhausted}
              onClick={() => void onResume("revise", {}, compiledInstructions)}
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
