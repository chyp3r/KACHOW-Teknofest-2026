from unittest.mock import AsyncMock

import pytest

from app.api.exceptions.authorization import AuthorizationException
from app.core.authz.attributes import Action, Resource, Subject
from app.core.authz.engine import GrantView
from app.core.authz.service import AuthzService
from app.core.enums.user_role import UserRole


def _subject(role=UserRole.EMPLOYEE, user_id="u-1", company_id="company-1") -> Subject:
    return Subject(user_id=user_id, role=role, company_id=company_id)


def _document(company_id="company-1", owner_id="u-1") -> Resource:
    return Resource(type="document", id="doc-1", company_id=company_id, owner_id=owner_id)


class _FakeGrantRepository:
    def __init__(self, grants=()):
        self.grants = list(grants)
        self.calls = []

    async def list_active_for_subject(self, company_id, role, user_id, action):
        self.calls.append((company_id, role, user_id, action))
        return self.grants


async def test_no_cache_recomputes_every_call_via_the_grant_repository():
    grant_repo = _FakeGrantRepository()
    service = AuthzService(grant_repo, decision_cache=None)

    decision = await service.authorize(_subject(), Action.DOCUMENT_READ, _document())

    assert decision.permit is True
    assert len(grant_repo.calls) == 1


async def test_root_subject_skips_grant_resolution_entirely():
    grant_repo = _FakeGrantRepository()
    service = AuthzService(grant_repo, decision_cache=None)
    subject = Subject(user_id="root-1", role=UserRole.ROOT, company_id=None)

    decision = await service.authorize(subject, "system:read_all", resource=None)

    assert decision.permit is True
    assert grant_repo.calls == []


async def test_grant_from_the_repository_is_actually_consulted():
    grant = GrantView(
        id="g-1",
        subject_type="user",
        subject_id="u-1",
        action=Action.DOCUMENT_DELETE,
        resource_type="document",
        resource_selector={"any": True},
        effect="permit",
        priority=0,
    )
    grant_repo = _FakeGrantRepository([grant])
    service = AuthzService(grant_repo, decision_cache=None)
    resource = _document(owner_id="someone-else")

    decision = await service.authorize(_subject(), Action.DOCUMENT_DELETE, resource)

    assert decision.permit is True
    assert decision.matched_rule == "g-1"


async def test_authorize_or_raise_raises_on_deny():
    grant_repo = _FakeGrantRepository()
    service = AuthzService(grant_repo, decision_cache=None)
    resource = _document(owner_id="someone-else")

    with pytest.raises(AuthorizationException):
        await service.authorize_or_raise(_subject(), Action.DOCUMENT_DELETE, resource)


async def test_authorize_or_raise_passes_on_permit():
    grant_repo = _FakeGrantRepository()
    service = AuthzService(grant_repo, decision_cache=None)

    await service.authorize_or_raise(_subject(), Action.DOCUMENT_READ, _document())  # no raise


async def test_cache_hit_skips_the_grant_repository():
    grant_repo = _FakeGrantRepository()
    cache = AsyncMock()
    cache.get.return_value = None
    service = AuthzService(grant_repo, decision_cache=cache)

    await service.authorize(_subject(), Action.DOCUMENT_READ, _document())
    assert len(grant_repo.calls) == 1
    cache.set.assert_awaited_once()

    cache.get.reset_mock()
    from app.core.authz.engine import Decision

    cache.get.return_value = Decision(permit=True, reason="cached")
    grant_repo.calls.clear()

    decision = await service.authorize(_subject(), Action.DOCUMENT_READ, _document())
    assert decision.reason == "cached"
    assert grant_repo.calls == []


async def test_invalidate_company_bumps_the_cache_epoch():
    grant_repo = _FakeGrantRepository()
    cache = AsyncMock()
    service = AuthzService(grant_repo, decision_cache=cache)

    await service.invalidate_company("company-1")

    cache.bump_epoch.assert_awaited_once_with("company-1")


async def test_invalidate_company_is_a_noop_without_a_cache():
    service = AuthzService(_FakeGrantRepository(), decision_cache=None)
    await service.invalidate_company("company-1")  # no raise
