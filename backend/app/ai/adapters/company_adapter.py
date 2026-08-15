"""A company's runtime style adapter -- Faz C2, the RLHF layer's
instant-effect half (see [[app.ai.adapters.injection]] for how it reaches a
prompt, and #185's own framing).

Deliberately a plain, immutable dataclass with no I/O and no import of
``app.domains`` anywhere in this module: this codebase's AI Core never
imports the domains layer (see ``docs/architecture/backend.md``, "Backend
yalnızca AI Core'u çağırır" -- the dependency only ever points the other
way). The actual Redis/Postgres-backed reader/writer that produces one of
these lives in ``app.domains.companies.provider`` instead and is injected
into the draft/revise graphs as a plain async callable at construction
time, the exact same pattern ``app.domains.units.provider.
get_active_units_for_routing`` already established for the routing graph's
``units_provider``.
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional


@dataclass(frozen=True)
class CompanyAdapter:
    """One company's accumulated style preferences.

    Carries ONLY style and format, never facts -- enforced structurally,
    not just by convention: nothing in this class holds anything resembling
    a claim about the world (a fact, a name, a date), only preferences about
    *how* to write. ``preferred_examples`` is real generated text, so it is
    fed into the same ``ornek_sizintisi`` (example-leak) deterministic check
    ``style_examples`` already goes through (see ``draft_verifier.
    verify_draft``'s ``style_examples`` parameter) -- a company name or date
    that leaks out of a preferred example is caught exactly like one
    leaking out of a retrieved few-shot example, no separate check needed.

    Attributes:
        company_id: Which tenant this adapter belongs to.
        version: Bumped on every write (see ``app.domains.companies.
            provider.set_company_adapter``) -- lets a training run (Faz C3)
            or an admin's manual edit both be told apart in the audit trail
            and in ``GET .../adapter``'s response.
        style_rules: Short Turkish sentences describing a writing
            preference (e.g. "Kapanışta her zaman 'Arz ederim' kullan").
            Rendered as a bullet list, applied as guidance, never as a
            source of fact.
        preferred_examples: Full example texts the company has approved as
            representative of its preferred style. Same trust boundary as
            ``style_examples``: style reference only, subject to the same
            leak check.
        avoided_patterns: The mirror of ``style_rules`` -- short
            descriptions of a pattern this company's drafts should NOT use
            (e.g. "Edilgen çatı kullanma").
        trained_at: ISO-8601 timestamp of the last write, or None if this
            adapter has never been set (see :meth:`empty`).
        sample_count: How many feedback/training samples informed this
            version -- 0 for a hand-authored adapter (an admin typing rules
            directly, before Faz C3's automated mining exists). Purely
            informational, never used to gate whether the adapter applies.
    """

    company_id: str
    version: int = 0
    style_rules: tuple[str, ...] = field(default_factory=tuple)
    preferred_examples: tuple[str, ...] = field(default_factory=tuple)
    avoided_patterns: tuple[str, ...] = field(default_factory=tuple)
    trained_at: Optional[str] = None
    sample_count: int = 0

    @property
    def is_empty(self) -> bool:
        """True when there is nothing here worth injecting into a prompt."""
        return not (self.style_rules or self.preferred_examples or self.avoided_patterns)

    @classmethod
    def empty(cls, company_id: str) -> "CompanyAdapter":
        """The adapter a company with no configured preferences resolves to.

        Never ``None`` -- every caller (``writer_node``, ``rewrite_node``,
        ...) can unconditionally check ``.is_empty`` instead of also
        handling a missing adapter as a separate case.
        """
        return cls(company_id=company_id)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation -- what actually gets written into
        ``CompanyModel.settings`` and the Redis cache value.

        ``company_id`` is deliberately excluded: the settings blob lives
        *inside* that company's own row, re-stating its id there would be
        redundant data that could drift from the row's real id.
        """
        return {
            "version": self.version,
            "style_rules": list(self.style_rules),
            "preferred_examples": list(self.preferred_examples),
            "avoided_patterns": list(self.avoided_patterns),
            "trained_at": self.trained_at,
            "sample_count": self.sample_count,
        }

    @classmethod
    def from_dict(cls, company_id: str, value: Optional[dict[str, Any]]) -> "CompanyAdapter":
        """Reconstruct from a ``to_dict()``-shaped mapping (or ``None``,
        for a company that has never had one set)."""
        if not value:
            return cls.empty(company_id)
        return cls(
            company_id=company_id,
            version=int(value.get("version") or 0),
            style_rules=tuple(value.get("style_rules") or ()),
            preferred_examples=tuple(value.get("preferred_examples") or ()),
            avoided_patterns=tuple(value.get("avoided_patterns") or ()),
            trained_at=value.get("trained_at"),
            sample_count=int(value.get("sample_count") or 0),
        )


#: Async callable taking a ``company_id`` and returning that company's
#: current adapter (never raises, never returns None -- see
#: ``CompanyAdapter.empty``) -- injected into ``create_draft_graph``/
#: ``create_revise_graph`` the same way ``routing_graph.UnitsProvider`` is,
#: so this module (and every graph module) never imports ``app.domains``.
AdapterProvider = Callable[[str], Awaitable[CompanyAdapter]]
