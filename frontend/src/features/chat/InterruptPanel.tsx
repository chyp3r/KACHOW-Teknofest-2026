import { AlertCircle, CheckCircle2, ChevronDown, FileText } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { InterruptState } from "../../types/chat";

export function InterruptPanel({
  interrupt,
  loading,
  onResume,
}: {
  interrupt: InterruptState;
  loading: boolean;
  onResume: (
    action: "answer" | "approve" | "revise" | "reject",
    answers: Record<string, string>,
    instructions: string,
  ) => Promise<void>;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [instructions, setInstructions] = useState("");
  const questions = interrupt.payload.questions ?? [];
  const canSubmitAnswers = questions
    .filter((question) => question.required !== false)
    .every((question) => answers[question.key]?.trim());
  const isMissingInformation = interrupt.kind === "missing_information";

  const submitAnswers = (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmitAnswers || loading) return;
    void onResume("answer", answers, "");
  };

  return (
    <section
      className={`interrupt-panel ${
        isMissingInformation ? "interrupt-information" : "interrupt-approval"
      }`}
      aria-labelledby="interrupt-title"
    >
      <header className="interrupt-header">
        <span className="interrupt-icon">
          {isMissingInformation ? (
            <AlertCircle size={20} />
          ) : (
            <CheckCircle2 size={20} />
          )}
        </span>
        <div>
          <span className="eyebrow">İşlem sizden bilgi bekliyor</span>
          <h2 id="interrupt-title">
            {isMissingInformation
              ? "Devam etmek için birkaç bilgi gerekli"
              : "Hazırlanan taslak onayınızı bekliyor"}
          </h2>
          <p>
            {isMissingInformation
              ? "Alanları tamamladığınızda çalışma kaldığı yerden devam edecek."
              : "Taslağı inceleyip onaylayabilir veya değişiklik isteyebilirsiniz."}
          </p>
        </div>
      </header>

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

      {isMissingInformation ? (
        <form className="interrupt-form" onSubmit={submitAnswers}>
          <div className="interrupt-question-grid">
            {questions.map((question) => (
              <label key={question.key}>
                <span>
                  {question.label}
                  {question.required !== false && (
                    <small className="required-mark">Gerekli</small>
                  )}
                </span>
                {question.why && <small>{question.why}</small>}
                <input
                  value={answers[question.key] ?? ""}
                  placeholder={question.example ?? ""}
                  required={question.required !== false}
                  onChange={(event) =>
                    setAnswers((previous) => ({
                      ...previous,
                      [question.key]: event.target.value,
                    }))
                  }
                />
              </label>
            ))}
          </div>
          <div className="interrupt-actions">
            <small>
              {canSubmitAnswers
                ? "Bilgiler hazır. İşleme devam edebilirsiniz."
                : "Devam etmek için gerekli alanları doldurun."}
            </small>
            <button
              className="button button-primary"
              type="submit"
              disabled={loading || !canSubmitAnswers}
            >
              {loading ? "Gönderiliyor…" : "Bilgileri gönder ve devam et"}
            </button>
          </div>
        </form>
      ) : (
        <div className="interrupt-form form-stack">
          <label>
            Revizyon notu
            <textarea
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              placeholder="Revizyon istiyorsanız talimatınızı yazın."
            />
          </label>
          <div className="interrupt-actions approval-actions">
            <button
              className="button button-primary"
              disabled={loading}
              onClick={() => void onResume("approve", {}, "")}
            >
              Onayla
            </button>
            <button
              className="button button-secondary"
              disabled={loading || !instructions.trim()}
              onClick={() => void onResume("revise", {}, instructions)}
            >
              Revizyon iste
            </button>
            <button
              className="button button-danger"
              disabled={loading}
              onClick={() => void onResume("reject", {}, "")}
            >
              Reddet
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
