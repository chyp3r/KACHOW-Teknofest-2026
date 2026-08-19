"""A company's mandatory drafting rules -- admin-authored constraints the
writer/reviser must follow, and the judge must grade against.

Sibling of ``app.ai.adapters.company_adapter.CompanyAdapter`` (same package,
same injected-callable pattern, same "AI Core never imports app.domains"
rule -- the reader/writer lives in ``app.domains.companies.provider``), but
deliberately stored under its own settings key rather than folded into
``CompanyAdapter.style_rules``: ``CompanyAdapter`` is what an automated
training run (Faz C3) rewrites wholesale on every successful run (see
``set_company_adapter``'s "replaces the whole list" contract); a rule an
admin hand-authored here must survive that rewrite untouched, so it cannot
live in the same list.

Unlike ``CompanyAdapter``, a rule set is not asserted into a prompt on
trust alone -- ``app.ai.verification.llm_judge.judge_draft`` is handed the
same rendered block and asked whether the draft actually followed it (see
``DraftJudgeVerdict.company_rules_ok``), and a violation becomes a numbered
defect the existing verify/revise repair loop fixes automatically, the same
loop every other deterministic/judge finding already goes through.
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Optional


@dataclass(frozen=True)
class CompanyRule:
    """One admin-authored drafting rule.

    Attributes:
        id: A short, stable slug (e.g. "K3") assigned server-side when the
            rule is created -- referenced by the judge's own
            ``violated_rule_ids`` so a violation can be traced back to the
            exact rule without re-matching free text. Stable across edits to
            *other* rules in the same set (see
            ``app.domains.companies.provider.set_company_rules``), so a
            rule's id does not shift just because an admin reordered or
            removed a different one.
        text: The rule itself, in Turkish, as the admin wrote it (e.g.
            "Kapanışta her zaman 'Arz ederim' kullan.").
        severity: "zorunlu" (mandatory -- a violation blocks automatic
            approval the same way a critical judge finding does) or
            "onerilen" (recommended -- surfaced to the judge and the writer,
            but never forces human review on its own).
        enabled: False keeps a rule stored without applying it -- lets an
            admin temporarily disable one without losing its text/id.
    """

    id: str
    text: str
    severity: Literal["zorunlu", "onerilen"] = "zorunlu"
    enabled: bool = True


@dataclass(frozen=True)
class CompanyRuleSet:
    """One company's full set of mandatory/recommended drafting rules.

    Attributes:
        company_id: Which tenant this rule set belongs to.
        version: Bumped on every write (see
            ``app.domains.companies.provider.set_company_rules``).
        rules: The full rule list, in admin-authored order.
        updated_at: ISO-8601 timestamp of the last write, or None if this
            rule set has never been set (see :meth:`empty`).
    """

    company_id: str
    version: int = 0
    rules: tuple[CompanyRule, ...] = field(default_factory=tuple)
    updated_at: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        """True when there is nothing here worth injecting into a prompt or
        handing to the judge."""
        return not self.enabled_rules

    @property
    def enabled_rules(self) -> tuple[CompanyRule, ...]:
        """Only the rules currently switched on -- what every consumer
        (prompt injection, the judge) actually reads."""
        return tuple(rule for rule in self.rules if rule.enabled)

    @classmethod
    def empty(cls, company_id: str) -> "CompanyRuleSet":
        """The rule set a company with nothing configured resolves to.

        Never ``None`` -- every caller can unconditionally check
        ``.is_empty`` instead of also handling a missing rule set as a
        separate case, same convention as ``CompanyAdapter.empty``.
        """
        return cls(company_id=company_id)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation -- what actually gets written into
        ``CompanyModel.settings`` and the Redis cache value."""
        return {
            "version": self.version,
            "rules": [
                {
                    "id": rule.id,
                    "text": rule.text,
                    "severity": rule.severity,
                    "enabled": rule.enabled,
                }
                for rule in self.rules
            ],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, company_id: str, value: Optional[dict[str, Any]]) -> "CompanyRuleSet":
        """Reconstruct from a ``to_dict()``-shaped mapping (or ``None``,
        for a company that has never had one set)."""
        if not value:
            return cls.empty(company_id)
        rules = tuple(
            CompanyRule(
                id=str(item.get("id") or ""),
                text=str(item.get("text") or ""),
                severity=item.get("severity") or "zorunlu",
                enabled=bool(item.get("enabled", True)),
            )
            for item in (value.get("rules") or [])
            if item.get("text")
        )
        return cls(
            company_id=company_id,
            version=int(value.get("version") or 0),
            rules=rules,
            updated_at=value.get("updated_at"),
        )


#: Async callable taking a ``company_id`` and returning that company's
#: current rule set (never raises, never returns None -- see
#: ``CompanyRuleSet.empty``) -- injected into ``create_draft_graph``/
#: ``create_revise_graph`` the same way ``AdapterProvider`` is.
RulesProvider = Callable[[str], Awaitable[CompanyRuleSet]]
