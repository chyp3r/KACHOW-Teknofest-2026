"""Renders identity info (company or caller) into prompt text.

Three separate render targets, on purpose:

- :func:`format_agent_identity` -- the assistant's self-description, fed
  into ``assistant.md``'s ``{{agent_identity}}`` placeholder via
  ``app.ai.prompts.manager``. When ``profile.is_empty``, returns the exact
  sentence the template used to hard-code, so a company with nothing
  configured sees byte-identical behaviour to before this feature existed.
- :func:`format_user_address` -- the caller's own name, fed into
  ``assistant.md``'s ``{{user_display_name}}`` placeholder. Takes a plain
  string (``PlanningState.user_display_name``, the caller's ``username``),
  not a profile object -- there is no provider/caching layer here, the
  value is already sitting on the authenticated request.
- :func:`format_identity_brief_section` -- a brief section for
  ``app.ai.workflows.draft_graph._build_brief``, mirroring
  ``_format_style_examples``'s "return '' rather than an empty header"
  rule. Unlike ``CompanyAdapter``'s style block, this section's content is
  a fact (the company's own name/letterhead), so ``draft_verifier.
  verify_draft`` must be told to trust it via its ``trusted_facts``
  parameter -- otherwise the writer's own institutional header would be
  flagged as an unsupported claim on every single draft.

This section used to describe itself as a *fallback*, applied only when
the writing brief's own "gönderen" slot (``app.ai.workflows.writing_brief``,
section 8) came back unspecified. That was backwards: a real, admin-entered
identity is the most reliable signal for who is writing this letter that
exists anywhere in the pipeline -- more reliable than a guess derived from
the *incoming* document's own header fields, which is what an unspecified
"gönderen" slot fell back to before ``resolve_party_context`` existed (see
``app.ai.identity.parties``). ``_resolve_yazan_taraf`` now consults this
same profile *before* falling back to the document, so by the time this
section renders, section 8's own "gönderen" is normally already this
company's own identity -- this section is now the primary source, not a
fallback, and only an explicit contrary statement in the user's own message
(surfaced in section 8 as a ``user_text``-sourced slot) overrides it.
"""

from typing import Optional

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


def format_user_address(display_name: Optional[str]) -> str:
    """Render the assistant's addressing instruction for the current caller.

    Args:
        display_name: The authenticated caller's ``username`` (see
            ``PlanningState.user_display_name``), or ``None`` in the open
            demo/dev path or when it wasn't resolved.

    Returns:
        The text to substitute into ``assistant.md``'s
        ``{{user_display_name}}`` placeholder. Never empty -- a neutral
        instruction when no name is known, so the model doesn't invent one.
    """
    if not display_name:
        return "Kullanıcının adı bilinmiyor; nötr, kişiselleştirilmemiş bir dille hitap et."
    return (
        f'Kullanıcının adı **{display_name}**. Selamlarken veya doğrudan '
        f'hitap ederken bu adı kullan (örn. "Merhaba {display_name},").'
    )


def format_identity_brief_section(profile: CompanyProfile, section_number: int = 9) -> str:
    """Render the draft brief's "KURUM KİMLİĞİ" section.

    Args:
        profile: The requesting company's current profile.
        section_number: The brief's own numbering for this section (see
            ``app.ai.workflows.draft_graph._build_brief``) -- kept a
            parameter rather than hard-coded so the brief's section order
            can change without this module needing to know why.

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
    if profile.default_signer_name:
        lines.append(f"   - Varsayılan İmza Adı Soyadı: {profile.default_signer_name}")

    body = "\n".join(lines)
    return (
        f"{section_number}. KURUM KİMLİĞİ (SİSTEM TARAFINDAN SAĞLANDI -- KAYNAK BİLGİ "
        "SAYILIR VE ESASTIR):\n"
        f"{body}\n"
        "   → Bu, YAZAN TARAFIN (bizim, gönderen kurumun) kimliğidir -- antet ve imza "
        "bloğunda KULLANILACAK kimlik budur. Gelen evrakın kendi antet/imza bilgisiyle "
        "ASLA karıştırma; o karşı tarafa aittir (bkz. bölüm 3). Yazım Briefi'nde "
        "(bölüm 8) kullanıcının kendi metninden (\"... olarak\", \"... adına\") açıkça "
        "çıkarılmış, bu kimlikten FARKLI bir gönderen belirtilmişse yalnızca o zaman bu "
        "kimliğin yerine geçer.\n"
    )
