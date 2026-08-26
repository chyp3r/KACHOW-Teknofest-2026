"""Bir mesajı önceden hesaplanmış sınıf prototipleriyle kosinüs benzerliğine göre eşleştirir.

Karar merdiveninin 2. katmanı: sözcüksel kurallar (~0 ms, parafraza kör) ile
hızlı katman modeli (~1-3 s, tek bir yapılandırılmış etiket için) arasında yer alır.
Yalnızca sözcüksel katmanın çekimser kaldığı mesajlar buraya ulaşır.

Bu neden ayrı bir katmana değer
--------------------------------
Kısa bir mesaj üzerinde tek bir ``embed_query`` çağrısı, halihazırda bellekte ve
ısınmış durumdaki bir modele karşı ölçüldüğünde p50'de ~21 ms, p95'te ~29 ms
tutuyor -- ``HybridRetriever`` da her mevzuat aramasında aynı servisi çağırıyor.
Buna karşılık tek bir hızlı katman etiketi, JSON şeması, Pydantic doğrulaması ve
olası bir yeniden deneme dahil edildiğinde 1-3 saniye sürüyor. Yani burada
çözülen bir parafraz, bir üst basamağa kıyasla maliyetin sadece birkaç yüzdesine
mal oluyor.

Neden tek başına karar vermiyor
--------------------------------
Bir prototip isabeti için **hem** yüksek bir mutlak benzerlik **hem de** bir
sonrakiyle net bir fark gerekir. Kısa Türkçe cümleler arasındaki kosinüs
benzerliği sıkışık bir dağılım gösterir -- birbiriyle alakasız resmi üslup
cümleleri bile genellikle 0.6 civarında kalır -- bu yüzden tek başına mutlak bir
eşik sürekli tetiklenir, tek başına bir fark ölçütü de birbirinden farklı ama
ikisi de kötü olan iki eşleşmede tetiklenir. Bu kontrollerden herhangi birinin
başarısız olması modele düşmek anlamına gelir; bu da gerçekten belirsiz bir
mesaj için doğru sonuçtur.

Bayatlama (staleness)
----------------------
Vektör dosyası, kendisini üreten embedding modelini, boyutunu ve policy
sürümünü kaydeder. Herhangi bir uyuşmazlıkta eşleştirici kendini devre dışı
bırakır ve her mesaj eskisi gibi üst katmana yükseltilir. Farklı bir modelle
üretilmiş vektörlerden karar vermek, bir model çağrısına para ödemekten daha
kötüdür: bu, yavaş olmak yerine kendinden emin bir şekilde yanlış olmaktır.
"""

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.policy import POLICY_VERSION, get_policy
from app.core.config import settings

logger = logging.getLogger(__name__)

__all__ = ["SemanticMatch", "PrototypeMatcher", "PROTOTYPE_DIR"]

#: ``scripts/build_prototypes.py``'nin çıktısını yazdığı yer.
#:
#: Çalışma dizinine göre, ``MEVZUAT_CORPUS_DIR`` ile aynı şekilde göreli.
#: Bunu ``__file__``'dan türetmek daha derli toplu görünüyordu ama yanlıştı:
#: konteyner içinde paket kökü çalışma dizininin *kendisi* olduğundan, onun
#: üzerinden yukarı çıkmak `/`'e iniyordu ve vektörler her mount'un dışında
#: yazılıyor, konteyner kapandığında sessizce kayboluyordu.
PROTOTYPE_DIR = Path(settings.PROTOTYPE_DIR)


@dataclass(frozen=True)
class SemanticMatch:
    """Bir ailenin bir mesaj için en iyi etiketi.

    Attributes:
        label: Kazanan sınıf.
        similarity: O sınıfın en iyi prototipine olan kosinüs benzerliği.
        runner_up_gap: İkinci en iyi sınıfa göre ne kadar önde olduğu.
        decisive: Her iki eşiğin de geçilip geçilmediği. Kararsız (decisive
            olmayan) bir eşleşme yine de döndürülür -- log satırı için faydalı
            bir kanıttır -- ama işleme alınmamalıdır.
    """

    label: str
    similarity: float
    runner_up_gap: float
    decisive: bool


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """İki vektörün kosinüs benzerliği; ikisinden biri sıfır büyüklükteyse 0.0."""
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class PrototypeMatcher:
    """Önceden hesaplanmış prototip vektörlerini yükler ve mesajları bunlara karşı puanlar."""

    def __init__(
        self,
        embeddings_client: BaseEmbeddingsClient,
        *,
        model_name: str,
        prototype_dir: Optional[Path] = None,
    ) -> None:
        """Her aile için prototip vektörlerini yükler.

        Args:
            embeddings_client: Yalnızca gelen mesajı embed etmek için kullanılır.
                İstek anında hiçbir prototip embed edilmez.
            model_name: Kullanımdaki embedding modeli; her vektör dosyasındaki
                damgaya karşı kontrol edilir.
            prototype_dir: Testler için vektör dizininin geçersiz kılınması.
        """
        self._client = embeddings_client
        self._model_name = model_name
        self._dir = prototype_dir or PROTOTYPE_DIR
        self._families: dict[str, list[tuple[str, list[float]]]] = {}
        self._load()

    @property
    def available(self) -> bool:
        """Herhangi bir ailenin başarıyla yüklenip yüklenmediği."""
        return bool(self._families)

    def _load(self) -> None:
        """Her ailenin vektör dosyasını okur; bayat veya okunamayanları atlar."""
        if not self._dir.exists():
            logger.info(
                "No prototype directory at %s; semantic matching disabled. "
                "Run scripts/build_prototypes.py to enable it.",
                self._dir,
            )
            return

        for path in sorted(self._dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Unreadable prototype file %s; skipping.", path)
                continue

            if payload.get("model") != self._model_name:
                logger.warning(
                    "Prototype file %s was built with model %r but %r is active; "
                    "skipping rather than matching against stale vectors.",
                    path.name,
                    payload.get("model"),
                    self._model_name,
                )
                continue

            if payload.get("policy_version") != POLICY_VERSION:
                logger.warning(
                    "Prototype file %s was built under policy %s but %s is active; "
                    "skipping.",
                    path.name,
                    payload.get("policy_version"),
                    POLICY_VERSION,
                )
                continue

            entries = [
                (entry["label"], entry["vector"])
                for entry in payload.get("prototypes", [])
                if entry.get("vector")
            ]
            if entries:
                self._families[payload["family"]] = entries

        if self._families:
            logger.info(
                "Prototype matcher loaded families: %s", sorted(self._families)
            )

    async def label_similarities(self, text: str, family: str) -> Optional[dict[str, float]]:
        """Bir mesajı, sadece kazananla değil bir ailenin her etiketiyle karşılaştırıp puanlar.

        Aşağıdaki tekil ``match()`` sonucu bir *karar*dır -- her etiketi
        kazanan artı kararlı/kararsız bir hükme indirger, ki bu eski "semantik
        basamak tek başına karar verir ya da sessiz kalır" merdiveni için tam
        olarak doğrudur. Füzyon katmanı (``app.ai.workflows.router_fusion``)
        bunun yerine sürekli bir kanıt olarak her etiket için tam benzerliğe
        ihtiyaç duyar -- "bu her bir etikete ne kadar yakın" bilgisi, tıpkı
        sözcüksel katmanın niyet başına skorları gibi, "hangi etiket kazandı"
        bilgisinden daha zengin bir özelliktir.

        Asla hata fırlatmaz. Bir embedding kesintisi bunu ``None``'a
        düşürür ve çağıran taraf semantik kanıtı, tıpkı ``match()``'in
        yaptığı gibi, yok sayar.

        Args:
            text: Kullanıcının mesajı.
            family: Karşılaştırılacak aile.

        Returns:
            Etiket -> en iyi kosinüs benzerliği, ya da aile mevcut değilse,
            metin boşsa ya da embedding çağrısı başarısız olduysa None.
        """
        entries = self._families.get(family)
        if not entries or not (text or "").strip():
            return None

        try:
            vector = await self._client.embed_query(text)
        except Exception:
            logger.warning(
                "Embedding call failed; semantic matching skipped for this turn.",
                exc_info=True,
            )
            return None

        best_per_label: dict[str, float] = {}
        for label, prototype in entries:
            score = _cosine(vector, prototype)
            if score > best_per_label.get(label, -1.0):
                best_per_label[label] = score

        return best_per_label or None

    async def match(self, text: str, family: str) -> Optional[SemanticMatch]:
        """Bir mesajı bir ailenin prototipleriyle karşılaştırıp puanlar.

        Asla hata fırlatmaz. Bir embedding kesintisi bu katmanı no-op'a
        düşürür ve çağıran taraf, bu katman var olmadan önce yaptığı gibi
        üst basamağa yükseltir.

        Args:
            text: Kullanıcının mesajı.
            family: Karşılaştırılacak aile.

        Returns:
            En iyi eşleşme, ya da aile mevcut değilse, metin boşsa ya da
            embedding çağrısı başarısız olduysa None.
        """
        best_per_label = await self.label_similarities(text, family)
        if not best_per_label:
            return None

        ranked = sorted(best_per_label.items(), key=lambda item: (-item[1], item[0]))
        label, similarity = ranked[0]
        gap = similarity - ranked[1][1] if len(ranked) > 1 else similarity

        policy = get_policy().semantic
        decisive = (
            similarity >= policy.decisive_similarity and gap >= policy.decisive_margin
        )

        return SemanticMatch(
            label=label,
            similarity=round(similarity, 4),
            runner_up_gap=round(gap, 4),
            decisive=decisive,
        )
