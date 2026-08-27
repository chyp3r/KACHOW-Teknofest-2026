import { useState, type FormEvent } from "react";
import type { PromptQuestion } from "../../types/chat";
import { Button } from "../../components/Button";
import { Input } from "../../components/FormControls";

export type PromptAnswer = string | string[];
export type PromptAnswers = Record<string, PromptAnswer>;

function isAnswered(question: PromptQuestion, value: PromptAnswer | undefined): boolean {
  if (question.multi_select) return Array.isArray(value) && value.length > 0;
  return typeof value === "string" && value.trim().length > 0;
}

// The single card every "ask the user" surface renders through -- the
// pre-draft writing brief, the missing-information gate, and clarify's
// intent question. Modeled on Claude Code's plan-mode AskUserQuestion: one
// question at a time, not one big form with every field open at once.
// Picking a single-select option advances immediately; a multi-select or
// free-text question needs an explicit "İleri" -- the last question's
// button reads as the caller's own submitLabel and calls onSubmit.
export function PromptQuestionCard({
  title,
  intro,
  questions,
  resolved,
  loading,
  submitLabel = "Devam et",
  onSubmit,
}: {
  title?: string;
  intro?: string;
  questions: PromptQuestion[];
  resolved?: Record<string, { value: string; label?: string; source?: string }>;
  loading: boolean;
  submitLabel?: string;
  onSubmit: (answers: PromptAnswers) => void;
}) {
  const [stepIndex, setStepIndex] = useState(0);
  const [answers, setAnswers] = useState<PromptAnswers>({});
  const [freeText, setFreeText] = useState<Record<string, string>>({});
  const [otherOpen, setOtherOpen] = useState<Record<string, boolean>>({});

  if (questions.length === 0) return null;

  const total = questions.length;
  const question = questions[Math.min(stepIndex, total - 1)];
  const isLast = stepIndex >= total - 1;
  const hasOptions = question.options.length > 0;
  const showFreeText = !hasOptions || (otherOpen[question.key] ?? false);
  const value = answers[question.key];
  const resolvedEntries = Object.entries(resolved ?? {});
  const nextLabel = isLast ? submitLabel : "İleri";

  const advance = (nextAnswers: PromptAnswers) => {
    setAnswers(nextAnswers);
    if (isLast) {
      if (!loading) onSubmit(nextAnswers);
      return;
    }
    setStepIndex((index) => Math.min(index + 1, total - 1));
  };

  const goBack = () => {
    setStepIndex((index) => Math.max(0, index - 1));
  };

  const selectSingle = (optionValue: string) => {
    if (loading) return;
    advance({ ...answers, [question.key]: optionValue });
  };

  const toggleMulti = (optionValue: string) => {
    setAnswers((previous) => {
      const current = Array.isArray(previous[question.key])
        ? (previous[question.key] as string[])
        : [];
      const next = current.includes(optionValue)
        ? current.filter((item) => item !== optionValue)
        : [...current, optionValue];
      return { ...previous, [question.key]: next };
    });
  };

  const confirmMulti = () => {
    if (loading) return;
    if (question.required && !isAnswered(question, value)) return;
    advance({ ...answers });
  };

  const submitFreeText = (event: FormEvent) => {
    event.preventDefault();
    if (loading) return;
    const text = (freeText[question.key] ?? "").trim();
    if (question.required && !text) return;
    advance({ ...answers, [question.key]: text });
  };

  const skip = () => {
    if (loading) return;
    advance({ ...answers });
  };

  const exampleValue = (question.example ?? "").trim();
  const freeTextValue = freeText[question.key] ?? (hasOptions ? "" : typeof value === "string" ? value : "");
  const canAcceptExample = Boolean(exampleValue) && !freeTextValue.trim();

  const acceptExample = () => {
    if (loading || !exampleValue) return;
    setFreeText((previous) => ({ ...previous, [question.key]: exampleValue }));
  };

  return (
    <div className="prompt-question-card">
      {(title || intro) && (
        <header className="prompt-question-card-header">
          {title && <h3>{title}</h3>}
          {intro && <p>{intro}</p>}
        </header>
      )}

      {stepIndex === 0 && resolvedEntries.length > 0 && (
        <div className="prompt-question-resolved">
          <span className="prompt-question-resolved-title">Bilinenler</span>
          <ul>
            {resolvedEntries.map(([key, entry]) => (
              <li key={key}>{entry.label ?? entry.value}</li>
            ))}
          </ul>
        </div>
      )}

      {total > 1 && (
        <div className="prompt-question-progress">
          <span>
            Soru {stepIndex + 1} / {total}
          </span>
          <div className="prompt-question-progress-bar">
            <div
              className="prompt-question-progress-fill"
              style={{ width: `${((stepIndex + 1) / total) * 100}%` }}
            />
          </div>
        </div>
      )}

      <div className="prompt-question-step" key={question.key}>
        {question.header && <span className="prompt-question-chip">{question.header}</span>}
        <p className="prompt-question-text">
          {question.question}
          {question.required && (
            <span className="required-mark" aria-hidden="true">
              {" "}
              *
            </span>
          )}
        </p>
        {question.help && <p className="prompt-question-help">{question.help}</p>}

        {hasOptions && !showFreeText && (
          <>
            <div className="prompt-question-options" role="group">
              {question.options.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  disabled={loading}
                  className={`prompt-question-option ${
                    (
                      question.multi_select
                        ? Array.isArray(value) && value.includes(option.value)
                        : value === option.value
                    )
                      ? "is-selected"
                      : ""
                  }`}
                  onClick={() =>
                    question.multi_select ? toggleMulti(option.value) : selectSingle(option.value)
                  }
                >
                  <span className="prompt-question-option-label">{option.label}</span>
                  {option.description && (
                    <span className="prompt-question-option-description">
                      {option.description}
                    </span>
                  )}
                </button>
              ))}
              {question.allow_free_text && (
                <button
                  type="button"
                  disabled={loading}
                  className="prompt-question-option prompt-question-option-other"
                  onClick={() =>
                    setOtherOpen((previous) => ({ ...previous, [question.key]: true }))
                  }
                >
                  Diğer…
                </button>
              )}
            </div>
            <div className="prompt-question-nav">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={stepIndex === 0 || loading}
                onClick={goBack}
              >
                ← Geri
              </Button>
              {!question.required && (
                <Button type="button" variant="ghost" size="sm" disabled={loading} onClick={skip}>
                  Bu soruyu atla
                </Button>
              )}
              {question.multi_select && (
                <Button
                  type="button"
                  size="sm"
                  loading={loading && isLast}
                  disabled={loading || (question.required && !isAnswered(question, value))}
                  onClick={confirmMulti}
                >
                  {nextLabel}
                </Button>
              )}
            </div>
          </>
        )}

        {showFreeText && (
          <form className="prompt-question-freetext" onSubmit={submitFreeText}>
            <Input
              autoFocus
              disabled={loading}
              value={freeTextValue}
              placeholder={exampleValue}
              onKeyDown={(event) => {
                if (event.key === "Tab" && !event.shiftKey && canAcceptExample) {
                  event.preventDefault();
                  acceptExample();
                }
              }}
              onChange={(event) =>
                setFreeText((previous) => ({ ...previous, [question.key]: event.target.value }))
              }
              aria-label={question.header || question.question}
            />
            {canAcceptExample && (
              <button
                type="button"
                className="prompt-question-example-hint"
                disabled={loading}
                onClick={acceptExample}
              >
                Öneri: <strong>{exampleValue}</strong>
                <span className="prompt-question-example-key" aria-hidden="true">Tab</span>
              </button>
            )}
            <div className="prompt-question-nav">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={stepIndex === 0 || loading}
                onClick={goBack}
              >
                ← Geri
              </Button>
              {hasOptions && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={loading}
                  onClick={() =>
                    setOtherOpen((previous) => ({ ...previous, [question.key]: false }))
                  }
                >
                  Seçeneklere dön
                </Button>
              )}
              {!question.required && !hasOptions && (
                <Button type="button" variant="ghost" size="sm" disabled={loading} onClick={skip}>
                  Bu soruyu atla
                </Button>
              )}
              <Button
                type="submit"
                size="sm"
                loading={loading && isLast}
                disabled={loading || (question.required && !(freeText[question.key] ?? "").trim())}
              >
                {nextLabel}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
