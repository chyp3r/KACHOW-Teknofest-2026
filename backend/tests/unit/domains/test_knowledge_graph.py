"""Unit tests for the pure compliance-knowledge-graph builder.

No I/O, no async, no mocks -- `build_knowledge_graph` is a pure function over
already-loaded document data, so every test here constructs its input by hand
(or, for the golden-corpus test, from fixture files copied under
tests/fixtures/knowledge_graph/ -- never read from backend/storage_data/,
which is real upload state and not a fixed test asset).
"""

import json
import pathlib

from app.domains.documents.knowledge_graph import (
    DocumentGraphInput,
    MevzuatReferenceInput,
    MissingFieldInput,
    build_knowledge_graph,
)

FIXTURES_DIR = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "knowledge_graph"


def _missing_field(key, label, mevzuat, reason="çünkü mevzuat öyle diyor", severity="zorunlu"):
    return MissingFieldInput(key=key, label=label, severity=severity, mevzuat=mevzuat, reason=reason)


def _entry(storage_path, missing_fields=(), mevzuat_references=(), has_analysis=True):
    return DocumentGraphInput(
        storage_path=storage_path,
        file_name=f"{storage_path}.pdf",
        document_type_label="Resmî Yazı",
        compliance_status="incomplete" if missing_fields else "compliant",
        has_analysis=has_analysis,
        missing_fields=tuple(missing_fields),
        mevzuat_references=tuple(mevzuat_references),
    )


def _load_fixture(name: str) -> DocumentGraphInput:
    data = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
    return DocumentGraphInput(
        storage_path=data["storage_path"],
        file_name=data["file_name"],
        document_type_label=data["document_type_label"],
        compliance_status=data["compliance_status"],
        has_analysis=True,
        missing_fields=tuple(
            MissingFieldInput(
                key=mf["key"], label=mf["label"], severity=mf["severity"],
                mevzuat=mf["mevzuat"], reason=mf["reason"],
            )
            for mf in data["missing_fields"]
        ),
        mevzuat_references=tuple(
            MevzuatReferenceInput(mevzuat=ref["mevzuat"], aciklama=ref["aciklama"])
            for ref in data["mevzuat_references"]
        ),
    )


def test_one_missing_field_produces_document_madde_kanun_and_one_ihlal_edge():
    entry = _entry(
        "uploads/a.pdf",
        missing_fields=[_missing_field(
            "sayi", "Sayı",
            "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik m.11",
            reason="Belgelerde sayı bulunması zorunludur.",
        )],
    )

    graph = build_knowledge_graph([entry])

    node_ids = {node.id for node in graph.nodes}
    assert node_ids == {"doc:uploads/a.pdf", "madde:2646:11", "kanun:2646"}
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.source == "doc:uploads/a.pdf"
    assert edge.target == "madde:2646:11"
    assert edge.edge_type == "ihlal"
    assert edge.source_kind == "rule"
    assert edge.field_key == "sayi"
    assert edge.field_label == "Sayı"
    assert edge.severity == "zorunlu"
    assert edge.reason == "Belgelerde sayı bulunması zorunludur."


def test_same_article_number_under_different_laws_produces_two_madde_nodes():
    entry = _entry(
        "uploads/b.pdf",
        missing_fields=[
            _missing_field("muhatap", "Muhatap", "RYUEHY m.4"),
            _missing_field(
                "basvuran_adi", "Başvuranın adı ve soyadı",
                "3071 sayılı Dilekçe Hakkının Kullanılmasına Dair Kanun m.4",
            ),
        ],
    )

    graph = build_knowledge_graph([entry])

    madde_ids = {node.id for node in graph.nodes if node.node_type == "madde"}
    assert madde_ids == {"madde:2646:4", "madde:3071:4"}


def test_rule_edge_count_equals_total_missing_fields_across_all_inputs():
    entries = [
        _entry("uploads/a.pdf", missing_fields=[
            _missing_field("sayi", "Sayı", "RYUEHY m.11"),
            _missing_field("tarih", "Tarih", "RYUEHY m.12"),
        ]),
        _entry("uploads/b.pdf", missing_fields=[
            _missing_field("konu", "Konu", "RYUEHY m.13"),
        ]),
    ]

    graph = build_knowledge_graph(entries)

    rule_edges = [edge for edge in graph.edges if edge.source_kind == "rule"]
    assert len(rule_edges) == 3
    assert graph.insights.rule_edge_count == 3


def test_mevzuat_reference_resolves_through_three_tiers():
    entry = _entry(
        "uploads/c.pdf",
        mevzuat_references=[
            MevzuatReferenceInput(
                mevzuat="RYUEHY MADDE 15- (3)",
                aciklama="İlgi bölümü kuralına atıf.",
            ),
            MevzuatReferenceInput(
                mevzuat="Devlet Memurları Kanunu",
                aciklama="Kanun düzeyinde bir atıf, madde numarası yok.",
            ),
            MevzuatReferenceInput(
                mevzuat="Tamamen alakasız bir cümle, hiçbir mevzuata atıf yok.",
                aciklama="Çözülemeyen bir atıf.",
            ),
        ],
    )

    graph = build_knowledge_graph([entry])

    llm_edges = [edge for edge in graph.edges if edge.source_kind == "llm"]
    assert len(llm_edges) == 2  # the unresolved one produces no edge

    madde_edge = next(e for e in llm_edges if e.target == "madde:2646:15")
    assert madde_edge.edge_type == "atif"
    assert madde_edge.aciklama == "İlgi bölümü kuralına atıf."
    assert madde_edge.raw == "RYUEHY MADDE 15- (3)"

    kanun_edge = next(e for e in llm_edges if e.target == "kanun:657")
    assert kanun_edge.edge_type == "atif"

    assert graph.insights.llm_edge_count == 2
    assert graph.insights.unresolved_reference_count == 1


def test_one_document_missing_two_fields_under_the_same_madde_counts_once():
    """The distinct-document counting trap: a document missing both
    imza_sahibi and imza_unvani produces two rule edges into madde:2646:17,
    but the madde's document_count must read 1, not 2 -- otherwise the
    headline stat overstates how many documents are actually affected."""
    entry = _entry(
        "uploads/d.pdf",
        missing_fields=[
            _missing_field("imza_sahibi", "İmza sahibi", "RYUEHY m.17"),
            _missing_field("imza_unvani", "İmza sahibinin unvanı", "RYUEHY m.17"),
        ],
    )

    graph = build_knowledge_graph([entry])

    madde_17 = next(n for n in graph.nodes if n.id == "madde:2646:17")
    edges_into_madde_17 = [e for e in graph.edges if e.target == "madde:2646:17"]
    assert len(edges_into_madde_17) == 2
    assert madde_17.document_count == 1


def test_document_with_no_cached_analysis_is_an_isolated_node_not_skipped():
    entries = [
        _entry("uploads/has-analysis.pdf", missing_fields=[
            _missing_field("sayi", "Sayı", "RYUEHY m.11"),
        ]),
        _entry("uploads/no-analysis.pdf", has_analysis=False),
    ]

    graph = build_knowledge_graph(entries)

    document_nodes = [n for n in graph.nodes if n.node_type == "document"]
    assert len(document_nodes) == 2
    assert graph.insights.document_count == 2

    isolated = next(n for n in document_nodes if n.storage_path == "uploads/no-analysis.pdf")
    assert isolated.has_analysis is False
    assert not any(e.source == isolated.id for e in graph.edges)


def test_empty_input_returns_an_empty_graph_without_raising():
    graph = build_knowledge_graph([])

    assert graph.nodes == ()
    assert graph.edges == ()
    assert graph.insights.document_count == 0
    assert graph.insights.madde_count == 0
    assert graph.insights.kanun_count == 0
    assert graph.insights.rule_edge_count == 0
    assert graph.insights.llm_edge_count == 0
    assert graph.insights.unresolved_reference_count == 0
    assert graph.insights.top_breached_madde is None


def _golden_graph():
    """Rebuilding per-test rather than sharing a class-scoped fixture: the
    builder is a pure, sub-millisecond function reading three small fixture
    files, and pytest-asyncio's auto mode does not play well with
    class-scoped fixtures in this project's pytest version."""
    entries = [_load_fixture(name) for name in ("cy050.json", "cy034.json", "cy012.json")]
    return build_knowledge_graph(entries)


class TestGoldenCorpus:
    """Pins the whole pipeline to three real (fixture-copied) analyses.

    Every number below was hand-derived from the fixture JSON before this
    test was written -- see the session's plan file for the worked
    calculation -- so a change to this test's expectations should come with
    a re-derivation, not a "make it pass" edit.
    """

    def test_node_and_edge_totals(self):
        graph = _golden_graph()
        assert graph.insights.document_count == 3
        assert graph.insights.madde_count == 7  # m.4, 10, 12, 13, 14, 15, 17
        assert graph.insights.kanun_count == 1  # every citation in this fixture set is RYUEHY
        assert graph.insights.rule_edge_count == 11  # 4 + 4 + 3 missing_fields
        assert graph.insights.llm_edge_count == 9  # 3 + 3 + 3 mevzuat_references, all resolve
        assert graph.insights.unresolved_reference_count == 0
        assert len(graph.nodes) == 3 + 7 + 1
        assert len(graph.edges) == 11 + 9

    def test_expected_madde_node_ids(self):
        graph = _golden_graph()
        madde_ids = {n.id for n in graph.nodes if n.node_type == "madde"}
        assert madde_ids == {
            "madde:2646:4", "madde:2646:10", "madde:2646:12", "madde:2646:13",
            "madde:2646:14", "madde:2646:15", "madde:2646:17",
        }

    def test_headline_is_m17_breached_by_all_three_documents(self):
        graph = _golden_graph()
        top = graph.insights.top_breached_madde
        assert top is not None
        assert top.madde_id == "madde:2646:17"
        assert top.kanun == "2646"
        assert top.madde == "17"
        assert top.document_count == 3
        assert set(top.field_labels) == {"İmza sahibi", "İmza sahibinin unvanı"}
