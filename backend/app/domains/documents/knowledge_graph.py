"""Uyumluluk bilgi grafiği için saf (pure) oluşturucu -- Evrak x Madde x Kanun.

Bu modül tasarlanmadan önce her aday kenar (edge) türü gerçek korpus
üzerinde ölçüldü (tam tabloyu görmek için oturumun plan dosyasına bakın).
İki tanesi hayatta kaldı:

- `ihlal` (Evrak -> Madde, `source_kind="rule"`): elle bakımı yapılan
  `REQUIRED_FIELD_RULES` tablosunun (`app.ai.compliance.field_rule`) ürettiği
  `missing_fields`'tan gelir. Deterministiktir ve varlığı garantidir --
  bkz. `test_mevzuat_citation.py`'nin, her kural atfının eksiksiz çözüldüğünü
  doğrulayan sözleşme (contract) testi. **Manşet içgörünün
  (`top_breached_madde`) okuyabileceği tek kenar kaynağı budur.**
- `atif` (Evrak -> Madde veya Kanun, `source_kind="llm"`): modelin serbest
  metin `mevzuat_references` alanından gelir. Aynı evrakın tekrar analiz
  edilmesi durumunda yeniden üretilebilir olmadığından manşeti hiçbir zaman
  belirlemez -- yalnızca kural kenarları belirler.

**v2 güncellemesi:** dördüncü ve beşinci düğüm türü olarak Entity ve Konu
eklendi -- bkz. `entity_resolution.py`. v1'de, çıkarılan evrak metniyle
anahtarlanan herhangi bir düğümün dışlanması kararı tersine çevrildi,
tamamen terk edilmedi: her aday (`muhatap`, `entities`, `gonderen_kurum`)
ölçüldü ve her biri, ham haliyle kullanıldığında OCR hasarını doğrudan saf
*düğüm kimliğine* taşıyor -- `muhatap` bir şey üretmeden önce boşluk/markdown
onarımı gerektiriyor, `entities` ise "TBMM"nin dört farklı yüzey formunun tek
bir düğüme çözülmesini gerektiriyor. Bu kaynakları dışlamak yerine
`entity_resolution.resolve_entities` bunları çözüyor: düğüm kimliği
kanonikleştirilmiş bir anahtardır (ham dizgenin saf bir fonksiyonu, asla ham
dizgenin kendisi değil) ve o düğüme birleşen her ham yüzey formu, ifşa
edilebilmesi için düğüm üzerinde saklanır. Hayatta kalan değişmez kural daha
dar ama yine de mutlaktır: hiçbir düğüm kimliği *doğrudan* ham çıkarılmış
metin değildir. Evrak kimlikleri çağırandan gelir (bir Postgres birincil
anahtarı); Madde/Kanun kimlikleri `app.ai.compliance.resolve_citation`'dan
ve derlenmiş bir kanun sicilinden gelir; Entity/Konu kimlikleri ise
kanonikleştiriciden gelir.

`muhatap`, `gonderen_kurum` ve tüm korpustaki her `entities[]` bahsi, tek bir
paylaşılan kanonikleştirme geçişinden çözülür -- bu, bir evrakın muhatabı ile
başka bir evrakın aynı kuruma yaptığı bahsin tek bir düğümde birleşmesini
sağlar (ölçüldü: `muhatap`'taki "TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA"
ile `entities[]` içindeki "Türkiye Büyük Millet Meclisi Başkanlığı" bahsi
aynı şekilde kanonikleşiyor). `konu` ise ayrı bir geçişle kendi `konu:`
ad alanına çözülür -- paylaşılan bir konu dizgesi, paylaşılan bir kurumla
aynı türden bir şey değildir ve ad alanlarını karıştırmak bir konu ile bir
kurumun çakışmasına yol açardı.

Madde düğüm kimliği, çıplak değil bileşik olarak `madde:{kanun}:{madde}`
şeklindedir -- `canonical_legislation` kanun ve maddeyi bilinçli olarak ayrı
ad alanlarında tutar (kendi docstring'ine bakın), ama grafiğin birleştirme
(join) yapması gerekir: gerçek korpus üzerinde ölçüldüğünde, madde 4 hem
2646 sayılı kanun (RYUEHY) hem de 3071 sayılı kanun altında var oluyor ve
çıplak bir `madde:4` kimliği iki ilgisiz maddeyi sessizce birleştirirdi.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from app.ai.compliance import resolve_citation
from app.ai.compliance.mevzuat_citation import KANUN_TITLE
from app.domains.documents.entity_resolution import resolve_entities


@dataclass(frozen=True)
class MissingFieldInput:
    """Grafik oluşturucunun ihtiyaç duyduğu haliyle tek bir `MissingField` --
    karşılık geldiği kaynak yapı için bkz.
    `app.ai.compliance.evrak_field.MissingField`."""

    key: str
    label: str
    severity: str
    mevzuat: str
    reason: str


@dataclass(frozen=True)
class MevzuatReferenceInput:
    """Tek bir `mevzuat_references[]` girdisi -- bkz.
    `app.domains.documents.schema.document_schema.MevzuatReferenceSchema`."""

    mevzuat: str
    aciklama: str


@dataclass(frozen=True)
class DocumentGraphInput:
    """Bir evrakın grafiğe katkısı; çağıranın tuttuğu yerden zaten
    yüklenmiş halde (Postgres satırı + analiz önbelleği, ya da bir test
    fixture'ı) -- bu modül kendisi hiçbir şey okumaz."""

    storage_path: str
    file_name: str
    document_type_label: Optional[str] = None
    compliance_status: Optional[str] = None
    has_analysis: bool = True
    missing_fields: tuple[MissingFieldInput, ...] = ()
    mevzuat_references: tuple[MevzuatReferenceInput, ...] = ()
    #: Entity/Konu/attribute-payload kaynakları, hepsi opsiyonel -- bunları
    #: hiç ayarlamayan bir fixture veya çağıran (örn. her v1 testi,
    #: `_load_fixture`), bu modül büyümeden önce yayınlanan grafikle
    #: bayt bayt aynı olacak şekilde sıfır entity/konu düğümü ve sıfır yeni
    #: kenar üretmelidir.
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
    """Bir Evrak, Madde veya Kanun düğümü. Belirli bir `node_type` için
    anlamlı olmayan alanlar varsayılan değerinde bırakılır -- bunun neden
    etiketli bir union yerine düz, opsiyonel alanlardan oluşan bir yığın
    olarak kaldığı için modül docstring'ine bakın: üç düğüm türünün tek bir
    şekli paylaşması, üç ayrı dataclass artı bir ayırt edici kullanmaktan
    daha basit şekilde oluşturulur, test edilir ve serileştirilir."""

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
    #: Yalnızca "entity" düğümleri için -- "kurum" | "kisi" | "diger", bkz.
    #: entity_resolution._classify_kind. Sezgisel bir tahmindir, kesin
    #: doğru kabul edilmemelidir.
    entity_kind: Optional[str] = None
    #: Yalnızca "entity" düğümleri için -- bu düğümde birleşen her ham
    #: yüzey formu, böylece inceleyici (inspector) birleşmeyi gizlemek
    #: yerine ifşa edebilir.
    surface_forms: tuple[str, ...] = ()
    #: Şimdilik yalnızca "document" düğümleri için -- düğüm inceleyicisinin
    #: türe özgü yükü (payload). Daha fazla tipli alan yerine genel bir
    #: sözlük kullanılmasının nedeni, şeklin gerçekten node_type'a göre
    #: değişmesi ve büyümesinin beklenmesidir; madde/kanun/entity
    #: düğümlerinin ihtiyaç duyduğu her şey zaten yukarıdaki tipli
    #: alanlarda mevcuttur.
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    """Bir `ihlal` (kural) ya da `atif` (LLM) kenarı. İki şeklin tek bir
    dataclass'ta neden paylaşıldığı için `GraphNode`'a bakın."""

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
    """Manşet istatistik: en fazla *farklı* evrak tarafından ihlal edilen
    madde; yalnızca `ihlal` kenarlarından sayılır (asla `atif`'ten değil --
    bkz. modül docstring'i)."""

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
    """Entity ve Konu biriktirme geçişleri arasında paylaşılır -- ikisi de
    aynı şekle sahip "ham dizge yığınını çöz, sonra çözülmüş her grup için
    farklı evrak sayısını say" işlemidir; tek fark, `kind`/`surface_forms`
    alanlarının anlamlı olup olmamasıdır (Entity'de anlamlıdır, Konu'da
    varsayılan değerlerinde bırakılır -- Konu'nun benzer bir kavramı yoktur:
    bir konu bir kurum/kişi ile aynı şey değildir ve kanonik anahtarı zaten
    saklamaya değer tek yüzey formudur)."""

    label: str
    kind: Optional[str] = None
    surface_forms: tuple[str, ...] = ()
    document_ids: set[str] = field(default_factory=set)


def build_knowledge_graph(entries: list[DocumentGraphInput]) -> KnowledgeGraph:
    """Zaten yüklenmiş evrak verisinden korpus genelinde grafiği oluşturur.

    Args:
        entries: Evrak başına bir `DocumentGraphInput`. Önbelleğe alınmış
            analizi olmayan bir evrak yine de bir girdi alır
            (`has_analysis=False`, boş alan/atıf demetleri) -- asla
            atlanmamalıdır, aksi halde "9 üzerinden 7" gibi bir manşet
            yanlış 9 üzerinden hesaplanır.

    Returns:
        Grafik: her evrak izole veya bağlı bir düğüm olarak, her
        madde/kanun/entity/konu en az bir kenarla ulaşılabilir olarak ve
        manşet istatistiğin çıkarıldığı içgörülerle birlikte.
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

    # --- Entity/Konu çözümü: aşağıdaki evrak-başına döngü kenarları
    # atamadan *önce*, tüm korpustaki her ham dizge üzerinde tek bir geçiş.
    # Bunu yapmak, bir evrakın `muhatap`'ı ile başka bir evrakın aynı
    # kuruma yaptığı `entities[]` bahsinin tek bir düğümde birleşmesini
    # sağlar -- evrak başına çözüm yapmak evraklar arası örtüşmeyi asla
    # görmezdi. Konu, kendi ayrı çözülen ad alanını alır (bkz.
    # `_NamedGroupAccumulator`'ın docstring'i).
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

    def ensure_entity(raw: str) -> Optional[str]:
        # `resolve_entities` deliberately omits raw strings that canonicalize
        # to nothing (a bare 4+ digit number, pure markdown/whitespace noise)
        # -- such a `raw` here means this particular mention isn't a real
        # entity, not a bug, so it's skipped rather than looked up.
        resolved = resolved_entities.get(raw)
        if resolved is None:
            return None
        entity_id = f"entity:{resolved.key}"
        if entity_id not in entity_accumulators:
            entity_accumulators[entity_id] = _NamedGroupAccumulator(
                label=resolved.label, kind=resolved.kind, surface_forms=resolved.surface_forms,
            )
        return entity_id

    def ensure_konu(raw: str) -> Optional[str]:
        resolved = resolved_konu.get(raw)
        if resolved is None:
            return None
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
            if entity_id is not None:
                entity_accumulators[entity_id].document_ids.add(doc_id)
                edges.append(GraphEdge(source=doc_id, target=entity_id, edge_type="muhatap", source_kind="rule"))
                rule_edge_count += 1

        if entry.gonderen_kurum:
            entity_id = ensure_entity(entry.gonderen_kurum)
            if entity_id is not None:
                entity_accumulators[entity_id].document_ids.add(doc_id)
                edges.append(GraphEdge(source=doc_id, target=entity_id, edge_type="gonderen", source_kind="rule"))
                rule_edge_count += 1

        # `entities[]` bir evrak içinde aynı bahsi tekrar edebilir (modelden
        # tekilleştirme yapması istenmiyor); evrak başına çözülmüş entity
        # başına en fazla bir `bahseder` kenarına indirgenir, aksi halde
        # tekrarlanan bir bahis, hiçbir gerçek bilgi eklemeden o entity'nin
        # document_count'a yakın kenar sayısını sessizce şişirirdi.
        seen_entity_ids: set[str] = set()
        for raw_entity in entry.entities:
            if not raw_entity:
                continue
            entity_id = ensure_entity(raw_entity)
            if entity_id is None or entity_id in seen_entity_ids:
                continue
            seen_entity_ids.add(entity_id)
            entity_accumulators[entity_id].document_ids.add(doc_id)
            edges.append(GraphEdge(source=doc_id, target=entity_id, edge_type="bahseder", source_kind="llm"))
            llm_edge_count += 1

        if entry.konu:
            konu_id = ensure_konu(entry.konu)
            if konu_id is not None:
                konu_accumulators[konu_id].document_ids.add(doc_id)
                edges.append(GraphEdge(source=doc_id, target=konu_id, edge_type="konu", source_kind="rule"))
                rule_edge_count += 1

        for missing_field in entry.missing_fields:
            citation = resolve_citation(missing_field.mevzuat)
            if citation.kanun is None or citation.madde is None:
                # REQUIRED_FIELD_RULES kapalı, elle bakımı yapılan bir
                # kümedir ve atıflarının eksiksiz çözüldüğü sözleşme testiyle
                # doğrulanır (bkz. test_mevzuat_citation.py) -- bu dal,
                # gerçek veri için erişilemez olmalıdır. Kural bir şekilde
                # ihlal edilirse tüm grafiği çökertmek yerine atla.
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
        # Önce id'ye göre artan sırayla sıralanır ki `max` (eşitlik
        # durumunda ilk maksimal elemanı döndürür) eşitlikleri
        # sözlüksel olarak en küçük madde id'sine doğru bozsun; bu da
        # kazananı deterministik tutar.
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
