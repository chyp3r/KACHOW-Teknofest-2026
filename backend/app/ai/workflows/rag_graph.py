import logging
import re
from typing import Any, Dict, List, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)

RETRIEVAL_LIMIT = 4

#: Naif bir sorguya hakim olan ama alım (retrieval) için hiçbir sinyal
#: taşımayan kelimeler. Bunları çıkarmak, hibrit retriever'ın BM25 yarısının
#: mevzuatta gerçekten geçen terimler üzerinden skorlama yapmasını sağlar.
TURKISH_STOPWORDS = frozenset(
    {
        "acaba", "ama", "ancak", "bana", "bazı", "belki", "ben", "beni", "benim",
        "bir", "biri", "birkaç", "birşey", "biz", "bu", "buna", "bunu", "bunun",
        "çok", "çünkü", "da", "daha", "de", "değil", "diye", "eğer", "en", "gibi",
        "hem", "hep", "hepsi", "her", "hiç", "için", "ile", "ise", "kez", "ki",
        "kim", "mi", "mı", "mu", "mü", "nasıl", "ne", "neden", "nerde", "nerede",
        "nereye", "niçin", "niye", "o", "sanki", "şey", "siz", "şu", "tüm", "ve",
        "veya", "ya", "yani", "olarak", "olan", "bunlar", "hakkında", "kadar",
        "sonra", "önce", "üzere", "göre",
    }
)

#: Yalın bir soruya eklenmeye değer terimler; böylece sparse retriever'ın
#: eşleştirebileceği gerçek mevzuat kelime dağarcığı olur.
DOMAIN_EXPANSION = "mevzuat yönetmelik madde hüküm resmî yazışma"

#: Python'ın kendi `str.lower()` metodu "İ" (U+0130, noktalı büyük I) harfini
#: "i" + birleşen üst nokta (U+0307) şeklinde eşler -- yani aşağıdaki her
#: stopword'ün yazıldığı tek code point'lik "i" ile asla eşleşmeyen iki code
#: point'lik bir string üretir. Bu yüzden "İçin".lower() != "için" olur ve her
#: stopword'ün büyük harfli hali filtreden sessizce kaçardı. Küçültmeden önce
#: açıkça çevriliyor; bu kod tabanındaki diğer Türkçe'ye duyarlı küçük harfe
#: çevirme işlemleriyle (bkz. app.ai.compliance.checker.normalize_value) aynı
#: tek satırlık düzeltme -- ASCII "I" kasıtlı olarak dokunulmadan bırakıldı,
#: çünkü Python'ın varsayılan .lower() metodu bunu zaten doğru şekilde "i"ye
#: eşliyor.
_TURKISH_CASEFOLD = str.maketrans({"İ": "i"})


def _turkish_lower(token: str) -> str:
    """Bir token'ı, Türkçe stopword'lerin gerçekte yazıldığı şekilde küçük harfe çevirir."""
    return token.translate(_TURKISH_CASEFOLD).lower()


class RAGState(TypedDict, total=False):
    """Alım (retrieval) workflow'u için LangGraph state'i."""

    original_query: str
    search_query: str
    documents: List[Document]
    context: str
    attempts: int


def build_search_query(query: str) -> str:
    """Bir kullanıcı sorusunu, model çağırmadan bir alım (retrieval) sorgusuna dönüştürür.

    Analiz grafiği zaten şunu ortaya koymuştu (bkz. ``_build_mevzuat_query``):
    deterministik sorgu oluşturma, bu korpusa karşı bir model yeniden
    yazımından daha iyi sonuç verir; çünkü retriever'ın sparse yarısı literal
    mevzuat token'larıyla eşleşir. Bunun yerine geçtiği rewrite node'u, daha
    kötü bir sorguya ulaşmak için tam bir üretim (generation) harcıyordu.

    Args:
        query: Kullanıcının sorusu veya doküman özeti.

    Returns:
        Anahtar kelime yoğunluklu bir sorgu string'i.
    """
    cleaned = re.sub(r"[^\w\sçğıöşüÇĞİÖŞÜ]", " ", query or "").strip()
    if not cleaned:
        return ""

    terms = [
        token
        for token in cleaned.split()
        if len(token) > 2 and _turkish_lower(token) not in TURKISH_STOPWORDS
    ]
    if not terms:
        terms = cleaned.split()

    # Sorguyu sınırlı tut: yaklaşık bir düzine terimden sonra BM25 skorlaması
    # düzleşir ve dense yarı, birbiriyle ilgisiz konuları ortalamaya başlar.
    return " ".join(terms[:12] + [DOMAIN_EXPANSION])


def create_rag_graph(llm_client: BaseLLMClient, hybrid_retriever: HybridRetriever):
    """Alım (retrieval) workflow'unu oluşturur ve derler.

    Akış: START -> prepare_query -> retrieve -> END

    Args:
        llm_client: Arayüz uyumluluğu için korunuyor; alım (retrieval) artık
            bir modele ihtiyaç duymuyor.
        hybrid_retriever: Mevzuat korpusu üzerinde dense + sparse retriever.

    Returns:
        Derlenmiş LangGraph workflow'u.
    """

    async def prepare_query_node(state: RAGState) -> Dict[str, Any]:
        query = build_search_query(state.get("original_query", ""))
        logger.info("Prepared retrieval query: %s", query)
        return {"search_query": query, "attempts": state.get("attempts", 0) + 1}

    async def retrieve_node(state: RAGState) -> Dict[str, Any]:
        logger.info("Running Retrieve Node...")
        query = state.get("search_query") or state.get("original_query", "")
        try:
            docs = await hybrid_retriever.retrieve(query, limit=RETRIEVAL_LIMIT)
            context = "\n\n".join(
                f"[DOKÜMAN {index}] (Kaynak: {doc.metadata.get('mevzuat', 'bilinmiyor')})\n"
                f"{doc.page_content}"
                for index, doc in enumerate(docs, start=1)
            )
            return {"documents": docs, "context": context}
        except Exception:
            logger.exception("Retrieve Node failed")
            return {"documents": [], "context": ""}

    builder = StateGraph(RAGState)
    builder.add_node("prepare_query", prepare_query_node)
    builder.add_node("retrieve", retrieve_node)

    builder.add_edge(START, "prepare_query")
    builder.add_edge("prepare_query", "retrieve")
    builder.add_edge("retrieve", END)

    return builder.compile()
