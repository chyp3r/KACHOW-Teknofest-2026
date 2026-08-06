import { ArrowDownAZ, FileText, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState } from "../../components/EmptyState";
import { StatusBadge } from "../../components/StatusBadge";
import type { DocumentMetadata } from "../../types/documents";

export function DocumentTable({
  documents,
  selected,
  loading,
  onSelect,
}: {
  documents: DocumentMetadata[];
  selected: DocumentMetadata | null;
  loading: boolean;
  onSelect: (document: DocumentMetadata) => void;
}) {
  const [query, setQuery] = useState("");
  const [type, setType] = useState("all");
  const [ascending, setAscending] = useState(false);
  const types = useMemo(
    () => [
      ...new Set(
        documents.map((item) => item.document_type_label || item.document_type),
      ),
    ],
    [documents],
  );
  const filtered = useMemo(
    () =>
      documents
        .filter((item) => {
          const matchesQuery = `${item.file_name} ${item.summary}`
            .toLocaleLowerCase("tr-TR")
            .includes(query.toLocaleLowerCase("tr-TR"));
          return (
            matchesQuery &&
            (type === "all" ||
              (item.document_type_label || item.document_type) === type)
          );
        })
        .sort(
          (a, b) =>
            (new Date(a.upload_time).getTime() -
              new Date(b.upload_time).getTime()) *
            (ascending ? 1 : -1),
        ),
    [ascending, documents, query, type],
  );

  return (
    <section className="surface document-list-card">
      <div className="section-heading">
        <div>
          <h2>Kayıtlı evraklar</h2>
          <p>{documents.length} evrak kütüphanede bulunuyor.</p>
        </div>
      </div>
      <div className="table-toolbar">
        <label className="search-field">
          <Search size={17} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Evraklarda ara"
            aria-label="Evraklarda ara"
          />
        </label>
        <select
          value={type}
          onChange={(event) => setType(event.target.value)}
          aria-label="Dosya türüne göre filtrele"
        >
          <option value="all">Tüm türler</option>
          {types.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
        <button
          className="button button-secondary"
          onClick={() => setAscending((value) => !value)}
        >
          <ArrowDownAZ size={16} />
          {ascending ? "Eskiden yeniye" : "Yeniden eskiye"}
        </button>
      </div>
      {loading ? (
        <div className="table-loading">Evraklar yükleniyor…</div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="Evrak bulunamadı"
          description={
            query || type !== "all"
              ? "Arama veya filtre ölçütlerini değiştirin."
              : "İlk evrakınızı yukarıdaki alandan yükleyin."
          }
        />
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Evrak</th>
                <th>Tür</th>
                <th>Durum</th>
                <th>Yüklenme tarihi</th>
                <th>
                  <span className="sr-only">İşlem</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr
                  key={item.storage_path}
                  className={
                    selected?.storage_path === item.storage_path
                      ? "selected-row"
                      : ""
                  }
                >
                  <td>
                    <strong>{item.file_name}</strong>
                    <span>{item.summary || "Özet bulunmuyor."}</span>
                  </td>
                  <td>{item.document_type_label || item.document_type}</td>
                  <td>
                    <StatusBadge
                      tone={
                        item.compliance_status === "COMPLIANT"
                          ? "success"
                          : "warning"
                      }
                    >
                      {item.compliance_status === "COMPLIANT"
                        ? "Uygun"
                        : "Kontrol gerekli"}
                    </StatusBadge>
                  </td>
                  <td>
                    {new Intl.DateTimeFormat("tr-TR", {
                      dateStyle: "medium",
                    }).format(new Date(item.upload_time))}
                  </td>
                  <td>
                    <button
                      className="button button-quiet"
                      onClick={() => onSelect(item)}
                    >
                      {selected?.storage_path === item.storage_path
                        ? "Seçili"
                        : "Seç"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
