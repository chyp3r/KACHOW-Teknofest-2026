"""Asistan ajanının bir tur için çağırabileceği ``suggest_unit`` aracı.

``assistant.md``'nin 4. temel yeteneği ("Birim Yönlendirme") şimdiye kadar
yalnızca tam taslak akışının bir adımı (``planning_graph._step_routing``)
olarak çalışıyordu. Bu araç, aynı yeteneği sohbette doğrudan bir soru olarak
kullanılabilir kılar ("bu evrak hangi birime gider?", "ilgili birimi öner").

Ayrı, taslak-dışı ``POST /routing/suggest`` uç noktasıyla **aynı**
``routing_graph``'ı çalıştırır: yalnızca şirketin aktif birim listesini okuyup
sıralar, hiçbir yan etkisi yoktur -- bu yüzden ``propose_transfer`` /
``request_handoff``'ın aksine bir onay kapısı gerektirmez, salt-okunur bir
getirmedir.
"""

import logging
from typing import Any, Callable, Optional

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolSpec
from app.ai.workflows.events import child_config

logger = logging.getLogger(__name__)


class SuggestUnitArgs(BaseModel):
    """``suggest_unit`` aracının argümanları."""

    konu: str = Field(
        default="",
        description=(
            "Yüklü bir evrak veya aktif bir taslak YOKSA, yönlendirilecek talebin "
            "kısa bir Türkçe özeti (konu, tür, muhatap). Evrak veya taslak varsa "
            "boş bırak; araç doğrudan onların metni üzerinden çalışır."
        ),
    )


def build_routing_tools(
    *,
    company_id: Optional[str],
    routing_graph: Any,
    active_draft_text: str = "",
    document_text: str = "",
    config: Optional[RunnableConfig] = None,
    on_routing_result: Optional[Callable[[dict], None]] = None,
) -> list[ToolSpec]:
    """``suggest_unit`` aracını inşa eder.

    Args:
        company_id: Çağıranın kiracısı -- ``routing_graph`` yalnızca bu
            şirketin aktif yönlendirilebilir birimlerini görür (birimler
            şirket-kapsamlıdır; bkz. ``RoutingState.company_id``). Boş/None
            olması, başka bir şirketin birimlerine düşmek yerine "hiç birim
            tanımlı değil"e degrade eder.
        routing_graph: Derlenmiş birim-yönlendirme alt-grafı
            (``create_routing_graph``); ``_step_routing`` ile aynı örnek.
        active_draft_text: Bu turda aktif bir taslak varsa metni -- önceliklidir.
        document_text: Aktif taslak yoksa, yüklü evrakın çıkarılmış metni.
        config: Assist adımının çalıştırılabilir config'i; routing düğümünün
            kendi ilerleme olaylarının ("Birim Yönlendirme") SSE akışına
            ulaşması için ``child_config`` ile alt-grafa iletilir.
        on_routing_result: Araç bir sonuç ürettiğinde ham ``routing_graph``
            durumuyla çağrılan isteğe bağlı yan kanal (bkz.
            ``handoff_tools.on_handoff_requested``); çağıran öneriyi
            ``SessionFocus``'a taşımak isterse kullanır.

    Returns:
        Tek araçlı bir liste.
    """

    async def _suggest_unit(konu: str = "") -> str:
        text = (active_draft_text or document_text or konu or "").strip()
        if not text:
            return (
                "Birim önerisi için yönlendirilecek bir metin yok. Yüklü bir evrak "
                "veya aktif bir taslak yoksa, yönlendirilecek talebi 'konu' "
                "argümanında kısaca özetleyerek bu aracı yeniden çağır."
            )
        try:
            state = await routing_graph.ainvoke(
                # confidence_score bilinçli olarak geçilmiyor: routing_node
                # onu 100.0'a varsayar ve gerçek model-analizli yola girer.
                # Burada yönlendirilen bir "taslak güven skoru" değil, bir
                # evrak/talep metnidir.
                {"draft": text, "company_id": company_id or ""},
                config=child_config(config),
            )
        except Exception:
            logger.exception("suggest_unit routing failed")
            return "Birim önerisi üretilirken bir hata oluştu; lütfen daha sonra tekrar deneyin."

        routed = state.get("routed_unit")
        if not routed:
            return "Şu an için uygun bir birim önerisi çıkarılamadı."

        if on_routing_result:
            on_routing_result(dict(state))

        lines = [f"Önerilen birim: {routed}"]
        reasoning = (state.get("reasoning") or state.get("justification") or "").strip()
        if reasoning:
            lines.append(f"Gerekçe: {reasoning}")
        alternatives = [
            name
            for name in (state.get("alternative_units") or [])
            if name and name != routed
        ]
        if alternatives:
            lines.append(f"Alternatif birimler: {', '.join(alternatives)}")
        if state.get("requires_human_approval"):
            lines.append(
                "Not: Güven düzeyi düşük veya birim listesi eksik; yetkili bir "
                "kullanıcının teyidi önerilir."
            )
        return "\n".join(lines)

    return [
        ToolSpec(
            name="suggest_unit",
            description=(
                "Bir evrağın veya bir talebin kurum içinde hangi birime sevk "
                "edilmesi gerektiğini gerekçesiyle önerir. Kullanıcı 'bu hangi "
                "birime gider', 'ilgili birimi öner', 'nereye yönlendirmeli' gibi "
                "bir soru sorduğunda çağır. Yüklü bir evrak veya aktif bir taslak "
                "varsa doğrudan onun üzerinden çalışır; yoksa 'konu' argümanına "
                "yönlendirilecek talebin kısa bir özetini yaz. Sonuç: önerilen "
                "birim, gerekçe ve varsa alternatif birimler."
            ),
            args_schema=SuggestUnitArgs,
            handler=_suggest_unit,
        )
    ]
