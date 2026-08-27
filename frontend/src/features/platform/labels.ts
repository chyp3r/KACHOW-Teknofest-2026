// Backend, rol / iş akışı türü / iş akışı sonucu / ajan adlarını İngilizce
// veya snake_case kimlikler olarak döndürür. Platform "Kullanıcı
// İstatistikleri" ekranı bunları kullanıcıya Türkçe gösterir; bilinmeyen bir
// değer alt çizgisi ayrılmış haliyle görünür, kaybolmaz.

const ROLE_LABELS: Record<string, string> = {
  root: "Kök yönetici",
  admin: "Yönetici",
  manager: "Müdür",
  employee: "Çalışan",
};

const INTENT_LABELS: Record<string, string> = {
  draft: "Taslak",
  revise: "Revizyon",
  assist: "Asistan",
  clarify: "Netleştirme",
  analyze: "Analiz",
  routing: "Yönlendirme",
};

const RUN_STATUS_LABELS: Record<string, string> = {
  completed: "Tamamlandı",
  running: "Çalışıyor",
  failed: "Başarısız",
  needs_human_approval: "İnsan onayı gerekli",
  revise_requested: "Revizyon istendi",
  rejected: "Reddedildi",
  approved: "Onaylandı",
  needs_input: "Bilgi bekleniyor",
};

// `kachow_llm_tokens_total`'ın `agent` etiketi, ajanın sınıf-tipi adıdır
// (`BaseAgent.name` -> ör. "WriterAgent"). Bilinmeyen bir ad, "Agent" son
// ekini atıp olduğu gibi gösterilir.
const AGENT_LABELS: Record<string, string> = {
  WriterAgent: "Yazar",
  ReviserAgent: "Revize edici",
  JudgeAgent: "Kalite yargıcı",
  AssistantAgent: "Asistan",
  RouterAgent: "Yönlendirici",
  ClassifierAgent: "Sınıflandırıcı",
  IntentClassifier: "Niyet sınıflandırıcı",
  ComplianceAgent: "Uygunluk denetçisi",
  SummarizerAgent: "Özetleyici",
  MemorySummarizerAgent: "Hafıza özetleyici",
  ConflictAuditorAgent: "Çelişki denetçisi",
  GuardrailJudgeAgent: "Güvenlik yargıcı",
};

// `kind` etiketi Prometheus'ta "prompt" / "completion" olarak gelir.
const TOKEN_KIND_LABELS: Record<string, string> = {
  prompt: "İstem (girdi)",
  completion: "Tamamlama (çıktı)",
  input: "Girdi",
  output: "Çıktı",
  total: "Toplam",
};

function look(map: Record<string, string>, value: string): string {
  return map[value] ?? value.replace(/_/g, " ");
}

export const roleLabel = (value: string) => look(ROLE_LABELS, value);
export const intentLabel = (value: string) => look(INTENT_LABELS, value);
export const runStatusLabel = (value: string) => look(RUN_STATUS_LABELS, value);
export const agentLabel = (value: string) =>
  AGENT_LABELS[value] ?? value.replace(/Agent$/, "").replace(/_/g, " ");
export const tokenKindLabel = (value: string) => look(TOKEN_KIND_LABELS, value);
