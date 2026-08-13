"""The decision algorithm: ``authorize(subject, action, resource, env, grants) -> Decision``.

Pure and DB-independent by design -- exactly the property that made
``app.ai.policy.schema.Policy`` fully unit-testable without mocking
anything, which matters here even more: this repo's test suite is
overwhelmingly mock-based (see ``AGENTS.md``/``tests/conftest.py``), so a
decision function that needs a live session or a Redis connection to be
exercised would only ever be tested through the DB-backed wrapper
(``app.core.authz.service.AuthzService``), not on its own. ``grants`` is
passed in already resolved (``app.core.authz.repository.PermissionGrantRepository``
does the DB read; ``AuthzService`` is what actually calls this with
non-empty grants) so this module never imports SQLAlchemy or Redis.

Composition order with the rest of the security stack (unchanged from the
tenancy plan, restated here since this is where it is enforced):

    1. Tenant scope   -- this function's own step 0, plus the repository
                          layer's mandatory ``company_id`` filter (and, from
                          a future RLS phase, Postgres row security).
    2. ABAC decision  -- this function.
    3. Clearance      -- ``app.core.permissions.role_checker.assert_clearance``,
                          called separately by the router, *after* this
                          decision permits.
    4. Guardrails     -- ``app.ai.guardrails.output_gate`` /
                          ``app.ai.tools.document_tools``' deny-at-retrieval.

Clearance is deliberately not folded into step 2: ``app.ai.tools.
document_tools`` compares clearance directly and returns a refusal string to
the model (not an exception) from inside a compiled LangGraph node, and by
this repo's own layering rule ``app.ai.*`` never imports ``app.domains.*`` --
injecting a DB-backed PDP call there would violate it. Keeping clearance a
separate, always-applied gate also means a caller can never construct a
grant that bypasses it: ``authorize()`` permitting an action says nothing
about whether the subject may *read the content* of a resource above its
clearance ceiling.
"""

from dataclasses import dataclass
from typing import Optional, Sequence

from app.core.authz.attributes import Resource, Subject, Environment
from app.core.authz.rules import BUILTIN_RULES
from app.core.enums.user_role import UserRole


@dataclass(frozen=True)
class GrantView:
    """A single resolved, currently-active ``permission_grants`` row.

    Deliberately not the SQLAlchemy model itself -- keeps this module and
    ``engine.py`` free of any ORM/DB import. ``app.core.authz.repository``
    is the only place a ``PermissionGrantModel`` becomes one of these.

    Attributes:
        id: The grant's row id, echoed in ``Decision.matched_rule`` so a
            denied/permitted request's audit trail can point at exactly
            which grant decided it.
        subject_type: ``"user"`` or ``"role"`` -- ``"unit"`` is reserved for
            a future phase once ``unit_memberships`` exists, and never
            appears in a resolved ``GrantView`` today.
        subject_id: A ``users.id`` (subject_type="user") or a ``UserRole``
            value (subject_type="role").
        action: An ``Action`` constant, or ``"*"``.
        resource_type: A ``Resource.type`` value, or ``"*"``.
        resource_selector: ``{"any": True}`` (matches every resource of
            ``resource_type``), ``{"owner": "self"}`` (matches only when
            ``resource.owner_id == subject.user_id``), or ``{"id": "..."}``
            (matches only that one resource).
        effect: ``"permit"`` or ``"deny"``.
        priority: Higher wins among competing ``permit`` grants.
        time_boxed: True when the grant has a ``valid_from``/``valid_until``
            window (even if currently inside it) -- the repository already
            filtered to *currently active* rows, but a time-boxed grant's
            decision must never be cached past its own expiry, so this flag
            is what ``AuthzService`` checks to decide cacheability.
    """

    id: str
    subject_type: str
    subject_id: str
    action: str
    resource_type: str
    resource_selector: dict
    effect: str
    priority: int
    time_boxed: bool = False


@dataclass(frozen=True)
class Decision:
    """The outcome of one ``authorize()`` call.

    Attributes:
        permit: Whether the action is allowed.
        reason: Human-readable explanation, safe to surface in logs/audit
            trails (never includes secret material -- grants carry no
            secrets to begin with).
        matched_rule: The built-in rule (``"<role>:<action>"``) or
            ``GrantView.id`` that decided this, or ``None`` for the implicit
            deny (no rule or grant matched at all).
        cacheable: False for decisions ``AuthzService`` must never persist
            in the Redis decision cache -- a tenant-boundary deny (cheap to
            recompute, and caching it buys nothing) or a decision that
            depended on a time-boxed grant (caching it past the grant's own
            expiry would keep permitting after the grant lapsed).
    """

    permit: bool
    reason: str
    matched_rule: Optional[str] = None
    cacheable: bool = True


def role_permitted(role: UserRole, allowed_roles: Sequence[UserRole]) -> bool:
    """Whether ``role`` is one of ``allowed_roles``.

    Extracted out of ``app.api.dependency.require_roles`` so that dependency
    is a thin shim over this module (per the tenancy plan's ABAC design)
    rather than re-implementing the same membership check inline -- with
    identical behaviour, so no existing route or test making that call
    changes. Not itself a PDP decision (no tenant/ownership reasoning): it
    exists purely so "is this role allowed at all" has one place to live
    next to the rest of the engine.
    """
    return role in allowed_roles


def _resource_selector_matches(selector: dict, subject: Subject, resource: Optional[Resource]) -> bool:
    """Whether a grant's ``resource_selector`` matches ``resource`` for ``subject``."""
    if selector.get("any") is True:
        return True
    if resource is None:
        return False
    owner_selector = selector.get("owner")
    if owner_selector == "self":
        return resource.owner_id == subject.user_id
    id_selector = selector.get("id")
    if id_selector is not None:
        return resource.id == id_selector
    return False


def _grant_matches(grant: GrantView, subject: Subject, action: str, resource: Optional[Resource]) -> bool:
    """Whether ``grant`` applies to this ``(subject, action, resource)`` triple.

    Subject matching happened one layer up, in
    ``app.core.authz.repository.PermissionGrantRepository.list_active_for_subject``
    (it is a WHERE clause there, not repeated here) -- this only re-checks
    action and resource, which is all a pre-resolved ``GrantView`` still
    needs deciding.
    """
    action_matches = grant.action == action or grant.action == "*"
    if not action_matches:
        return False
    if resource is not None:
        type_matches = grant.resource_type == resource.type or grant.resource_type == "*"
        if not type_matches:
            return False
    return _resource_selector_matches(grant.resource_selector, subject, resource)


def authorize(
    subject: Subject,
    action: str,
    resource: Optional[Resource],
    env: Optional[Environment] = None,
    grants: Sequence[GrantView] = (),
) -> Decision:
    """Decide whether ``subject`` may perform ``action`` on ``resource``.

    Algorithm (see this module's own docstring for how this composes with
    clearance/guardrails downstream):

        0. Tenant gate: a non-ROOT subject touching a resource outside its
           own company is denied outright, before any rule or grant is
           consulted. A ROOT subject is only permitted through when it has
           explicitly scoped into that company (``env.company_scope``) --
           an un-scoped ROOT reading company resources is denied here too
           (root's system-wide read paths use a dedicated ``system:*``
           action with ``resource=None``, which skips this gate entirely).
        1. Any matching ``deny`` grant wins outright.
        2. Among matching ``permit`` grants, the highest ``priority`` wins.
        3. Otherwise, the built-in role rules (``rules.BUILTIN_RULES``)
           decide.
        4. No rule or grant matched: implicit deny.

    Args:
        subject: The caller.
        action: An ``Action`` constant.
        resource: The target, or ``None`` for a resource-less/creation-time
            check (e.g. ``unit:manage`` ahead of ``POST /units``, where
            there is no unit yet to attach a ``company_id`` to -- the
            caller's own company is implicitly the scope, so the tenant
            gate has nothing to check and is skipped).
        env: Request-time context. Defaults to "now, no root scope switch".
        grants: Pre-resolved, currently-active grants for this subject and
            action (see ``GrantView``). Empty by default -- callers that
            only need the tenant gate + built-in rules (no DB round trip)
            simply omit this.

    Returns:
        The decision.
    """
    if env is None:
        env = Environment()

    if resource is not None and resource.company_id is not None:
        if subject.role == UserRole.ROOT:
            if env.company_scope != resource.company_id:
                return Decision(
                    permit=False,
                    reason="root için şirket kapsamı (X-Company-Scope) ayarlanmamış",
                    cacheable=False,
                )
        elif subject.company_id != resource.company_id:
            return Decision(permit=False, reason="kaynak farklı bir şirkete ait", cacheable=False)

    deny_grants = [g for g in grants if g.effect == "deny" and _grant_matches(g, subject, action, resource)]
    if deny_grants:
        best = max(deny_grants, key=lambda g: g.priority)
        return Decision(
            permit=False,
            reason=f"açık red yetkisi: {best.id}",
            matched_rule=best.id,
            cacheable=not best.time_boxed,
        )

    permit_grants = [
        g for g in grants if g.effect == "permit" and _grant_matches(g, subject, action, resource)
    ]
    if permit_grants:
        best = max(permit_grants, key=lambda g: g.priority)
        return Decision(
            permit=True,
            reason=f"açık izin yetkisi: {best.id}",
            matched_rule=best.id,
            cacheable=not best.time_boxed,
        )

    for rule in BUILTIN_RULES:
        if rule.role != subject.role:
            continue
        if rule.action != action and rule.action != "*":
            continue
        if rule.scope == "any":
            return Decision(permit=True, reason="yerleşik kural (şirket geneli)", matched_rule=f"{rule.role}:{rule.action}")
        if rule.scope == "own" and resource is not None and resource.owner_id == subject.user_id:
            return Decision(permit=True, reason="yerleşik kural (sahiplik)", matched_rule=f"{rule.role}:{rule.action}")

    return Decision(permit=False, reason="eşleşen kural veya yetki yok (örtük red)")
