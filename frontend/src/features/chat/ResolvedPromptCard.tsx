import { CheckCircle2 } from "lucide-react";
import type { PromptQuestion, ResolvedPromptInteraction } from "../../types/chat";

function selectedLabels(
  question: PromptQuestion,
  answer: string | string[] | undefined,
): string[] {
  const values = Array.isArray(answer) ? answer : answer ? [answer] : [];
  return values.map(
    (value) =>
      question.options.find((option) => option.value === value)?.label ??
      (value === "__auto__" || value === "auto" ? "Otomatik belirlenecek" : value),
  );
}

export function ResolvedPromptCard({
  interaction,
}: {
  interaction: ResolvedPromptInteraction;
}) {
  const fallbackTitle =
    interaction.kind === "writing_brief"
      ? "Yazım bilgileri"
      : interaction.kind.startsWith("artifact_transfer")
        ? "Gönderim tercihi"
        : "İstenen bilgiler";

  return (
    <section className="resolved-prompt-card" aria-label="Yanıtlanan bilgiler">
      <header className="resolved-prompt-header">
        <div>
          <span className="resolved-prompt-eyebrow">Tamamlanan adım</span>
          <h3>{interaction.title ?? fallbackTitle}</h3>
        </div>
        <span className="resolved-prompt-status">
          <CheckCircle2 size={15} />
          Yanıtlandı
        </span>
      </header>

      {interaction.questions.length > 0 && (
        <dl className="resolved-prompt-answers">
          {interaction.questions.map((question, index) => {
            const labels = selectedLabels(question, interaction.answers[question.key]);
            return (
              <div className="resolved-prompt-answer" key={question.key}>
                <dt>
                  <span>{index + 1}</span>
                  {question.header ?? question.question}
                </dt>
                <dd>
                  {labels.length > 0
                    ? labels.map((label) => <span key={label}>{label}</span>)
                    : <span className="is-muted">Yanıt verilmedi</span>}
                </dd>
              </div>
            );
          })}
        </dl>
      )}

      {interaction.instructions && (
        <p className="resolved-prompt-note">
          <strong>Revizyon talimatı:</strong> {interaction.instructions}
        </p>
      )}
      {interaction.reason && (
        <p className="resolved-prompt-note">
          <strong>Gerekçe:</strong> {interaction.reason}
        </p>
      )}
    </section>
  );
}
