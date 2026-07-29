import logging
from typing import Dict, List

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    results_lists: List[List[Document]], k: int = 60
) -> List[Document]:
    """Reciprocal Rank Fusion (RRF) algorithm to merge multiple lists of retrieved documents

    based on their rank position.

    Args:
        results_lists: A list of lists of Document objects to merge.
        k: The constant parameter for the RRF formula (default: 60).
    """
    rrf_scores: Dict[str, float] = {}
    doc_map: Dict[str, Document] = {}

    # Iterate through each list of retrieved documents
    for results in results_lists:
        for rank, doc in enumerate(results, start=1):
            # Use page content as the unique identifier for duplicates
            key = doc.page_content
            doc_map[key] = doc

            if key not in rrf_scores:
                rrf_scores[key] = 0.0

            # Apply standard RRF formula: 1 / (k + rank)
            rrf_scores[key] += 1.0 / (k + rank)

    # Sort the unique documents by their RRF score descending
    sorted_keys = sorted(
        rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True
    )

    fused_documents = []
    for key in sorted_keys:
        original_doc = doc_map[key]
        # Copy to avoid mutating original
        fused_doc = Document(
            page_content=original_doc.page_content,
            metadata=original_doc.metadata.copy(),
        )
        # Store fused score in metadata
        fused_doc.metadata["rrf_score"] = rrf_scores[key]
        fused_documents.append(fused_doc)

    logger.debug(
        f"RRF fused {len(results_lists)} retrieval lists into {len(fused_documents)} unified results."
    )
    return fused_documents
