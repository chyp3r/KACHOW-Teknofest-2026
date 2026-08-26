import glob
import json
import logging
import os

from langchain_core.documents import Document

from app.ai.embeddings.chunking.base import BaseChunker

logger = logging.getLogger(__name__)

CORPUS_FILE_PATTERN = "*.md"


def _read_title(text: str, fallback: str) -> str:
    """İlk H1 satırından okunabilir mevzuat adını çıkar.

    Args:
        text: Dosyanın tam içeriği.
        fallback: H1 başlığı yoksa kullanılacak değer.

    Returns:
        Atıflarda kullanılan mevzuat başlığı.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


async def load_mevzuat_corpus(
    corpus_dir: str, chunker: BaseChunker
) -> list[Document]:
    """Mevzuat korpusunu diskten oku ve parçalara ayır (chunk).

    İndeksleme worker'ı ile BM25 bağımlılığı arasında bilerek paylaştırılmıştır.
    İkisi de birebir aynı chunk'ları üretmelidir: `reciprocal_rank_fusion` tam
    `page_content` üzerinden tekrarları eler, dolayısıyla iki yol farklı
    chunk'lasaydı her iki retriever'ın da bulduğu her pasaj iki kez görünür ve
    kullanılabilir bağlamı sessizce yarıya indirirdi.

    Dosyalar sıralı okunur, böylece chunk sırası — ve dolayısıyla BM25 skorlaması —
    çalıştırmalar arasında tekrarlanabilir olur.

    Args:
        corpus_dir: Mevzuat markdown dosyalarını barındıran dizin.
        chunker: Chunking stratejisi; çağıranlar aynı parametreleri geçirmelidir.

    Returns:
        `source` ve `mevzuat` metadata'sıyla etiketlenmiş chunk'lanmış belgeler.
        Dizin yoksa veya okunabilir dosya içermiyorsa boş liste döner.
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
    """Derlenmiş few-shot taslak örnekleri JSONL dosyasını oku.

    ``load_mevzuat_corpus``'un aksine burada chunking yapılmaz: her kayıt
    zaten ``scripts/curate_yazisma_examples.py`` tarafından üretilmiş, tam
    bir resmî yazının tamamıdır. Bir kayıt, bir Qdrant point'i olur.

    Args:
        examples_path: ``ornekler.jsonl`` dosyasının yolu.

    Returns:
        Dosya sırasına göre ayrıştırılmış kayıtlar. Dosya yoksa veya
        okunamıyorsa boş liste döner.
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
