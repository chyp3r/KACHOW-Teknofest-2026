import logging
import uuid
from typing import Any, Dict, List, Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.ai.embeddings.service import EmbeddedChunk
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)

#: Hibrit retriever'ın kullandığı seyrek vektörün adı. Bu tanıtılmadan önce
#: oluşturulan koleksiyonlarda bu yoktur, ve Qdrant koleksiyonun sahip
#: olmadığı bir vektörü adlandıran herhangi bir sorguyu reddeder.
SPARSE_VECTOR_NAME = "text-sparse"

#: upsert() çağrısı başına nokta sayısı. Yerel, aynı host'taki Docker
#: Qdrant'a karşı tek, gruplanmamış bir çağrı sorun değildi (boyuttan
#: bağımsız olarak bir saniyeden az), ama uzak bir kümeye (Evren) karşı
#: gerçekten zaman aşımına uğradığı canlı doğrulandı: bir çağrıda
#: 429 yoğun(1024)+seyrek noktayı indekslemek 120 saniyeden fazla sürdü ve
#: yine de bitmedi. Gruplama, her isteğin boyutunu korpus boyutundan
#: bağımsız olarak sınırlar, bu da başarısız bir grubun aksi halde başarılı
#: büyük bir upsert'i geçersiz kılmadığı anlamına gelir.
_UPSERT_BATCH_SIZE = 64

#: Bir ``filter_dict`` değerinin düz bir skaler (tam eşleşme) yerine
#: kullanabileceği aralık koşulu operatör anahtarları -- örn.
#: ``{"sensitivity_rank": {"lte": 3}}`` bir aramayı, payload alanı 3'te
#: veya altında olan parçalarla sınırlar. Qdrant'ın kendi ``models.Range``
#: alanlarından adlandırılmış, doğrudan geçirilir.
_RANGE_OPERATORS = frozenset({"lt", "lte", "gt", "gte"})


def _build_qdrant_filter(filter_dict: Optional[Dict[str, Any]]) -> Optional[models.Filter]:
    """Bu modülün ``filter_dict`` sözleşmesini bir Qdrant filtresine çevir.

    Bir değer ya bir skalerdir (tam eşleşme, orijinal ve hâlâ en yaygın
    durum -- ``{"storage_path": "uploads/x.pdf"}``) ya da sıralı bir sayısal
    payload alanına göre bir aramayı sınırlamak için kullanılan bir aralık
    operatörleri sözlüğüdür (``{"sensitivity_rank": {"lte": 3}}``) -- örn.
    RBAC yetki filtrelemesi, burada isteği yapanın rütbesinin üzerindeki bir
    parça, model onu zaten gördükten sonra alt akışta filtrelenmek yerine
    vektör aramasından hiç döndürülmemelidir.

    Args:
        filter_dict: Bu modülün filtre sözleşmesi, veya filtre yoksa None/boş.

    Returns:
        Eşdeğer Qdrant filtresi, veya ``filter_dict`` boşsa None.
    """
    if not filter_dict:
        return None

    must_conditions = []
    for key, val in filter_dict.items():
        if isinstance(val, dict):
            range_kwargs = {op: bound for op, bound in val.items() if op in _RANGE_OPERATORS}
            must_conditions.append(
                models.FieldCondition(key=key, range=models.Range(**range_kwargs))
            )
        else:
            must_conditions.append(
                models.FieldCondition(key=key, match=models.MatchValue(value=val))
            )
    return models.Filter(must=must_conditions)


class QdrantStore(BaseVectorStore):
    """Vektör depolama ve arama için BaseVectorStore'un Qdrant istemci implementasyonu."""

    def __init__(self, qdrant_url: str, api_key: Optional[str] = None):
        """Qdrant Store istemcisini başlat.

        Args:
            qdrant_url: Qdrant DB'nin uç nokta URL'i (örn. "http://localhost:6333",
                veya LOCAL_MODE=False iken Evren'in özel kümesi).
            api_key: Evren'in kümesi için gerekli takım API anahtarı;
                yerel Docker-Compose Qdrant'a karşı kullanılmaz (ve gereksizdir).
        """
        self.qdrant_url = qdrant_url
        # port=None (qdrant-client'ın kendi varsayılanı her zaman 6333)
        # böylece açık bir port taşımayan bir URL, URL'nin ne söylediğinden
        # bağımsız olarak 6333'e zorlanmak yerine şemanın kendi varsayılanına
        # (https için 443) düşer. Her zaman ":6333"ü açıkça belirten yerel
        # Docker Qdrant URL'i için zararsızdır -- o yine kazanır, çünkü
        # qdrant-client bu `port` kwarg'ına yalnızca URL'nin kendisi hiçbirini
        # taşımadığında düşer. 6333'ü doğrudan açığa çıkarmak yerine
        # takıma özel bir yol öneki (örn.
        # "https://evren-vektor.ssyz.org.tr/team07") ile 443'te düz bir HTTPS
        # ters proxy'nin arkasında oturan Evren'in kümesi için gereklidir --
        # canlı doğrulandı: qdrant-client varsayılanıyla (port=6333) her
        # istek zaman aşımına uğradı; port=None ile aynı URL 443'e çözülür
        # ve başarılı olur.
        # qdrant-client, hiçbiri verilmediğinde 5 saniyelik bir zaman aşımına
        # (DEFAULT_GRPC_TIMEOUT, REST için de yeniden kullanılır) varsayılan
        # olarak geçer -- aynı host'taki yerel Docker Qdrant'a karşı sorun
        # değil, ama birkaç yüz embed edilmiş parçanın tek, gruplanmamış
        # upsert_documents() çağrısı, internet üzerinden Evren'in kümesine
        # karşı gerçekten bundan daha uzun süreye ihtiyaç duyar. Canlı
        # doğrulandı: 429 örnekli yazışma korpusunu Evren'e karşı
        # indekslemek 5s varsayılanında WriteTimeout ile zaman aşımına uğradı.
        self.client = AsyncQdrantClient(
            url=qdrant_url, api_key=api_key, port=None, timeout=120
        )
        # collection_name -> "seyrek vektörü var mı" önbelleği. Süreç
        # başına bir kez sondalanır, böylece eski bir koleksiyon bir ekstra
        # çağrıya mal olur, alma başına başarısız bir sorguya (ve bir yığın
        # izine) değil.
        self._sparse_support: Dict[str, bool] = {}
        logger.info(f"Initialized AsyncQdrantClient targeting: {qdrant_url}")

    async def _has_sparse_vector(self, collection_name: str) -> bool:
        """Bir koleksiyonun seyrek vektörler için yapılandırılıp yapılandırılmadığını bildir.

        Args:
            collection_name: İncelenecek koleksiyon.

        Returns:
            Koleksiyon hibrit retriever'ın ihtiyaç duyduğu seyrek vektörü
            tanımlıyorsa True. Bilinmeyen veya ulaşılamayan koleksiyonlar
            False bildirir, böylece alma hata vermek yerine yalnızca
            yoğun-vektöre düşer.
        """
        cached = self._sparse_support.get(collection_name)
        if cached is not None:
            return cached

        try:
            info = await self.client.get_collection(collection_name)
            sparse_config = getattr(info.config.params, "sparse_vectors", None) or {}
            has_sparse = SPARSE_VECTOR_NAME in sparse_config
        except Exception:
            logger.warning(
                "Could not inspect collection '%s'; assuming no sparse vectors.",
                collection_name,
            )
            has_sparse = False

        if not has_sparse:
            logger.warning(
                "Collection '%s' has no '%s' vector, so hybrid search will run "
                "dense-only. The collection predates hybrid indexing; re-run "
                "scripts/index_mevzuat.py to rebuild it with sparse vectors.",
                collection_name,
                SPARSE_VECTOR_NAME,
            )

        self._sparse_support[collection_name] = has_sparse
        return has_sparse

    async def create_collection(
        self, collection_name: str, vector_size: int, distance: str = "Cosine"
    ) -> bool:
        """Koleksiyonu oluştur, veya var olan birinin şemasını doğrula.

        Var olan bir koleksiyon körü körüne kabul edilmez, *kontrol edilir*.
        Önceki sürüm var olan herhangi bir koleksiyonda başarı döndürüyordu,
        bu yüzden seyrek vektörler var olmadan önce oluşturulan bir tanesi,
        her alma Qdrant'tan bir 400 loglarken hibrit aramayla kalıcı olarak
        uyumsuz kalıyordu.

        Args:
            collection_name: Hedef koleksiyon.
            vector_size: Yoğun vektör boyutsallığı.
            distance: Mesafe metriği adı.

        Returns:
            Koleksiyon varsa ve yoğun arama için kullanılabilirse True.
        """
        dist_enum = models.Distance.COSINE
        dist_lower = distance.lower()
        if dist_lower == "euclidean":
            dist_enum = models.Distance.EUCLID
        elif dist_lower == "dot":
            dist_enum = models.Distance.DOT

        try:
            if await self.client.collection_exists(collection_name):
                return await self._validate_existing(collection_name, vector_size)

            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size, distance=dist_enum
                ),
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: models.SparseVectorParams(
                        index=models.SparseIndexParams(on_disk=True)
                    )
                },
            )
            self._sparse_support[collection_name] = True
            logger.info(
                "Created Qdrant collection '%s' (dense=%d, sparse=%s).",
                collection_name,
                vector_size,
                SPARSE_VECTOR_NAME,
            )
            return True
        except Exception as e:
            logger.error(
                f"Qdrant create_collection failed for '{collection_name}': {e}",
                exc_info=True,
            )
            return False

    async def _validate_existing(
        self, collection_name: str, vector_size: int
    ) -> bool:
        """Var olan bir koleksiyonun kodun beklediğiyle eşleştiğini kontrol et.

        Args:
            collection_name: Kontrol edilecek koleksiyon.
            vector_size: Çağıranın yazmayı amaçladığı yoğun boyutsallık.

        Returns:
            Koleksiyon bu boyutta yoğun yazmaları kabul edebiliyorsa True.
        """
        try:
            info = await self.client.get_collection(collection_name)
            params = info.config.params

            existing_vectors = params.vectors
            existing_size = getattr(existing_vectors, "size", None)
            if existing_size is None and isinstance(existing_vectors, dict):
                default = existing_vectors.get("")
                existing_size = getattr(default, "size", None)

            if existing_size is not None and existing_size != vector_size:
                # 768 boyutlu vektörleri 3584 boyutlu bir koleksiyona yazmak
                # her noktada başarısız olur ve bunun dışında yalnızca
                # sessiz bir hiçbir-şey-yapmama olarak görünür.
                logger.error(
                    "Collection '%s' has dimension %d but the embedding model "
                    "produces %d. Delete the collection and re-index.",
                    collection_name,
                    existing_size,
                    vector_size,
                )
                return False

            sparse_config = getattr(params, "sparse_vectors", None) or {}
            has_sparse = SPARSE_VECTOR_NAME in sparse_config
            self._sparse_support[collection_name] = has_sparse
            if not has_sparse:
                logger.warning(
                    "Collection '%s' exists without a '%s' vector; hybrid search "
                    "will fall back to dense-only. Re-index to enable it.",
                    collection_name,
                    SPARSE_VECTOR_NAME,
                )
            else:
                logger.info("Collection '%s' already exists and is valid.", collection_name)
            return True
        except Exception as e:
            logger.error(
                f"Could not validate existing collection '{collection_name}': {e}",
                exc_info=True,
            )
            return False

    async def upsert_documents(
        self, collection_name: str, chunks: List[EmbeddedChunk]
    ) -> bool:
        """Embed edilmiş parçaları Qdrant koleksiyonuna upsert et."""
        if not chunks:
            return True

        points = []
        for chunk in chunks:
            point_id = str(uuid.uuid4())
            # Ham metni herhangi bir metadata anahtarıyla birlikte payload içine kaydet
            payload = {"text": chunk.text, **chunk.metadata}

            # Seyrek vektör varlığına göre vektörü biçimlendir
            if chunk.sparse_vector:
                vector_data = {
                    "": chunk.vector,
                    "text-sparse": models.SparseVector(
                        indices=chunk.sparse_vector["indices"],
                        values=chunk.sparse_vector["values"],
                    ),
                }
            else:
                vector_data = chunk.vector

            points.append(
                models.PointStruct(
                    id=point_id, vector=vector_data, payload=payload
                )
            )

        try:
            for start in range(0, len(points), _UPSERT_BATCH_SIZE):
                batch = points[start : start + _UPSERT_BATCH_SIZE]
                await self.client.upsert(collection_name=collection_name, points=batch)
            logger.debug(
                f"Upserted {len(chunks)} chunks to collection '{collection_name}'."
            )
            return True
        except Exception as e:
            logger.error(
                f"Qdrant upsert failed for collection '{collection_name}': {e}",
                exc_info=True,
            )
            return False

    async def similarity_search(
        self, collection_name: str, query_vector: List[float], limit: int = 5, filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Qdrant koleksiyonunda benzer vektörleri ara ve normalize edilmiş payload nesneleri döndür."""
        try:
            # `search()`, qdrant-client 1.x'te `query_points()` lehine
            # kaldırıldı. Bu metod exception'ları yuttuğu ve boş bir liste
            # döndürdüğü için, kaldırılan API'yi çağırmak her yoğun
            # aramanın sessizce sonuç döndürmemesine neden oluyordu, hibrit
            # almayı yalnızca-seyreğe düşürüyordu.
            qdrant_filter = _build_qdrant_filter(filter_dict)

            response = await self.client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
                query_filter=qdrant_filter,
            )

            hits = []
            for hit in response.points:
                payload = hit.payload or {}
                # Pop out the raw text key
                text = payload.pop("text", "")
                hits.append(
                    {"text": text, "score": hit.score, "metadata": payload}
                )
            return hits
        except Exception as e:
            logger.error(
                f"Qdrant similarity_search failed in '{collection_name}': {e}",
                exc_info=True,
            )
            return []

    async def hybrid_search(
        self,
        collection_name: str,
        query_vector: List[float],
        sparse_indices: List[int],
        sparse_values: List[float],
        limit: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Qdrant Prefetch API ve RRF füzyonu kullanarak yerel hibrit arama yap."""
        try:
            qdrant_filter = _build_qdrant_filter(filter_dict)

            # Yoğun ve seyrek için prefetch sorgularını tanımla
            dense_prefetch = models.Prefetch(
                query=query_vector,
                using="",  # Varsayılan yoğun vektör
                limit=limit * 3,  # Birleştirmek için daha fazla aday getir
                filter=qdrant_filter,
            )

            prefetch_list = [dense_prefetch]
            # Yalnızca sorgunun jetonları *ve* koleksiyonun gerçekten
            # vektörü tanımladığı durumda seyreği önden getir. Koleksiyonun
            # sahip olmadığı bir vektörü adlandırmak, Qdrant'ın tüm isteği
            # bir 400 ile reddetmesine neden olur.
            if (
                sparse_indices
                and sparse_values
                and await self._has_sparse_vector(collection_name)
            ):
                prefetch_list.append(
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse_indices,
                            values=sparse_values,
                        ),
                        using=SPARSE_VECTOR_NAME,
                        limit=limit * 3,
                        filter=qdrant_filter,
                    )
                )

            # Tek bir prefetch dalının birleştirecek bir şeyi yok; bozuk bir
            # RRF gidiş-dönüşü ödemek yerine doğrudan yoğun aramaya git.
            if len(prefetch_list) == 1:
                return await self.similarity_search(
                    collection_name=collection_name,
                    query_vector=query_vector,
                    limit=limit,
                    filter_dict=filter_dict,
                )

            # Qdrant'ı Füzyon ile sorgula (Reciprocal Rank Fusion)
            response = await self.client.query_points(
                collection_name=collection_name,
                prefetch=prefetch_list,
                query=models.FusionQuery(
                    fusion=models.Fusion.RRF
                ),
                limit=limit,
            )

            hits = []
            for hit in response.points:
                payload = hit.payload or {}
                text = payload.pop("text", "")
                hits.append(
                    {"text": text, "score": hit.score, "metadata": payload}
                )
            return hits
        except Exception as e:
            # Yığın izi olmadan loglandı: aşağıdaki yoğun yedek hâlâ sorguyu
            # yanıtlar, bu yüzden bu bir çökme değil, bir bozulma bildirimidir.
            # Alma başına tam bir yığın izi yaymak gerçek hataları logda gömüyordu.
            logger.warning(
                "Qdrant hybrid_search failed in '%s' (%s); falling back to dense search.",
                collection_name,
                e,
            )
            self._sparse_support[collection_name] = False
            # Benzerlik aramasına düş
            return await self.similarity_search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                filter_dict=filter_dict,
            )

    async def delete_collection(self, collection_name: str) -> bool:
        """Qdrant veritabanından bir koleksiyonu sil."""
        try:
            exists = await self.client.collection_exists(collection_name)
            if not exists:
                logger.info(
                    f"Collection '{collection_name}' does not exist, no need to delete."
                )
                return True
            await self.client.delete_collection(collection_name)
            logger.info(f"Deleted Qdrant collection: '{collection_name}'")
            return True
        except Exception as e:
            logger.error(
                f"Qdrant delete_collection failed for '{collection_name}': {e}",
                exc_info=True,
            )
            return False

    async def delete_by_filter(
        self, collection_name: str, filter_dict: Dict[str, Any]
    ) -> bool:
        """Koleksiyonun geri kalanını düşürmeden bir filtreyle eşleşen her
        noktayı (örn. tek bir belgenin parçalarını) sil."""
        if not filter_dict:
            logger.error(
                f"delete_by_filter refused an empty filter for '{collection_name}' "
                "-- would have deleted every point in the collection."
            )
            return False
        try:
            exists = await self.client.collection_exists(collection_name)
            if not exists:
                return True
            await self.client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=_build_qdrant_filter(filter_dict)
                ),
            )
            return True
        except Exception as e:
            logger.error(
                f"Qdrant delete_by_filter failed for '{collection_name}': {e}",
                exc_info=True,
            )
            return False

