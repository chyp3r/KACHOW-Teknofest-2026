"""Frozen built-in role/action rules -- the PDP's baseline, DB-independent layer.

Same pattern as ``app.ai.policy.schema``: a frozen, versionless-but-import
-time-validated Python structure rather than a YAML/JSON rule file. The
rules below only ever get more specific through ``permission_grants`` (see
``engine.py``); they are never edited per-deployment, so there is nothing a
config format would buy here that a frozen tuple doesn't already give for
free (typo safety, no parse path to drift from what's actually evaluated).

Mirrors the yetki matrisi (permission matrix) in the tenancy plan's ABAC
section: ROOT is unrestricted (its own tenant gate in ``engine.authorize``
is what actually limits it, not this table); ADMIN and MANAGER act
company-wide (``scope="any"``) on every resource type below; EMPLOYEE is
restricted to resources it owns (``scope="own"``). Company/unit-management
actions (``unit:manage``, ``user:manage``, ``permission:grant``/``revoke``)
have no EMPLOYEE rule at all -- see ``check_invariants`` for why an
apparently "missing" role is fine there but not for the resource actions.
"""

from dataclasses import dataclass

from app.core.enums.user_role import UserRole
from app.core.authz.attributes import Action


@dataclass(frozen=True)
class Rule:
    """One built-in grant: ``role`` may perform ``action`` within ``scope``.

    Attributes:
        role: The ``UserRole`` this rule applies to.
        action: An ``Action`` constant, or ``"*"`` (matches any action --
            used only for ``UserRole.ROOT``).
        scope: ``"any"`` -- permitted company-wide (the tenant gate in
            ``engine.authorize`` still applies, so this never crosses
            companies). ``"own"`` -- permitted only when
            ``resource.owner_id == subject.user_id``.
    """

    role: UserRole
    action: str
    scope: str


#: Resource-level actions every role that manages a company (ADMIN, MANAGER)
#: can reach company-wide; EMPLOYEE only reaches its own.
_OWNERSHIP_SCOPED_ACTIONS: tuple[str, ...] = (
    Action.DOCUMENT_READ,
    Action.DOCUMENT_UPDATE,
    Action.DOCUMENT_DELETE,
    Action.DRAFT_READ,
    Action.DRAFT_UPDATE,
    Action.DRAFT_DELETE,
    Action.DRAFT_SEND,
    Action.ARTIFACT_TRANSFER,
)

#: Management actions with no ownership concept -- company-wide or nothing.
_MANAGEMENT_ACTIONS: tuple[str, ...] = (
    Action.UNIT_MANAGE,
    Action.USER_MANAGE,
    Action.PERMISSION_GRANT,
    Action.PERMISSION_REVOKE,
)

BUILTIN_RULES: tuple[Rule, ...] = (
    Rule(role=UserRole.ROOT, action="*", scope="any"),
    *(Rule(role=UserRole.ADMIN, action=action, scope="any") for action in _OWNERSHIP_SCOPED_ACTIONS),
    *(Rule(role=UserRole.ADMIN, action=action, scope="any") for action in _MANAGEMENT_ACTIONS),
    *(Rule(role=UserRole.MANAGER, action=action, scope="any") for action in _OWNERSHIP_SCOPED_ACTIONS),
    *(Rule(role=UserRole.MANAGER, action=action, scope="any") for action in _MANAGEMENT_ACTIONS),
    *(Rule(role=UserRole.EMPLOYEE, action=action, scope="own") for action in _OWNERSHIP_SCOPED_ACTIONS),
)


def check_invariants() -> None:
    """Assert every non-ROOT role has at least one resource-scoped rule.

    Same invariant shape as ``app.ai.policy.schema.Policy.check_invariants``'
    ``role_clearance_map`` completeness check: an omitted role here is a bug
    (a role the engine cannot reason about at all), not a restrictive
    default -- ROOT is exempt since its single wildcard rule already covers
    everything.

    Raises:
        ValueError: If ADMIN, MANAGER or EMPLOYEE has zero rules.
    """
    roles_with_rules = {rule.role for rule in BUILTIN_RULES}
    missing = {UserRole.ADMIN, UserRole.MANAGER, UserRole.EMPLOYEE} - roles_with_rules
    if missing:
        raise ValueError(
            f"authz.rules.BUILTIN_RULES is missing entries for: {sorted(r.value for r in missing)}"
        )


check_invariants()
