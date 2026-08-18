"""A company's identity -- who the agent says it is, and whose letterhead a
draft's own header/signature block resolves to when the writing brief leaves
that slot unspecified.

Deliberately a separate structure from ``app.ai.adapters.company_adapter.
CompanyAdapter``, not a few more fields bolted onto it: ``CompanyAdapter``'s
whole contract is "never a source of fact, only a style preference" (see its
own docstring); a company's real name, its letterhead and its default
signer title are facts, not style. Mixing the two would mean either
weakening that contract or teaching every adapter consumer to split fields
back apart by hand. Same "AI Core never imports ``app.domains``" rule as
``company_adapter.py`` applies here -- the reader/writer lives in
``app.domains.companies.provider`` instead and is injected into the
assistant/draft/revise graphs as a plain async callable at construction
time, the same ``adapter_provider``/``units_provider`` pattern.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


@dataclass(frozen=True)
class CompanyProfile:
    """One company's identity, as far as the AI layer needs to know it.

    Attributes:
        company_id: Which tenant this profile belongs to.
        version: Bumped on every write (see ``app.domains.companies.
            provider.set_company_profile``) -- same audit-trail purpose as
            ``CompanyAdapter.version``.
        display_name: The company's full legal/official name (e.g.
            "Ankara Büyükşehir Belediyesi Fen İşleri Dairesi Başkanlığı").
        short_name: A shorter form for casual reference, if different from
            ``display_name``.
        agent_name: What the assistant calls itself when introducing itself
            (e.g. "Fen İşleri Karar Destek Asistanı"). Empty means the
            system default identity applies (see ``format_agent_identity``).
        letterhead: The multi-line "T.C. ..." institutional header a draft's
            own header section should use when the writing brief doesn't
            already supply a sender identity.
        default_signer_title: The title (unvan) to fall back to in a
            draft's signature block when neither the writing brief nor the
            source document supplies one (e.g. "Daire Başkanı").
        updated_at: ISO-8601 timestamp of the last write, or None if this
            profile has never been set (see :meth:`empty`).
    """

    company_id: str
    version: int = 0
    display_name: str = ""
    short_name: str = ""
    agent_name: str = ""
    letterhead: str = ""
    default_signer_title: str = ""
    updated_at: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        """True when there is nothing here worth overriding the system
        default identity or a draft's default header/signature with."""
        return not (
            self.display_name
            or self.short_name
            or self.agent_name
            or self.letterhead
            or self.default_signer_title
        )

    @classmethod
    def empty(cls, company_id: str) -> "CompanyProfile":
        """The profile a company with nothing configured resolves to.

        Never ``None`` -- every caller can unconditionally check
        ``.is_empty`` instead of also handling a missing profile as a
        separate case, same convention as ``CompanyAdapter.empty``.
        """
        return cls(company_id=company_id)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation -- what actually gets written into
        ``CompanyModel.settings`` and the Redis cache value.

        ``company_id`` is deliberately excluded, same reasoning as
        ``CompanyAdapter.to_dict``: the settings blob already lives inside
        that company's own row.
        """
        return {
            "version": self.version,
            "display_name": self.display_name,
            "short_name": self.short_name,
            "agent_name": self.agent_name,
            "letterhead": self.letterhead,
            "default_signer_title": self.default_signer_title,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, company_id: str, value: Optional[dict[str, Any]]) -> "CompanyProfile":
        """Reconstruct from a ``to_dict()``-shaped mapping (or ``None``,
        for a company that has never had one set)."""
        if not value:
            return cls.empty(company_id)
        return cls(
            company_id=company_id,
            version=int(value.get("version") or 0),
            display_name=str(value.get("display_name") or ""),
            short_name=str(value.get("short_name") or ""),
            agent_name=str(value.get("agent_name") or ""),
            letterhead=str(value.get("letterhead") or ""),
            default_signer_title=str(value.get("default_signer_title") or ""),
            updated_at=value.get("updated_at"),
        )


#: Async callable taking a ``company_id`` and returning that company's
#: current profile (never raises, never returns None -- see
#: ``CompanyProfile.empty``) -- injected into the planning/draft/revise
#: graphs the same way ``AdapterProvider`` is.
ProfileProvider = Callable[[str], Awaitable[CompanyProfile]]
