import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.agents.router import RouterAgent
from app.ai.policy import get_policy
from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.events import emit_node_end, emit_node_start
from app.ai.workflows.intent_scorer import normalize
from app.ai.workflows.resilience import LLM_RETRY, TRANSIENT_ERRORS, node_timeout

logger = logging.getLogger(__name__)

#: Bu skorun altında draft, model çağrısıyla otomatik yönlendirilecek kadar
#: güvenilir değildir -- routing yine de her zaman en iyi çaba (best-effort)
#: bir birim önerir (bkz. `_best_effort_unit`), yalnızca boş bırakılmak
#: yerine denetim için `requires_human_approval=True` işaretlenir. Policy
#: bunu `MIN_AUTOMATED_CONFIDENCE_SCORE` ile birlikte sahipleniyor; ikisi
#: arasındaki ilişki zorunlu bir değişmezdir: 70 "gözden geçirilmeden
#: gönderilebilir" demektir, 50 "otomatik yönlendirilecek kadar güvenilir
#: değil" demektir, ve bunları ters çevirmek, yönlendirilemeyecek kadar
#: zayıf bir draft'ı aynı anda gönderilebilecek kadar iyi yapardı.
HUMAN_APPROVAL_SCORE_THRESHOLD = get_policy().routing.human_approval_score_threshold

#: Yönlendirme için uygun, tek bir şirkete kapsanmış birimler için
#: `(ad, açıklama)` çiftleri. Çağıran tarafından sağlanır (bkz.
#: `create_routing_graph`) ve her kararda yeniden getirilir -- artık modül
#: seviyesinde bir sabit yok, çünkü liste artık policy değil, çalışma
#: zamanında yönetiliyor (bkz. `app.domains.units`). `company_id` alır
#: çünkü birimler şirket-kapsamlıdır (Faz 1 tenancy çalışması): burada her
#: şirketin birimlerini döndürmek, bir kiracının bölüm adlarını/
#: açıklamalarını başka bir kiracının yönlendirme prompt'una sızdırırdı.
UnitsProvider = Callable[[str], Awaitable[List[Tuple[str, str]]]]


class RoutingState(TypedDict, total=False):
    """Birim-yönlendirme workflow'u için LangGraph state'i.

    ``total=False`` ile bildirildi ve node'un yazdığı her anahtarı içeriyor.
    LangGraph, state şemasında bulunmayan anahtarlar için güncellemeleri
    düşürür; bu yüzden node onları döndürmesine rağmen
    ``routed_unit``/``reasoning``/``priority`` daha önce API yanıtına hiç
    ulaşmıyordu.
    """

    draft: str
    confidence_score: float
    #: Hangi şirketin birim listesine göre yönlendirileceği. Artık her
    #: çağıran bunu sağlıyor (`DraftService.generate_draft_and_route`,
    #: `routing/router.py`ve `planning_graph.py`'ın routing alt-çağrısı
    #: üzerinden `PlanningState.company_id`) -- boş/eksik olması, her
    #: şirketin birimlerine geri düşmek yerine yine de "hiç birim
    #: tanımlanmamış"a düşer (bkz. `routing_node`'un `if not units:` dalı);
    #: bu tutmayan herhangi bir çağıran için fail-secure'dır.
    company_id: str
    final_destination: Optional[str]
    justification: str
    routed_unit: Optional[str]
    reasoning: str
    priority: str
    requires_human_approval: bool
    #: Bir ikinci sıradaki belirlenebildiğinde, ikinci tercih birim adı/
    #: adları -- asla `routed_unit`'in yerine geçmez, yalnızca onunla
    #: birlikte gösterilen bir seçenektir (bkz. Görev'in "her zaman bir
    #: öneri + alternatif" gereksinimi). Şirketin yalnızca bir aktif birimi
    #: varsa boştur.
    alternative_units: List[str]


class RouteOutput(BaseModel):
    """Yapılandırılmış yönlendirme kararı.

    ``destination``/``alternative`` bir ``Literal`` yerine düz ``str``'dir --
    uygun birim kümesi çalışma zamanında yönetilir ve iki yönlendirme
    çağrısı arasında değişebilir, dolayısıyla yanıt modelinin tipine
    gömülemez. Çağıran (aşağıdaki `routing_node`), her ikisini de prompt'ta
    gerçekten sunulan birim listesine karşı doğrular.
    """

    destination: str = Field(
        description="Yazının yönlendirileceği birim. Yalnızca verilen listeden bir birim seçilmelidir."
    )
    alternative: str = Field(
        default="",
        description=(
            "Birincil öneri uygun bulunmazsa denenebilecek ikinci en uygun birim. "
            "Yalnızca verilen listeden, birincil öneriyle aynı olmayan bir birim adı. "
            "Uygun bir alternatif yoksa boş bırak."
        ),
    )
    justification: str = Field(
        description="Yazının içeriğine göre neden bu birime yönlendirildiğinin kısa Türkçe gerekçesi."
    )


def _decision(
    destination: Optional[str],
    justification: str,
    *,
    requires_human_approval: bool,
    alternatives: Tuple[str, ...] = (),
) -> Dict[str, Any]:
    """Bir karar için tam routing state güncellemesini oluşturur.

    Args:
        destination: Seçilen birimin adı, ya da yalnızca şirketin hiç aktif
            birimi olmadığında ``None`` -- diğer her durum bunu ayarsız
            bırakmak yerine ``_best_effort_unit``'ten doldurur (bkz. o
            fonksiyonun kendi docstring'i).
        justification: Türkçe gerekçe.
        requires_human_approval: Bu seçimin gözden geçirme için
            işaretlenecek kadar düşük güvenli olup olmadığı -- aynı bayrağı
            `app.domains.documents.draft_service` ve draft-kalite skoru da
            puanlama/denetim için kullanır. Kaydedilir, ama asla
            `destination`'ı vermemek için bir gerekçe değildir: bir birim
            önerisi her zaman hiç olmamasından iyidir (bkz. Görev'in kendi
            gereksinimi).
        alternatives: Varsa, ikinci sıradaki birim adı/adları.

    Returns:
        Hem kanonik hem de API'ye görünen anahtar adlarıyla state güncellemesi.
    """
    return {
        "final_destination": destination,
        "justification": justification,
        "routed_unit": destination,
        "reasoning": justification,
        "priority": "Yüksek" if requires_human_approval else "Normal",
        "requires_human_approval": requires_human_approval,
        "alternative_units": list(alternatives),
    }


def _format_units(units: List[Tuple[str, str]]) -> str:
    """`(ad, açıklama)` çiftlerini prompt için Türkçe bir madde listesi olarak render eder."""
    return "\n".join(f"- {name}: {description}" for name, description in units)


def _tokenize(text: str) -> set[str]:
    """Metni önemli (uzunluk > 2) normalleştirilmiş token'larına indirger."""
    return {token for token in normalize(text).split() if len(token) > 2}


def _rank_units(draft: str, units: List[Tuple[str, str]]) -> List[str]:
    """Her birimin adı+açıklamasının, draft'ın kendi kelime dağarcığıyla
    ne kadar örtüştüğüne göre sıralanmış hali -- en yüksek örtüşme önce.

    Hiç sinyal olmaması yerine kasıtlı olarak zayıf, deterministik bir
    sinyal (semantik eşleşme değil, düz token örtüşmesi): hiçbir şey
    örtüşmediğinde (boş bir draft, ilgisiz kelime dağarcığı), her birim 0
    puan alır ve Python'ın kararlı (stable) sıralaması onları çağıranın
    kendi sırasında bırakır, böylece bu yine de keyfi bir karıştırma
    yerine kullanılabilir *bir şey* döndürür.

    Args:
        draft: Birimlerin puanlanacağı draft metni (boş olabilir).
        units: `(ad, açıklama)` çiftleri.

    Returns:
        Birim adları, en iyi eşleşme önce. `units` ile aynı uzunlukta.
    """
    draft_tokens = _tokenize(draft)
    return [
        name
        for name, _description in sorted(
            units,
            key=lambda unit: len(draft_tokens & _tokenize(f"{unit[0]} {unit[1]}")),
            reverse=True,
        )
    ]


def _best_effort_unit(draft: str, units: List[Tuple[str, str]]) -> Tuple[str, Tuple[str, ...]]:
    """Bir birincil + (en fazla bir) alternatif birim; `units` boş
    değilken boş olmayacağı garanti edilir.

    Eskiden `routed_unit`'i ayarsız bırakan her dalın artık bunun yerine
    çağırdığı deterministik fallback: model başarısız olsun, listede
    olmayan bir şey döndürsün ya da hiç sormaya yetecek kadar güvenli
    olmasın (`score < HUMAN_APPROVAL_SCORE_THRESHOLD`), şirketin kendi
    birim listesi kullanıcıya asla eli boş sunulmaz (bkz. Görev'in "her
    zaman en az bir öneri" gereksinimi) -- makul bir tahmin, doldurulmamış
    bir alandan iyidir, ve çağırana görünür `requires_human_approval`
    bayrağı yine de bu belirli seçimin denetim için bir fallback olduğunu
    kaydeder.

    Args:
        draft: Puanlanacak draft metni (boş olabilir).
        units: Bu şirketin aktif `(ad, açıklama)` birimleri. Boş
            olmamalıdır -- "hiç birim tanımlanmamış" durumu, buraya hiç
            ulaşılmadan önce çağıran tarafından ele alınır.

    Returns:
        En yüksek sıradaki birim adı ve varsa ikinci sıradakiyle birlikte
        0-veya-1 uzunlukta bir tuple.
    """
    ranking = _rank_units(draft, units)
    return ranking[0], tuple(ranking[1:2])


def _fill_alternative(
    draft: str, units: List[Tuple[str, str]], primary: str, candidate: str
) -> Tuple[str, ...]:
    """Bu kararın alternatifini çözer: geçerliyse modelin kendi seçimi,
    değilse `primary`'yi hariç tutan deterministik best-effort ikinci sıradaki.

    Args:
        draft: Draft metni (deterministik fallback sıralaması için).
        units: Bu şirketin aktif birimleri.
        primary: Zaten karar verilmiş birincil hedef.
        candidate: Modelin kendi `RouteOutput.alternative`'ı, geçersiz
            olabilir (listede yok, boş, ya da `primary`'nin bir kopyası).

    Returns:
        0-veya-1 uzunlukta bir tuple.
    """
    unit_names = {name for name, _ in units}
    if candidate and candidate != primary and candidate in unit_names:
        return (candidate,)
    remaining = [unit for unit in units if unit[0] != primary]
    if not remaining:
        return ()
    return tuple(_rank_units(draft, remaining)[:1])


def create_routing_graph(llm_client: BaseLLMClient, units_provider: UnitsProvider):
    """Birim-yönlendirme workflow'unu oluşturur ve derler.

    Akış: START -> route -> END

    Args:
        llm_client: Yönlendirme kararı için kullanılan LLM. Hızlı-katman
            (fast-tier) istemciyi geçirin: çıktı bir etiket artı bir cümledir.
        units_provider: Bir `company_id` alan ve o şirketin şu anda aktif
            `(ad, açıklama)` birimlerini, her çağrıda yeniden okuyarak
            döndüren async çağrılabilir (bkz.
            `app.domains.units.provider.get_active_units_for_routing`) --
            `llm_client` ile aynı şekilde enjekte edilir, böylece bu modül
            `app.domains`'i asla doğrudan import etmez.

    Returns:
        Derlenmiş LangGraph workflow'u.
    """
    router_agent = RouterAgent(llm_client)

    @node_timeout("route")
    async def routing_node(state: RoutingState, config: RunnableConfig) -> Dict[str, Any]:
        logger.info("Running Routing Node...")
        await emit_node_start(
            config, "routing", "Birim Yönlendirme", "İlgili birim belirleniyor..."
        )

        score = state.get("confidence_score", 100.0)
        draft = (state.get("draft") or "").strip()
        company_id = state.get("company_id") or ""
        units = await units_provider(company_id) if company_id else []

        if not units:
            # Gerçekten önerecek hiçbir şeyi olmayan tek dal -- aşağıdaki
            # diğer her durum, `destination`'ı ayarsız bırakmak yerine her
            # zaman `_best_effort_unit`'ten doldurur (bkz. Görev'in "her
            # zaman en az bir öneri" gereksinimi).
            logger.warning("No active units configured; routing cannot assign one.")
            update = _decision(
                None,
                "Şirkette tanımlı aktif birim bulunmuyor.",
                requires_human_approval=True,
            )
        elif not draft:
            primary, alternatives = _best_effort_unit(draft, units)
            update = _decision(
                primary,
                "Yönlendirilecek bir taslak metni bulunmadığı için birim, şirketin birim "
                "listesinden en olası seçenek olarak önerildi; gözden geçirilmesi önerilir.",
                requires_human_approval=True,
                alternatives=alternatives,
            )
        elif score < HUMAN_APPROVAL_SCORE_THRESHOLD:
            logger.warning("Confidence score %.1f too low; falling back to a best-effort pick.", score)
            primary, alternatives = _best_effort_unit(draft, units)
            update = _decision(
                primary,
                "Yazının güven skoru düşük olduğu için birim, taslağın içeriğine göre en "
                "olası seçenek olarak önerildi; gözden geçirilmesi önerilir.",
                requires_human_approval=True,
                alternatives=alternatives,
            )
        else:
            unit_names = {name for name, _ in units}
            prompt = (
                f'Taslak İçeriği:\n"""\n{draft}\n"""\n'
                f"Güven Skoru: {score}\n\n"
                "Bu yazının konusunu analiz ederek en uygun birime yönlendir. Mümkünse "
                "ikinci en uygun birimi de alternatif olarak belirt.\n"
                f"Yönlendirme yapabileceğin birimler:\n{_format_units(units)}\n\n"
                "Yalnızca yukarıdaki listeden bir birim adı seç.\n\n"
                "Yönlendirme kararını ve kısa gerekçesini yapılandırılmış Türkçe formatta döndür."
            )
            try:
                res: RouteOutput = await router_agent.run_structured(
                    messages=prompt, response_model=RouteOutput, temperature=0.0
                )
                if res.destination in unit_names:
                    alternatives = _fill_alternative(draft, units, res.destination, res.alternative)
                    update = _decision(
                        res.destination,
                        res.justification,
                        requires_human_approval=False,
                        alternatives=alternatives,
                    )
                else:
                    logger.warning(
                        "Router returned a unit outside the offered list: %r", res.destination
                    )
                    primary, alternatives = _best_effort_unit(draft, units)
                    update = _decision(
                        primary,
                        "Model tanımlı birim listesi dışında bir yanıt verdi; birim, taslağın "
                        "içeriğine göre en olası seçenek olarak önerildi; gözden geçirilmesi "
                        "önerilir.",
                        requires_human_approval=True,
                        alternatives=alternatives,
                    )
            except TRANSIENT_ERRORS:
                logger.warning("Routing Node hit a transient error; retrying.")
                raise
            except Exception:
                logger.exception("Routing Node failed")
                primary, alternatives = _best_effort_unit(draft, units)
                update = _decision(
                    primary,
                    "Yönlendirme sırasında bir hata oluştu; birim, taslağın içeriğine göre en "
                    "olası seçenek olarak önerildi; gözden geçirilmesi önerilir.",
                    requires_human_approval=True,
                    alternatives=alternatives,
                )

        await emit_node_end(
            config, "routing", "Birim Yönlendirme", "Birim yönlendirmesi tamamlandı.", update
        )
        return update

    builder = StateGraph(RoutingState)
    builder.add_node("route", routing_node, retry_policy=LLM_RETRY)
    builder.add_edge(START, "route")
    builder.add_edge("route", END)

    return builder.compile()
