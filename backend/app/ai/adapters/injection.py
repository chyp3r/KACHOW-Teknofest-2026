"""Renders a ``CompanyAdapter`` into a prompt block.

Mirrors ``app.ai.workflows.draft_graph._format_style_examples`` on purpose
-- same "return '' rather than an empty header" rule (a header with nothing
under it reads to the model as a missing-context signal, not as "nothing
this time"), same "style/format only, never a source of fact" boundary
language, same real-example leak-check story. That function was already the
established, working pattern for "extra per-turn context that must never
be mistaken for the brief"; this reuses it rather than inventing a second
convention.
"""

from app.ai.adapters.company_adapter import CompanyAdapter
from app.ai.adapters.company_rules import CompanyRuleSet

#: Prefixed onto the whole block so a reader (human or model) sees at a
#: glance which company's preferences these are, without needing to cross-
#: reference the brief.
_BOUNDARY_NOTE = (
    "Bu bölümdeki hiçbir kural veya örnek, brief'te bulunmayan bir kurum adı, "
    "kişi, tarih, sayı veya mevzuat maddesi eklemek için gerekçe olamaz -- "
    "yalnızca dil, ton ve biçim tercihi bildirir."
)


def format_adapter_block(adapter: CompanyAdapter) -> str:
    """Render a company's style adapter as an appended prompt section.

    Args:
        adapter: The company's current adapter (see
            ``app.domains.companies.provider.get_company_adapter``).

    Returns:
        "" when the adapter is empty -- exactly ``_format_style_examples``'s
        own rule, and for the same reason: an "adapter kuralları" header
        with nothing under it would read as a signal, not as "this company
        has none configured yet".
    """
    if adapter.is_empty:
        return ""

    sections: list[str] = []

    if adapter.style_rules:
        rules = "\n".join(f"- {rule}" for rule in adapter.style_rules)
        sections.append(f"**Uygulanacak kurallar:**\n{rules}")

    if adapter.avoided_patterns:
        avoided = "\n".join(f"- {pattern}" for pattern in adapter.avoided_patterns)
        sections.append(f"**Kaçınılacak kalıplar:**\n{avoided}")

    if adapter.preferred_examples:
        examples = "\n\n".join(
            f"<ornek>\n{text}\n</ornek>" for text in adapter.preferred_examples
        )
        sections.append(
            "**Tercih edilen üslup örnekleri** (bilgi kaynağı DEĞİLDİR, yalnızca bu "
            "şirketin tercih ettiği üslubu göstermek içindir; içlerindeki hiçbir kurum, "
            f"kişi, tarih veya sayıyı taslağa taşıma):\n\n{examples}"
        )

    body = "\n\n".join(sections)
    return (
        "\n\n### BU ŞİRKETE ÖZGÜ YAZIM TERCİHLERİ:\n"
        f"{body}\n\n"
        f"{_BOUNDARY_NOTE}"
    )


def format_rules_block(ruleset: CompanyRuleSet) -> str:
    """Render a company's mandatory drafting rules as a prompt section.

    Args:
        ruleset: The company's current rule set (see
            ``app.domains.companies.provider.get_company_rules``).

    Returns:
        "" when the rule set is empty -- same convention as
        ``format_adapter_block``: a header with nothing under it reads as a
        missing-context signal, not as "this company has no rules configured
        yet".
    """
    if ruleset.is_empty:
        return ""

    mandatory = [rule for rule in ruleset.enabled_rules if rule.severity == "zorunlu"]
    recommended = [rule for rule in ruleset.enabled_rules if rule.severity != "zorunlu"]

    sections: list[str] = []
    if mandatory:
        lines = "\n".join(f"[{rule.id}] {rule.text}" for rule in mandatory)
        sections.append(f"**Zorunlu:**\n{lines}")
    if recommended:
        lines = "\n".join(f"[{rule.id}] {rule.text}" for rule in recommended)
        sections.append(f"**Önerilen (mümkünse uy):**\n{lines}")

    body = "\n\n".join(sections)
    return (
        "\n\n### ŞİRKETE ÖZGÜ ZORUNLU KURALLAR (UYULMASI ZORUNLUDUR):\n"
        f"{body}\n\n"
        f"{_BOUNDARY_NOTE}"
    )
