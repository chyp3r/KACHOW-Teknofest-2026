"""Bağlam penceresi doluluk dökümü -- sohbet göstergesinin (ContextUsageRing) verisi.

``planning_graph._run_assist`` her assist turunda bu dökümü üretip
``final_result.details.context_usage`` içine koyar; ``ChatService.compact_session``
aynı yardımcıyı, sohbet sıkıştırıldıktan sonraki yeni durumla çağırır. Segment
token sayıları, gerçek üretim çağrısının boyutlandığı ``count_tokens``
tahmin edicisiyle hesaplanır.
"""

from __future__ import annotations

from app.ai.llms.base import BaseLLMClient

#: Assist adımının kendi cevabı için, prompt'un yanında ayrılan token payı.
#: ``planning_graph`` bunu ``ASSIST_COMPLETION_RESERVE_TOKENS`` olarak da
#: yeniden dışa verir (geriye dönük uyum).
COMPLETION_RESERVE_TOKENS = 1024


def compute_context_usage(
    llm_client: BaseLLMClient,
    *,
    system_prompt: str,
    input_text: str = "",
    document_context: str = "",
    history_summary: str = "",
    history_turns: list[dict[str, str]] | None = None,
    reserved_tokens: int = COMPLETION_RESERVE_TOKENS,
) -> dict:
    """Bağlam penceresinin ne kadarının, ne için dolu olduğunu döker.

    Args:
        llm_client: Aktif sağlayıcı istemcisi (``context_window`` ve
            ``count_tokens`` buradan alınır).
        system_prompt: Asistan sistem yönergesi (sabit maliyet).
        input_text: Bu turun kullanıcı mesajı; sıkıştırma dökümünde boş.
        document_context: ``context_builder``'ın yerleştirdiği belge bloğu.
        history_summary: Yuvarlanan konuşma özeti.
        history_turns: Birebir taşınan geçmiş penceresi.
        reserved_tokens: Yanıt için ayrılan pay.

    Returns:
        ``{"total", "used", "free", "segments": [{"key","label","tokens"}]}``.
        Yalnızca token'ı > 0 olan segmentler listelenir.
    """
    count = llm_client.count_tokens
    total = llm_client.context_window
    segments = [
        {"key": "system", "label": "Sistem yönergesi", "tokens": count(system_prompt)},
        {"key": "document_context", "label": "Belge bağlamı", "tokens": count(document_context)},
        {"key": "history_summary", "label": "Geçmiş özeti", "tokens": count(history_summary)},
        {
            "key": "history",
            "label": "Sohbet geçmişi",
            "tokens": sum(count(str(turn.get("content", ""))) for turn in (history_turns or [])),
        },
        {"key": "input", "label": "Güncel mesaj", "tokens": count(input_text)},
        {"key": "reserved", "label": "Yanıt için ayrılan", "tokens": reserved_tokens},
    ]
    used = sum(segment["tokens"] for segment in segments)
    return {
        "total": total,
        "used": min(used, total),
        "free": max(total - used, 0),
        "segments": [segment for segment in segments if segment["tokens"] > 0],
    }
