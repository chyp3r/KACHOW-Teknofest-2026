import { Route } from "lucide-react";
import { useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { ApiErrorNotice } from "../components/ApiErrorNotice";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useDrafts } from "../hooks/useDrafts";
import { useRoutingSuggestion } from "../hooks/useRoutingSuggestion";
import { Button } from "../components/Button";
import { Select, Textarea } from "../components/FormControls";
import { FormActions } from "../components/LayoutPrimitives";
import { Alert, Card } from "../components/Surface";

export function RoutingPage() {
  const drafts = useDrafts();
  const routing = useRoutingSuggestion();
  const [selectedDraftId, setSelectedDraftId] = useState("");
  const [text, setText] = useState("");
  const [confidence, setConfidence] = useState<number | null>(null);

  const submit = async () => {
    await routing.suggest(
      confidence !== null
        ? { draft: text.trim(), confidence_score: confidence }
        : { draft: text.trim() },
    );
  };

  return (
    <div className="page page-scroll">
      <PageHeader
        title="Yönlendirme Önerisi"
        description="Taslak metni için stateless backend önerisi alın; nihai karar yetkili kullanıcıdadır."
      />
      <div className="routing-layout">
        <Card className="form-stack" padding="prominent">
          <Select label="Kalıcı taslaktan seç (isteğe bağlı)" value={selectedDraftId} onChange={(event) => {
              const nextId = event.target.value;
              setSelectedDraftId(nextId);
              const draft = drafts.drafts.find((item) => item.id === nextId);
              if (draft) {
                setText(draft.content);
                setConfidence(draft.confidence_score ?? null);
              }
              routing.reset();
            }}>
              <option value="">Serbest metin kullan</option>
              {drafts.drafts.map((draft) => <option key={draft.id} value={draft.id}>Sürüm {draft.version} · {draft.destination ?? "Taslak"}</option>)}
          </Select>
          <Textarea label="Taslak veya evrak metni" counter={`${text.length}/20.000 karakter`} value={text} minLength={1} maxLength={20000} rows={12} onChange={(event) => { setText(event.target.value); routing.reset(); }} />
          <ApiErrorNotice error={routing.errorObject ?? routing.error} />
          <FormActions><Button loading={routing.loading} disabled={!text.trim()} onClick={() => void submit()}>Yönlendirme önerisi al</Button></FormActions>
        </Card>
        <Card className="routing-result" padding="prominent" aria-live="polite">
          {routing.suggestion ? (
            <>
              <div className="section-heading"><div><span className="eyebrow">Öneri</span><h2>{routing.suggestion.routed_unit}</h2></div><StatusBadge tone={confidence !== null && confidence < 60 ? "warning" : "success"}>{routing.suggestion.priority}</StatusBadge></div>
              {confidence !== null && confidence < 60 && <Alert variant="warning">Güven skoru düşük olduğundan insan değerlendirmesi özellikle önemlidir.</Alert>}
              <h3>Gerekçe</h3>
              <p>{routing.suggestion.reasoning || routing.suggestion.justification || "Backend gerekçe döndürmedi."}</p>
              <small>Bu sonuç kalıcılaştırılmaz ve nihai karar değildir.</small>
            </>
          ) : (
            <EmptyState icon={Route} title="Henüz öneri yok" description="Metni girip backend yönlendirme akışını çalıştırın." />
          )}
        </Card>
      </div>
    </div>
  );
}
