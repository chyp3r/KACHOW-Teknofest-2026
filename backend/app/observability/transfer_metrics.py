"""Prometheus collectors for the artifact transfer domain (Faz 5, #205).

Same one-module-per-domain shape `ai_metrics.py`/`company_metrics.py`
already establish: module-level `Counter`s that self-register with the
default registry at import time, plus a no-op `init_transfer_metrics()`
so `main.py` has an explicit, greppable call site.
"""

import logging

from prometheus_client import Counter

logger = logging.getLogger(__name__)

#: Every `ArtifactTransferService.execute()` outcome, by channel
#: (`"chat"|"ai"|"rest"`) and result (`"success"|"denied"|"not_found"`).
#: An idempotent replay (an already-executed transfer returned as-is for a
#: repeated `idempotency_key`) is deliberately not counted here -- it is
#: not a new attempt, and counting it would double-count the same transfer
#: on every client retry.
ARTIFACT_TRANSFERS = Counter(
    "kachow_artifact_transfers_total",
    "Artifact transfer attempts, by channel and result.",
    ["channel", "result"],
)

#: `TransferPolicy.evaluate` deny decisions specifically, by
#: `TransferPolicyDecision.reason_code` (`"self_transfer"`,
#: `"recipient_inactive"`, `"clearance"`, `"favorite_required"`) -- a
#: narrower signal than `ARTIFACT_TRANSFERS{result="denied"}`, which also
#: covers a PDP-level `Action.ARTIFACT_TRANSFER` denial that never reaches
#: `TransferPolicy` at all.
TRANSFER_POLICY_DENIALS = Counter(
    "kachow_transfer_policy_denials_total",
    "TransferPolicy deny decisions, by reason.",
    ["reason"],
)


def init_transfer_metrics() -> None:
    """Force this module's import so its collectors register with Prometheus.

    Symmetric with `app.observability.ai_metrics.init_ai_metrics` and
    `app.observability.company_metrics.init_company_metrics`.
    """
    logger.debug("Transfer metrics registered.")
