"""Sınırlı ve gözlemlenebilir prompt derlemesi.

Bağlam eskiden üç ayrı yerde (assist adımı, taslak brief'i, analiz prompt'u)
satır içi olarak inşa ediliyordu; her birinin kendi rastgele kırpma yöntemi
vardı ve hiçbiri modelin gerçek bağlam penceresine karşı bir şey ölçmüyordu --
bkz. ``app/ai/llms/base.py``'deki ``count_tokens``. Bu modül "string'leri
birleştir ve umut et" yaklaşımının yerine açık bir bütçe koyar: zorunlu
parçalar asla düşürülmez, isteğe bağlı parçalar bütçe tükenene kadar öncelik
sırasına göre tutulur ve sığmayan her şey sessizce kırpılmak yerine sonuçta
raporlanır.
"""

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from app.ai.context.budget import TokenBudget
from app.ai.llms.base import BaseLLMClient

logger = logging.getLogger(__name__)

#: `text`'i `budget_tokens`'a sığacak şekilde küçültür, (hâlâ çok büyük
#: olabilecek) sonucu döndürür. Bir blok tamamen düşürülmeden önce denenir.
Compressor = Callable[[str, int], str]


class ContextBudgetExceeded(Exception):
    """Bağlamın ``required`` blokları tek başına mevcut bütçeyi aşıyor.

    Modelin bağlam penceresini sessizce taşırmak yerine fırlatılır --
    önceki davranış (her şeyi birleştir, Ollama baştan kırpsın) tam olarak
    bu modülün ortadan kaldırmak için var olduğu hata modudur.
    """


@dataclass(frozen=True)
class ContextBlock:
    """Bir prompt'un tek başına boyutlandırılabilen, adlandırılmış bir parçası.

    Attributes:
        id: Sabit ad. Gözlemlenebilirlik için (``AssembledContext.dropped``
            / ``.compressed``) ve render edilmiş metni ada göre geri bulmak
            için kullanılır.
        priority: Bütçe darken düşürülme sırası -- daha düşük olan önce
            düşürülür. Aynı önceliği paylaşan bloklar ``ContextBuilder.build``'e
            geçirildikleri sırayla düşürülür. ``required`` bloklar için
            önemsizdir.
        render: Bloğun metnini üretir. Düz bir string yerine ertelenmiş
            (async bir çağrılabilir) olması, çağıranın bu tur için dahil
            etmemeye karar verdiği bir bloğun kendi biçimlendirme maliyetini
            hiç ödememesini sağlar.
        compressor: İsteğe bağlı bir blok düşürülmeden önce, ya da tek
            başına sığmayan zorunlu bir blok ``ContextBudgetExceeded``
            fırlatmadan önce denenen isteğe bağlı geri dönüş:
            ``compressor(text, budget_tokens) -> str``.
        required: Asla düşürülmez. Tek başına sığmıyorsa yine de önce
            ``compressor``'dan geçirilir -- "required" bu içeriğin temsil
            edilmesi gerektiği anlamına gelir, tam olarak bu metnin
            değiştirilmeden gönderilmesi gerektiği anlamına gelmez.
    """

    id: str
    priority: int
    render: Callable[[], Awaitable[str]]
    compressor: Optional[Compressor] = None
    required: bool = False


@dataclass(frozen=True)
class AssembledContext:
    """Bir ``ContextBuilder.build`` çağrısının render edilmiş sonucu.

    Attributes:
        texts: Dahil edilen her blok id'si için son metin (düşürülen bloklar
            burada yer almaz).
        dropped: Sıkıştırmadan sonra bile sığmayan blok id'leri.
        compressed: Yalnızca kendi compressor'ı çalıştıktan sonra tutulan
            blok id'leri.
        total_tokens: ``texts`` içindeki her bloğun toplam boyutu.
    """

    texts: dict[str, str]
    dropped: tuple[str, ...]
    compressed: tuple[str, ...]
    total_tokens: int

    def get(self, block_id: str, default: str = "") -> str:
        """Bir bloğun metnini, ya da düşürülmüş/mevcut değilse ``default``'u döndürür."""
        return self.texts.get(block_id, default)


class ContextBuilder:
    """Bağımsız boyutlandırılmış bloklardan sınırlı bir prompt derler.

    Her bloğu render eder, ``required`` olanları koşulsuz tutar, ardından
    isteğe bağlı olanları bütçe tükenene kadar artan ``priority`` sırasına
    göre tutar -- geri kalanları (bir compressor tanımlıysa) sıkıştırır ya da
    düşürür. Hiçbir şey sessizce kırpılmaz: sığmayan şey yutulmak yerine
    sonuçta raporlanır.
    """

    def __init__(self, llm_client: BaseLLMClient):
        """Builder'ı başlatır.

        Args:
            llm_client: ``count_tokens``'ı sağlar -- gerçek üretim çağrısının
                boyutlandırılacağı aynı tahmin edici, böylece bu builder'ın
                uyguladığı bütçe sağlayıcının gördüğüyle eşleşir.
        """
        self._llm_client = llm_client

    async def build(
        self, blocks: list[ContextBlock], budget: TokenBudget
    ) -> AssembledContext:
        """``blocks``'u render edip ``budget``'a sığdırır.

        Args:
            blocks: Bu prompt için aday bloklar.
            budget: İçine sığdırılacak token bütçesi.

        Returns:
            Derlenmiş bağlam.

        Raises:
            ContextBudgetExceeded: Zorunlu bloklar tek başına sığmıyor.
        """
        rendered: dict[str, str] = {}
        for block in blocks:
            rendered[block.id] = await block.render()

        required = [b for b in blocks if b.required]
        optional = sorted(
            (b for b in blocks if not b.required), key=lambda b: b.priority
        )

        count_tokens = self._llm_client.count_tokens

        # Zorunlu bir blok asla düşürülmez, ama tüm çağrı tamamen
        # başarısız olmadan önce sıkıştırılma şansı yine de verilir --
        # required, "bu içerik temsil edilmelidir" demektir, "ne olursa
        # olsun bu tam metin gönderilmelidir" demek değildir.
        texts: dict[str, str] = {}
        compressed: list[str] = []
        required_tokens = 0
        for block in required:
            text = rendered[block.id]
            cost = count_tokens(text)
            available_for_block = budget.available - required_tokens
            if cost > available_for_block and block.compressor is not None:
                shrunk = block.compressor(text, max(available_for_block, 0))
                shrunk_cost = count_tokens(shrunk)
                if shrunk_cost < cost:
                    text, cost = shrunk, shrunk_cost
                    compressed.append(block.id)
            texts[block.id] = text
            required_tokens += cost

        if required_tokens > budget.available:
            raise ContextBudgetExceeded(
                f"Required context blocks need {required_tokens} tokens; "
                f"only {budget.available} available."
            )

        dropped: list[str] = []
        remaining = budget.available - required_tokens

        for block in optional:
            text = rendered[block.id]
            cost = count_tokens(text)

            if cost <= remaining:
                texts[block.id] = text
                remaining -= cost
                continue

            if block.compressor is not None and remaining > 0:
                shrunk = block.compressor(text, remaining)
                shrunk_cost = count_tokens(shrunk)
                if shrunk_cost <= remaining:
                    texts[block.id] = shrunk
                    compressed.append(block.id)
                    remaining -= shrunk_cost
                    continue

            dropped.append(block.id)
            logger.info("Context block '%s' dropped (budget exhausted).", block.id)

        total_tokens = sum(count_tokens(text) for text in texts.values())
        return AssembledContext(
            texts=texts,
            dropped=tuple(dropped),
            compressed=tuple(compressed),
            total_tokens=total_tokens,
        )
