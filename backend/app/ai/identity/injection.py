"""Renders a ``CompanyProfile`` into prompt text.

Two separate render targets, on purpose:

- :func:`format_agent_identity` -- the assistant's self-description, fed
  into ``assistant.md``'s ``{{agent_identity}}`` placeholder via
  ``app.ai.prompts.manager``. When ``profile.is_empty``, returns the exact
  sentence the template used to hard-code, so a company with nothing
  configured sees byte-identical behaviour to before this feature existed.
- :func:`format_identity_brief_section` -- a brief section for
  ``app.ai.workflows.draft_graph._build_brief``, mirroring
  ``_format_style_examples``'s "return '' rather than an empty header"
  rule. Unlike ``CompanyAdapter``'s style block, this section's content is
  a fact (the company's own name/letterhead), so ``draft_verifier.
  verify_draft`` must be told to trust it via its ``trusted_facts``
  parameter -- otherwise the writer's own institutional header would be
  flagged as an unsupported claim on every single draft.
"""

from app.ai.identity.company_profile import CompanyProfile

#: The identity the assistant presents when no company profile is
#: configured -- kept as the literal sentence ``assistant.md`` used to
#: hard-code, so an unconfigured company's prompt renders byte-for-byte the
#: same as before ``{{agent_identity}}`` existed.
_DEFAULT_SYSTEM_NAME = "KACHOW Evrak Karar Destek Sistemi (EKDS)"
_DEFAULT_AGENT_NAME = "KACHOW Karar Destek Sistemi Asistanı"


def format_agent_identity(profile: CompanyProfile) -> str:
    """Render the assistant's self-description sentence(s).

    Args:
        profile: The requesting company's current profile (see
            ``app.domains.companies.provider.get_company_profile``).

    Returns:
        The identity text to substitute into ``assistant.md``'s
        ``{{agent_identity}}`` placeholder. Never empty.
    """
    if profile.is_empty:
        return (
            f"Sen, **{_DEFAULT_SYSTEM_NAME}** için özel olarak tasarlanmış "
            "kurumsal asistansın. Kullanıcıyla sohbet eder, sistemin "
            "yetenekleri hakkındaki sorularını yanıtlar ve gerektiğinde "
            "yüklenmiş bir belgenin içeriğine veya mevzuata dair sorularını, "
            "sana tanımlı araçları (tools) kullanarak yanıtlarsın."
        )

    system_name = profile.display_name or profile.short_name or _DEFAULT_SYSTEM_NAME
    agent_name = profile.agent_name or _DEFAULT_AGENT_NAME
    return (
        f'Sen, **{system_name}** için özel olarak tasarlanmış, "{agent_name}" '
        "adını kullanan kurumsal asistansın. Kullanıcıyla sohbet eder, "
        "sistemin yetenekleri hakkındaki sorularını yanıtlar ve gerektiğinde "
        "yüklenmiş bir belgenin içeriğine veya mevzuata dair sorularını, sana "
        "tanımlı araçları (tools) kullanarak yanıtlarsın."
    )


def format_identity_brief_section(profile: CompanyProfile) -> str:
    """Render the draft brief's "KURUM KİMLİĞİ" section.

    Args:
        profile: The requesting company's current profile.

    Returns:
        "" when the profile is empty -- same convention as
        ``app.ai.adapters.injection.format_adapter_block``: a header with
        nothing under it reads as a missing-context signal, not as "this
        company has no profile configured yet".
    """
    if profile.is_empty:
        return ""

    lines: list[str] = []
    if profile.display_name:
        lines.append(f"   - Kurum Adı: {profile.display_name}")
    if profile.letterhead:
        lines.append(f"   - Antet: {profile.letterhead}")
    if profile.default_signer_title:
        lines.append(f"   - Varsayılan İmza Unvanı: {profile.default_signer_title}")

    body = "\n".join(lines)
    return (
        "9. KURUM KİMLİĞİ (SİSTEM TARAFINDAN SAĞLANDI -- KAYNAK BİLGİ SAYILIR):\n"
        f"{body}\n"
        '   → Yazım Briefi\'nde (bölüm 8) bir "gönderen" belirtilmişse o esastır -- '
        "bu bölüm yalnızca o slot boş kaldığında kullanılacak varsayılandır.\n"
    )
