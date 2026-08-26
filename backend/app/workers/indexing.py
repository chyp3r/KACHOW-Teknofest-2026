"""Kaynak korpusların vektör deposuna arka planda indekslenmesi.

Aşağıdaki her iki indeksleyici de Qdrant koleksiyonunu *türetilmiş durum*
olarak ele alır: commit edilmiş bir veri seti dizini tek doğruluk kaynağıdır.
`QdrantStore.upsert_documents` her nokta için rastgele bir UUID ürettiğinden,
bir indeksi yeniden çalıştırmak her noktayı çoğaltır ve rank fusion'ı
bozar; bu yüzden her worker, uzlaştırmaya çalışmak yerine koleksiyonunu
sıfırdan yeniden oluşturur.
"""

import logging
import os

from pydantic import BaseModel, Field

from app.ai.embeddings.chunking.base import BaseChunker
from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.embeddings.service import EmbeddedChunk
from app.ai.retrieval.corpus_loader import load_mevzuat_corpus, load_yazisma_examples
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)

DIMENSION_PROBE_TEXT = "boyut testi"

#: Yalnızca aşağıdaki gömülü tanımlayıcıyı oluşturmak için kullanılan
#: yazışma-türü etiketleri -- workflow'un Türkçe-etiket tablosunu import
#: etmek yerine yerel tutuldu, böylece bu modülün draft workflow paketine
#: bağımlılığı yok.
_TYPE_LABELS = {
    "cover_letter": "Üst yazı",
    "response_letter": "Cevap yazısı",
    "information_notice": "Bilgilendirme metni",
    "other_official": "Diğer resmî yazışma",
}

#: Tam mektup gövdesinin ne kadarının gömülü tanımlayıcıya besleneceği.
#: Nokta payload'ı her zaman tam metni saklar (aşağıya bakın); yalnızca
#: *arama anahtarı* kısaltılır, çünkü bir sorgu kısa bir konu cümlesidir ve
#: tam gövdeyi gömmek bu sinyali standart başlık/imza metninin altına
#: gömerdi.
DESCRIPTOR_BODY_CHARS = 600


class IndexingReport(BaseModel):
    """Bir indeksleme çalışmasının sonucu."""

    collection_name: str = Field(description="İndekslenen koleksiyonun adı.")
    chunk_count: int = Field(description="Yüklenen parça sayısı.")
    vector_size: int = Field(description="Tespit edilen gömme vektörü boyutu.")
    recreated: bool = Field(description="Koleksiyon sıfırdan oluşturuldu mu.")


async def index_mevzuat_corpus(
    *,
    corpus_dir: str,
    collection_name: str,
    embeddings_client: BaseEmbeddingsClient,
    vector_store: BaseVectorStore,
    chunker: BaseChunker,
    recreate: bool = True,
) -> IndexingReport:
    """Mevzuat korpusunu yükler, gömer ve upsert eder.

    Args:
        corpus_dir: Mevzuat markdown dosyalarını barındıran dizin.
        collection_name: Hedef vektör deposu koleksiyonu.
        embeddings_client: Parçaları gömmek ve vektör boyutunu ölçmek için kullanılan istemci.
        vector_store: Hedef vektör deposu.
        chunker: Parçalama stratejisi; BM25 yolunda kullanılanla eşleşmelidir.
        recreate: Upsert öncesi koleksiyonu silip yeniden oluşturur.

    Returns:
        Neyin indekslendiğini açıklayan bir rapor.

    Raises:
        RuntimeError: Korpus boşsa veya vektör deposu yazmayı reddederse.
    """
    documents = await load_mevzuat_corpus(corpus_dir, chunker)
    if not documents:
        raise RuntimeError(
            f"Mevzuat korpusu boş veya okunamadı: {corpus_dir}. İndeksleme yapılmadı."
        )

    # Boyutu yapılandırmak yerine ölçüyoruz, böylece gömme modelini
    # değiştirmek kod değişikliği gerektirmez ve bir ayarla sessizce
    # çelişemez.
    probe = await embeddings_client.embed_query(DIMENSION_PROBE_TEXT)
    vector_size = len(probe)
    logger.info("Detected embedding dimension: %d", vector_size)

    if recreate:
        await vector_store.delete_collection(collection_name)

    created = await vector_store.create_collection(
        collection_name=collection_name, vector_size=vector_size
    )
    if not created:
        raise RuntimeError(
            f"'{collection_name}' koleksiyonu oluşturulamadı; indeksleme durduruldu."
        )

    import os
    from app.ai.retrieval.sparse_encoder import SparseBM25Encoder

    # Hibrit arama için sparse encoder'ı eğit ve kaydet
    encoder = SparseBM25Encoder()
    encoder.fit(documents)
    vocab_path = os.path.join(corpus_dir, "sparse_vocab.json")
    encoder.save(vocab_path)

    texts = [document.page_content for document in documents]
    vectors = await embeddings_client.embed_documents(texts)

    chunks = []
    for document, vector in zip(documents, vectors):
        indices, values = encoder.encode_document(document.page_content)
        chunks.append(
            EmbeddedChunk(
                text=document.page_content,
                vector=vector,
                metadata=document.metadata,
                sparse_vector={"indices": indices, "values": values},
            )
        )

    # QdrantStore exception'ları yutar ve False döner. Bu kontrol olmasa
    # script boş bir koleksiyon üzerinde başarı bildirir -- örneğin bir
    # gömme-modeli değişikliği farklı boyutlu eski bir koleksiyon
    # bıraktığında.
    stored = await vector_store.upsert_documents(
        collection_name=collection_name, chunks=chunks
    )
    if not stored:
        raise RuntimeError(
            f"'{collection_name}' koleksiyonuna yazma başarısız oldu. "
            "Koleksiyonun vektör boyutu gömme modeliyle uyuşmuyor olabilir."
        )

    logger.info(
        "Indexed %d chunk(s) into '%s' (vector_size=%d).",
        len(chunks),
        collection_name,
        vector_size,
    )
    return IndexingReport(
        collection_name=collection_name,
        chunk_count=len(chunks),
        vector_size=vector_size,
        recreated=recreate,
    )


def _build_descriptor(record: dict) -> str:
    """Bir stil örneğinin üzerinde gömüldüğü ve sparse-encode edildiği kısa metni oluşturur.

    Bilinçli olarak mektubun tamamı değil: bir retrieval sorgusu kısa bir
    konu cümlesidir (konu + kullanıcı talimatları) ve tüm mektubu gömmek,
    onu aynı türdeki diğer örneklerden gerçekten ayıran tek cümlenin
    standart başlık/imza bloğu tarafından sulandırılmasına yol açardı.
    """
    type_label = _TYPE_LABELS.get(record["correspondence_type"], record["correspondence_type"])
    return (
        f"{record.get('baslik', '')}\n"
        f"{type_label} / {record.get('niyet', '')}\n"
        f"{record.get('text', '')[:DESCRIPTOR_BODY_CHARS]}"
    )


async def index_yazisma_examples(
    *,
    examples_path: str,
    collection_name: str,
    embeddings_client: BaseEmbeddingsClient,
    vector_store: BaseVectorStore,
    recreate: bool = True,
) -> IndexingReport:
    """Derlenmiş few-shot taslak örnek korpusunu gömer ve upsert eder.

    ``index_mevzuat_corpus``'un aksine parçalama adımı yoktur:
    ``scripts/curate_yazisma_examples.py``'nin ürettiği her JSONL kaydı
    zaten tam ve bütün bir resmi mektuptur, ve bir few-shot örneği tam bir
    belge yapısını öğretmek için bütün kalmalıdır. Yalnızca kısa bir
    tanımlayıcı (bkz. ``_build_descriptor``) gömülür ve sparse-encode
    edilir; nokta payload'ı, draft writer prompt'unun gerçekten geri
    ihtiyaç duyduğu tam mektup metnini taşır.

    Args:
        examples_path: ``ornekler.jsonl`` dosyasının yolu.
        collection_name: Hedef vektör deposu koleksiyonu.
        embeddings_client: Tanımlayıcıları gömmek ve vektör boyutunu ölçmek
            için kullanılan istemci.
        vector_store: Hedef vektör deposu.
        recreate: Upsert öncesi koleksiyonu silip yeniden oluşturur.

    Returns:
        Neyin indekslendiğini açıklayan bir rapor.

    Raises:
        RuntimeError: Korpus boşsa veya vektör deposu yazmayı reddederse.
    """
    from langchain_core.documents import Document

    records = load_yazisma_examples(examples_path)
    if not records:
        raise RuntimeError(
            f"Yazışma örnek korpusu boş veya okunamadı: {examples_path}. İndeksleme yapılmadı."
        )

    probe = await embeddings_client.embed_query(DIMENSION_PROBE_TEXT)
    vector_size = len(probe)
    logger.info("Detected embedding dimension: %d", vector_size)

    if recreate:
        await vector_store.delete_collection(collection_name)

    created = await vector_store.create_collection(
        collection_name=collection_name, vector_size=vector_size
    )
    if not created:
        raise RuntimeError(
            f"'{collection_name}' koleksiyonu oluşturulamadı; indeksleme durduruldu."
        )

    from app.ai.retrieval.sparse_encoder import SparseBM25Encoder

    descriptors = [_build_descriptor(record) for record in records]

    encoder = SparseBM25Encoder()
    encoder.fit([Document(page_content=descriptor) for descriptor in descriptors])
    vocab_path = os.path.join(os.path.dirname(examples_path), "sparse_vocab.json")
    encoder.save(vocab_path)

    vectors = await embeddings_client.embed_documents(descriptors)

    chunks = []
    for record, descriptor, vector in zip(records, descriptors, vectors):
        indices, values = encoder.encode_document(descriptor)
        chunks.append(
            EmbeddedChunk(
                text=record["text"],
                vector=vector,
                metadata={
                    "example_id": record["id"],
                    "correspondence_type": record["correspondence_type"],
                    "kategori": record.get("kategori", ""),
                    "niyet": record.get("niyet", ""),
                    "baslik": record.get("baslik", ""),
                    "kurum": record.get("kurum", ""),
                    "char_len": record.get("char_len", len(record["text"])),
                    "source_path": record.get("source_path", ""),
                },
                sparse_vector={"indices": indices, "values": values},
            )
        )

    # index_mevzuat_corpus ile aynı gerekçe: QdrantStore exception'ları
    # yutar ve False döner, bu yüzden bu kontrol bir boyut uyuşmazlığını
    # sessizce boş bir koleksiyon yerine gürültülü bir hataya dönüştürür.
    stored = await vector_store.upsert_documents(
        collection_name=collection_name, chunks=chunks
    )
    if not stored:
        raise RuntimeError(
            f"'{collection_name}' koleksiyonuna yazma başarısız oldu. "
            "Koleksiyonun vektör boyutu gömme modeliyle uyuşmuyor olabilir."
        )

    logger.info(
        "Indexed %d yazışma örneği into '%s' (vector_size=%d).",
        len(chunks),
        collection_name,
        vector_size,
    )
    return IndexingReport(
        collection_name=collection_name,
        chunk_count=len(chunks),
        vector_size=vector_size,
        recreated=recreate,
    )
