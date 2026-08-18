import { X } from "lucide-react";
import { Button } from "../../components/Button";
import { Card } from "../../components/Surface";
import type { GraphNode } from "../../types/documents";

const ENTITY_KIND_LABELS: Record<string, string> = {
  kurum: "Kurum",
  kisi: "Kişi",
  diger: "Diğer",
};

const ATTRIBUTE_LABELS: Record<string, string> = {
  sayi: "Sayı",
  tarih: "Tarih",
  konu: "Konu",
  muhatap: "Muhatap",
  gonderen_kurum: "Gönderen kurum",
  ivedilik: "İvedilik",
};

function showAttribute(value: unknown): string {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

/** The click-a-node-to-see-its-attributes panel the unified graph is built
 * around -- every node type renders a different payload from the same flat
 * `GraphNode` shape (see that dataclass's own docstring for why it stays a
 * flat bag of optionals rather than a per-type union), so this component is
 * one big switch on `node.node_type`, not five separate components. */
export function NodeInspector({
  node,
  onClose,
  onOpenDocument,
}: {
  node: GraphNode | null;
  onClose: () => void;
  onOpenDocument?: (storagePath: string) => void;
}) {
  if (!node) return null;

  return (
    <Card className="node-inspector" role="complementary" aria-label="Düğüm ayrıntıları">
      <div className="node-inspector-header">
        <h3>{node.label}</h3>
        <Button variant="ghost" size="sm" aria-label="Kapat" onClick={onClose}>
          <X />
        </Button>
      </div>

      {node.node_type === "document" && (
        <div className="node-inspector-body">
          <dl className="node-inspector-attributes">
            {(["sayi", "tarih", "konu", "muhatap", "gonderen_kurum", "ivedilik"] as const).map((key) => (
              <div key={key}>
                <dt>{ATTRIBUTE_LABELS[key]}</dt>
                <dd>{showAttribute(node.attributes[key])}</dd>
              </div>
            ))}
          </dl>
          {node.attributes.summary != null && node.attributes.summary !== "" && (
            <p className="node-inspector-summary">{String(node.attributes.summary)}</p>
          )}
          {node.attributes.missing_field_count != null && (
            <p className="node-inspector-note">
              {node.attributes.missing_field_count} eksik alan
            </p>
          )}
          {node.storage_path && onOpenDocument && (
            <Button onClick={() => onOpenDocument(node.storage_path!)}>Belgeyi aç</Button>
          )}
        </div>
      )}

      {node.node_type === "entity" && (
        <div className="node-inspector-body">
          <p className="node-inspector-note">
            {`${node.entity_kind ? ENTITY_KIND_LABELS[node.entity_kind] ?? node.entity_kind : "Sınıflandırılmamış"} · ${
              node.document_count ?? 0
            } belge`}
          </p>
          {node.surface_forms.length > 1 && (
            <>
              <p className="node-inspector-note">
                Bu düğüm {node.surface_forms.length} farklı yazım biçiminden birleştirildi:
              </p>
              <ul className="node-inspector-surface-forms">
                {node.surface_forms.map((form) => (
                  <li key={form}>{form}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {node.node_type === "madde" && (
        <div className="node-inspector-body">
          <p className="node-inspector-note">
            {node.field_labels.join(", ") || "Alan bilgisi yok"}
          </p>
          <p className="node-inspector-note">{`${node.document_count ?? 0} evrakta ihlal`}</p>
        </div>
      )}

      {node.node_type === "kanun" && (
        <div className="node-inspector-body">
          <p className="node-inspector-note">Kanun no: {node.kanun}</p>
        </div>
      )}

      {node.node_type === "konu" && (
        <div className="node-inspector-body">
          <p className="node-inspector-note">{node.document_count ?? 0} evrakta geçiyor</p>
        </div>
      )}
    </Card>
  );
}
