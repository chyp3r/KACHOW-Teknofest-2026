"""Kimlik bilgisini (şirket veya arayan) prompt metnine render eder.

Bilinçli olarak üç ayrı render hedefi:

- :func:`format_agent_identity` -- asistanın kendini tanıtması,
  ``app.ai.prompts.manager`` aracılığıyla ``assistant.md``'nin
  ``{{agent_identity}}`` yer tutucusuna beslenir. ``profile.is_empty``
  olduğunda, şablonun daha önce sabit kodladığı tam cümleyi döndürür;
  böylece hiçbir şey yapılandırılmamış bir şirket, bu özellik var olmadan
  önceki davranışla bayt bayt aynı davranışı görür.
- :func:`format_user_address` -- arayanın kendi adı,
  ``assistant.md``'nin ``{{user_display_name}}`` yer tutucusuna beslenir.
  Bir profil nesnesi değil, düz bir string alır (``PlanningState.
  user_display_name``, arayanın ``username``'i) -- burada bir
  sağlayıcı/önbellekleme katmanı yoktur, değer zaten kimliği doğrulanmış
  isteğin üzerinde durur.
- :func:`format_identity_brief_section` --
  ``app.ai.workflows.draft_graph._build_brief`` için bir brief bölümü,
  ``_format_style_examples``'ın "boş bir başlık yerine '' döndür" kuralını
  yansıtır. ``CompanyAdapter``'ın stil bloğunun aksine, bu bölümün içeriği
  bir gerçektir (şirketin kendi adı/anteti), bu yüzden
  ``draft_verifier.verify_draft``'a bunun ``trusted_facts`` parametresi
  aracılığıyla buna güvenmesi söylenmelidir -- aksi halde yazarın kendi
  kurumsal başlığı her taslakta desteklenmeyen bir iddia olarak
  işaretlenirdi.

Bu bölüm eskiden kendisini yalnızca yazım briefinin kendi "gönderen" alanı
(``app.ai.workflows.writing_brief``, bölüm 8) belirtilmemiş geldiğinde
uygulanan bir *yedek* olarak tanımlıyordu. Bu tersti: gerçek, yönetici
tarafından girilmiş bir kimlik, bu mektubu kimin yazdığı konusunda pipeline'ın
herhangi bir yerinde var olan en güvenilir sinyaldir -- ``resolve_party_context``
var olmadan önce belirtilmemiş bir "gönderen" alanının yedeklendiği,
*gelen* belgenin kendi başlık alanlarından türetilen bir tahminden daha
güvenilirdir (bkz. ``app.ai.identity.parties``). ``_resolve_yazan_taraf``
artık belgeye yedeklenmeden *önce* bu aynı profile başvurur, bu yüzden bu
bölüm render edildiğinde bölüm 8'in kendi "gönderen"i normalde zaten bu
şirketin kendi kimliğidir -- bu bölüm artık bir yedek değil birincil
kaynaktır ve yalnızca kullanıcının kendi mesajındaki açık bir aykırı ifade
(bölüm 8'de ``user_text`` kaynaklı bir alan olarak ortaya çıkar) onun
üzerine yazar.
"""

from typing import Optional

from app.ai.identity.company_profile import CompanyProfile

#: Hiçbir şirket profili yapılandırılmadığında asistanın sunduğu kimlik --
#: ``assistant.md``'nin sabit kodladığı cümle olarak korunur; böylece
#: yapılandırılmamış bir şirketin promptu, ``{{agent_identity}}`` var olmadan
#: önceki haliyle bayt bayt aynı render edilir.
_DEFAULT_SYSTEM_NAME = "KACHOW Evrak Karar Destek Sistemi (EKDS)"
_DEFAULT_AGENT_NAME = "KACHOW Karar Destek Sistemi Asistanı"


def format_agent_identity(profile: CompanyProfile) -> str:
    """Asistanın kendini tanıtma cümlesini/cümlelerini render eder.

    Args:
        profile: İstek yapan şirketin güncel profili (bkz.
            ``app.domains.companies.provider.get_company_profile``).

    Returns:
        ``assistant.md``'nin ``{{agent_identity}}`` yer tutucusunun yerine
        geçecek kimlik metni. Asla boş değildir.
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
    """Asistanın güncel arayana hitap etme talimatını render eder.

    Args:
        display_name: Kimliği doğrulanmış arayanın ``username``'i (bkz.
            ``PlanningState.user_display_name``), veya açık demo/dev
            yolunda ya da çözümlenmediğinde ``None``.

    Returns:
        ``assistant.md``'nin ``{{user_display_name}}`` yer tutucusunun
        yerine geçecek metin. Asla boş değildir -- hiçbir ad bilinmediğinde
        modelin bir ad uydurmaması için nötr bir talimat.
    """
    if not display_name:
        return "Kullanıcının adı bilinmiyor; nötr, kişiselleştirilmemiş bir dille hitap et."
    return (
        f'Kullanıcının adı **{display_name}**. Selamlarken veya doğrudan '
        f'hitap ederken bu adı kullan (örn. "Merhaba {display_name},").'
    )


def format_identity_brief_section(profile: CompanyProfile, section_number: int = 9) -> str:
    """Taslak briefinin "KURUM KİMLİĞİ" bölümünü render eder.

    Args:
        profile: İstek yapan şirketin güncel profili.
        section_number: Bu bölüm için briefin kendi numaralandırması (bkz.
            ``app.ai.workflows.draft_graph._build_brief``) -- bu modülün
            briefin bölüm sırasının neden değiştiğini bilmesine gerek
            kalmadan değişebilmesi için sabit kodlanmak yerine bir
            parametre olarak tutulur.

    Returns:
        Profil boşsa "" -- ``app.ai.adapters.injection.format_adapter_block``
        ile aynı kural: altında hiçbir şey olmayan bir başlık, "bu şirketin
        henüz yapılandırılmış bir profili yok" değil, eksik bağlam sinyali
        olarak okunur.
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
