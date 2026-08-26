"""Taslak yazarı için few-shot üslup örneği getirimi.

``HybridRetriever``'ı, genel bir pasaj retriever'ının bilmesine gerek
olmayan iki kuralla sarmalar: yanlış ``correspondence_type``'a ait bir
örnek, hiç örnek olmamasından daha kötüdür (yanlış mektup biçimini öğretir)
ve aynı kurumdan iki örnek, yazarı tüm örnekler arasında paylaşılan yapıyı
değil o kurumun antetli kağıdını taklit etmeye yönlendirir.
"""

import logging
from dataclasses import dataclass

from app.ai.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)

#: Kurum çeşitliliği filtresi daraltmadan önce, istenen her örnek başına
#: getirilen aday sayısı. Sıralamanın en üstünde aynı kurumdan birkaç
#: sonucun nihai seçimi aç bırakmaması için yeterince geniş tutulur.
_CANDIDATE_MULTIPLIER = 3


@dataclass(frozen=True)
class StyleExample:
    """Yazar/revizör prompt'u için getirilmiş bir resmî yazı örneği."""

    text: str
    correspondence_type: str
    niyet: str
    kurum: str
    baslik: str


class ExampleRetriever:
    """Taslak yazarı için üslup referans örnekleri getirir."""

    def __init__(self, retriever: HybridRetriever):
        self._retriever = retriever

    async def retrieve(
        self,
        *,
        query: str,
        correspondence_type: str,
        limit: int = 2,
        char_budget: int = 4000,
    ) -> list[StyleExample]:
        """Verilen bir mektup türü için en fazla ``limit`` kadar üslup örneği getir.

        Asla hata fırlatmaz: getirim, taslak yazarı için opsiyonel bir
        kalite artışıdır, bir bağımlılık değildir; bu yüzden herhangi bir
        hata (Qdrant çökmesi, embedding çağrısının başarısız olması, boş
        korpus) hatayı yaymak yerine boş listeye düşer.

        Args:
            query: Kısa konu sorgusu -- genelde tam brief değil, konu +
                kullanıcı talimatları.
            correspondence_type: Kesin filtre; yalnızca bu türe ait
                örnekler değerlendirilir.
            limit: Döndürülecek maksimum örnek sayısı.
            char_budget: Döndürülen örneklerin metninin toplam karakter
                uzunluğu için üst sınır. Toplam metin bu sınırı aşarsa
                önce en uzun örnek çıkarılır.

        Returns:
            Kuruma göre sıralanmış ve çeşitlendirilmiş, ``char_budget``
            içinde kalan, en fazla ``limit`` kadar örnek. Eşleşme yoksa
            veya hata oluşursa boş liste.
        """
        if not query.strip() or not correspondence_type:
            return []

        try:
            documents = await self._retriever.retrieve(
                query,
                limit=limit * _CANDIDATE_MULTIPLIER,
                filter_dict={"correspondence_type": correspondence_type},
            )
        except Exception:
            logger.exception(
                "Style example retrieval failed for correspondence_type=%s.",
                correspondence_type,
            )
            return []

        examples: list[StyleExample] = []
        seen_kurum: set[str] = set()
        for document in documents:
            metadata = document.metadata
            kurum = metadata.get("kurum") or ""
            if kurum and kurum in seen_kurum:
                continue
            examples.append(
                StyleExample(
                    text=document.page_content,
                    correspondence_type=metadata.get(
                        "correspondence_type", correspondence_type
                    ),
                    niyet=metadata.get("niyet", ""),
                    kurum=kurum,
                    baslik=metadata.get("baslik", ""),
                )
            )
            if kurum:
                seen_kurum.add(kurum)
            if len(examples) >= limit:
                break

        return _apply_char_budget(examples, char_budget)


def _apply_char_budget(
    examples: list[StyleExample], char_budget: int
) -> list[StyleExample]:
    """Toplam metin bütçeye sığana kadar önce en uzun örneği çıkar.

    Her zaman en az bir örneği korur (tek başına bütçeyi aşsa bile) --
    aşırı büyük tek bir örnek yine de sıfırdan iyidir ve DraftPolicy'nin
    bütçesi yazarın genel bağlam penceresinde zaten pay bırakır.
    """
    kept = list(examples)
    while len(kept) > 1 and sum(len(example.text) for example in kept) > char_budget:
        longest = max(kept, key=lambda example: len(example.text))
        kept.remove(longest)
    return kept
