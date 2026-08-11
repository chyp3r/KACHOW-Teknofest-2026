import { useState, type FormEvent } from "react";
import type { PromptQuestion } from "../../types/chat";
import { Button } from "../../components/Button";
import { Input } from "../../components/FormControls";
import { FormActions } from "../../components/LayoutPrimitives";

export type PromptAnswer = string | string[];
export type PromptAnswers = Record<string, PromptAnswer>;

function isSelected(value: PromptAnswer | undefined, optionValue: string, multiSelect: boolean): boolean {
  if (value === undefined) return false;
  if (multiSelect) return Array.isArray(value) && value.includes(optionValue);
  return value === optionValue;
}

function isAnswered(question: PromptQuestion, value: PromptAnswer | undefined): boolean {
  if (question.multi_select) return Array.isArray(value) && value.length > 0;
  return typeof value === "string" && value.trim().length > 0;
}

// The single card every "ask the user" surface renders through -- the
// pre-draft writing brief, the missing-information gate, and clarify's
// intent question. A question with no options renders as a plain labeled
// input (the missing-information shape); a question with options renders as
// a clickable button group, optionally with a "Diğer…" free-text fallback.
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
  const [answers, setAnswers] = useState<PromptAnswers>({});
  const [customText, setCustomText] = useState<Record<string, string>>({});
  const [customOpen, setCustomOpen] = useState<Record<string, boolean>>({});

  const selectSingle = (key: string, value: string) => {
    setCustomOpen((previous) => ({ ...previous, [key]: false }));
    setAnswers((previous) => ({ ...previous, [key]: value }));
  };

  const toggleMulti = (key: string, value: string) => {
    setAnswers((previous) => {
      const current = Array.isArray(previous[key]) ? (previous[key] as string[]) : [];
      const next = current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value];
      return { ...previous, [key]: next };
    });
  };

  const setCustom = (question: PromptQuestion, text: string) => {
    setCustomText((previous) => ({ ...previous, [question.key]: text }));
    if (question.multi_select) {
      setAnswers((previous) => {
        // Keep only the selected options' own values; the free-text entry
        // is re-appended fresh on every keystroke rather than tracked as a
        // separate array slot.
        const selectedOptions = Array.isArray(previous[question.key])
          ? (previous[question.key] as string[]).filter((item) =>
              question.options.some((option) => option.value === item),
            )
          : [];
        return {
          ...previous,
          [question.key]: text.trim() ? [...selectedOptions, text] : selectedOptions,
        };
      });
    } else {
      setAnswers((previous) => ({ ...previous, [question.key]: text }));
    }
  };

  const resolvedEntries = Object.entries(resolved ?? {});
  const canSubmit = questions
    .filter((question) => question.required)
    .every((question) => isAnswered(question, answers[question.key]));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit || loading) return;
    onSubmit(answers);
  };

  return (
    <form className="prompt-question-card" onSubmit={submit}>
      {(title || intro) && (
        <header className="prompt-question-card-header">
          {title && <h3>{title}</h3>}
          {intro && <p>{intro}</p>}
        </header>
      )}

      {resolvedEntries.length > 0 && (
        <div className="prompt-question-resolved">
          <span className="prompt-question-resolved-title">Bilinenler</span>
          <ul>
            {resolvedEntries.map(([key, entry]) => (
              <li key={key}>{entry.label ?? entry.value}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="prompt-question-list">
        {questions.map((question) => {
          const value = answers[question.key];
          const hasOptions = question.options.length > 0;
          const otherOpen = customOpen[question.key] ?? false;
          const showFreeText = !hasOptions || otherOpen;

          return (
            <div className="prompt-question" key={question.key}>
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

              {hasOptions && (
                <div className="prompt-question-options" role="group">
                  {question.options.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={`prompt-question-option ${
                        isSelected(value, option.value, question.multi_select) ? "is-selected" : ""
                      }`}
                      onClick={() =>
                        question.multi_select
                          ? toggleMulti(question.key, option.value)
                          : selectSingle(question.key, option.value)
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
                      className={`prompt-question-option prompt-question-option-other ${
                        otherOpen ? "is-selected" : ""
                      }`}
                      onClick={() =>
                        setCustomOpen((previous) => ({ ...previous, [question.key]: !otherOpen }))
                      }
                    >
                      Diğer…
                    </button>
                  )}
                </div>
              )}

              {showFreeText && (
                <Input
                  value={
                    hasOptions
                      ? (customText[question.key] ?? "")
                      : typeof value === "string"
                        ? value
                        : ""
                  }
                  placeholder={question.example ?? ""}
                  onChange={(event) => setCustom(question, event.target.value)}
                  aria-label={question.header || question.question}
                />
              )}
            </div>
          );
        })}
      </div>

      <FormActions className="prompt-question-actions">
        <Button type="submit" loading={loading} disabled={!canSubmit}>
          {submitLabel}
        </Button>
      </FormActions>
    </form>
  );
}
