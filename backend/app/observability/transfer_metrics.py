"""Artifact transfer domaini için Prometheus collector'ları (Faz 5, #205).

`ai_metrics.py`/`company_metrics.py`'nin zaten oturttuğu aynı domain-başına-
tek-modül şekli: import zamanında varsayılan registry'ye kendi kendine
kayıt olan modül seviyesi `Counter`'lar, artı `main.py`'nin açık, grep'lenebilir
bir çağrı noktasına sahip olması için no-op bir `init_transfer_metrics()`.
"""

import logging

from prometheus_client import Counter

logger = logging.getLogger(__name__)

#: Her `ArtifactTransferService.execute()` sonucu, kanala
#: (`"chat"|"ai"|"rest"`) ve sonuca (`"success"|"denied"|"not_found"`) göre.
#: Idempotent bir tekrar (tekrarlanan bir `idempotency_key` için olduğu
#: gibi döndürülen zaten çalıştırılmış bir transfer) burada kasıtlı olarak
#: sayılmaz -- bu yeni bir deneme değildir ve sayılması, her istemci
#: tekrarında aynı transferin çift sayılmasına yol açardı.
ARTIFACT_TRANSFERS = Counter(
    "kachow_artifact_transfers_total",
    "Artifact transfer attempts, by channel and result.",
    ["channel", "result"],
)

#: Özellikle `TransferPolicy.evaluate` deny kararları,
#: `TransferPolicyDecision.reason_code`'a göre (`"self_transfer"`,
#: `"recipient_inactive"`, `"clearance"`, `"favorite_required"`) --
#: `ARTIFACT_TRANSFERS{result="denied"}`'den daha dar bir sinyal; o
#: ayrıca `TransferPolicy`'e hiç ulaşmayan PDP seviyesindeki bir
#: `Action.ARTIFACT_TRANSFER` reddini de kapsar.
TRANSFER_POLICY_DENIALS = Counter(
    "kachow_transfer_policy_denials_total",
    "TransferPolicy deny decisions, by reason.",
    ["reason"],
)


def init_transfer_metrics() -> None:
    """Collector'larının Prometheus'a kayıt olması için bu modülün import edilmesini zorunlu kılar.

    `app.observability.ai_metrics.init_ai_metrics` ve
    `app.observability.company_metrics.init_company_metrics` ile simetriktir.
    """
    logger.debug("Transfer metrics registered.")
