// The assistant agent's tool names are internal identifiers (snake_case,
// English). The workflow/decision-flow UI shows them to the user as steps, so
// they get a Turkish label here. An unknown name (a new backend tool the
// frontend hasn't caught up to) degrades to a de-underscored form rather than
// disappearing.
const TOOL_LABELS: Record<string, string> = {
  search_document: "Belgede arama",
  search_document_regex: "Belgede metin araması",
  get_document_details: "Belge özeti ve üst verisi",
  get_document_outline: "Belge sayfa dökümü",
  get_document_section: "Belge sayfası okuma",
  search_legislation: "Mevzuat araması",
  search_legislation_live: "Güncel mevzuat araması",
  suggest_unit: "Birim önerisi",
  request_handoff: "İlgili akışa devretme",
  propose_transfer: "Aktarım önerisi",
};

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name.replace(/_/g, " ");
}
