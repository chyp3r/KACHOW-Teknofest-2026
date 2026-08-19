"""Unit tests for the ABAC PDP core (app.core.authz.engine).

Pure-function coverage only -- no DB, no Redis, no FastAPI. See
tests/unit/core/authz/test_service.py for the DB/cache-backed
AuthzService layer, and tests/unit/domains/test_permission_grant_router.py
for the HTTP surface.
"""

import pytest

from app.core.authz.attributes import Action, Environment, Resource, Subject
from app.core.authz.engine import GrantView, authorize, role_permitted
from app.core.enums.user_role import UserRole


def _subject(role: UserRole, user_id: str = "u-1", company_id: str = "company-1") -> Subject:
    return Subject(user_id=user_id, role=role, company_id=company_id)


def _document(company_id: str = "company-1", owner_id: str = "u-1", doc_id: str = "doc-1") -> Resource:
    return Resource(type="document", id=doc_id, company_id=company_id, owner_id=owner_id)


# ==========================================
# Tenant gate
# ==========================================
def test_employee_reading_a_different_companys_document_is_denied():
    subject = _subject(UserRole.EMPLOYEE, company_id="company-1")
    resource = _document(company_id="company-2", owner_id="u-1")
    decision = authorize(subject, Action.DOCUMENT_READ, resource)
    assert decision.permit is False
    assert decision.cacheable is False


def test_manager_of_company_a_cannot_read_company_b_document():
    """Regression guard for the tenancy plan's explicit MANAGER cross-company test."""
    subject = _subject(UserRole.MANAGER, company_id="company-a")
    resource = _document(company_id="company-b", owner_id="someone-else")
    decision = authorize(subject, Action.DOCUMENT_READ, resource)
    assert decision.permit is False


def test_root_without_company_scope_is_denied_a_company_resource():
    subject = Subject(user_id="root-1", role=UserRole.ROOT, company_id=None)
    resource = _document(company_id="company-1")
    decision = authorize(subject, Action.DOCUMENT_READ, resource, Environment(company_scope=None))
    assert decision.permit is False


def test_root_scoped_into_the_resources_company_is_permitted():
    subject = Subject(user_id="root-1", role=UserRole.ROOT, company_id=None)
    resource = _document(company_id="company-1")
    decision = authorize(subject, Action.DOCUMENT_READ, resource, Environment(company_scope="company-1"))
    assert decision.permit is True


def test_resource_with_no_company_id_skips_the_tenant_gate():
    """drafts.company_id is still nullable (Faz 3) -- the gate must not crash or deny on None."""
    subject = _subject(UserRole.EMPLOYEE)
    resource = Resource(type="draft", id="d-1", company_id=None, owner_id="u-1")
    decision = authorize(subject, Action.DRAFT_READ, resource)
    assert decision.permit is True


def test_employee_may_update_its_own_drafts_destination():
    subject = _subject(UserRole.EMPLOYEE, user_id="u-1")
    resource = Resource(type="draft", id="d-1", company_id="company-1", owner_id="u-1")
    decision = authorize(subject, Action.DRAFT_UPDATE, resource)
    assert decision.permit is True


def test_employee_may_not_update_another_employees_draft_destination():
    subject = _subject(UserRole.EMPLOYEE, user_id="u-2")
    resource = Resource(type="draft", id="d-1", company_id="company-1", owner_id="u-1")
    decision = authorize(subject, Action.DRAFT_UPDATE, resource)
    assert decision.permit is False


def test_manager_may_update_any_drafts_destination_company_wide():
    subject = _subject(UserRole.MANAGER, user_id="mgr-1")
    resource = Resource(type="draft", id="d-1", company_id="company-1", owner_id="u-1")
    decision = authorize(subject, Action.DRAFT_UPDATE, resource)
    assert decision.permit is True


# ==========================================
# Built-in role rules
# ==========================================
def test_employee_reads_its_own_document():
    subject = _subject(UserRole.EMPLOYEE, user_id="u-1")
    resource = _document(owner_id="u-1")
    decision = authorize(subject, Action.DOCUMENT_READ, resource)
    assert decision.permit is True
    assert decision.matched_rule == f"{UserRole.EMPLOYEE}:{Action.DOCUMENT_READ}"


def test_employee_cannot_read_a_colleagues_document():
    subject = _subject(UserRole.EMPLOYEE, user_id="u-1")
    resource = _document(owner_id="u-2")
    decision = authorize(subject, Action.DOCUMENT_READ, resource)
    assert decision.permit is False


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.MANAGER])
def test_admin_and_manager_read_any_document_company_wide(role):
    subject = _subject(role, user_id="u-1")
    resource = _document(owner_id="someone-else")
    decision = authorize(subject, Action.DOCUMENT_READ, resource)
    assert decision.permit is True


def test_employee_has_no_unit_manage_rule():
    subject = _subject(UserRole.EMPLOYEE)
    decision = authorize(subject, Action.UNIT_MANAGE, resource=None)
    assert decision.permit is False


def test_admin_can_manage_units_with_no_concrete_resource():
    subject = _subject(UserRole.ADMIN)
    decision = authorize(subject, Action.UNIT_MANAGE, resource=None)
    assert decision.permit is True


def test_no_matching_rule_is_an_implicit_deny():
    subject = _subject(UserRole.EMPLOYEE)
    decision = authorize(subject, "some:unknown-action", resource=None)
    assert decision.permit is False
    assert decision.matched_rule is None


# ==========================================
# role_permitted (require_roles shim)
# ==========================================
def test_role_permitted_matches_membership():
    assert role_permitted(UserRole.ADMIN, (UserRole.ADMIN, UserRole.MANAGER)) is True
    assert role_permitted(UserRole.EMPLOYEE, (UserRole.ADMIN, UserRole.MANAGER)) is False


# ==========================================
# DB-backed grants: deny wins, priority, expiry, selectors
# ==========================================
def _grant(**overrides) -> GrantView:
    base = dict(
        id="grant-1",
        subject_type="user",
        subject_id="u-1",
        action=Action.DOCUMENT_DELETE,
        resource_type="document",
        resource_selector={"any": True},
        effect="permit",
        priority=0,
        time_boxed=False,
    )
    base.update(overrides)
    return GrantView(**base)


def test_explicit_deny_grant_overrides_a_permitting_builtin_rule():
    subject = _subject(UserRole.ADMIN)
    resource = _document(owner_id="someone-else")
    deny = _grant(id="deny-1", action=Action.DOCUMENT_DELETE, effect="deny")
    decision = authorize(subject, Action.DOCUMENT_DELETE, resource, grants=[deny])
    assert decision.permit is False
    assert decision.matched_rule == "deny-1"


def test_explicit_deny_outranks_a_higher_priority_permit():
    subject = _subject(UserRole.EMPLOYEE)
    resource = _document(owner_id="u-1")
    permit = _grant(id="permit-1", effect="permit", priority=1000)
    deny = _grant(id="deny-1", effect="deny", priority=0)
    decision = authorize(subject, Action.DOCUMENT_DELETE, resource, grants=[permit, deny])
    assert decision.permit is False
    assert decision.matched_rule == "deny-1"


def test_highest_priority_permit_wins_among_competing_grants():
    subject = _subject(UserRole.EMPLOYEE)
    resource = _document(owner_id="someone-else")
    low = _grant(id="low", priority=1)
    high = _grant(id="high", priority=5)
    decision = authorize(subject, Action.DOCUMENT_DELETE, resource, grants=[low, high])
    assert decision.permit is True
    assert decision.matched_rule == "high"


def test_grant_lets_an_employee_reach_a_document_it_does_not_own():
    subject = _subject(UserRole.EMPLOYEE, user_id="u-1")
    resource = _document(owner_id="u-2")
    grant = _grant(subject_id="u-1", resource_selector={"any": True})
    decision = authorize(subject, Action.DOCUMENT_DELETE, resource, grants=[grant])
    assert decision.permit is True


def test_owner_self_selector_only_matches_the_subjects_own_resource():
    subject = _subject(UserRole.EMPLOYEE, user_id="u-1")
    own = _document(owner_id="u-1")
    other = _document(owner_id="u-2")
    grant = _grant(resource_selector={"owner": "self"})
    assert authorize(subject, Action.DOCUMENT_DELETE, own, grants=[grant]).permit is True
    # Without the grant, an employee already reads its own doc via the
    # built-in rule -- use an action with no built-in EMPLOYEE rule at all
    # so this assertion isolates the selector, not the builtin fallback.
    assert authorize(subject, Action.PERMISSION_GRANT, other, grants=[grant]).permit is False


def test_id_selector_only_matches_that_one_resource():
    subject = _subject(UserRole.EMPLOYEE, user_id="u-1")
    target = _document(owner_id="u-2", doc_id="doc-target")
    other = _document(owner_id="u-2", doc_id="doc-other")
    grant = _grant(resource_selector={"id": "doc-target"})
    assert authorize(subject, Action.DOCUMENT_DELETE, target, grants=[grant]).permit is True
    assert authorize(subject, Action.DOCUMENT_DELETE, other, grants=[grant]).permit is False


def test_wildcard_action_grant_matches_any_action():
    subject = _subject(UserRole.EMPLOYEE, user_id="u-1")
    resource = _document(owner_id="u-2")
    grant = _grant(action="*")
    decision = authorize(subject, Action.DOCUMENT_DELETE, resource, grants=[grant])
    assert decision.permit is True


def test_time_boxed_grant_marks_the_decision_not_cacheable():
    subject = _subject(UserRole.EMPLOYEE, user_id="u-1")
    resource = _document(owner_id="u-2")
    grant = _grant(time_boxed=True)
    decision = authorize(subject, Action.DOCUMENT_DELETE, resource, grants=[grant])
    assert decision.permit is True
    assert decision.cacheable is False


def test_builtin_rule_decision_is_cacheable_by_default():
    decision = authorize(_subject(UserRole.ADMIN), Action.DOCUMENT_READ, _document())
    assert decision.cacheable is True


def test_grant_for_a_different_action_does_not_apply():
    subject = _subject(UserRole.EMPLOYEE, user_id="u-1")
    resource = _document(owner_id="u-2")
    grant = _grant(action=Action.DRAFT_SEND)
    decision = authorize(subject, Action.DOCUMENT_DELETE, resource, grants=[grant])
    assert decision.permit is False


def test_grant_for_a_different_resource_type_does_not_apply():
    subject = _subject(UserRole.EMPLOYEE, user_id="u-1")
    resource = _document(owner_id="u-2")
    grant = _grant(resource_type="draft", resource_selector={"any": True})
    decision = authorize(subject, Action.DOCUMENT_DELETE, resource, grants=[grant])
    assert decision.permit is False
