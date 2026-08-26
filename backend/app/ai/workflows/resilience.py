"""LangGraph node'ları için merkezileştirilmiş dayanıklılık (resilience) ilkelleri.

LangGraph, ``RetryPolicy``'yi sürümler arasında ``langgraph.pregel`` ile
``langgraph.types`` arasında taşıdı. Bu kod tabanında ona ihtiyaç duyan her
modül onu doğrudan LangGraph'tan değil buradan import ediyor; böylece bir
sürüm yükseltmesinde yalnızca tek bir import yolunun düzeltilmesi yeterli
oluyor, her grafikte grep-and-replace yapmak gerekmiyor.
"""

import asyncio
import functools
import logging
import time
from typing import Any, Awaitable, Callable, Optional, TypeVar

import httpx

from app.ai.policy import get_policy
from app.ai.policy.budget import node_budget
from app.observability.ai_metrics import NODE_DURATION

try:
    from langgraph.types import RetryPolicy
except ImportError:  # pragma: no cover - depends on the resolved langgraph version
    from langgraph.pregel import RetryPolicy  # type: ignore[no-redef,assignment]

logger = logging.getLogger(__name__)

T = TypeVar("T")

class NodeBudgetExceeded(Exception):
    """Bir node, kendi zaman bütçesini aşarak çalıştı.

    Kasıtlı olarak bir `TimeoutError` *değil* ve kasıtlı olarak
    `TRANSIENT_ERRORS` içinde yer almıyor. İkisi birbirine benziyor ama
    zıt şeyler ifade ediyor: httpx'ten gelen bir `TimeoutError`, askıda kalmış
    ve tekrar denemeye değer bir bağlantıdır; buysa işin kendisinin bütçe için
    çok yavaş olduğunu söylüyor -- ve yerel bir modelde bu neredeyse her
    zaman ikinci denemede de doğru olacaktır.

    Bunu yeniden denemek fiilen zararlıydı. `suggest_mevzuat` normalde 70s'lik
    bir bütçeye karşı 28-34s'de bitiyor; ara sıra uzun sürdüğünde, LangGraph
    node'u yeniden deniyor, bir 70s daha harcıyor ve sonra tüm isteği
    başarısız kılıyordu. Marjinal bir yavaşlama, 502 ile biten 166s'lik bir
    beklemeye dönüşüyordu; oysa hiçbir şey yapmamak 71s'e mal olacak ve yine
    de kullanılabilir bir cevap verecekti.
    """


#: İkinci bir denemeye değer geçici hatalar: Ollama veya Qdrant'a askıda
#: kalmış/kopmuş bir bağlantı; bir doğrulama hatası veya şema uyuşmazlığı
#: değil (bunlar tüm node'u yeniden denemek yerine BaseAgent.run_structured'ın
#: kendi düzeltme döngüsüyle ele alınır), ve bütçe tükenmesi de değil (bkz.
#: NodeBudgetExceeded).
TRANSIENT_ERRORS = (ConnectionError, httpx.HTTPError, httpx.TimeoutException)

#: UI'a token akıtmayan (stream etmeyen) LLM destekli node'lar için. Zaten
#: token yaymış bir node'u (draft writer) yeniden denemek, tüm üretimi
#: frontend'in streamingText'ine tekrar oynatırdı -- bu node'lar
#: dayanıklılığını bunun yerine reflexion döngüsünden alır (bkz.
#: draft_graph.py), asla bu policy'den değil.
LLM_RETRY = RetryPolicy(
    max_attempts=2,
    initial_interval=0.5,
    backoff_factor=2.0,
    retry_on=TRANSIENT_ERRORS,
)

#: Bir LLM çağrısından daha ucuza yeniden denenebilen alım (retrieval) /
#: vektör-deposu I/O'su için.
IO_RETRY = RetryPolicy(
    max_attempts=3,
    initial_interval=0.3,
    backoff_factor=2.0,
    retry_on=TRANSIENT_ERRORS,
)

#: Node başına timeout bütçeleri; bunları raporlayan çağrı noktalarında
#: okunabilirlik için modül takma adı olarak tutuluyor. Değerler
#: ``app.ai.policy`` içinde yaşıyor, böylece onları workflow tavanıyla
#: ilişkilendiren değişmezlerin (invariant) yanında duruyorlar.
NODE_TIMEOUT_SECONDS = get_policy().budget.node_seconds


def _reasoning_level_of(args: tuple[Any, ...]) -> Optional[str]:
    """Çalışmanın reasoning level'ını bir LangGraph node'unun state argümanından okur.

    Args:
        args: Sarmalanan (wrapped) node'un pozisyonel argümanları. LangGraph
            her zaman state'i ilk sırada geçirir.

    Returns:
        Level değeri, ya da grafiğin state'i böyle bir alan taşımıyorsa None
        -- ``DocumentAnalysisState`` ve ``RoutingState`` taşımaz, ve bütçe
        çözümlemesi bunlar için balanced'a geri düşer.
    """
    state = args[0] if args else None
    if isinstance(state, dict):
        level = state.get("reasoning_level")
        return level if isinstance(level, str) else None
    return None


def node_timeout(
    node: str,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Bir async node'u, çağrı zamanında çözümlenen bir bütçeye saran decorator.

    Kasıtlı olarak bir sayı yerine bir node *adı* alır. Önceki imza bir float
    alıyordu ve bu, grafik inşa edilirken değerlendiriliyordu -- bir grafik
    işlem başına bir kez derlendiğinden, istek başına hiçbir değer ona asla
    ulaşamıyordu. ``reasoning_levels.timeout_multiplier``'ın, özellik
    eklendiğinden beri var olmasına rağmen bir node bütçesini hiç
    etkilememesinin nedeni budur.

    Args:
        node: ``BudgetPolicy.node_seconds`` içinde anahtar olarak kullanılan
            node adı.

    Returns:
        Decorator.
    """

    def _decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def _wrapped(*args: Any, **kwargs: Any) -> T:
            budget = node_budget(node, _reasoning_level_of(args))
            started = time.perf_counter()
            # "node_budget", bu node'un kendi subgraph adı değil -- bu
            # decorator'ın hangi grafiği sardığını bilmesinin bir yolu yok
            # (document_analysis_graph/routing_graph arasında paylaşılıyor)
            # ve tek başına `node` etiketi zaten belirsizliği gideriyor.
            # Kasıtlı olarak planning_graph.py'ın kendi
            # NODE_DURATION.observe() çağrısından (graph="planning") ayrı bir
            # etiket değeri; o çağrı tüm bir plan *adımını*
            # (classification/brief/draft/routing) ölçer -- bu ise bunlardan
            # birinin içindeki tekil node'u ölçer, tıpkı
            # evaluation/latency/budget_report.py'ın (E3)
            # BudgetPolicy.node_seconds'a karşı raporladığı aynı
            # granülaritede.
            try:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=budget)
            except (asyncio.TimeoutError, TimeoutError) as exc:
                NODE_DURATION.labels(
                    graph="node_budget", node=node, status="failed"
                ).observe(time.perf_counter() - started)
                # Retry policy'nin bunu es geçmesi için ayrı bir tip olarak
                # yeniden fırlatılıyor (re-raise). Bütçesini aşan bir node
                # onu tekrar aşacaktır; çağıranın kendi düşürme
                # (degradation) yolu burada yararlı olan tepkidir.
                raise NodeBudgetExceeded(
                    f"Node '{node}' exceeded its {budget:.0f}s budget."
                ) from exc
            except Exception:
                NODE_DURATION.labels(
                    graph="node_budget", node=node, status="failed"
                ).observe(time.perf_counter() - started)
                raise
            else:
                NODE_DURATION.labels(
                    graph="node_budget", node=node, status="completed"
                ).observe(time.perf_counter() - started)
                return result

        return _wrapped

    return _decorator


async def with_fast_tier_fallback(
    primary: Callable[[], Awaitable[T]],
    fallback: Callable[[], Awaitable[T]],
) -> T:
    """``primary``'yi çalıştırır; hata durumunda ``fallback``'ı bir kez çalıştırır.

    Kalite katmanından hızlı katmana yalnızca *hata yolunda* düşmek için
    kullanılır -- yaygın durum hiçbir zaman fallback'in maliyetini ödemez.
    Bu, doküman-analizi node'unun mevcut iki katmanlı düşürme
    (degradation) merdiveninin üçüncü basamağıdır (birleşik şema ->
    yalnızca sınıflandırma -> bu).

    Args:
        primary: Argümanlarına zaten bağlanmış, tercih edilen çağrı.
        fallback: Yalnızca ``primary`` hata fırlatırsa denenen, düşürülmüş
            (degraded) çağrı.

    Returns:
        Hangisi başarılı olduysa o çağrının sonucu.

    Raises:
        Exception: Her iki deneme de başarısız olduysa, fallback'in
            fırlattığı istisna.
    """
    try:
        return await primary()
    except Exception:
        logger.warning("Primary call failed; falling back to the fast tier.", exc_info=True)
        return await fallback()
