import { useNavigate } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";
import { Alert } from "../components/Surface";
import { EntityGraphView } from "../features/graph/EntityGraphView";
import { useKnowledgeGraph } from "../hooks/useKnowledgeGraph";

export function GraphPage() {
  const navigate = useNavigate();
  const { graph, loading, error } = useKnowledgeGraph();

  return (
    <div className="page page-scroll graph-page">
      <PageHeader
        title="Mevzuat Haritası"
        description="Evraklar, kurumlar/kişiler ve mevzuat maddeleri arasındaki ilişkilerin grafiği."
      />

      {error && <Alert variant="error">{error}</Alert>}

      <EntityGraphView
        graph={graph}
        loading={loading}
        onSelectDocument={(storagePath) =>
          navigate(`/documents/${encodeURIComponent(storagePath)}`)
        }
      />
    </div>
  );
}
