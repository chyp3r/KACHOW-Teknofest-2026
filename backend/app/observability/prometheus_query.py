"""Prometheus HTTP API'sine karşı küçük, salt-okunur bir sorgu istemcisi.

Yalnızca `GET /root/users/insights`'in global "AI token kullanımı" panelini
beslemek için var. Prometheus per-kullanıcı token verisi tutmaz
(`app.observability.ai_metrics.LLM_TOKENS` yalnızca `agent`/`kind` etiketli --
kardinalite gerekçesi için kiracılık planına bakın), bu yüzden buradaki
görünüm de sistem genelidir.

Ulaşılamayan / yapılandırılmamış bir Prometheus (Docker dışı geliştirme,
kapalı monitoring stack'i) bir hata değil, boş bir paneldir: her fonksiyon
uyarı loglar ve boş yapı döndürür.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 3.0


async def _instant_query(promql: str) -> list[dict[str, Any]]:
    """`GET /api/v1/query` -- anlık vektör; `[{"metric": {...}, "value": [ts, "n"]}]`.

    Hiçbir zaman fırlatmaz: ağ hatası, 5xx veya bozuk gövde -> ``[]``.
    """
    url = f"{settings.PROMETHEUS_URL.rstrip('/')}/api/v1/query"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params={"query": promql})
        response.raise_for_status()
        body = response.json()
    except Exception as exc:  # noqa: BLE001 -- kasıtlı: panel opsiyoneldir
        logger.warning("Prometheus query failed (%s): %s", promql, exc)
        return []
    if body.get("status") != "success":
        logger.warning("Prometheus query returned non-success: %s", body.get("error"))
        return []
    return body.get("data", {}).get("result", [])


def _sum_by(result: list[dict[str, Any]], label: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for series in result:
        key = series.get("metric", {}).get(label, "")
        try:
            value = float(series.get("value", [None, "0"])[1])
        except (TypeError, ValueError, IndexError):
            continue
        totals[key] = totals.get(key, 0.0) + value
    return totals


async def llm_token_usage() -> dict[str, Any]:
    """`kachow_llm_tokens_total`'ın sistem geneli dökümü.

    Returns:
        ``{"by_agent": {agent: tokens}, "by_kind": {kind: tokens},
        "total": tokens, "available": bool}``. Prometheus'a ulaşılamazsa
        ``available`` False ve sözlükler boştur.
    """
    by_agent_raw = await _instant_query("sum by (agent) (kachow_llm_tokens_total)")
    by_kind_raw = await _instant_query("sum by (kind) (kachow_llm_tokens_total)")

    by_agent = {k: v for k, v in _sum_by(by_agent_raw, "agent").items() if k}
    by_kind = {k: v for k, v in _sum_by(by_kind_raw, "kind").items() if k}
    total = sum(by_kind.values()) or sum(by_agent.values())

    return {
        "by_agent": by_agent,
        "by_kind": by_kind,
        "total": total,
        "available": bool(by_agent or by_kind),
    }
