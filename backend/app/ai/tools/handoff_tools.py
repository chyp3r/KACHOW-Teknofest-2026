"""Asistan ajanının bir tur için çağırabileceği request_handoff aracı (Faz 7).

``assistant.md``'nin kendi "Üretim Yasağı" kuralı, modele beş temel yeteneğinin
dışındaki her şeyi kibarca reddetmesini söyler -- ama "Cevap Taslağı Hazırlama"
(taslak hazırlama) ve aktif taslağı revize etme, o beşten *ikisidir*.
``draft``/``revise``'e yönlendirilmesi gerekirken bunun yerine ``assist``'e
düşen bir mesajın (zayıf veya yedek bir yönlendirme kararı; bu düzeltmenin
deterministik yarısı için bkz. ``planning_graph._deterministic_handoff_target``),
asistanın kendi serbest formatlı yanıtının güvenilir biçimde sinyal verdiği
bir metin kalıbı yoktur -- ``propose_transfer``'ın aksine, sonradan tespit
edilecek sabit bir şekil de yoktur. Bu araç, modele içeriği kendisi yazmak
(bu, teknik olarak kullanılabilir bir mektup üretse bile ruh olarak Üretim
Yasağı'nı ihlal eder) veya tamamen meşru bir isteği baştan reddetmek yerine
"bu, bana değil draft/revise'e ait" demenin açık, yapılandırılmış bir yolunu verir.

``app.ai.tools.transfer_tools`` ile aynı tek-tur, yalnızca-öner şekli:
handler asla doğrudan graph durumunu mutasyona uğratmaz (bir araç handler'ı
assist adımının kendi düğümünün içinde çalışır, nedeni için o modülün
docstring'ine bakın); isteği yalnızca bir yan kanal geri çağırımı üzerinden
``planning_graph._step_assist``'e geri verir; bu, hedef akışın kendi
adımlarını ``plan_steps``'e fiilen ekleyen şeydir.
"""

from typing import Callable, Literal

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolSpec


class RequestHandoffArgs(BaseModel):
    """Arguments for the ``request_handoff`` tool."""

    target: Literal["draft", "revise"] = Field(
        description=(
            "Bu istek gerçekte hangi akışa ait: 'draft' (yeni bir resmî yazı/taslak "
            "hazırlanması isteniyor) veya 'revise' (mevcut aktif taslakta somut bir "
            "değişiklik isteniyor)."
        )
    )
    reason: str = Field(
        default="",
        description="Bu isteğin neden kendi görev alanın yerine bu akışa ait olduğunun kısa gerekçesi.",
    )


def build_handoff_tools(
    *,
    has_active_draft: bool,
    on_handoff_requested: Callable[[dict], None],
) -> list[ToolSpec]:
    """``request_handoff`` aracını inşa eder.

    Args:
        has_active_draft: Bu turda ``SessionFocus.active_draft``'ın ayarlı
            olup olmadığı -- revize edilecek hiçbir şey olmadığında
            ``target="revise"`` reddedilir (asla devredilmez); bu,
            ``_step_revise``/``intent_scorer.score_intents``'in deterministik
            yönlendirme yoluna zaten verdiği aynı garantidir (C-öğesi:
            revise, aktif bir taslak olmadan asla devredilmez).
        on_handoff_requested: Model bu aracı çağırdığında
            ``{"target": ..., "reason": ...}`` alan yan kanal geri çağırımı --
            ``build_transfer_tools``'un ``on_transfer_proposed``'ini tam olarak yansıtır.

    Returns:
        Tek araçlı bir liste.
    """

    async def _request_handoff(target: str, reason: str = "") -> str:
        if target == "revise" and not has_active_draft:
            return (
                "Şu anda revize edilecek aktif bir taslak yok; bu isteğe normal "
                "yanıtını vermeye devam et."
            )
        on_handoff_requested({"target": target, "reason": reason})
        return "İstek ilgili akışa yönlendiriliyor; buna ek bir açıklama üretmene gerek yok."

    return [
        ToolSpec(
            name="request_handoff",
            description=(
                "Kullanıcının mesajı aslında yeni bir resmî yazı/taslak hazırlanmasını "
                "(draft) veya mevcut aktif taslakta somut bir değişiklik yapılmasını "
                "(revise) istiyorsa -- ama bu istek yanlışlıkla sana yönlendirildiyse -- "
                "kendi cevabını üretmeye veya reddetmeye çalışmak yerine bu aracı çağır. "
                "Yalnızca istek gerçekten bu iki akıştan birine aitse çağır; genel bir "
                "soru, sohbet veya sistemin görev alanı dışında kalan bir istek için "
                "ASLA çağırma."
            ),
            args_schema=RequestHandoffArgs,
            handler=_request_handoff,
        )
    ]
