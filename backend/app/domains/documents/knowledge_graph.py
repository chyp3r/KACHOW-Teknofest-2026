"""Pure builder for the compliance knowledge graph -- Document x Madde x Kanun.

Every candidate edge type was measured against the real corpus before this
module was designed (see the session's plan file for the full table). Two
survive:

- `ihlal` (Document -> Madde, `source_kind="rule"`): from `missing_fields`,
  itself produced by the hand-maintained `REQUIRED_FIELD_RULES` table
  (`app.ai.compliance.field_rule`). Deterministic and guaranteed present --
  see `test_mevzuat_citation.py`'s contract test, which asserts every rule
  citation resolves fully. **This is the only edge source the headline
  insight (`top_breached_madde`) may read.**
- `atif` (Document -> Madde or Kanun, `source_kind="llm"`): from the model's
  free-text `mevzuat_references`. Not reproducible across re-analyses of the
  same document, so it never drives the headline -- only the rule edges do.

Deliberately excluded: any node keyed by extracted document text (an
institution name, a signer, an entity). Every candidate was measured and
each one puts OCR damage straight into *node identity* -- `muhatap` needs
whitespace-repair before it yields anything, `entities` needs four surface
forms of "TBMM" resolved to one node, `gonderen_kurum` yields nothing at
all. Excluding them makes an invariant hold absolutely: no node id in this
graph is ever derived from extracted document text. Document ids come from
the caller (a Postgres primary key); Madde/Kanun ids come from
`app.ai.compliance.resolve_citation` and a curated law registry.

The Madde node id is `madde:{kanun}:{madde}`, composed rather than bare --
`canonical_legislation` keeps law and article in separate namespaces on
purpose (see its own docstring), but a graph needs the join: measured on the
real corpus, article 4 exists under both kanun 2646 (RYUEHY) and kanun 3071,
and a bare `madde:4` id would silently merge two unrelated articles.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.ai.compliance import resolve_citation
from app.ai.compliance.mevzuat_citation import KANUN_TITLE


@dataclass(frozen=True)
class MissingFieldInput:
    """One `MissingField` as the graph builder needs it -- see
    `app.ai.compliance.evrak_field.MissingField` for the source shape this
    mirrors."""

    key: str
    label: str
    severity: str
    mevzuat: str
    reason: str


@dataclass(frozen=True)
class MevzuatReferenceInput:
    """One `mevzuat_references[]` entry -- see
    `app.domains.documents.schema.document_schema.MevzuatReferenceSchema`."""

    mevzuat: str
    aciklama: str


@dataclass(frozen=True)
class DocumentGraphInput:
    """One document's contribution to the graph, already loaded from
    wherever the caller keeps it (Postgres row + analysis cache, or a test
    fixture) -- this module never reads anything itself."""

    storage_path: str
    file_name: str
    document_type_label: Optional[str] = None
    compliance_status: Optional[str] = None
    has_analysis: bool = True
    missing_fields: tuple[MissingFieldInput, ...] = ()
    mevzuat_references: tuple[MevzuatReferenceInput, ...] = ()


@dataclass(frozen=True)
class GraphNode:
    """A Document, Madde or Kanun node. Fields not meaningful for a given
    `node_type` are left at their default -- see the module docstring for
    why this stays a flat bag of optional fields rather than a tagged
    union: three node kinds sharing one shape is simpler to build, test and
    serialise than three dataclasses plus a discriminator."""

    id: str
    node_type: str  # "document" | "madde" | "kanun"
    label: str
    storage_path: Optional[str] = None
    file_name: Optional[str] = None
    document_type_label: Optional[str] = None
    compliance_status: Optional[str] = None
    has_analysis: Optional[bool] = None
    kanun: Optional[str] = None
    madde: Optional[str] = None
    field_labels: tuple[str, ...] = ()
    document_count: Optional[int] = None


@dataclass(frozen=True)
class GraphEdge:
    """An `ihlal` (rule) or `atif` (LLM) edge. See `GraphNode` for why the
    two shapes share one dataclass."""

    source: str
    target: str
    edge_type: str  # "ihlal" | "atif"
    source_kind: str  # "rule" | "llm"
    field_key: Optional[str] = None
    field_label: Optional[str] = None
    severity: Optional[str] = None
    reason: Optional[str] = None
    aciklama: Optional[str] = None
    raw: Optional[str] = None


@dataclass(frozen=True)
class TopBreachedMadde:
    """The headline stat: the madde breached by the most *distinct*
    documents, counted from `ihlal` edges only (never `atif` -- see the
    module docstring)."""

    madde_id: str
    kanun: str
    madde: str
    field_labels: tuple[str, ...]
    document_count: int


@dataclass(frozen=True)
class GraphInsights:
    document_count: int
    madde_count: int
    kanun_count: int
    rule_edge_count: int
    llm_edge_count: int
    unresolved_reference_count: int
    top_breached_madde: Optional[TopBreachedMadde]


@dataclass(frozen=True)
class KnowledgeGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    insights: GraphInsights


@dataclass
class _MaddeAccumulator:
    kanun: str
    madde: str
    field_labels: list[str] = field(default_factory=list)
    rule_document_ids: set[str] = field(default_factory=set)


def build_knowledge_graph(entries: list[DocumentGraphInput]) -> KnowledgeGraph:
    """Build the corpus-wide compliance graph from already-loaded document data.

    Args:
        entries: One `DocumentGraphInput` per document. A document with no
            cached analysis still gets an entry (`has_analysis=False`, empty
            field/reference tuples) -- it must never be skipped, or a
            headline like "7 of 9" would be computed against the wrong 9.

    Returns:
        The graph: every document as an isolated-or-connected node, every
        madde/kanun reached by at least one edge, and the insights the
        headline stat is drawn from.
    """
    document_nodes: list[GraphNode] = []
    madde_index: dict[str, _MaddeAccumulator] = {}
    kanun_nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    rule_edge_count = 0
    llm_edge_count = 0
    unresolved_reference_count = 0

    def ensure_kanun(kanun: str) -> str:
        kanun_id = f"kanun:{kanun}"
        if kanun_id not in kanun_nodes:
            kanun_nodes[kanun_id] = GraphNode(
                id=kanun_id,
                node_type="kanun",
                label=KANUN_TITLE.get(kanun, f"{kanun} sayılı mevzuat"),
                kanun=kanun,
            )
        return kanun_id

    def ensure_madde(kanun: str, madde: str) -> str:
        ensure_kanun(kanun)
        madde_id = f"madde:{kanun}:{madde}"
        if madde_id not in madde_index:
            madde_index[madde_id] = _MaddeAccumulator(kanun=kanun, madde=madde)
        return madde_id

    for entry in entries:
        doc_id = f"doc:{entry.storage_path}"
        document_nodes.append(
            GraphNode(
                id=doc_id,
                node_type="document",
                label=entry.file_name,
                storage_path=entry.storage_path,
                file_name=entry.file_name,
                document_type_label=entry.document_type_label,
                compliance_status=entry.compliance_status,
                has_analysis=entry.has_analysis,
            )
        )

        for missing_field in entry.missing_fields:
            citation = resolve_citation(missing_field.mevzuat)
            if citation.kanun is None or citation.madde is None:
                # REQUIRED_FIELD_RULES is a closed, hand-maintained set whose
                # citations are contract-tested to fully resolve (see
                # test_mevzuat_citation.py) -- this branch should be
                # unreachable for real data. Skip rather than crash the
                # whole graph if it is ever violated.
                continue
            madde_id = ensure_madde(citation.kanun, citation.madde)
            accumulator = madde_index[madde_id]
            if missing_field.label not in accumulator.field_labels:
                accumulator.field_labels.append(missing_field.label)
            accumulator.rule_document_ids.add(doc_id)
            edges.append(
                GraphEdge(
                    source=doc_id,
                    target=madde_id,
                    edge_type="ihlal",
                    source_kind="rule",
                    field_key=missing_field.key,
                    field_label=missing_field.label,
                    severity=missing_field.severity,
                    reason=missing_field.reason,
                )
            )
            rule_edge_count += 1

        for reference in entry.mevzuat_references:
            citation = resolve_citation(reference.mevzuat)
            if citation.kanun is None:
                unresolved_reference_count += 1
                continue
            target_id = (
                ensure_madde(citation.kanun, citation.madde)
                if citation.madde is not None
                else ensure_kanun(citation.kanun)
            )
            edges.append(
                GraphEdge(
                    source=doc_id,
                    target=target_id,
                    edge_type="atif",
                    source_kind="llm",
                    aciklama=reference.aciklama,
                    raw=reference.mevzuat,
                )
            )
            llm_edge_count += 1

    madde_nodes = [
        GraphNode(
            id=madde_id,
            node_type="madde",
            label=f"m.{accumulator.madde}",
            kanun=accumulator.kanun,
            madde=accumulator.madde,
            field_labels=tuple(accumulator.field_labels),
            document_count=len(accumulator.rule_document_ids),
        )
        for madde_id, accumulator in madde_index.items()
    ]

    top_breached_madde = None
    if madde_nodes:
        # Sorted ascending by id first so `max` (which returns the first
        # maximal element on a tie) breaks ties toward the lexicographically
        # smallest madde id, keeping the winner deterministic.
        winner = max(sorted(madde_nodes, key=lambda node: node.id), key=lambda node: node.document_count)
        if winner.document_count > 0:
            top_breached_madde = TopBreachedMadde(
                madde_id=winner.id,
                kanun=winner.kanun,
                madde=winner.madde,
                field_labels=winner.field_labels,
                document_count=winner.document_count,
            )

    insights = GraphInsights(
        document_count=len(document_nodes),
        madde_count=len(madde_nodes),
        kanun_count=len(kanun_nodes),
        rule_edge_count=rule_edge_count,
        llm_edge_count=llm_edge_count,
        unresolved_reference_count=unresolved_reference_count,
        top_breached_madde=top_breached_madde,
    )

    return KnowledgeGraph(
        nodes=tuple(document_nodes) + tuple(madde_nodes) + tuple(kanun_nodes.values()),
        edges=tuple(edges),
        insights=insights,
    )
