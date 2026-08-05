"""Resolves an authenticated user's effective confidentiality clearance.

The role model (see ``UserRole``'s own docstring): ADMIN and MANAGER both
clear every level -- a company manager is trusted with full access, the same
as an admin. EMPLOYEE's ceiling is not fixed by role at all; it comes from
that individual's own ``UserModel.clearance_level``, since two employees can
legitimately need different access to the same document set.

This module was previously an empty package (only a stale ``.pyc`` on disk,
no source) -- the RBAC layer ``GuardrailPolicy.role_clearance_map`` and
``app.ai.guardrails.output_gate`` were designed around from the start, but
never actually wired to a real requester until now.
"""

from typing import Optional

from app.ai.policy import get_policy
from app.api.exceptions.authorization import AuthorizationException
from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.enums.user_role import UserRole
from app.domains.users.model.user_model import UserModel


def clearance_for(user: Optional[UserModel]) -> Optional[SensitivityLevel]:
    """Resolve a user's confidentiality ceiling.

    Args:
        user: The authenticated user, or ``None`` when unauthenticated (the
            open demo/dev path when ``settings.REQUIRE_AUTH`` is off).

    Returns:
        ``None`` when there is no authenticated user -- fail-secure, the
        same "unknown clearance clears nothing" default
        ``app.ai.guardrails.output_gate.evaluate_response`` already
        documents for its own ``requester_clearance`` parameter. Otherwise
        the resolved level: the policy ceiling for ADMIN/MANAGER, or the
        individual ``user.clearance_level`` for EMPLOYEE.
    """
    if user is None:
        return None

    policy = get_policy().guardrail
    try:
        role = UserRole(user.role)
    except ValueError:
        # An unrecognised role string (data corruption, or a role value
        # retired from the enum with rows never migrated) resolves to no
        # clearance rather than raising -- a guardrail lookup must never
        # itself become the reason a request 500s.
        return None

    if role in (UserRole.ADMIN, UserRole.MANAGER):
        return policy.role_clearance_map[role]

    try:
        return SensitivityLevel(user.clearance_level)
    except ValueError:
        return policy.role_clearance_map[UserRole.EMPLOYEE]


def bypasses_ownership(user: Optional[UserModel]) -> bool:
    """Whether ``user`` sees every document company-wide, not just its own.

    ADMIN/MANAGER already clear every confidentiality level (see
    :func:`clearance_for`) -- confirmed with the user that "company managers
    can access everything" extends to ownership too, not just clearance:
    the pre-existing per-owner isolation (``DocumentRepository.is_owned_by``,
    added for the unrelated "user B cannot reach user A's document" IDOR
    fix) previously applied uniformly regardless of role, so even an admin
    could not open a document they did not personally upload.

    Args:
        user: The authenticated user, or ``None``.

    Returns:
        True for ADMIN/MANAGER, False otherwise (including ``None``/an
        unrecognised role -- ownership isolation is the fail-secure default).
    """
    if user is None:
        return False
    try:
        role = UserRole(user.role)
    except ValueError:
        return False
    return role in (UserRole.ADMIN, UserRole.MANAGER)


def assert_clearance(user: Optional[UserModel], required_level: SensitivityLevel) -> None:
    """Raise unless ``user`` clears ``required_level``.

    Convenience wrapper for the router-level checks
    (``documents/router.py``, ``chat/router.py``) that need to turn an
    insufficient clearance into an HTTP 403 -- the tool layer
    (``document_tools.py``) and ``output_gate.py`` compare
    :func:`clearance_for`'s result directly instead, since a tool call
    returns a refusal string to the model rather than raising.

    Args:
        user: The authenticated user, or ``None``.
        required_level: The resource's confidentiality level.

    Raises:
        AuthorizationException: If ``user`` is ``None`` or does not clear
            ``required_level``.
    """
    clearance = clearance_for(user)
    if clearance is None or clearance < required_level:
        raise AuthorizationException(message="Bu içeriği görüntülemek için yeterli yetkiniz yok.")
