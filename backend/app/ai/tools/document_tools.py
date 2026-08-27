"""Asistan ajanının bir tur için bağlayabileceği araç fabrikaları.

Buradaki her handler, *bu* isteğe zaten eklenmiş belge üzerine bir closure'dır
(``document_id``, ``cached_document``) -- modele argüman olarak geçirmesi
için asla bir belge id'si verilmez, bu yüzden yapısal olarak kullanıcının
gerçekten eklediği belge dışında hiçbir belgeyi arayamaz veya okuyamaz.
Hiçbir belge eklenmediğinde, :func:`build_assistant_tools` belge kapsamlı
araçları basitçe atlar; model onları hiçbir zaman çağırmak için görmez.
"""

import json
import logging
import re
from typing import Any, Callable, Optional

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.ai.documents.anchors import format_anchor
from app.ai.documents.outline import build_outline, format_outline
from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.guardrails.sensitivity import assessment_from_analysis
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from app.ai.tools.mevzuat_tools import NOT_FOUND as _LIVE_NOT_FOUND
from app.ai.tools.mevzuat_tools import build_live_legislation_tools
from app.ai.tools.registry import ToolSpec
from app.ai.workflows.events import child_config
from app.core.enums.sensitivity_level import SensitivityLevel
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)

QA_COLLECTION_NAME = "document_qa"

#: Vektör araması hiçbir şey döndürmediğinde ve yanıtlamanın başka bir yolu
#: olmadığında yedek dilim boyutu. Prompt bütçesini şişirmesin diye sınırlı.
TEXT_SLICE_CHARS = 8000

#: ``search_document_regex``'in modele döndüreceği en fazla eşleşen satır --
#: geniş bir kalıbın (örn. ``\d+``) tüm belgeyi bağlama boşaltmasını engeller.
REGEX_MATCH_LIMIT = 40

#: `search_legislation`'ın (yerel `mevzuat` koleksiyonu) en iyi sonucunun,
#: sorguyu gerçekten yanıtlamadığının işareti sayılacağı RRF skor eşiği --
#: bkz. `HybridRetriever.retrieve` (hybrid.py:93), Qdrant'ın native RRF
#: füzyonundan gelen skoru buraya yazar. `RETRIEVAL_LIMIT=4` (rag_graph.py)
#: nedeniyle sonuç sayısı tek başına zayıf bir sinyal -- neredeyse her
#: sorgu 4 komşu döndürür, alakasız olsa bile.
#:
#: DEĞER KALİBRE EDİLMEDİ. Qdrant'ın RRF sabiti ve bu koleksiyondaki gerçek
#: skor dağılımı yalnızca canlı ölçümle bilinir --
#: `python scripts/evaluate_mevzuat_retrieval.py --show-scores` bilinen
#: cevaplanabilir/cevaplanamaz sorgular için skorları yazdırır; o ölçümden
#: çıkan değer bu yorumla birlikte güncellenmelidir (EXCERPT_CHAR_LIMIT'in
#: mevzuat_tools.py'de belgelendiği gibi). Kalibrasyon tamamlanana kadar bu,
#: canlı eskalasyonun hiç tetiklenmemesi yönünde -- yani en güvenli yönde --
#: hata yapması için kasıtlı olarak yüksek tutulmuş bir üst sınırdır.
WEAK_SCORE_THRESHOLD = 0.05


class ToolResult(BaseModel):
    """Bir aracın model için değil, output gate için fiilen döndürdüğü şey.

    Model yalnızca bir handler'ın döndürdüğü düz string'i görür (LangChain'in
    araç çağrısı sözleşmesi bir string ister, ve bunu değiştirmek burada
    kapsam dışıdır) -- bu, aynı çağrının, ``on_anchor_referenced``'in sayfa
    referanslarını zaten raporladığı şekilde ``on_tool_result`` aracılığıyla
    raporlanan paralel, yapılandırılmış bir kaydıdır.
    ``app.ai.guardrails.output_gate.evaluate_response``, ``text``/``source_ids``'i
    bu turun dayanaklılık kaynakları olarak, ``sensitivity_level``'ı ise
    sızmış bir PII aralığının gizlilik damgalı bir belgeye kadar izlenip
    izlenmediğini bilmek için kullanır.
    """

    tool: str = Field(description="Bu sonucu üreten araç adı.")
    text: str = Field(description="Modele döndürülenle aynı metin.")
    citations: list[str] = Field(
        default_factory=list, description="Atıfta bulunulan sayfa çıpaları (örn. '[s. 3]')."
    )
    source_ids: list[str] = Field(
        default_factory=list, description="Bu sonucun dayandığı belge/mevzuat tanımlayıcıları."
    )
    sensitivity_level: SensitivityLevel = Field(default=SensitivityLevel.UNMARKED)
    confidence: float = Field(
        default=1.0, description="Gerçek bir alma isabeti için 1.0, düşürülmüş bir yedek yol için daha düşük."
    )


class SearchDocumentArgs(BaseModel):
    """Arguments for the ``search_document`` tool."""

    query: str = Field(description="Belgede aranacak soru veya anahtar kelimeler.")


class SearchDocumentRegexArgs(BaseModel):
    """Arguments for the ``search_document_regex`` tool."""

    pattern: str = Field(
        description=(
            "Python düzenli ifade (regex) söz dizimi. Büyük/küçük harf duyarsız, "
            "satır satır uygulanır. Birebir bir ifade de geçerli bir kalıptır "
            "(örn. 'E-12345', '15/08/2024', 'sayılı Kanun')."
        )
    )


class GetDocumentDetailsArgs(BaseModel):
    """``get_document_details`` hiçbir argüman almaz; analiz zaten eklenmiş
    tek belgeye kapsamlanmıştır."""


class GetDocumentOutlineArgs(BaseModel):
    """``get_document_outline`` hiçbir argüman almaz; eklenmiş tek belgenin
    her sayfasını listeler."""


class GetDocumentSectionArgs(BaseModel):
    """Arguments for the ``get_document_section`` tool."""

    page: int = Field(description="Okunacak sayfa numarası (1'den başlar).")


class SearchLegislationArgs(BaseModel):
    """Arguments for the ``search_legislation`` tool."""

    query: str = Field(description="Mevzuat veritabanında aranacak konu veya soru.")


#: İstek yapanın yetkisi, belgenin gizlilik derecesini kapsamadığında, her
#: belge kapsamlı araç tarafından gerçek pasaj yerine döndürülür --
#: alma-noktasında-reddet, bir sızıntıyı durdurmanın en ucuz ve en sağlam
#: noktası (içerik modelin bağlamına hiç ulaşmaz, bu yüzden
#: ``output_gate.py``'nin aşağı akış kontrolleri etrafından parafraz edilemez).
_CLEARANCE_REFUSAL = "Bu belgenin içeriğini görüntülemek için yeterli yetkiniz yok."


def build_assistant_tools(
    *,
    document_id: Optional[str],
    cached_document: dict[str, Any],
    vector_store: Optional[BaseVectorStore],
    embeddings_client: Optional[BaseEmbeddingsClient],
    qa_sparse_encoder: SparseBM25Encoder,
    qa_result_limit: int,
    rag_graph: Any,
    config: Optional[RunnableConfig],
    on_anchor_referenced: Optional[Callable[[str], None]] = None,
    on_tool_result: Optional[Callable[[ToolResult], None]] = None,
    requester_clearance: Optional[SensitivityLevel] = None,
) -> list[ToolSpec]:
    """Bir tur için asistan ajanının kullanabileceği araç setini inşa eder.

    Args:
        document_id: Eklenmiş belgenin depolama yolu, veya None.
        cached_document: ``document_id`` ayarlıysa belgenin önbelleklenmiş
            analizi/çıkarılmış metni/sayfaları (bkz.
            ``planning_graph._load_cached_document``).
        vector_store: Belge almayı destekleyen vektör deposu.
        embeddings_client: Belge almayı destekleyen embeddings istemcisi.
        qa_sparse_encoder: Fit edilmemiş sparse encoder; birleştirme
            öncesi belge Soru-Cevap yolunun RRF füzyonunun sözcüksel yarısı
            için kullandığı aynı encoder.
        qa_result_limit: Bir belge aramasının döndürdüğü maksimum pasaj.
        rag_graph: Derlenmiş mevzuat alma alt-graph'ı.
        config: Assist adımının çalıştırılabilir config'i; kendi ilerleme
            olaylarının (ve herhangi bir izleme geri çağırımının) yine de
            SSE akışına ulaşması için ``child_config`` aracılığıyla RAG
            alt-graph'ına iletilir.
        on_anchor_referenced: ``get_document_section`` bir sayfa okuduğunda
            bir sayfa çıpasıyla (örn. ``"[s. 3]"``) çağrılır; böylece çağıran
            onu ``SessionFocus.last_referenced_anchor``'a taşıyabilir.
        on_tool_result: Gerçek içerik döndüren her araç çağrısından sonra bir
            ``ToolResult`` ile çağrılır; böylece çağıran,
            ``output_gate.evaluate_response``'un dayanaklılık/sızıntı
            kontrolü yapması için bu turun gerçek kaynaklarını
            biriktirebilir -- bunun handler'ların modele döndürdüğü şeyde bir
            değişiklik yerine neden bir yan kanal olduğu için
            ``ToolResult``'un docstring'ine bakın.
        requester_clearance: Kimliği doğrulanmış çağıranın çözümlenmiş yetkisi
            (bkz. ``app.core.permissions.role_checker.clearance_for``).
            ``None``, kontrolü tamamen atlar -- ``chat/router.py``'nin
            sahiplik kontrolünün "kimliği doğrulanmış kullanıcı yok"
            (``settings.REQUIRE_AUTH`` kapalı) için zaten kullandığı aynı
            kural; böylece belgelenmiş yerel-geliştirme kaçış kapısı, her
            belge aracı çağrısını sessizce reddetmek yerine gerçekten açık
            kalır. Bu, daha nadir PII/semantik-sızıntı engeli için ``None``
            üzerinde başarısızlık-güvenli kalan ``output_gate.py``'nin kendi
            ``requester_clearance`` işlemesinden daha dardır -- buradaki
            alma-noktasında-reddet, daha kaba, çok daha sık tetiklenen bir
            kapıdır ve ikisi aynı savunmanın bağımsız katmanlarıdır, her
            sınırda aynı fikirde olmaları gerekmez.

    Returns:
        Yalnızca bir belge eklendiğinde belge kapsamlı araçlar; belge olsun
        olmasın bir RAG graph'ı mevcut olduğunda mevzuat araması.
    """
    tools: list[ToolSpec] = []

    def _report(result: ToolResult) -> None:
        if on_tool_result:
            on_tool_result(result)

    # Bu tur için yaşayan eskalasyon durumu: search_legislation_live'ın
    # sarmalayıcısı (aşağıda), search_legislation gerçekten denenmeden --
    # ya da denenip güçlü sonuç bulmuşken -- ağa çıkmamak için bunu okur.
    # build_assistant_tools() turda bir kez çağrıldığından (bkz.
    # planning_graph._run_assist), bu closure hem AssistantAgent'ın
    # MAX_TOOL_TURNS=2 iç turunun her ikisine de doğal olarak yayılır.
    _legislation_state = {"attempted": False, "weak": False}

    if document_id:
        document_sensitivity = assessment_from_analysis(
            cached_document.get("analysis") or {}
        ).effective_level
        clearance_ok = (
            requester_clearance is None or requester_clearance >= document_sensitivity
        )

        def _pages() -> list[str]:
            pages = cached_document.get("pages")
            if pages:
                return pages
            text = cached_document.get("extracted_text")
            return [text] if text else []

        async def _search_document(query: str) -> str:
            if not clearance_ok:
                return _CLEARANCE_REFUSAL
            if not (vector_store and embeddings_client):
                return "Belge arama şu anda kullanılamıyor."
            passages: list[str] = []
            try:
                query_vector = await embeddings_client.embed_query(query)
                sparse_indices, sparse_values = qa_sparse_encoder.encode_query(query)
                # Yukarıdaki clearance_ok kapısının yanında derinlemesine
                # savunma: bu belgenin her parçası aynı belge düzeyi
                # dereceyle etiketlendi (bkz.
                # DocumentService._index_for_qa), bu yüzden bu, tek belge
                # kapsamlı bu araç için o bütün-belge kontrolüyle şu anda
                # fazlalıklı -- ama burada hiçbir şeye mal olmaz ve
                # gelecekteki bir çapraz belge arama aracının Qdrant'ın
                # fazla sınıflandırılmış bir parçayı döndürmesine baştan
                # hiç izin vermemesini fiilen sağlayan şeydir.
                search_filter: dict[str, Any] = {"storage_path": document_id}
                if requester_clearance is not None:
                    search_filter["sensitivity_rank"] = {"lte": requester_clearance.rank}
                hits = await vector_store.hybrid_search(
                    collection_name=QA_COLLECTION_NAME,
                    query_vector=query_vector,
                    sparse_indices=sparse_indices,
                    sparse_values=sparse_values,
                    limit=qa_result_limit,
                    filter_dict=search_filter,
                )
                for hit in hits:
                    text = hit.get("text")
                    if not text:
                        continue
                    page = (hit.get("metadata") or {}).get("page")
                    passages.append(f"{format_anchor(page)} {text}" if page else text)
            except Exception:
                logger.exception("Assistant document search failed")

            confidence = 1.0
            degraded = False
            if not passages and cached_document.get("extracted_text"):
                # Bir alma kesintisi ile "gerçekten eşleşen pasaj yok"
                # eskiden hiçbir ayırt edici sinyal olmadan bu aynı dala
                # çöküyordu, bu yüzden model belgenin açılış satırlarını
                # gerçek, hedeflenmiş bir isabetle aynı güvenle okuyordu --
                # ve 60 sayfalık bir belgenin 40. sayfası hakkındaki bir
                # soru, yanlışlıkla 1-2. sayfalardan yanıtlanıyordu.
                # `confidence`, ToolResult/output_gate'in dayanaklılık
                # kontrolü için farkı zaten kaydediyordu; `degraded`, daha
                # önce hiç işareti olmayan, modelin kendisinin okuduğu
                # metne aynı gerçeği taşır.
                passages = [cached_document["extracted_text"][:TEXT_SLICE_CHARS]]
                confidence = 0.5
                degraded = True
            if not passages:
                return "Belgede bu soruyla ilgili bir içerik bulunamadı."

            text = "\n\n---\n\n".join(passages)
            if degraded:
                text = (
                    "[Not: Hedefli arama sonuç vermedi; bu, belgenin yalnızca "
                    "başlangıç kısmıdır ve sorunuzla doğrudan ilgili olmayabilir.]"
                    f"\n\n{text}"
                )
            _report(
                ToolResult(
                    tool="search_document",
                    text=text,
                    source_ids=[document_id],
                    sensitivity_level=document_sensitivity,
                    confidence=confidence,
                )
            )
            return text

        async def _get_document_details() -> str:
            if not clearance_ok:
                return _CLEARANCE_REFUSAL
            analysis = cached_document.get("analysis") or {}
            if not analysis:
                return "Belge analiz bilgisi mevcut değil."

            raw_metadata = analysis.get("fields") or analysis.get("metadata") or {}
            metadata = (
                json.dumps(raw_metadata, ensure_ascii=False, indent=2, default=str)
                if isinstance(raw_metadata, dict)
                else str(raw_metadata)
            )
            parts = [
                f"Özet: {analysis.get('summary') or 'Özet mevcut değil.'}",
                f"Üst veri: {metadata}",
            ]
            if analysis.get("compliance_status"):
                parts.append(f"Uygunluk durumu: {analysis['compliance_status']}")
            if analysis.get("missing_fields"):
                # Bu listenin her üreticisi MissingField.model_dump()
                # dict'leri yazar (bkz. document_analysis_graph.py'nin
                # check_compliance_node'u), asla çıplak string değil --
                # listeyi doğrudan birleştirmek, gerçek bir uygunluk
                # boşluğu olan herhangi bir belgede TypeError fırlatıyordu;
                # asistan bunu sessizce yutup belgenin analizi hiç
                # olmadan yanıt veriyordu. `label`, her dict'in taşıması
                # garanti edilen tek anahtardır.
                labels = [
                    item.get("label", str(item)) if isinstance(item, dict) else str(item)
                    for item in analysis["missing_fields"]
                ]
                parts.append("Eksik alanlar: " + ", ".join(labels))
            text = "\n\n".join(parts)
            _report(
                ToolResult(
                    tool="get_document_details",
                    text=text,
                    source_ids=[document_id],
                    sensitivity_level=document_sensitivity,
                )
            )
            return text

        async def _get_document_outline() -> str:
            if not clearance_ok:
                return _CLEARANCE_REFUSAL
            pages = _pages()
            if not pages:
                return "Belge metni mevcut değil."
            text = format_outline(build_outline(pages))
            _report(
                ToolResult(
                    tool="get_document_outline",
                    text=text,
                    source_ids=[document_id],
                    sensitivity_level=document_sensitivity,
                )
            )
            return text

        async def _get_document_section(page: int) -> str:
            if not clearance_ok:
                return _CLEARANCE_REFUSAL
            pages = _pages()
            if not pages:
                return "Belge metni mevcut değil."
            if page < 1 or page > len(pages):
                return f"Belgede {page}. sayfa yok. Belge {len(pages)} sayfadan oluşuyor."
            anchor = format_anchor(page)
            if on_anchor_referenced:
                on_anchor_referenced(anchor)
            text = f"{anchor}\n\n{pages[page - 1]}"
            _report(
                ToolResult(
                    tool="get_document_section",
                    text=text,
                    citations=[anchor],
                    source_ids=[document_id],
                    sensitivity_level=document_sensitivity,
                )
            )
            return text

        async def _search_document_regex(pattern: str) -> str:
            """RAG dışında, belge metni üzerinde birebir/regex satır araması.

            `search_document` anlamsal (vektör) arama yapar; kesin bir dizge --
            bir sayı, tarih, atıf kodu, birebir bir ifade -- veya bir terimin
            *tüm* geçtiği yerlerin sayımı gerektiğinde bu araç daha güvenilirdir.
            """
            if not clearance_ok:
                return _CLEARANCE_REFUSAL
            try:
                regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
            except re.error as exc:
                return f"Geçersiz düzenli ifade: {exc}"
            pages = _pages()
            if not pages:
                return "Belge metni mevcut değil."

            hits: list[str] = []
            total = 0
            for page_number, page_text in enumerate(pages, start=1):
                anchor = format_anchor(page_number)
                for line in page_text.splitlines():
                    if not regex.search(line):
                        continue
                    total += 1
                    if len(hits) < REGEX_MATCH_LIMIT:
                        stripped = line.strip()
                        hits.append(
                            f"{anchor} {stripped}" if stripped else f"{anchor} (boş satır eşleşti)"
                        )

            if not hits:
                return f"'{pattern}' kalıbıyla eşleşen satır bulunamadı."

            text = "\n".join(hits)
            if total > len(hits):
                text += f"\n\n[... toplam {total} eşleşmenin ilk {len(hits)}'i gösterildi]"
            _report(
                ToolResult(
                    tool="search_document_regex",
                    text=text,
                    source_ids=[document_id],
                    sensitivity_level=document_sensitivity,
                )
            )
            return text

        tools.extend(
            [
                ToolSpec(
                    name="search_document",
                    description=(
                        "Yüklenmiş belgede belirli bir soru veya konuyla ilgili "
                        "içerik ara. Belgenin belirli bir kısmı hakkında soru "
                        "sorulduğunda kullan. Sonuçlar [s. N] ile sayfa atfı taşır."
                    ),
                    args_schema=SearchDocumentArgs,
                    handler=_search_document,
                ),
                ToolSpec(
                    name="get_document_details",
                    description=(
                        "Belgenin özetini, üst verilerini (tarih, sayı, konu, "
                        "muhatap vb.) ve uygunluk denetimi sonucunu getirir. "
                        "Belgenin genel niteliği hakkında soru sorulduğunda kullan."
                    ),
                    args_schema=GetDocumentDetailsArgs,
                    handler=_get_document_details,
                ),
                ToolSpec(
                    name="get_document_outline",
                    description=(
                        "Belgenin sayfa listesini ve her sayfanın ilk satırını "
                        "getirir. Belgenin genel yapısını görmek veya hangi "
                        "sayfada ne olduğunu bulmak için search_document sonuç "
                        "vermeden önce ya da 'kaç sayfa' gibi sorularda kullan."
                    ),
                    args_schema=GetDocumentOutlineArgs,
                    handler=_get_document_outline,
                ),
                ToolSpec(
                    name="get_document_section",
                    description=(
                        "Belgenin belirli bir sayfasının tam metnini okur. "
                        "Kullanıcı belirli bir sayfayı işaret ettiğinde (örn. "
                        "'3. sayfayı açıkla') veya get_document_outline ile "
                        "ilgili sayfayı belirledikten sonra kullan."
                    ),
                    args_schema=GetDocumentSectionArgs,
                    handler=_get_document_section,
                ),
                ToolSpec(
                    name="search_document_regex",
                    description=(
                        "Belge metninde düzenli ifade (regex) veya birebir dizge "
                        "ile satır araması yapar -- vektör tabanlı search_document'in "
                        "aksine. Kesin bir sayı/tarih/atıf kodu ararken, bir ifadenin "
                        "belgede geçip geçmediğini ya da kaç kez geçtiğini "
                        "doğrularken kullan. Sonuçlar [s. N] ile sayfa atfı taşır."
                    ),
                    args_schema=SearchDocumentRegexArgs,
                    handler=_search_document_regex,
                ),
            ]
        )

    if rag_graph is not None:

        async def _search_legislation(query: str) -> str:
            try:
                result = await rag_graph.ainvoke(
                    {"original_query": query, "attempts": 0},
                    config=child_config(config),
                )
                context = result.get("context") or ""
                documents = result.get("documents") or []
            except Exception:
                logger.exception("Assistant legislation search failed")
                context = ""
                documents = []
            # search_legislation_live'ın sarmalayıcısının okuduğu eskalasyon
            # sinyali. Sayı tek başına zayıf bir sinyal -- RETRIEVAL_LIMIT=4
            # (rag_graph.py) nedeniyle neredeyse her sorgu 4 komşu döndürür,
            # alakasız olsa bile; asıl sinyal en iyi sonucun RRF skoru (bkz.
            # WEAK_SCORE_THRESHOLD'un kendi yorumu).
            top_score = documents[0].metadata.get("score", 0.0) if documents else 0.0
            _legislation_state["attempted"] = True
            _legislation_state["weak"] = (not documents) or top_score < WEAK_SCORE_THRESHOLD
            if not context:
                return "İlgili bir mevzuat maddesi bulunamadı."
            # Mevzuat, doğası gereği kamuya açık referans materyalidir, asla
            # gizlilik damgalı bir kaynak değil -- bu turda bir belge
            # ekli olsun olmasın her zaman UNMARKED.
            _report(ToolResult(tool="search_legislation", text=context))
            return context

        tools.append(
            ToolSpec(
                name="search_legislation",
                description=(
                    "İlgili kanun, yönetmelik ve mevzuat maddelerini ara. "
                    "Kullanıcı mevzuat veya hukuki dayanak hakkında soru "
                    "sorduğunda kullan."
                ),
                args_schema=SearchLegislationArgs,
                handler=_search_legislation,
            )
        )

    # Bilinçli olarak korpus aracından sonra eklenir: model sıralı bir
    # listeden seçer ve çevrimdışı yol varsayılan olmalıdır. build_live_
    # legislation_tools() kendi içinde settings.LOCAL_MODE +
    # settings.MEVZUAT_MCP_ENABLED + sunucu kaydı şartlarını kontrol eder;
    # hiçbiri tutmuyorsa boş liste döner ve modele asla çalışamayacak bir
    # araç sunulmaz.
    live_tools = build_live_legislation_tools()
    if live_tools:
        tools.append(_guard_live_legislation_tool(live_tools[0], _legislation_state, _report))

    return tools


def _guard_live_legislation_tool(
    live_tool: ToolSpec,
    legislation_state: dict[str, bool],
    report: Callable[[ToolResult], None],
) -> ToolSpec:
    """``search_legislation_live``'ı, yalnızca yerel arama gerçekten
    denenip zayıf çıktığında ağa çıkacak şekilde sarmalar.

    Model, açıklamaya uyup uymamakta serbesttir -- aynı yanıtta her iki
    aracı da isteyebilir, ya da yereli hiç denemeden canlıyı ilk turda
    çağırabilir. ``AssistantAgent.run_stream`` bir yanıtın tüm
    ``tool_calls``'larını sırayla yürüttüğü için (bkz. assistant.py), bu
    sarmalayıcı asıl ağ I/O'sundan hemen önce ``legislation_state``'i
    okuyan çalışma zamanı kapısıdır: model iki aracı aynı yanıtta isterse
    bile ``search_legislation`` önce çalışır ve durumu yazar, sonra bu
    kapı gerçekten zayıf olup olmadığını görür; model doğrudan canlıyı
    çağırırsa ``attempted`` hâlâ ``False`` olduğu için kapı reddeder.

    Ayrıca alttaki ``live_tool.handler``'ın atladığı ``ToolResult``
    raporlamasını da burada tamamlar -- onsuz, canlı aramadan gelen metin
    modelin bağlamına girer ama ``output_gate.evaluate_response``'un
    dayanaklılık kontrolüne hiç görünmez ve içindeki her somut iddia
    (madde no, tarih) desteksiz sayılıp karartılır.
    """

    async def _guarded_handler(query: str) -> str:
        if not (legislation_state["attempted"] and legislation_state["weak"]):
            return (
                "Önce search_legislation ile yerel korpüste ara. Sonuç yoksa "
                "veya yetersizse bu aracı tekrar çağırabilirsin."
            )
        result = await live_tool.handler(query=query)
        if result and result != _LIVE_NOT_FOUND:
            # Mevzuat.gov.tr'den gelen metin de kamuya açık referans
            # materyalidir -- search_legislation'ın kendi _report çağrısıyla
            # aynı gerekçe, aynı UNMARKED gizlilik seviyesi.
            report(ToolResult(tool="search_legislation_live", text=result))
        return result

    return ToolSpec(
        name=live_tool.name,
        description=live_tool.description,
        args_schema=live_tool.args_schema,
        handler=_guarded_handler,
    )
