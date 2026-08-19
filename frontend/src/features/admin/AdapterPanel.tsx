import { Save } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "../../components/Button";
import { Textarea } from "../../components/FormControls";
import { Alert, Card, Spinner } from "../../components/Surface";
import { useCompanySettings } from "../../hooks/useCompanySettings";

const lines = (value: string) => value.split("\n").map((item) => item.trim()).filter(Boolean);

export function AdapterPanel({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const settings = useCompanySettings(companyId);
  const [styleRules, setStyleRules] = useState("");
  const [preferred, setPreferred] = useState("");
  const [avoided, setAvoided] = useState("");
  useEffect(() => { if (settings.adapter) { setStyleRules(settings.adapter.style_rules.join("\n")); setPreferred(settings.adapter.preferred_examples.join("\n")); setAvoided(settings.adapter.avoided_patterns.join("\n")); } }, [settings.adapter]);
  if (settings.loading) return <div className="table-loading"><Spinner />Model ayarları yükleniyor…</div>;
  return <Card className="management-panel"><header className="management-panel-header"><div><h2>Üslup adaptörü</h2><p>Sürüm {settings.adapter?.version ?? 0} · {settings.adapter?.sample_count ?? 0} örnek{settings.adapter?.trained_at ? ` · ${new Date(settings.adapter.trained_at).toLocaleString("tr-TR")}` : ""}</p></div></header>{settings.error && <Alert variant="error">{settings.error instanceof Error ? settings.error.message : "Adaptör yüklenemedi."}</Alert>}<div className="management-form"><Textarea label="Üslup kuralları" description="Her satıra bir kural." rows={6} value={styleRules} disabled={!canManage} onChange={(event) => setStyleRules(event.target.value)} /><Textarea label="Tercih edilen örnekler" description="Her satıra bir örnek." rows={6} value={preferred} disabled={!canManage} onChange={(event) => setPreferred(event.target.value)} /><Textarea label="Kaçınılacak kalıplar" description="Her satıra bir kalıp." rows={6} value={avoided} disabled={!canManage} onChange={(event) => setAvoided(event.target.value)} />{canManage && <Button leadingIcon={<Save />} loading={settings.saving} onClick={() => void settings.updateAdapter({ style_rules: lines(styleRules), preferred_examples: lines(preferred), avoided_patterns: lines(avoided) })}>Adaptörü kaydet</Button>}</div></Card>;
}
