import { CheckCircle2, Route, Sparkles } from "lucide-react";
import { useEffect } from "react";
import { ApiErrorNotice } from "../../components/ApiErrorNotice";
import { Button } from "../../components/Button";
import { StatusBadge } from "../../components/StatusBadge";
import { useRoutingSuggestion } from "../../hooks/useRoutingSuggestion";
import type { PersistedDraft } from "../../types/drafts";
import { isRoutingDocumentType } from "../../types/routing";
import { UnitPicker } from "./UnitPicker";

export function DraftRoutingPanel({
  draft,
  sourceDocumentType,
  saving,
  onSave,
}: {
  draft: PersistedDraft;
  sourceDocumentType?: string | null;
  saving: boolean;
  onSave: (destination: string) => void;
}) {
  const routing = useRoutingSuggestion();
  const reset = routing.reset;
  const confidence = draft.confidence_score;

  useEffect(() => {
    reset();
  }, [draft.id, reset]);

  const suggest = () => routing.suggest({
    draft: draft.content,
    ...(confidence !== null ? { confidence_score: confidence } : {}),
    ...(isRoutingDocumentType(sourceDocumentType)
      ? { document_type: sourceDocumentType }
      : {}),
  });

  const suggestionApplied = Boolean(
    routing.suggestion?.routed_unit
      && routing.suggestion.routed_unit === draft.destination,
  );

  return (
    <div className="draft-routing-view">
      <section className="draft-routing-intro">
        <span><Route /></span>
        <div>
          <h3>Birim yönlendirme</h3>
          <p>Seçili taslağın içeriğine göre hedef birim önerisi alın ve son kararı burada verin.</p>
        </div>
      </section>

      <section className="draft-routing-context">
        <div>
          <small>Mevcut hedef birim</small>
          <strong>{draft.destination || "Henüz belirlenmedi"}</strong>
        </div>
        <div>
          <small>Güven göstergesi</small>
          <strong>{confidence === null ? "—" : `${Math.round(confidence)} / 100`}</strong>
        </div>
        <Button
          leadingIcon={<Sparkles />}
          loading={routing.loading}
          disabled={!draft.content.trim()}
          onClick={() => void suggest()}
        >
          {routing.suggestion ? "Öneriyi yenile" : "Yönlendirme önerisi al"}
        </Button>
      </section>

      <ApiErrorNotice error={routing.errorObject ?? routing.error} />

      {routing.suggestion ? (
        <section className="draft-routing-result" aria-live="polite">
          <header>
            <div>
              <small>Önerilen birim</small>
              <h3>{routing.suggestion.routed_unit}</h3>
            </div>
            <StatusBadge tone={confidence !== null && confidence < 60 ? "warning" : "success"}>
              {routing.suggestion.priority}
            </StatusBadge>
          </header>
          <div className="draft-routing-reason">
            <strong>Öneri gerekçesi</strong>
            <p>
              {routing.suggestion.reasoning
                || routing.suggestion.justification
                || "Yönlendirme gerekçesi bulunmuyor."}
            </p>
          </div>
          <footer>
            <p>Nihai hedef birim kararı kullanıcıya aittir.</p>
            <div>
              <UnitPicker
                currentDestination={draft.destination}
                saving={saving}
                onSave={onSave}
              />
              <Button
                leadingIcon={suggestionApplied ? <CheckCircle2 /> : <Route />}
                loading={saving}
                disabled={suggestionApplied || saving}
                onClick={() => onSave(routing.suggestion!.routed_unit)}
              >
                {suggestionApplied ? "Hedef birim olarak seçildi" : "Öneriyi hedef birim yap"}
              </Button>
            </div>
          </footer>
        </section>
      ) : (
        <section className="draft-routing-empty" aria-live="polite">
          <span><Route /></span>
          <div>
            <h3>Henüz yönlendirme önerisi yok</h3>
            <p>Taslak metnini ayrıca kopyalamanıza gerek yok; öneri seçili taslaktan üretilecek.</p>
          </div>
        </section>
      )}
    </div>
  );
}
