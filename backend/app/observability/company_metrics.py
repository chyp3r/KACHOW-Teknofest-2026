"""Company-tagged, deliberately small Prometheus collector set -- the
tenancy plan's own cardinality warning applies here: `app.observability.
ai_metrics`'s ~20 collectors already cross `graph x node x status`, and
multiplying that by a growing, never-shrinking set of company slugs would
permanently inflate the series count even for deleted companies. This
module is kept to exactly the handful of company-level business signals
worth that cost, label value always the human-readable `slug` (not the
uuid `id`), matching what a Grafana dashboard viewer would actually type
into a `company` template variable.

`kachow_company_requests_total` is deliberately single-labelled
(`company` only, no `endpoint_group`) -- attributing a request to a route
group needs either per-route instrumentation or reading matched-route
state from a second middleware pass, and this module's whole point is
staying cheap and simple; the existing generic HTTP metrics
(`app.observability.metrics`, unlabelled by company) already cover the
per-route breakdown.
"""

import logging
from typing import Optional

from prometheus_client import Counter, Gauge

logger = logging.getLogger(__name__)

COMPANY_REQUESTS = Counter(
    "kachow_company_requests_total",
    "Authenticated requests, by company.",
    ["company"],
)

COMPANY_DOCUMENTS = Counter(
    "kachow_company_documents_total",
    "Documents registered, by company.",
    ["company"],
)

COMPANY_DRAFTS = Counter(
    "kachow_company_drafts_total",
    "Draft versions created, by company and status.",
    ["company", "status"],
)

COMPANY_GUARDRAIL_BLOCKS = Counter(
    "kachow_company_guardrail_blocks_total",
    "Guardrail deny/block decisions, by company and kind.",
    ["company", "kind"],
)

#: Refreshed opportunistically whenever `AnalyticsService.summary` runs for
#: a company (see that module), not on a continuous timer -- there is no
#: periodic-task runner in this codebase to drive one (no celery/cron; see
#: `app.lifespan`'s own startup-only scope), so this gauge's value is only
#: as fresh as the last analytics summary request for that company. Still
#: honest: it reports what it actually last measured, not a fabricated
#: continuous signal.
COMPANY_ACTIVE_USERS = Gauge(
    "kachow_company_active_users",
    "Users active in the last 7 days, by company (refreshed on each analytics summary call).",
    ["company"],
)

#: company_id -> slug. Populated lazily by `resolve_slug`, never evicted --
#: a company's slug is immutable after creation (see `CompanyModel.slug`'s
#: own docstring), so a permanently-growing cache bounded by "however many
#: companies exist" is safe, the same reasoning `documents/service.py`'s
#: `_qa_vector_size` probe-once-per-process cache already relies on.
_slug_cache: dict[str, str] = {}


def cache_slug(company_id: str, slug: str) -> None:
    """Record a known `company_id` -> `slug` mapping, e.g. right after
    `CompanyRepository.get_by_id` already loaded the row for another
    reason -- avoids a second lookup purely for the metrics label."""
    _slug_cache[company_id] = slug


def cached_slug(company_id: Optional[str]) -> Optional[str]:
    """The cached slug for `company_id`, or `None` on a cache miss.

    Deliberately does not query the database itself -- this module must
    stay free of a DB dependency so it can be imported from anywhere
    (including `app.api.dependency`, which already imports a lot). Callers
    that can afford a lookup (they already have a `CompanyRepository` in
    hand, e.g. `get_current_user`) should call `cache_slug` once they have
    the answer.
    """
    if company_id is None:
        return None
    return _slug_cache.get(company_id)


def note_request(company_id: Optional[str]) -> None:
    """Increment `COMPANY_REQUESTS` for `company_id`, if its slug is already
    cached. A cache miss (the company's slug was never resolved this
    process) is silently skipped rather than triggering a lookup -- see
    `cached_slug`'s docstring."""
    slug = cached_slug(company_id)
    if slug is not None:
        COMPANY_REQUESTS.labels(company=slug).inc()


def note_document_registered(company_slug: str) -> None:
    COMPANY_DOCUMENTS.labels(company=company_slug).inc()


def note_draft_created(company_slug: str, status: Optional[str]) -> None:
    COMPANY_DRAFTS.labels(company=company_slug, status=status or "unknown").inc()


def note_guardrail_block(company_slug: str, kind: str) -> None:
    COMPANY_GUARDRAIL_BLOCKS.labels(company=company_slug, kind=kind).inc()


def set_active_users(company_slug: str, count: int) -> None:
    COMPANY_ACTIVE_USERS.labels(company=company_slug).set(count)


def init_company_metrics() -> None:
    """Force this module's import so its collectors register with Prometheus.

    Symmetric with `app.observability.ai_metrics.init_ai_metrics` -- see
    that function's own docstring for why this exists as an explicit,
    greppable call site even though every collector here already registers
    itself at module import time.
    """
    logger.debug("Company metrics registered.")
