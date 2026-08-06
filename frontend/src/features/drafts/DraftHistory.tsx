import { Clock3, FilePenLine } from "lucide-react";
import { EmptyState } from "../../components/EmptyState";
import type { DraftHistoryEntry } from "../../hooks/useDraftHistory";
import type { DraftResult } from "../../types/documents";

const DATE_FORMAT = new Intl.DateTimeFormat("tr-TR", {
  dateStyle: "medium",
  timeStyle: "short",
});

export function DraftHistory({
  entries,
  activeDraft,
  onSelect,
}: {
  entries: DraftHistoryEntry[];
  activeDraft: DraftResult | null;
  onSelect: (entry: DraftHistoryEntry) => void;
}) {
  return (
    <section className="surface draft-history-section">
      <div className="section-heading">
        <div>
          <h2>Taslak geçmişi</h2>
          <p>Bu tarayıcıda oluşturulan son {entries.length} taslak.</p>
        </div>
      </div>
      {entries.length === 0 ? (
        <EmptyState
          icon={FilePenLine}
          title="Henüz kayıtlı taslak yok"
          description="Oluşturduğunuz taslaklar burada listelenecek."
        />
      ) : (
        <ol className="draft-history-list">
          {entries.map((entry) => (
            <li key={entry.id}>
              <button
                type="button"
                className="draft-history-card"
                aria-pressed={entry.result === activeDraft}
                onClick={() => onSelect(entry)}
              >
                <span className="draft-history-meta">
                  <strong>{entry.source.file_name}</strong>
                  <time dateTime={entry.createdAt}>
                    <Clock3 size={13} />
                    {DATE_FORMAT.format(new Date(entry.createdAt))}
                  </time>
                </span>
                <span className="draft-history-destination">
                  {entry.result.destination || "Birim yönlendirmesi bekliyor"}
                </span>
                <span className="draft-history-preview">
                  {entry.result.draft}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
