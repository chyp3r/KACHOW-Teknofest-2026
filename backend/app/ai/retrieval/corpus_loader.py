import glob
import json
import logging
import os

from langchain_core.documents import Document

from app.ai.embeddings.chunking.base import BaseChunker

logger = logging.getLogger(__name__)

CORPUS_FILE_PATTERN = "*.md"


def _read_title(text: str, fallback: str) -> str:
    """Extract the human-readable regulation name from the first H1 line.

    Args:
        text: Full file contents.
        fallback: Value to use when no H1 heading is present.

    Returns:
        The regulation title used in citations.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


async def load_mevzuat_corpus(
    corpus_dir: str, chunker: BaseChunker
) -> list[Document]:
    """Read and chunk the legislation corpus from disk.

    Shared deliberately by the indexing worker and the BM25 dependency. Both must
    produce byte-identical chunks: `reciprocal_rank_fusion` de-duplicates on exact
    `page_content`, so if the two paths chunked differently every passage found by
    both retrievers would appear twice and quietly halve the usable context.

    Files are read in sorted order so chunk order — and therefore BM25 scoring — is
    reproducible across runs.

    Args:
        corpus_dir: Directory holding the legislation markdown files.
        chunker: Chunking strategy; callers must pass identical parameters.

    Returns:
        Chunked documents tagged with `source` and `mevzuat` metadata. Empty when
        the directory is absent or holds no readable files.
    """
    if not os.path.isdir(corpus_dir):
        logger.warning(
            "Mevzuat corpus directory not found at %s; legislation retrieval will "
            "return no results.",
            corpus_dir,
        )
        return []

    paths = sorted(glob.glob(os.path.join(corpus_dir, CORPUS_FILE_PATTERN)))
    if not paths:
        logger.warning("No %s files found in %s.", CORPUS_FILE_PATTERN, corpus_dir)
        return []

    documents: list[Document] = []
    for path in paths:
        file_name = os.path.basename(path)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            logger.exception("Failed to read mevzuat file %s", path)
            continue

        if not text.strip():
            logger.warning("Skipping empty mevzuat file %s.", file_name)
            continue

        title = _read_title(text, fallback=file_name)
        chunks = await chunker.split_text(text)
        for chunk in chunks:
            chunk.metadata = {
                **chunk.metadata,
                "source": file_name,
                "mevzuat": title,
            }
        documents.extend(chunks)
        logger.info("Loaded %d chunk(s) from %s.", len(chunks), file_name)

    logger.info(
        "Mevzuat corpus loaded: %d chunk(s) from %d file(s).",
        len(documents),
        len(paths),
    )
    return documents


def load_yazisma_examples(examples_path: str) -> list[dict]:
    """Read the curated few-shot draft examples JSONL.

    Unlike ``load_mevzuat_corpus`` this performs no chunking: each record is
    already a single full official letter, produced by
    ``scripts/curate_yazisma_examples.py``. One record becomes one Qdrant
    point.

    Args:
        examples_path: Path to the ``ornekler.jsonl`` file.

    Returns:
        The parsed records, in file order. Empty when the file is absent or
        unreadable.
    """
    if not os.path.isfile(examples_path):
        logger.warning(
            "Yazışma örnekleri dosyası bulunamadı: %s; örnek getirimi sonuçsuz kalacak.",
            examples_path,
        )
        return []

    records: list[dict] = []
    with open(examples_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    logger.info("Loaded %d yazışma example(s) from %s.", len(records), examples_path)
    return records
