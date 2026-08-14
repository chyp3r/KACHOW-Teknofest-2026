from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.exceptions.rate_limit import RateLimitException
from app.domains.quotas.service import DOCUMENTS_METRIC, DRAFTS_METRIC, QuotaService, current_period


@pytest.fixture
def usage_repo():
    return AsyncMock()


@pytest.fixture
def quota_repo():
    return AsyncMock()


@pytest.fixture
def service(usage_repo, quota_repo):
    return QuotaService(usage_repo, quota_repo)


def _quota(max_documents=None, max_drafts=None):
    quota = MagicMock()
    quota.max_documents_per_month = max_documents
    quota.max_drafts_per_month = max_drafts
    return quota


@pytest.mark.asyncio
async def test_no_quota_row_means_unlimited(service, quota_repo, usage_repo):
    quota_repo.get.return_value = None

    await service.check_and_increment("company-a", DOCUMENTS_METRIC)

    usage_repo.increment.assert_awaited_once_with("company-a", DOCUMENTS_METRIC, current_period(), 1)


@pytest.mark.asyncio
async def test_under_limit_increments_without_raising(service, quota_repo, usage_repo):
    quota_repo.get.return_value = _quota(max_documents=10)
    usage_repo.get.return_value = MagicMock(count=5)

    await service.check_and_increment("company-a", DOCUMENTS_METRIC)

    usage_repo.increment.assert_awaited_once()


@pytest.mark.asyncio
async def test_at_limit_raises_and_does_not_increment(service, quota_repo, usage_repo):
    quota_repo.get.return_value = _quota(max_documents=5)
    usage_repo.get.return_value = MagicMock(count=5)

    with pytest.raises(RateLimitException):
        await service.check_and_increment("company-a", DOCUMENTS_METRIC)

    usage_repo.increment.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_use_of_the_month_with_no_counter_row_yet_is_under_limit(service, quota_repo, usage_repo):
    """A company that hasn't used a metric yet this period has no
    usage_counters row at all -- must be treated as 0, not skipped/denied."""
    quota_repo.get.return_value = _quota(max_documents=1)
    usage_repo.get.return_value = None

    await service.check_and_increment("company-a", DOCUMENTS_METRIC)

    usage_repo.increment.assert_awaited_once()


@pytest.mark.asyncio
async def test_documents_and_drafts_limits_are_independent(service, quota_repo, usage_repo):
    """A documents-only limit must never block a drafts check for the same company."""
    quota_repo.get.return_value = _quota(max_documents=1, max_drafts=None)
    usage_repo.get.return_value = MagicMock(count=1)

    await service.check_and_increment("company-a", DRAFTS_METRIC)

    usage_repo.increment.assert_awaited_once_with("company-a", DRAFTS_METRIC, current_period(), 1)


@pytest.mark.asyncio
async def test_usage_summary_reports_used_and_limit_per_metric(service, quota_repo, usage_repo):
    quota_repo.get.return_value = _quota(max_documents=10, max_drafts=None)
    usage_repo.get.side_effect = [MagicMock(count=3), None]

    summary = await service.usage_summary("company-a")

    assert summary[DOCUMENTS_METRIC] == {"period": current_period(), "used": 3, "limit": 10}
    assert summary[DRAFTS_METRIC] == {"period": current_period(), "used": 0, "limit": None}
