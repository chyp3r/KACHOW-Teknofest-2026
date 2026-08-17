"""Unit tests for `Action.ARTIFACT_TRANSFER` -- the PDP gate
`ArtifactTransferService.execute` calls.

Same pure-function shape as `test_engine.py`: no DB, no mocks, `authorize`
called directly.
"""

from app.core.authz.attributes import Action, Resource, Subject
from app.core.authz.engine import authorize
from app.core.enums.user_role import UserRole


def _subject(role: UserRole, user_id: str = "u-1", company_id: str = "company-1") -> Subject:
    return Subject(user_id=user_id, role=role, company_id=company_id)


def _artifact(
    kind: str = "draft", company_id: str = "company-1", owner_id: str = "u-1", artifact_id: str = "a-1"
) -> Resource:
    return Resource(type=kind, id=artifact_id, company_id=company_id, owner_id=owner_id)


def test_employee_may_transfer_its_own_draft():
    decision = authorize(_subject(UserRole.EMPLOYEE), Action.ARTIFACT_TRANSFER, _artifact(owner_id="u-1"))
    assert decision.permit is True


def test_employee_may_not_transfer_someone_elses_draft():
    decision = authorize(_subject(UserRole.EMPLOYEE), Action.ARTIFACT_TRANSFER, _artifact(owner_id="u-2"))
    assert decision.permit is False


def test_employee_may_not_transfer_someone_elses_document():
    decision = authorize(
        _subject(UserRole.EMPLOYEE), Action.ARTIFACT_TRANSFER, _artifact(kind="document", owner_id="u-2")
    )
    assert decision.permit is False


def test_admin_may_transfer_any_artifact_company_wide():
    decision = authorize(_subject(UserRole.ADMIN), Action.ARTIFACT_TRANSFER, _artifact(owner_id="someone-else"))
    assert decision.permit is True


def test_manager_may_transfer_any_artifact_company_wide():
    decision = authorize(_subject(UserRole.MANAGER), Action.ARTIFACT_TRANSFER, _artifact(owner_id="someone-else"))
    assert decision.permit is True


def test_cross_tenant_transfer_is_denied_even_for_an_admin():
    subject = _subject(UserRole.ADMIN, company_id="company-a")
    resource = _artifact(company_id="company-b", owner_id="someone-else")
    decision = authorize(subject, Action.ARTIFACT_TRANSFER, resource)
    assert decision.permit is False
