import logging
from typing import Dict, List

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    results_lists: List[List[Document]], k: int = 60
) -> List[Document]:
    """Getirilen birden çok belge listesini, rank pozisyonlarına dayanarak

    birleştiren Reciprocal Rank Fusion (RRF) algoritması.

    Args:
        results_lists: Birleştirilecek Document nesnesi listelerinin listesi.
        k: RRF formülü için sabit parametre (varsayılan: 60).
    """
    rrf_scores: Dict[str, float] = {}
    doc_map: Dict[str, Document] = {}

    # Getirilen her belge listesinde dolaş
    for results in results_lists:
        for rank, doc in enumerate(results, start=1):
            # Tekrarlar için sayfa içeriğini benzersiz tanımlayıcı olarak kullan
            key = doc.page_content
            doc_map[key] = doc

            if key not in rrf_scores:
                rrf_scores[key] = 0.0

            # Standart RRF formülünü uygula: 1 / (k + rank)
            rrf_scores[key] += 1.0 / (k + rank)

    # Benzersiz belgeleri RRF skoruna göre azalan sırada sırala
    sorted_keys = sorted(
        rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True
    )

    fused_documents = []
    for key in sorted_keys:
        original_doc = doc_map[key]
        # Orijinali değiştirmemek için kopyala
        fused_doc = Document(
            page_content=original_doc.page_content,
            metadata=original_doc.metadata.copy(),
        )
        # Birleşik skoru metadata'da sakla
        fused_doc.metadata["rrf_score"] = rrf_scores[key]
        fused_documents.append(fused_doc)

    logger.debug(
        f"RRF fused {len(results_lists)} retrieval lists into {len(fused_documents)} unified results."
    )
    return fused_documents
