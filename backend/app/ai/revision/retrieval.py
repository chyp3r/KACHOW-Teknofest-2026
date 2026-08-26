"""Bir revizyon için koşullu mevzuat yeniden çekme.

``run_revise`` asla yeniden sınıflandırma yapmaz (bkz.
``app.ai.workflows.revise``'in modül docstring'i) ve varsayılan olarak
mevzuatı da asla yeniden çekmez -- taslak ilk yazıldığında dondurulmuş olan
``active_draft.context``'i yeniden kullanır. Bu, yeni bir dayanağa ihtiyaç
duymayan bir ton/uzunluk düzenlemesi için doğrudur, ama donmuş bağlamın hiç
kapsamadığı bir kanun, madde veya kuruma atıfta bulunmasını isteyen bir
talimat için yanlıştır.

``maybe_extend_context``, bilinçli olarak tek istisnadır: yalnızca
``needs_reretrieval`` talimatın gerçekten normatif içerik tanıttığını
söylediğinde çalışır, herhangi bir hata veya zaman aşımında donmuş bağlama
düşer ve asla hata fırlatmaz.
"""

import asyncio
import logging
import re
from typing import Any, Optional

from app.ai.revision.instruction import RevisionInstruction, needs_reretrieval
from app.ai.session.focus import DraftVersion
from app.core.config import settings
from app.observability.ai_metrics import REVISION_RETRIEVAL

logger = logging.getLogger(__name__)

#: Yeniden çekme başına çekilen alıntılar -- document_analysis_graph'ın
#: kendi MEVZUAT_RESULT_LIMIT'i ile aynı büyüklük mertebesinde; bir
#: genişletmenin eklendiği donmuş bağlama baskın gelmeyeceği kadar küçük.
DEFAULT_RETRIEVAL_LIMIT = 5

_ALINTI_MARKER = re.compile(r"\[ALINTI (\d+)\]")


def _coerce_fields(classification: dict[str, Any]) -> dict[str, Any]:
    fields = (classification or {}).get("fields", {})
    if hasattr(fields, "model_dump"):
        return fields.model_dump()
    return fields if isinstance(fields, dict) else {}


def _build_query(instruction: RevisionInstruction, active_draft: DraftVersion) -> str:
    """Yeniden çekme sorgusunu, talimatın kendi normatif token'ları ile
    taslağın bilinen konusundan oluşturur --
    ``document_analysis_graph._build_mevzuat_query`` ile aynı "korpusun en
    iyi eşleştirdiği literal token'lar" gerekçesi, bir model yeniden yazımı değil."""
    fields = _coerce_fields(active_draft.classification)
    parts = [
        *instruction.normative_tokens,
        fields.get("konu") or "",
        active_draft.correspondence_type or "",
    ]
    query = " ".join(str(part) for part in parts if part).strip()
    return query or instruction.raw


def _next_index(frozen_context: str) -> int:
    numbers = [int(match) for match in _ALINTI_MARKER.findall(frozen_context)]
    return (max(numbers) + 1) if numbers else 1


def _render_new_excerpts(documents: list[Any], *, frozen_context: str, start_index: int) -> list[str]:
    """Yalnızca donmuş bağlamda henüz bulunmayan alıntıları render eder.

    Tekilleştirme, donmuş bağlamın render edilmiş metnine karşı düz bir alt
    dize kontrolüdür -- donmuş bağlam aynı korpustan aynı fonksiyonla
    (``document_analysis_graph._render_mevzuat_excerpts``) render edildi, bu
    yüzden orada zaten bulunan bir alıntı kelimesi kelimesine görünür.
    """
    rendered: list[str] = []
    index = start_index
    for document in documents:
        content = (document.page_content or "").strip()
        if not content or content in frozen_context:
            continue
        source = document.metadata.get("mevzuat", "bilinmiyor")
        rendered.append(f"[ALINTI {index}] (Kaynak: {source})\n{content}")
        index += 1
    return rendered


async def maybe_extend_context(
    *,
    instruction: RevisionInstruction,
    active_draft: DraftVersion,
    retriever: Optional[Any],
    limit: int = DEFAULT_RETRIEVAL_LIMIT,
    timeout_s: Optional[float] = None,
) -> tuple[str, dict[str, Any]]:
    """Talimat gerektiriyorsa taslağın donmuş mevzuat bağlamını genişletir.

    Args:
        instruction: Ayrıştırılmış revizyon talimatı.
        active_draft: ``context``'i ilk yazıldığındaki donmuş mevzuat
            alıntıları olan, revize edilmekte olan taslak sürümü.
        retriever: ``async def retrieve(query, limit) -> list[Document]``
            sunan bir hibrit/mevzuat retriever'ı, veya her zaman atlamak için
            None (``document_analysis_graph``'ın kendi "yapılandırılmış
            retriever yok" kuralıyla eşleşir).
        limit: İstenecek alıntı sayısı.
        timeout_s: Sert zaman aşımı; varsayılan olarak
            ``settings.REVISION_RERETRIEVAL_TIMEOUT_SECONDS``.

    Returns:
        ``(context, meta)``. Yeniden çekme atlandığında, zaman aşımına
        uğradığında veya başarısız olduğunda ``context`` donmuş bağlamla
        değişmeden aynıdır, aksi halde yeni bulunan alıntılar eklenmiş
        donmuş bağlamdır. ``meta``, ne olduğunu tanımlar:
        ``{"decision": "skipped"|"extended"|"failed", "query": str,
        "added": int}``.
    """
    frozen_context = active_draft.context or ""

    if (
        not settings.REVISION_RERETRIEVAL_ENABLED
        or retriever is None
        or not needs_reretrieval(instruction)
    ):
        REVISION_RETRIEVAL.labels(decision="skipped").inc()
        return frozen_context, {"decision": "skipped", "query": "", "added": 0}

    query = _build_query(instruction, active_draft)
    timeout = timeout_s if timeout_s is not None else settings.REVISION_RERETRIEVAL_TIMEOUT_SECONDS

    try:
        async with asyncio.timeout(timeout):
            documents = await retriever.retrieve(query, limit=limit)
    except Exception:
        logger.exception("Revision re-retrieval failed; keeping the frozen context.")
        REVISION_RETRIEVAL.labels(decision="failed").inc()
        return frozen_context, {"decision": "failed", "query": query, "added": 0}

    new_excerpts = _render_new_excerpts(
        documents, frozen_context=frozen_context, start_index=_next_index(frozen_context)
    )
    if not new_excerpts:
        REVISION_RETRIEVAL.labels(decision="skipped").inc()
        return frozen_context, {"decision": "skipped", "query": query, "added": 0}

    new_block = "\n\n".join(new_excerpts)
    extended = f"{frozen_context}\n\n{new_block}" if frozen_context else new_block
    REVISION_RETRIEVAL.labels(decision="extended").inc()
    return extended, {"decision": "extended", "query": query, "added": len(new_excerpts)}
