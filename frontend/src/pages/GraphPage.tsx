import { useNavigate } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";
import { Alert } from "../components/Surface";
import { KnowledgeGraphView } from "../features/graph/KnowledgeGraphView";
import { useKnowledgeGraph } from "../hooks/useKnowledgeGraph";

export function GraphPage() {
  const navigate = useNavigate();
  const { graph, loading, error } = useKnowledgeGraph();

  return (
    <div className="page page-scroll graph-page">
      <PageHeader
        title="Mevzuat Haritası"
        description="Evraklar ile mevzuat maddeleri arasındaki uyum ilişkilerinin grafiği."
      />

      {error && <Alert variant="error">{error}</Alert>}

      <KnowledgeGraphView
        graph={graph}
        loading={loading}
        onSelectDocument={(storagePath) =>
          navigate(`/documents/${encodeURIComponent(storagePath)}`)
        }
      />
    </div>
  );
}
