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

**v2 update:** a fourth and fifth node type, Entity and Konu, were added --
see `entity_resolution.py`. The v1 exclusion of any node keyed by extracted
document text was reversed, not abandoned: every candidate (`muhatap`,
`entities`, `gonderen_kurum`) was measured and each one puts OCR damage
straight into naive *node identity* if used raw -- `muhatap` needs
whitespace/markdown repair before it yields anything, `entities` needs four
surface forms of "TBMM" resolved to one node. Rather than exclude these
sources, `entity_resolution.resolve_entities` resolves them: the node id is
a canonicalized key (a pure function of the raw string, never the raw
string itself), and every raw surface form that merged into it is retained
on the node for disclosure. The invariant that survives is narrower but
still absolute: no node id is *directly* the raw extracted text. Document
ids come from the caller (a Postgres primary key); Madde/Kanun ids come from
`app.ai.compliance.resolve_citation` and a curated law registry; Entity/Konu
ids come from the canonicalizer.

`muhatap`, `gonderen_kurum` and every `entities[]` mention across the whole
corpus are resolved through one shared canonicalization pass -- this is what
lets a document's addressee and another document's mention of the same
institution collapse onto one node (measured: `muhatap`'s
"TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA" and an `entities[]` mention of
"Türkiye Büyük Millet Meclisi Başkanlığı" canonicalize identically). `konu`
is resolved through a separate pass into its own `konu:` namespace -- a
shared topic string is not the same kind of thing as a shared institution,
and mixing the namespaces would let a topic and an institution collide.

The Madde node id is `madde:{kanun}:{madde}`, composed rather than bare --
`canonical_legislation` keeps law and article in separate namespaces on
purpose (see its own docstring), but a graph needs the join: measured on the
real corpus, article 4 exists under both kanun 2646 (RYUEHY) and kanun 3071,
and a bare `madde:4` id would silently merge two unrelated articles.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from app.ai.compliance import resolve_citation
from app.ai.compliance.mevzuat_citation import KANUN_TITLE
from app.domains.documents.entity_resolution import resolve_entities


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
    #: Entity/Konu/attribute-payload sources, all optional -- a fixture or
    #: caller that never sets these (e.g. every v1 test, `_load_fixture`)
    #: must produce zero entity/konu nodes and zero new edges, byte-for-byte
    #: identical to the graph that shipped before this module grew them.
    sayi: Optional[str] = None
    tarih: Optional[str] = None
    konu: Optional[str] = None
    muhatap: Optional[str] = None
    gonderen_kurum: Optional[str] = None
    ivedilik: Optional[str] = None
    summary: Optional[str] = None
    entities: tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphNode:
    """A Document, Madde or Kanun node. Fields not meaningful for a given
    `node_type` are left at their default -- see the module docstring for
    why this stays a flat bag of optional fields rather than a tagged
    union: three node kinds sharing one shape is simpler to build, test and
    serialise than three dataclasses plus a discriminator."""

    id: str
    node_type: str  # "document" | "madde" | "kanun" | "entity" | "konu"
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
    #: "entity" nodes only -- "kurum" | "kisi" | "diger", see
    #: entity_resolution._classify_kind. Heuristic, not authoritative.
    entity_kind: Optional[str] = None
    #: "entity" nodes only -- every raw surface form that merged into this
    #: node, so the inspector can disclose the merge rather than hide it.
    surface_forms: tuple[str, ...] = ()
    #: "document" nodes only, for now -- the node inspector's per-type
    #: payload. A generic dict rather than more typed fields because this
    #: is where the shape genuinely varies by node_type and is expected to
    #: grow; madde/kanun/entity nodes already have everything they need in
    #: the typed fields above.
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    """An `ihlal` (rule) or `atif` (LLM) edge. See `GraphNode` for why the
    two shapes share one dataclass."""

    source: str
    target: str
    edge_type: str  # "ihlal" | "atif" | "muhatap" | "gonderen" | "bahseder" | "konu"
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
    entity_count: int
    konu_count: int
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


@dataclass
class _NamedGroupAccumulator:
    """Shared by the Entity and Konu accumulation passes -- both are
    "resolve a bag of raw strings, then count distinct documents per
    resolved group" with the same shape, differing only in whether `kind`/
    `surface_forms` are meaningful (Entity) or left at their defaults (Konu,
    which has no analogous concept -- a topic isn't a kurum/kişi and its
    canonical key already *is* its only surface form worth keeping)."""

    label: str
    kind: Optional[str] = None
    surface_forms: tuple[str, ...] = ()
    document_ids: set[str] = field(default_factory=set)


def build_knowledge_graph(entries: list[DocumentGraphInput]) -> KnowledgeGraph:
    """Build the corpus-wide graph from already-loaded document data.

    Args:
        entries: One `DocumentGraphInput` per document. A document with no
            cached analysis still gets an entry (`has_analysis=False`, empty
            field/reference tuples) -- it must never be skipped, or a
            headline like "7 of 9" would be computed against the wrong 9.

    Returns:
        The graph: every document as an isolated-or-connected node, every
        madde/kanun/entity/konu reached by at least one edge, and the
        insights the headline stat is drawn from.
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

    # --- Entity/Konu resolution: one pass over every raw string in the
    # whole corpus, *before* the per-document loop below assigns edges.
    # This is what lets one document's `muhatap` and another document's
    # `entities[]` mention of the same institution collapse onto one node
    # -- resolving per-document would never see the cross-document overlap.
    # Konu gets its own, separately-resolved namespace (see
    # `_NamedGroupAccumulator`'s docstring).
    all_entity_raw = [
        raw
        for entry in entries
        for raw in (entry.muhatap, entry.gonderen_kurum, *entry.entities)
        if raw
    ]
    resolved_entities = resolve_entities(all_entity_raw)
    all_konu_raw = [entry.konu for entry in entries if entry.konu]
    resolved_konu = resolve_entities(all_konu_raw)

    entity_accumulators: dict[str, _NamedGroupAccumulator] = {}
    konu_accumulators: dict[str, _NamedGroupAccumulator] = {}

    def ensure_entity(raw: str) -> str:
        resolved = resolved_entities[raw]
        entity_id = f"entity:{resolved.key}"
        if entity_id not in entity_accumulators:
            entity_accumulators[entity_id] = _NamedGroupAccumulator(
                label=resolved.label, kind=resolved.kind, surface_forms=resolved.surface_forms,
            )
        return entity_id

    def ensure_konu(raw: str) -> str:
        resolved = resolved_konu[raw]
        konu_id = f"konu:{resolved.key}"
        if konu_id not in konu_accumulators:
            konu_accumulators[konu_id] = _NamedGroupAccumulator(label=resolved.label)
        return konu_id

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
                attributes={
                    "sayi": entry.sayi,
                    "tarih": entry.tarih,
                    "konu": entry.konu,
                    "muhatap": entry.muhatap,
                    "gonderen_kurum": entry.gonderen_kurum,
                    "ivedilik": entry.ivedilik,
                    "summary": entry.summary,
                    "missing_field_count": len(entry.missing_fields),
                },
            )
        )

        if entry.muhatap:
            entity_id = ensure_entity(entry.muhatap)
            entity_accumulators[entity_id].document_ids.add(doc_id)
            edges.append(GraphEdge(source=doc_id, target=entity_id, edge_type="muhatap", source_kind="rule"))
            rule_edge_count += 1

        if entry.gonderen_kurum:
            entity_id = ensure_entity(entry.gonderen_kurum)
            entity_accumulators[entity_id].document_ids.add(doc_id)
            edges.append(GraphEdge(source=doc_id, target=entity_id, edge_type="gonderen", source_kind="rule"))
            rule_edge_count += 1

        # `entities[]` can repeat a mention within one document (the model
        # is not asked to deduplicate); collapse to at most one `bahseder`
        # edge per resolved entity per document, or a repeated mention
        # would silently inflate that entity's document_count-adjacent edge
        # count without adding any real information.
        seen_entity_ids: set[str] = set()
        for raw_entity in entry.entities:
            if not raw_entity:
                continue
            entity_id = ensure_entity(raw_entity)
            if entity_id in seen_entity_ids:
                continue
            seen_entity_ids.add(entity_id)
            entity_accumulators[entity_id].document_ids.add(doc_id)
            edges.append(GraphEdge(source=doc_id, target=entity_id, edge_type="bahseder", source_kind="llm"))
            llm_edge_count += 1

        if entry.konu:
            konu_id = ensure_konu(entry.konu)
            konu_accumulators[konu_id].document_ids.add(doc_id)
            edges.append(GraphEdge(source=doc_id, target=konu_id, edge_type="konu", source_kind="rule"))
            rule_edge_count += 1

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

    entity_nodes = [
        GraphNode(
            id=entity_id,
            node_type="entity",
            label=accumulator.label,
            entity_kind=accumulator.kind,
            surface_forms=accumulator.surface_forms,
            document_count=len(accumulator.document_ids),
        )
        for entity_id, accumulator in entity_accumulators.items()
    ]

    konu_nodes = [
        GraphNode(
            id=konu_id,
            node_type="konu",
            label=accumulator.label,
            document_count=len(accumulator.document_ids),
        )
        for konu_id, accumulator in konu_accumulators.items()
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
        entity_count=len(entity_nodes),
        konu_count=len(konu_nodes),
        rule_edge_count=rule_edge_count,
        llm_edge_count=llm_edge_count,
        unresolved_reference_count=unresolved_reference_count,
        top_breached_madde=top_breached_madde,
    )

    return KnowledgeGraph(
        nodes=(
            tuple(document_nodes)
            + tuple(madde_nodes)
            + tuple(kanun_nodes.values())
            + tuple(entity_nodes)
            + tuple(konu_nodes)
        ),
        edges=tuple(edges),
        insights=insights,
    )
