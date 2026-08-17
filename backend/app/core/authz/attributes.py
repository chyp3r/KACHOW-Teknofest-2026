"""Attribute types the PDP reasons over: Subject, Resource, Environment, Action.

Deliberately thin. ``Subject``/``Resource`` do not carry confidentiality
clearance -- that stays ``app.core.permissions.role_checker``'s own,
downstream concern (see ``engine.py``'s module docstring for why the two
must not be folded together).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.core.enums.user_role import UserRole


@dataclass(frozen=True)
class Subject:
    """The authenticated caller a decision is being made about.

    Attributes:
        user_id: The caller's ``UserModel.id``.
        role: The caller's ``UserRole``.
        company_id: The caller's tenant, or ``None`` for ``UserRole.ROOT``
            (see ``UserModel.company_id``'s docstring).
    """

    user_id: str
    role: UserRole
    company_id: Optional[str]


@dataclass(frozen=True)
class Resource:
    """The thing an action is being attempted against.

    Attributes:
        type: A short tag ("document", "draft", "unit", "user", ...) --
            matched against ``permission_grants.resource_type`` and rule
            actions' namespace prefix, not enforced as a closed set here.
        id: The resource's primary key, when it already exists (absent for
            a not-yet-created resource, e.g. a ``unit:manage`` check ahead
            of ``POST /units``).
        company_id: The resource's tenant. ``None`` only for tenant-less
            resources (a ``companies`` row itself, or a ``system:*`` action
            with no single-company target).
        owner_id: The resource's owner, when ownership is a meaningful
            concept for this resource type (documents, drafts). ``None``
            otherwise.
    """

    type: str
    id: Optional[str] = None
    company_id: Optional[str] = None
    owner_id: Optional[str] = None


@dataclass(frozen=True)
class Environment:
    """Request-time context outside subject/resource/action.

    Attributes:
        now: Evaluation time, for ``permission_grants.valid_from``/
            ``valid_until`` windows. Defaults to the current UTC time so
            call sites that don't care about time-boxed grants can omit it.
        company_scope: The company a ``UserRole.ROOT`` subject has
            explicitly switched into (``X-Company-Scope`` header), if any.
            Ignored for every other role.
    """

    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    company_scope: Optional[str] = None


class Action:
    """Namespaced action identifiers, ``"<resource_type>:<verb>"``.

    A plain string namespace (not an enum) on purpose: ``permission_grants.
    action`` is a free-text DB column so a future resource type can be
    granted against without a code change, and the wildcard ``"*"`` (root's
    built-in rule, and a delegated grant's own escape hatch) has to be a
    valid value in the same space as every concrete action.
    """

    DOCUMENT_READ = "document:read"
    DOCUMENT_UPDATE = "document:update"
    DOCUMENT_DELETE = "document:delete"
    DRAFT_READ = "draft:read"
    DRAFT_DELETE = "draft:delete"
    DRAFT_SEND = "draft:send"
    #: Gates `ArtifactTransferService.execute` for *either* artifact kind
    #: (draft or document) -- one action, not `draft:transfer`/`document:
    #: transfer` split, since the decision itself ("may this subject move
    #: this artifact to someone else") doesn't depend on which table the
    #: artifact lives in. `DRAFT_SEND` is kept as its own, older action
    #: (still gates nothing new -- `DraftShareService.send` now delegates
    #: to this one instead) rather than merged into it, since removing an
    #: `Action` value already referenced by existing `permission_grants`
    #: rows would silently invalidate them.
    ARTIFACT_TRANSFER = "artifact:transfer"
    UNIT_MANAGE = "unit:manage"
    USER_MANAGE = "user:manage"
    PERMISSION_GRANT = "permission:grant"
    PERMISSION_REVOKE = "permission:revoke"

    ALL: tuple[str, ...] = (
        DOCUMENT_READ,
        DOCUMENT_UPDATE,
        DOCUMENT_DELETE,
        DRAFT_READ,
        DRAFT_DELETE,
        DRAFT_SEND,
        ARTIFACT_TRANSFER,
        UNIT_MANAGE,
        USER_MANAGE,
        PERMISSION_GRANT,
        PERMISSION_REVOKE,
    )
