import math
import re
from typing import List, Optional

from langchain_core.documents import Document

from app.ai.embeddings.chunking.base import BaseChunker
from app.ai.embeddings.models import BaseEmbeddingsClient


def cosine_distance(u: List[float], v: List[float]) -> float:
    """Calculate the cosine distance between two vectors."""
    dot_product = sum(a * b for a, b in zip(u, v))
    norm_u = math.sqrt(sum(a * a for a in u))
    norm_v = math.sqrt(sum(b * b for b in v))
    if norm_u == 0 or norm_v == 0:
        return 1.0
    similarity = dot_product / (norm_u * norm_v)
    # Clip similarity to avoid floating point issues out of [-1, 1] range
    similarity = max(-1.0, min(1.0, similarity))
    return 1.0 - similarity


class SemanticChunker(BaseChunker):
    """Splits text based on semantic similarity/distance between consecutive
    sentences rather than character lengths.

    NOT WIRED INTO PRODUCTION -- and must not be, as-is. The only chunker
    any production call site uses is ``RecursiveChunker``
    (``app.ai.embeddings.chunking.recursive``); ``ChunkingPolicy``
    (``app.ai.policy.schema``) deliberately carries no strategy field
    selecting this class. This is not an oversight to "finish wiring up" --
    three concrete problems make it unsafe to plug into
    ``DocumentService._index_for_qa`` today:

    1. No ``start_index`` metadata. ``_index_for_qa`` reads a chunk's
       ``start_index`` to look up its page via
       ``app.ai.documents.anchors.build_page_map``, and
       ``RecursiveChunker`` provides it via
       ``RecursiveCharacterTextSplitter(add_start_index=True)``. This class
       emits only ``chunk_index``/``sentence_count``. Bolting it on as-is
       does not merely drop the ``[s. N]`` page citation -- if a future
       change joins the grouped sentences with ``" ".join(...)`` and
       treats a naive re-search as the offset, it collapses
       ``app.ai.documents.anchors.PAGE_SEPARATOR`` (``"\\n\\n"``) into a
       single space, so any offset computed from that joined string drifts
       by exactly the amount ``build_page_map`` uses to find page
       boundaries -- the citation would be *wrong*, not merely absent,
       which is worse.
    2. ``_split_into_sentences``'s regex is not safe for Turkish official
       correspondence. The negative lookbehind ``(?<![A-Z][a-z]\\.)`` only
       recognises ASCII uppercase, so it does not protect Turkish
       abbreviation patterns using ``İ/Ş/Ğ/Ç/Ö/Ü``, and it has no exception
       list for the common Turkish abbreviations ("Sn.", "Dr.", "T.C.",
       "vb.", "md.") or numbered-item markers ("1.", "2.") this document
       type is full of -- each one is a false sentence boundary.
    3. No maximum chunk size and no overlap. A long, topically-homogeneous
       document (which official correspondence often is) can produce one
       very large chunk that ``DraftPolicy.source_chunk_char_budget``
       drops entirely rather than truncating, and there is no overlap to
       recover an answer that lands on a chunk boundary the way
       ``RecursiveChunker``'s configured overlap does.

    This class stays in the package, exported and unit-tested, as an
    eval-only exploration arm (see ``evaluation``'s retrieval suite) --
    whether it beats ``RecursiveChunker`` on this document type is a
    measured question, not a settled one, and the answer belongs in a
    report, not in a docstring. Do not wire it into ``DocumentService``
    without first fixing (1)-(3) above and having eval numbers to justify
    the switch.
    """

    def __init__(
        self,
        embeddings_client: BaseEmbeddingsClient,
        threshold_type: str = "percentile",
        threshold_value: float = 85.0,
        min_sentences: int = 1,
    ):
        """Initialize Semantic Chunker.

        Args:
            embeddings_client: An instance of BaseEmbeddingsClient to generate sentence vectors.
            threshold_type: Type of thresholding to use. Options: "percentile", "static".
            threshold_value: Percentile value (0-100) or static distance threshold (0.0-1.0).
            min_sentences: Minimum number of sentences to keep in a chunk.
        """
        self.embeddings_client = embeddings_client
        self.threshold_type = threshold_type.lower()
        self.threshold_value = threshold_value
        self.min_sentences = min_sentences

    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences using a regex pattern."""
        # Split on sentence boundaries: dot, question mark, exclamation mark followed by whitespace.
        sentence_ends = re.compile(r"(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!)\s")
        sentences = sentence_ends.split(text)
        return [s.strip() for s in sentences if s.strip()]

    async def split_text(self, text: str, **kwargs) -> List[Document]:
        """Splits the text semantically using sentence embeddings."""
        sentences = self._split_into_sentences(text)

        if not sentences:
            return []
        if len(sentences) <= self.min_sentences:
            return [Document(page_content=text, metadata={"chunk_index": 0})]

        # 1. Generate embeddings for all sentences
        embeddings = await self.embeddings_client.embed_documents(sentences)

        # 2. Calculate cosine distances between consecutive sentences
        distances = []
        for i in range(len(embeddings) - 1):
            dist = cosine_distance(embeddings[i], embeddings[i + 1])
            distances.append(dist)

        # 3. Determine distance threshold for splitting
        if self.threshold_type == "percentile":
            if not distances:
                threshold = 0.5
            else:
                sorted_dists = sorted(distances)
                # Find index matching the percentile
                pct_index = int((self.threshold_value / 100.0) * len(distances))
                pct_index = max(0, min(pct_index, len(distances) - 1))
                threshold = sorted_dists[pct_index]
        else:
            threshold = self.threshold_value

        # 4. Group sentences based on splits
        chunks = []
        current_chunk_sentences = [sentences[0]]

        for i in range(len(distances)):
            next_sentence = sentences[i + 1]
            dist = distances[i]

            # If distance exceeds threshold, start a new chunk
            if dist > threshold and len(current_chunk_sentences) >= self.min_sentences:
                chunks.append(" ".join(current_chunk_sentences))
                current_chunk_sentences = [next_sentence]
            else:
                current_chunk_sentences.append(next_sentence)

        if current_chunk_sentences:
            chunks.append(" ".join(current_chunk_sentences))

        # 5. Return documents list
        return [
            Document(
                page_content=chunk_text,
                metadata={
                    "chunk_index": idx,
                    "sentence_count": len(self._split_into_sentences(chunk_text)),
                },
            )
            for idx, chunk_text in enumerate(chunks)
        ]
