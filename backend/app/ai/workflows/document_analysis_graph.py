import asyncio
import logging
from copy import deepcopy
from typing import Any, Optional, TypedDict

from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, create_model

from app.ai.agents.classifier import ClassifierAgent
from app.ai.agents.compliance import ComplianceAgent
from app.ai.compliance import (
    DOCUMENT_TYPE_LABELS,
    DOCUMENT_TYPE_QUERY_TERMS,
    EvrakField,
    check_required_fields,
    citation_support,
    detect_structural_signal,
    format_parsed_fields,
    format_structural_signal,
    merge_parsed_over_model,
    normalize_value,
    parse_labelled_fields,
)
from app.ai.agents.guardrail_judge import GuardrailJudgeAgent
from app.ai.guardrails.llm_nuance import judge_input_sensitivity
from app.ai.guardrails.sensitivity import SensitivityAssessment
from app.ai.guardrails.sensitivity import assess as assess_sensitivity
from app.ai.llms.base import BaseLLMClient
from app.ai.policy import get_policy
from app.ai.policy.budget import node_budget
from app.ai.summarization import ocr_warning
from app.ai.verification.draft_verifier import check_groundedness
from app.ai.workflows.events import emit_node_end, emit_node_error, emit_node_start, emit_partial
from app.ai.workflows.resilience import (
    IO_RETRY,
    LLM_RETRY,
    TRANSIENT_ERRORS,
    node_timeout,
)
from app.core.config import settings
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType
from app.core.enums.sensitivity_level import SensitivityLevel
from app.mcp.mevzuat_client import search_and_excerpt
from app.mcp.registry import MEVZUAT_SERVER, is_registered

logger = logging.getLogger(__name__)

#: Başlık alanları ilk sayfada ve imza/ek bloğu en sonda yer alır;
#: aradaki gövde metni özet için önemlidir, alan çıkarımı için değil.
HEAD_CHAR_BUDGET = 6000
TAIL_CHAR_BUDGET = 1500
MEVZUAT_RESULT_LIMIT = 3

#: Birleşik sınıflandır+çıkar çağrısı, bir düzine alan içeren iç içe bir nesne üretir.
ANALYSIS_MAX_TOKENS = 1536

#: suggest_mevzuat bütçesinden model çağrısının kullanabileceği pay; kalanı
#: düğümün kendi düşüş (degradation) yoluna bırakılır. Bu olmadan düğümün
#: zaman aşımı try/except bloğunun dışında tetiklenir -- burada fallback ona
#: erişemez -- ve tüm analiz, 5. gereksinimin isteğe bağlı yarısı yüzünden
#: başarısız olur.
SUGGESTION_BUDGET_SHARE = 0.85

#: Öneri düğümü için üretim üst sınırı. Çıktısı bir avuç tek cümlelik
#: gerekçeden ibarettir, dolayısıyla 1024 token'lık varsayılan modele
#: kullanmayacağı bir alan sağlar -- ama 384, gerçek alıntılara karşı çok
#: dardır ve kazandırdığından fazlasına mal olduğu ölçüldü: qwen3.5:9b
#: JSON'un ortasında kesildi, ayrıştırma başarısız oldu, yeniden denendi,
#: yine başarısız oldu ve çalışma, modelin kendi üretim süresinin 2 katı
#: sonra ham alıntı (raw-citation) fallback'ine düştü. Bu başarısızlık
#: yalnızca uçtan uca ortaya çıktı, 384'ü ilk seçen izole çağrıda değil --
#: izole bir zamanlamaya tekrar güvenmeden önce hatırlanmaya değer.
#:
#: 512 değeri altı belge/eksik-alan kombinasyonuna karşı, her biri iki kez
#: tekrarlanarak ölçüldü: 6/6 ilk denemede başarılı oldu, yeniden deneme
#: olmadı. Tek bir doğrulanmış sunucu sürecine karşı canlı uç nokta
#: üzerinden doğrulandı: aynı belgenin art arda üç yüklemesi her biri
#: 49-51s sürdü (sınırsızken 65-85s idi), ComplianceAgent çağrısının
#: kendisi ~35s'den ~25s'ye düştü ve deterministik çekirdek (tür, uyum
#: durumu, eksik alanlar) üçünde de aynıydı. MEVZUAT_RESULT_LIMIT'i
#: düşürmek de ölçüldü ve reddedildi: ~2s kazandırıyor ama cevabı
#: *değiştiriyor*; bu, sınırsız metni yeniden üreten bir üst sınırla aynı
#: türden bir kazanç değil.
SUGGESTION_MAX_TOKENS = 512


class DocumentAnalysisState(TypedDict, total=False):
    """Gelen evrak (evrak) analizi iş akışı için LangGraph durumu."""

    input_text: str
    is_ocr_text: bool
    # İmza/kaşe/el yazısı bölgeleri çıkarım sırasında zaten tespit edilmiştir
    # (app.infrastructure.extractors.marks.detect_marks); is_ocr_text ile aynı
    # şekilde doğrudan aktarılır -- tespit, bu graf başlamadan önce
    # rasterize edilmiş sayfaya karşı bir kez çalışır ve aşağıdaki
    # check_compliance_node bunu okuyan tek düğümdür. Bilinçli olarak ayrı
    # bir graf dalı/düğümü değildir (scan_sensitivity_node'un kullandığı
    # biçim): o örüntü bağımsız olarak END'e dallanır ve check_compliance_node
    # aynı çalışma içinde onun çıktısını göremez, ama check_compliance_node
    # bir belgenin imzalı okunup okunmadığına karar vermek için özellikle buna
    # ihtiyaç duyar.
    detected_marks: list[dict[str, Any]]
    document_type: str
    document_type_label: str
    summary: str
    fields: dict[str, Any]
    missing_fields: list[dict[str, Any]]
    compliance_status: str
    checked_field_count: int
    mevzuat_documents: list[Document]
    mevzuat_suggestions: list[dict[str, Any]]
    entities: list[str]
    sensitivity_assessment: dict[str, Any]


#: Yalnızca tür ve özet. Birleşik şema başarısız olduğunda fallback olarak kullanılır.
class DocumentClassificationOutput(BaseModel):
    """Gelen resmî bir evrakın yapılandırılmış tür ve özet bilgisi."""

    document_type: DocumentType = Field(
        description=(
            "Gelen evrakın türü. Yalnızca şu değerlerden biri olmalıdır: "
            "official_letter (resmî yazı), petition (dilekçe), "
            "information_request (bilgi edinme başvurusu), complaint (şikayet), "
            "circular (genelge), directive (talimat), report (rapor), "
            "minutes (tutanak), leave_request (izin talebi), other (diğer)."
        )
    )
    summary: str = Field(
        description="Evrakın kısa, öz ve nesnel Türkçe özeti (en çok 3 cümle)."
    )


def _build_merged_output_model() -> type[BaseModel]:
    """Birleşik analiz şemasını *düz (flat)* bir model olarak oluştur.

    Sınıflandırma ve alan çıkarımı eskiden aynı metin üzerinde, aynı kanıtı
    okuyan iki ayrı model çağrısıydı; bu yüzden ikincisi, birincisinin zaten
    ödediği bir prompt'u yeniden işliyordu. Bunları birleştirmek analiz
    aşamasının maliyetini yarıya indirir.

    Birleşim, elle yazılmak yerine :class:`EvrakField`'dan üretilir ve
    bilinçli olarak ``fields: EvrakField`` şeklinde iç içe değil, düzleştirilmiş
    olarak kurulur. Yerel 9B modeller, iç içe nesne şemaları için yeterince
    sık bozuk JSON üretiyor; iç içe geçmiş sürüm her iki denemede de
    doğrulamayı geçemedi ve "Evrak özeti çıkarılamadı." yoluna düştü.
    Skaler değerler ve string listelerinden oluşan düz bir şema, bu modellerin
    güvenilir biçimde ürettiği şeydir -- ve bunu ``EvrakField``'dan üretmek,
    alan tanımları için tek bir doğruluk kaynağı sağlar.

    Returns:
        En üst düzeyde ``document_type``, ``summary`` ve her ``EvrakField``
        özniteliğini içeren bir Pydantic modeli.
    """
    definitions: dict[str, Any] = {
        "document_type": (
            DocumentType,
            Field(
                description=(
                    "Gelen evrakın türü. Yalnızca şu değerlerden biri olmalıdır: "
                    "official_letter, petition, information_request, complaint, "
                    "circular, directive, report, minutes, leave_request, other."
                )
            ),
        ),
        "summary": (
            str,
            Field(description="Evrakın kısa, öz ve nesnel Türkçe özeti (en çok 3 cümle)."),
        ),
    }
    for name, info in EvrakField.model_fields.items():
        # Deepcopy edilir: FieldInfo örnekleri model başına durum taşır; bu
        # nesneleri doğrudan ikinci bir modele vermek, ikisinin onu paylaşmasına
        # yol açardı.
        definitions[name] = (info.annotation, deepcopy(info))

    return create_model("MergedDocumentAnalysisOutput", **definitions)


DocumentAnalysisOutput = _build_merged_output_model()

#: EvrakField'a ait anahtarlar; düz modeli tekrar ayırmak için kullanılır.
EVRAK_FIELD_KEYS = tuple(EvrakField.model_fields)


class MevzuatSuggestion(BaseModel):
    """Belgeyle ilgili tek bir mevzuat referansı."""

    mevzuat: str = Field(
        description="İlgili mevzuatın adı ve varsa madde numarası, alıntıda yazıldığı biçimde."
    )
    aciklama: str = Field(
        description="Bu hükmün evrakla ilişkisini açıklayan kısa Türkçe gerekçe."
    )


class MevzuatSuggestionOutput(BaseModel):
    """Getirilen alıntılara dayandırılmış, yapılandırılmış mevzuat önerileri."""

    suggestions: list[MevzuatSuggestion] = Field(
        default_factory=list,
        description="Yalnızca verilen alıntılara dayanan mevzuat önerileri.",
    )


def _trim_for_extraction(text: str) -> str:
    """Bir belgeyi, başlığı ve imza bloğu kısaltmadan sağ çıkacak şekilde kısalt.

    Args:
        text: Belgenin tam metni.

    Returns:
        Yeterince kısaysa metin değişmeden döner, aksi halde baş ve son kısımlar
        açık bir kesinti işareti ile birleştirilerek döner.
    """
    if len(text) <= HEAD_CHAR_BUDGET + TAIL_CHAR_BUDGET:
        return text
    return (
        f"{text[:HEAD_CHAR_BUDGET]}"
        "\n\n[... belgenin orta kısmı kısaltıldı ...]\n\n"
        f"{text[-TAIL_CHAR_BUDGET:]}"
    )


def _build_mevzuat_query(state: DocumentAnalysisState) -> str:
    """Mevzuat arama sorgusunu deterministik biçimde oluştur.

    Bir model yeniden yazımı yerine belge-türü etiketinden, konudan ve türün
    kendi mevzuat kelime dağarcığından kurulur: bunlar korpustaki gerçek
    (literal) token'lardır ve hibrit retriever'ın BM25 yarısının en iyi
    eşleştirdiği şey de budur.

    Kelime dağarcığı tek bir sabit string yerine türe göre değişir
    (`DOCUMENT_TYPE_QUERY_TERMS`). Sabit sürüm, korpus tek bir gerçekçi hedef
    içerdiğinde -- yazışma yönetmeliği -- yazılmıştı, bu yüzden terimleri her
    sorguda zararsızdı. Genişletilmiş korpusa karşı bir önyargıya dönüştüler:
    örnek türler üzerinde ölçüldüğünde, sabit ek izin taleplerini
    veri koruma kanununa, dilekçeleri ise memurlar kanununa çekiyordu; onu
    kaldırmak ise yönetmeliğe kendi belge türlerini kaybettiriyordu. Türe özgü
    terimler her ikisini de düzeltir.

    Bilinçli olarak uyum (compliance) raporuna bağlı değildir; böylece
    getirme (retrieval) ve uyum kontrolü bağımsız dallar olarak çalışabilir.

    Args:
        state: Mevcut iş akışı durumu.

    Returns:
        Arama sorgusu.
    """
    parts = [state.get("document_type_label") or "resmî yazı"]

    fields = state.get("fields") or {}
    konu = fields.get("konu")
    if konu:
        parts.append(str(konu))

    try:
        document_type = DocumentType(state.get("document_type", DocumentType.OTHER.value))
    except ValueError:
        document_type = DocumentType.OTHER
    parts.append(DOCUMENT_TYPE_QUERY_TERMS[document_type])

    return " ".join(parts).strip()


async def _fetch_live_mevzuat_excerpt(query: str) -> Optional[Document]:
    """``LOCAL_MODE=false`` iken bir konu sorgusunu canlı mevzuat.gov.tr
    aramasına gönderir ve hedefli bir alıntı döndürür.

    Bu, `retrieve_mevzuat_node`'a özgü bir yardımcıdır -- paylaşılan
    `app.mcp.mevzuat_client` yardımcılarının aksine kendi zaman aşımını
    taşır, çünkü tek bir çağıranı var ve o çağıranın bütçesi
    (`MEVZUAT_LIVE_SEARCH_TIMEOUT_SECONDS`) zaten sabit. `search_legislation
    (local)` her zaman önce çalışır; bu yalnızca onun üzerine ekler, hiçbir
    zaman yerine geçmez -- ağ hatası veya eşleşme yokluğu, çağıranın zaten
    sahip olduğu yerel sonuçları etkilemez.

    Args:
        query: `_build_mevzuat_query`'nin ürettiği konu sorgusu.

    Returns:
        Canlı eşleşen mevzuattan bir `Document`, ya da hiçbir şey
        eşleşmediğinde/hata veya zaman aşımı olduğunda None -- asla fırlatmaz.
    """
    try:
        resolved = await asyncio.wait_for(
            search_and_excerpt(query),
            timeout=settings.MEVZUAT_LIVE_SEARCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Live mevzuat search timed out after %ss for %r.",
            settings.MEVZUAT_LIVE_SEARCH_TIMEOUT_SECONDS,
            query,
        )
        return None
    except Exception:
        logger.warning("Live mevzuat search failed for %r.", query, exc_info=True)
        return None
    if resolved is None:
        return None
    document_id, excerpt = resolved
    return Document(
        page_content=excerpt,
        metadata={
            "mevzuat": f"mevzuat.gov.tr (canlı, mevzuat_id={document_id})",
            "source": f"mcp:{document_id}",
        },
    )


def _render_mevzuat_excerpts(documents: list[Document]) -> str:
    """Getirilen mevzuat alıntılarını prompt/görüntüleme bağlamı olarak render et.

    Args:
        documents: Hibrit retriever'ın döndürdüğü belgeler.

    Returns:
        Alıntıların tek bir string'de birleştirilmiş hali, hiç yoksa boş string.
    """
    parts: list[str] = []
    for index, document in enumerate(documents, start=1):
        source = document.metadata.get("mevzuat", "bilinmiyor")
        parts.append(f"[ALINTI {index}] (Kaynak: {source})\n{document.page_content}")
    return "\n\n".join(parts)


def _dedupe_suggestions(suggestions: list[dict[str, str]]) -> list[dict[str, str]]:
    """Aynı mevzuata atıf yapan ikinci ve sonraki önerileri at.

    `mevzuat`, kanunu ve maddesini birlikte taşır (ör. "RYUEHY m.11"), bu
    yüzden aynı normalize edilmiş `mevzuat` değerine sahip iki öneri aslında
    aynı bulgudur -- aynı kanunun farklı bir maddesi ayrı bir string olur ve
    dokunulmadan kalır. Retrieval, aynı maddeden birden çok alıntı
    döndürebilir (`MEVZUAT_RESULT_LIMIT` alıntı, parçalanmış (chunked) bir
    korpus), ve hem model hem de `_raw_citation_suggestions` (alıntı başına
    bir öneri) bu tekrarı olduğu gibi yeniden üretir; böylece
    `mevzuat_references`'ı okuyan bir kullanıcı aynı kuralı iki veya üç kez
    listelenmiş görür. İlk görülen kazanır -- retrieval sırası, alaka
    sırasıdır.

    Args:
        suggestions: Her biri bir `mevzuat` taşıyan, sırayla öneriler.

    Returns:
        Aynı öneriler, sırayla, aynı atıfa sahip sonraki girişler
        kaldırılmış olarak.
    """
    seen: set[str] = set()
    deduped = []
    for item in suggestions:
        key = normalize_value(item.get("mevzuat", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _raw_citation_suggestions(documents: list[Document]) -> list[dict[str, str]]:
    """Getirilen her alıntı için, yapısı gereği dayanaklı bir öneri oluştur.

    Her atıf, alıntının gerçekten hangi kanun altında getirildiğini adlandırır;
    bu yüzden `citation_support`'un reddedebileceği hiçbir şey yoktur. Hem
    LLM çağrısının kendisi başarısız olduğunda (mevcut düşüş yolu) hem de
    öneriler geldiğinde ama hepsi dayanak (grounding) kontrolünden geçemediğinde
    kullanılır -- her iki durumda da gereksinim, getirilen atıflarla
    karşılanır, yalnızca modelin açıklaması olmadan.

    `_dedupe_suggestions` ile tekilleştirilir: `documents`, getirilen alıntı
    başına bir girdidir ve aynı maddeden iki alıntı (parçalanmış bir korpus
    bunu rutin olarak döndürür) aksi halde burada iki özdeş satır üretirdi.
    """
    return _dedupe_suggestions(
        [
            {
                "mevzuat": document.metadata.get("mevzuat", "Bilinmeyen kaynak"),
                "aciklama": "İlgili olabilecek mevzuat alıntısı (otomatik açıklama üretilemedi).",
            }
            for document in documents
        ]
    )


def _flatten_fields_for_grounding(fields: dict[str, Any]) -> str:
    """Bir EvrakField sözlüğünü, dayanak (groundedness) kontrolü için düz metne çevir.

    `check_groundedness` normalize edilmiş alt dizi (substring) ve token
    örtüşmesiyle eşleştirir; bu yüzden her değerin tam string biçiminin
    sadakatle yeniden kurulmasına gerek yoktur -- bir liste değeri üzerinde
    `str()` bile her öğenin kelimelerini render edilen metnin içinde bırakır,
    ki bir alt dizi/örtüşme eşleşmesinin ihtiyacı olan da budur.

    Args:
        fields: Belgenin kendi çıkarılmış `EvrakField` değerleri.

    Returns:
        Boş olmayan her değerin boşlukla birleştirilmiş hali, tek bir string.
    """
    return " ".join(str(value) for value in fields.values() if value)


def create_document_analysis_graph(
    llm_client: BaseLLMClient,
    mevzuat_retriever: Optional[Any] = None,
    reasoning_llm_client: Optional[BaseLLMClient] = None,
    fast_llm_client: Optional[BaseLLMClient] = None,
    guard_llm_client: Optional[BaseLLMClient] = None,
):
    """Gelen evrak analizi iş akışını oluştur ve derle.

    Akış::

        START -> analyze -+-> check_compliance -+-> suggest_mevzuat -> END
                          |-> retrieve_mevzuat -/
                          \\-> scan_sensitivity -----------------------> END

    Uyum kontrolü saf hesaplamadır, mevzuat getirme ise ağ G/Ç'sidir; bu
    yüzden eş zamanlı dallar olarak çalışırlar. Ayrık durum anahtarları
    yazarlar, ki fan-out'u özel reducer'lar olmadan güvenli kılan da budur.
    Hassasiyet taraması da saf hesaplamadır (deterministik KVK/işaretleme
    tespiti, LLM çağrısı yok) ve kendi ayrık anahtarını yazar
    (``sensitivity_assessment``); ``suggest_mevzuat``'a değil doğrudan END'e
    dallanır çünkü bu alt-grafta hiçbir aşağı akış düğümü onu bekleyecek
    şekilde bloke olmaya ihtiyaç duymaz ve LangGraph, hangi kenarın END'e
    ulaştığından bağımsız olarak her dalın çıktısını aynı nihai durumda
    birleştirir.

    Detaylı, sınırsız uzunlukta bir özet burada bilinçli olarak
    **üretilmez**. Eskiden beşinci bir dal olarak (``summarize``)
    çalışıyordu, ama doğrudan ölçüldüğünde bu grafta açık farkla en yavaş
    şeydi (diğer her dalın <100s'sine karşı 184-288s) ve ``ainvoke``, her dal
    bitmeden dönemez -- yani sonucu kimse okumasa bile her yükleme bu
    maliyeti ödüyordu. Artık talep üzerine çalışır: bkz.
    ``app.ai.summarization.build_detailed_summary`` ve
    ``DocumentService.generate_detailed_summary``; bu grafın değil, zaten
    önbelleğe alınmış çıkarıma karşı kendi endpoint'i tarafından tetiklenir.

    Args:
        llm_client: Belge analizi için kullanılan LLM.
        mevzuat_retriever: İsteğe bağlı mevzuat retriever'ı -- bir
            HybridRetriever (yerel korpus) veya bir FallbackMevzuatRetriever
            (yerel fallback'li MCP-öncelikli, bkz. app.ai.retrieval.mcp_mevzuat);
            ``async retrieve(query, limit) -> list[Document]`` sağlayan
            herhangi bir şey çalışır. Verilmediğinde iki mevzuat düğümü
            no-op'a düşer, geri kalanı yine çalışır.
        reasoning_llm_client: Mevzuat önerisi adımı için isteğe bağlı ayrı
            bir istemci. Varsayılan olarak ``llm_client``.
        fast_llm_client: İsteğe bağlı hızlı katman istemcisi. Kalite katmanı
            hem birleşik hem de yalnızca-sınıflandırma yapılandırılmış
            çağrılarında başarısız olduğunda, ``DocumentType.OTHER``'a
            düşmeden önce hızlı katmanda bir deneme daha yapılır -- mevcut
            iki katmanlı düşüş merdiveninin altına, yalnızca başarısızlık
            yolunda ödenen üçüncü, ucuz bir basamak.
        guard_llm_client: Guardrail hakemi için isteğe bağlı istemci.
            Varsayılan olarak ``fast_llm_client or llm_client`` --
            genel hızlı katman modeli yerine Evren'in kendine özel ``guard``
            modeline yönlendirmek için ``app.ai.llms.get_guard_llm_client()``
            geçirin.

    Returns:
        Derlenmiş LangGraph iş akışı.
    """
    classifier_agent = ClassifierAgent(llm_client)
    compliance_agent = ComplianceAgent(reasoning_llm_client or llm_client)
    fallback_classifier_agent = ClassifierAgent(fast_llm_client) if fast_llm_client else None
    guardrail_judge_agent = GuardrailJudgeAgent(guard_llm_client or fast_llm_client or llm_client)

    @node_timeout("analyze")
    async def analyze_node(
        state: DocumentAnalysisState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Belgeyi tek bir çağrıda sınıflandır ve başlık alanlarını çıkar."""
        logger.info("Running Document Analysis Node (classify + extract)...")
        await emit_node_start(
            config,
            "classification",
            "Evrak Analizi",
            "Belge sınıflandırılıyor ve üst veriler çıkarılıyor...",
        )

        text = _trim_for_extraction(state["input_text"])

        # Yönetmelik başlık düzenini belirlediği için etiketli alanlar model
        # yerine düzenli ifadelerle okunur. Ayrıştırıcı, örnek korpusta
        # hiç uydurma değer üretmeden 60/60 puan alır.
        parsed = parse_labelled_fields(text)
        logger.info("Parsed %d labelled field(s) deterministically.", len(parsed))

        prompt = (
            "Aşağıdaki evrakın türünü belirle, kısa bir özetini çıkar ve üstveri "
            "alanlarını doldur.\n\n"
            "Tür ayrımında şu ölçütleri kullan:\n"
            "- official_letter: 'T.C.' başlığı, kurum antedi, Sayı/Tarih/Konu "
            "alanları ve kurum yetkilisinin unvanlı imzası bulunan yazı. "
            "Kurumlar arası yazışmaların varsayılan türüdür.\n"
            "- petition: bir vatandaşın kendi adına talep veya şikayet ilettiği, "
            "kurum antedi bulunmayan başvuru.\n"
            "- information_request: yalnızca 4982 sayılı Kanun kapsamında bilgi "
            "veya belge talebi açıkça istendiğinde.\n"
            # circular için açık ayırt edici kriterler gerekir. Bunlar olmadan
            # model, yukarıdaki paragrafın kurumlar arası yazışma için varsayılan
            # olarak adlandırdığı official_letter'a geri düşer -- ve bir genelge
            # yapısal olarak zaten resmî bir yazı*dır*, dolayısıyla onları yalnızca
            # muhatap ve kural koyucu dil ayırır. detect_structural_signal DAĞITIM'ı
            # zaten bildiriyordu, yani gözlem mevcuttu, eksik olan yalnızca ona göre
            # hareket edecek kriterdi. qwen3.5:9b üzerinde örnek korpusta ölçüldü:
            # tür doğruluğu 11/12 -> 12/12, üç tekrar boyunca kararlı (36/36).
            "- circular: tek bir muhataba değil 'DAĞITIM YERLERİNE' / 'Dağıtım' "
            "listesine gönderilen, tek bir olayı değil genel uygulama usul ve "
            "esaslarını düzenleyen yazı (genelge). Muhatabı dağıtım listesi olan ve "
            "'usul ve esaslar', 'tüm birimler' gibi genel düzenleme ifadeleri "
            "taşıyan yazıyı official_letter değil circular say.\n"
            "- directive: belirli bir birime verilen, uyulması zorunlu somut iş "
            "talimatı.\n"
            "- complaint: şikayet bildirimi. report: rapor. minutes: tutanak.\n"
            "- leave_request: izin talebi.\n"
            "- other: yalnızca yukarıdakilerin hiçbiri uymuyorsa.\n\n"
            "Kurum antetli ve unvanlı imza taşıyan bir yazıyı vatandaş başvurusu "
            "olarak sınıflandırma.\n"
            "Alan çıkarımında belgede gerçekten bulunmayan alanları null bırak; "
            "tahmin etme, örnek değer üretme.\n\n"
            f'EVRAK:\n"""\n{text}\n"""'
            # Deterministik regex gözlemleri, talimat olarak değil olgu olarak
            # enjekte edilir. qwen3:8b üzerinde ölçüldüğünde bunlar, zararlı
            # official_letter -> petition karışıklığını azaltır; bu önemlidir
            # çünkü belge türü, gerekli-alan kural tablosunu seçer.
            f"{format_structural_signal(detect_structural_signal(state['input_text']))}"
            f"{format_parsed_fields(parsed)}"
            f"{ocr_warning(state.get('is_ocr_text', False))}"
        )

        try:
            res = await classifier_agent.run_structured(
                messages=prompt,
                response_model=DocumentAnalysisOutput,
                temperature=0.0,
                max_tokens=ANALYSIS_MAX_TOKENS,
            )
            payload = res.model_dump()
            document_type = DocumentType(payload["document_type"])
            summary = payload["summary"]
            model_fields = {key: payload.get(key) for key in EVRAK_FIELD_KEYS}
        except TRANSIENT_ERRORS:
            # Kopan bir bağlantı bu merdivenin her katmanını eşit şekilde
            # etkiler (hepsi aynı Ollama örneğiyle konuşur), bu yüzden bağlantı
            # geri geldiğinde tüm düğümü yeniden denemek, aynı hatayla
            # karşılaşacak düşüş katmanları arasında dönmekten daha iyidir.
            logger.warning("Document Analysis Node hit a transient error; retrying.")
            raise
        except Exception:
            # Yalnızca tür ve özete geri düş. Birleşik şema hızlı yoldur,
            # bir zorunluluk değil: tam alan listesini tutamayan daha küçük
            # bir model, belgeyi "other"a düşürmek yerine yine de kullanılabilir
            # bir sınıflandırma üretmelidir.
            logger.warning(
                "Merged analysis failed; retrying with classification only.",
                exc_info=True,
            )
            try:
                fallback: DocumentClassificationOutput = (
                    await classifier_agent.run_structured(
                        messages=prompt,
                        response_model=DocumentClassificationOutput,
                        temperature=0.0,
                        max_retries=1,
                    )
                )
                document_type = DocumentType(fallback.document_type)
                summary = fallback.summary
            except TRANSIENT_ERRORS:
                logger.warning("Document Analysis Node hit a transient error; retrying.")
                raise
            except Exception:
                if fallback_classifier_agent is not None:
                    logger.warning(
                        "Classification-only analysis also failed; trying the "
                        "fast tier once before giving up.",
                        exc_info=True,
                    )
                    try:
                        fast_fallback: DocumentClassificationOutput = (
                            await fallback_classifier_agent.run_structured(
                                messages=prompt,
                                response_model=DocumentClassificationOutput,
                                temperature=0.0,
                                max_retries=1,
                            )
                        )
                        document_type = DocumentType(fast_fallback.document_type)
                        summary = fast_fallback.summary
                    except TRANSIENT_ERRORS:
                        logger.warning("Document Analysis Node hit a transient error; retrying.")
                        raise
                    except Exception:
                        logger.exception("Document Analysis Node failed on every tier")
                        document_type = DocumentType.OTHER
                        summary = "Evrak özeti çıkarılamadı."
                else:
                    logger.exception("Document Analysis Node failed")
                    document_type = DocumentType.OTHER
                    summary = "Evrak özeti çıkarılamadı."
            # Deterministik olarak ayrıştırılan alanlar hâlâ geçerlidir: bir
            # model hatası, belgeden doğrudan okunan değerleri yok saymamalıdır.
            model_fields = EvrakField().model_dump()

        # Yukarıdaki prompt'un kurulduğu baş/son kısaltılmış `text` değil, tam
        # ve kısaltılmamış belge -- böylece kanıt temelli kurtarma, değer
        # kısaltılmış ortada kaldığında bile onu dayanaklı hale getirebilir.
        merged_fields = merge_parsed_over_model(
            model_fields, parsed, document_text=state["input_text"]
        )
        update = {
            "document_type": document_type.value,
            "document_type_label": DOCUMENT_TYPE_LABELS[document_type],
            "summary": summary,
            "fields": merged_fields,
            "entities": merged_fields.get("entities", []),
        }

        # Sınıflandırmayı hemen görünür kıl. Toplam süreye asıl hakim olan
        # taslaktır; zaten var olan sonuçlar tutulurken kullanıcının bir
        # yükleme animasyonuna bakması için bir sebep yoktur.
        await emit_partial(config, "classification", update)
        return update

    async def check_compliance_node(
        state: DocumentAnalysisState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Gerekli alanları kontrol et. Saf küme çıkarma; LLM yok."""
        logger.info("Running Compliance Check Node...")
        try:
            fields = EvrakField(**(state.get("fields") or {}))
            # Bu belge için işaret tespiti hiç çalışmadıysa None döner
            # (bilinmiyor anlamında, imzasız değil) -- bkz.
            # DocumentAnalysisState.detected_marks ve check_required_fields'in
            # kendi docstring'i.
            marks = state.get("detected_marks")
            is_signed = (
                any(mark.get("kind") == "signature" for mark in marks)
                if marks is not None
                else None
            )
            report = check_required_fields(
                state.get("document_type", DocumentType.OTHER.value),
                fields,
                is_signed=is_signed,
            )
            update = {
                "missing_fields": [item.model_dump() for item in report.missing_fields],
                "compliance_status": report.status.value,
                "checked_field_count": report.checked_field_count,
            }
        except Exception:
            logger.exception("Compliance Check Node failed")
            update = {
                "missing_fields": [],
                "compliance_status": ComplianceStatus.INCOMPLETE.value,
                "checked_field_count": 0,
            }

        await emit_partial(config, "compliance", update)
        return update

    @node_timeout("scan_sensitivity")
    async def scan_sensitivity_node(
        state: DocumentAnalysisState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Gizlilik işaretlemesini ve KVK açığa çıkmasını değerlendir, ardından
        hiçbir örüntü eşleşmese bile belgenin anlam olarak hassas okunup
        okunmadığını nüans hakemine sor.

        ``analyze``'den ayrılan bağımsız bir daldır (yukarıdaki akış
        diyagramına bakın): bu alt-grafta hiçbir aşağı akış düğümü onu
        bekleyecek şekilde bloke olmaya ihtiyaç duymaz, bu yüzden
        ``suggest_mevzuat``'ın fan-in'ine katılmak yerine doğrudan END'e
        dallanır. ``DocumentService``, ``sensitivity_assessment``'ı, diğer
        her dalın çıktısıyla birlikte nihai birleşik durumdan okur.
        """
        logger.info("Running Sensitivity Scan Node...")
        input_text = state.get("input_text", "")
        try:
            fields = EvrakField(**(state.get("fields") or {}))
            assessment = assess_sensitivity(fields=fields, text=input_text)
        except Exception:
            logger.exception("Sensitivity Scan Node failed")
            assessment = SensitivityAssessment(
                level=SensitivityLevel.UNMARKED, requires_review=False
            )

        if not assessment.requires_review:
            # Yalnızca deterministik katman belgeyi zaten işaretlemediğinde
            # sormaya değer -- bu özellikle "hiçbir örüntü eşleşmedi ama
            # hassas okunuyor" durumudur; incelemeye zaten yönlendirilmiş bir
            # belge, burada ikinci bir görüşten bir şey kazanmaz.
            judge_verdict = await judge_input_sensitivity(guardrail_judge_agent, text=input_text)
            promotion_floor = get_policy().guardrail.judge_promotion_confidence
            if (
                judge_verdict is not None
                and judge_verdict.sensitive
                and judge_verdict.confidence >= promotion_floor
            ):
                assessment = assessment.model_copy(
                    update={
                        "requires_review": True,
                        "reasons": [
                            *assessment.reasons,
                            f"llm-judge anlam bazlı hassasiyet: {judge_verdict.reason}",
                        ],
                    }
                )

        update = {"sensitivity_assessment": assessment.model_dump(mode="json")}
        await emit_partial(config, "sensitivity", update)
        return update

    @node_timeout("retrieve_mevzuat")
    async def retrieve_mevzuat_node(
        state: DocumentAnalysisState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Belge için mevzuat alıntılarını getir.

        "rag" düğüm kimliği altında kendi node_start/node_end'ini yayınlar --
        frontend'deki "Mevzuat" panelinin hiç veri göstermemesinin (D1) kök
        nedeni, bu düğümün daha önce hiçbir şey yayınlamamasıydı; oysa
        getirdiği alıntılar gerçekti ve hem taslak özette hem de analiz
        yanıtının mevzuat_references alanında kullanılıyordu.
        """
        query = _build_mevzuat_query(state)
        await emit_node_start(
            config, "rag", "Mevzuat Tarama", "Mevzuat veri tabanında ilgili maddeler taranıyor..."
        )

        if mevzuat_retriever is None:
            logger.info("No mevzuat retriever configured; skipping retrieval.")
            await emit_node_end(
                config,
                "rag",
                "Mevzuat Tarama",
                "Mevzuat erişimi yapılandırılmadığı için atlandı.",
                {"search_query": query, "documents": [], "context": ""},
            )
            return {"mevzuat_documents": []}

        logger.info("Running Mevzuat Retrieval Node...")
        try:
            documents = await mevzuat_retriever.retrieve(query, limit=MEVZUAT_RESULT_LIMIT)
            # LOCAL_MODE=false iken canlı bir eskalasyon dene -- LOCAL_MODE=
            # true'da mevzuat-mcp yalnızca boot'taki curated 7 kanunu ısıtmak
            # için kullanılır (bkz. app.ai.retrieval.mcp_mevzuat), istek
            # başına burada değil. Bağımsız kapılı: yerel sonuç zaten elde,
            # canlı deneme başarısız olursa mevcut `documents` değişmeden
            # kalır -- bkz. _fetch_live_mevzuat_excerpt'in kendi docstring'i.
            live_enabled = (
                not settings.LOCAL_MODE
                and settings.MEVZUAT_MCP_ENABLED
                and is_registered(MEVZUAT_SERVER)
            )
            if live_enabled:
                live_document = await _fetch_live_mevzuat_excerpt(query)
                if live_document is not None:
                    documents = [live_document, *documents][:MEVZUAT_RESULT_LIMIT]
            logger.info("Retrieved %d mevzuat excerpt(s).", len(documents))
            await emit_node_end(
                config,
                "rag",
                "Mevzuat Tarama",
                f"{len(documents)} mevzuat alıntısı bulundu.",
                {
                    "search_query": query,
                    "documents": [
                        {
                            "page_content": document.page_content,
                            "metadata": document.metadata,
                        }
                        for document in documents
                    ],
                    "context": _render_mevzuat_excerpts(documents),
                },
            )
            return {"mevzuat_documents": documents}
        except TRANSIENT_ERRORS:
            # Kopan bir bağlantıyı grafın IO_RETRY politikasının yeniden
            # denemesine izin ver; burada yutmak, yeniden deneme politikasının
            # hiç tetiklenmemesi anlamına gelirdi.
            logger.warning("Mevzuat Retrieval Node hit a transient error; retrying.")
            raise
        except Exception:
            logger.exception("Mevzuat Retrieval Node failed")
            await emit_node_error(
                config,
                "rag",
                "Mevzuat Tarama",
                "Mevzuat taraması sırasında bir hata oluştu.",
                fatal=False,
            )
            return {"mevzuat_documents": []}

    @node_timeout("suggest_mevzuat")
    async def suggest_mevzuat_node(
        state: DocumentAnalysisState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Getirilen hükümlerin bu belgeyle nasıl ilişkili olduğunu açıkla."""
        documents = state.get("mevzuat_documents") or []
        if not documents:
            logger.info("No mevzuat excerpts available; skipping suggestion.")
            await emit_node_end(
                config, "classification", "Evrak Analizi", "Evrak analizi tamamlandı."
            )
            return {"mevzuat_suggestions": []}

        logger.info("Running Mevzuat Suggestion Node...")
        excerpts = "\n\n".join(
            f"[ALINTI {index}] (Kaynak: {document.metadata.get('mevzuat', 'bilinmiyor')})\n"
            f"{document.page_content}"
            for index, document in enumerate(documents, start=1)
        )
        missing_labels = ", ".join(
            item.get("label", "") for item in state.get("missing_fields") or []
        )
        prompt = (
            f"Evrak türü: {state.get('document_type_label', 'bilinmiyor')}\n"
            f"Evrak özeti: {state.get('summary', '')}\n"
            f"Tespit edilen eksik alanlar: {missing_labels or 'yok'}\n\n"
            f'MEVZUAT ALINTILARI:\n"""\n{excerpts}\n"""\n\n'
            "Yalnızca yukarıdaki alıntılara dayanarak bu evrakla ilgili mevzuat "
            "hükümlerini listele. Alıntılarda bulunmayan madde numarası veya kanun "
            "adı üretme."
        )
        # Dayanak (grounding) filtresi çalıştığında try bloğunun içinde
        # atanır; diğer her yolda (geçici hata yeniden denemesi, tam
        # başarısızlık fallback'i) 0 kalır çünkü `_raw_citation_suggestions`
        # yapısı gereği dayanaklıdır ve hiçbir şeyi atmaya ihtiyaç duymaz.
        dropped_suggestion_count = 0
        try:
            # Düğümün kendi bütçesinin altında, düğümün *içinde* sınırlanır;
            # böylece bir aşım node_timeout'a kaçmak yerine aşağıdaki düşüş
            # yoluna düşer. Alıntıları açıklamak, 5. gereksinimin isteğe bağlı
            # yarısıdır -- atıflar zaten getirilmiş ve doğrudur -- bu yüzden
            # yavaş bir model yalnızca açıklamaya mal olmalı, asla analize değil.
            #
            # Reasoning seviyesi burada `state`'ten okunur, tıpkı dıştaki
            # @node_timeout'un onu _reasoning_level_of aracılığıyla okuduğu
            # sebeple aynı: iki bütçe birlikte ölçeklenmelidir. DocumentAnalysisState
            # bugün bir reasoning_level alanı taşımıyor, bu yüzden ikisi de şu an
            # aynı dengeli varsayılana çözülüyor -- ama bu çözülme bağımsız olarak
            # gerçekleşti, yapısal olarak bağlı olmaktan ziyade birbirinden ayrı
            # yazılmış iki çağrı noktasının tesadüfen uyuşması yoluyla. Bu duruma
            # gelecekte bu satırı da güncellemeden bir reasoning_level alanı
            # eklenseydi, hızlı bir çalışma (dıştakinin 0.6x'i) bu iç sınırın
            # (0.85x) kendi node_timeout'unu aşmasına yol açardı ve
            # suggest_mevzuat'ın düşüş yolu -- bu iç sınırın var olma sebebinin
            # tamamı -- tekrar erişilemez hale gelirdi.
            res: MevzuatSuggestionOutput = await asyncio.wait_for(
                compliance_agent.run_structured(
                    messages=prompt,
                    response_model=MevzuatSuggestionOutput,
                    temperature=0.0,
                    max_tokens=SUGGESTION_MAX_TOKENS,
                ),
                timeout=node_budget("suggest_mevzuat", state.get("reasoning_level"))
                * SUGGESTION_BUDGET_SHARE,
            )
            suggestions = [item.model_dump() for item in res.suggestions]

            # Her öneriyi, güya çıkarıldığı alıntılara karşı doğrula --
            # yukarıdaki prompt modelden ALINTILARI'nda bulunmayan bir
            # madde/kanun uydurmamasını ister, ama şimdiye kadar hiçbir şey
            # bunu zorunlu kılmıyordu. Hiçbir alıntıda bulunmayan bir kanuna
            # atıf yapan öneri doğrudan atılır (bkz. `citation_support.grounded`);
            # atıf uydurmaysa açıklamasını kontrol etmeye bile değmez. Dayanaklı
            # bir atıfa sahip ama desteklenmeyen sayı/tarih/kurum/tutar iddiaları
            # içeren bir açıklamaya sahip öneri, atıfı korur ve yalnızca
            # açıklamayı kaybeder -- aşağıdaki except dalının fallback'inin zaten
            # kullandığı aynı nötr metin -- çünkü 5. gereksinimin asıl ihtiyacı
            # atıfın kendisidir.
            source_materials = "\n\n".join(
                part
                for part in (
                    excerpts,
                    state.get("summary", ""),
                    _flatten_fields_for_grounding(state.get("fields") or {}),
                )
                if part
            )
            grounded_suggestions = []
            dropped = 0
            for item in suggestions:
                support = citation_support(item.get("mevzuat", ""), documents)
                if not support.grounded:
                    dropped += 1
                    continue
                unsupported_claims = check_groundedness(
                    item.get("aciklama", ""), source_materials=source_materials
                )
                if unsupported_claims:
                    # Diagnostic-only: the citation itself already passed
                    # `citation_support` above, so this is never about a
                    # fabricated reference -- only ever about
                    # `check_groundedness` (built for auditing *drafts* against
                    # tool results, not for auditing a citation's own
                    # explanatory prose) flagging some claim in `aciklama`
                    # that its narrower source_materials don't happen to
                    # cover. Logged at warning, unlike the `dropped` branch
                    # above, because until now nothing recorded which claim
                    # triggered this or what text was discarded -- a user
                    # seeing the generic fallback message had no way to tell
                    # a real false positive from a genuine fabrication, and
                    # neither did anyone reading the logs afterward.
                    logger.warning(
                        "Mevzuat suggestion aciklama for [%s] failed "
                        "groundedness (%d unsupported claim(s): %s); "
                        "replacing with the generic fallback. Original: %r",
                        item.get("mevzuat", ""),
                        len(unsupported_claims),
                        [
                            f"{claim.kind}={claim.value!r}"
                            for claim in unsupported_claims
                        ],
                        item.get("aciklama", ""),
                    )
                    item = {
                        **item,
                        "aciklama": (
                            "İlgili olabilecek mevzuat alıntısı "
                            "(otomatik açıklama üretilemedi)."
                        ),
                    }
                grounded_suggestions.append(item)

            dropped_suggestion_count = dropped
            if dropped:
                logger.warning(
                    "Dropped %d ungrounded mevzuat suggestion(s) out of %d.",
                    dropped,
                    len(suggestions),
                )
            # Ham atıflara yalnızca model öneri *ürettiğinde* ve dayanak
            # kontrolü hepsini reddettiğinde geri düş. Kendisi boş bir liste
            # döndüren bir model meşru bir "önerilecek bir şey yok" kararı
            # vermiştir ve boş kalmalıdır; fallback gerektiren bir uydurma
            # olarak yeniden yorumlanmamalıdır.
            if suggestions and not grounded_suggestions:
                suggestions = _raw_citation_suggestions(documents)
            else:
                # Parçalanmış bir korpustan gelen `MEVZUAT_RESULT_LIMIT`
                # alıntısı aynı maddeye birden fazla kez düşebilir; bu durumda
                # modelin kendisine verilen her alıntı için bir öneri
                # yazmamak için hiçbir sebebi yoktur ve bu tekrarı, ham atıf
                # fallback'inin yapacağı gibi kendi çıktısında yeniden üretir.
                suggestions = _dedupe_suggestions(grounded_suggestions)
        except TRANSIENT_ERRORS:
            logger.warning("Mevzuat Suggestion Node hit a transient error; retrying.")
            raise
        except Exception:
            logger.exception("Mevzuat Suggestion Node failed")
            # Gereksinimi kaybetmek yerine ham atıflara düş.
            suggestions = _raw_citation_suggestions(documents)

        await emit_node_end(
            config,
            "classification",
            "Evrak Analizi",
            "Evrak analizi tamamlandı.",
            {
                "mevzuat_suggestions": suggestions,
                "dropped_suggestion_count": dropped_suggestion_count,
            },
        )
        return {"mevzuat_suggestions": suggestions}

    builder = StateGraph(DocumentAnalysisState)
    # check_compliance, zaten getirilmiş durum üzerinde saf hesaplama yapar ve
    # kendi try/except'inin ötesine hiçbir zaman istisna geçirmez, bu yüzden
    # bir yeniden deneme politikası taşımaz.
    builder.add_node("analyze", analyze_node, retry_policy=LLM_RETRY)
    builder.add_node("check_compliance", check_compliance_node)
    builder.add_node("retrieve_mevzuat", retrieve_mevzuat_node, retry_policy=IO_RETRY)
    builder.add_node("suggest_mevzuat", suggest_mevzuat_node, retry_policy=LLM_RETRY)
    builder.add_node("scan_sensitivity", scan_sensitivity_node)

    builder.add_edge(START, "analyze")
    # Fan out: compliance CPU'ya bağlıdır, retrieval ağa bağlıdır ve
    # hassasiyet taraması CPU'ya bağlıdır ve ikisinden de bağımsızdır.
    builder.add_edge("analyze", "check_compliance")
    builder.add_edge("analyze", "retrieve_mevzuat")
    builder.add_edge("analyze", "scan_sensitivity")
    # Fan in: LangGraph bu düğümü çalıştırmadan önce her iki dalı da bekler.
    builder.add_edge("check_compliance", "suggest_mevzuat")
    builder.add_edge("retrieve_mevzuat", "suggest_mevzuat")
    builder.add_edge("suggest_mevzuat", END)
    # Bağımsız dal -- doğrudan END'e kendi yolu.
    builder.add_edge("scan_sensitivity", END)

    return builder.compile()
