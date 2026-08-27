"""Revizyon alt-grafiği: eski tek parça el yapımı ``run_revise`` fonksiyonu
yerine, draft_graph'ın kendi doğrulama/onarım döngüsünü ve gözlemlenebilirliğini
yansıtan gerçek bir LangGraph iş akışı.

``draft_graph``'tan (sınıflandır -> yaz -> doğrula -> refleksiyon döngüsü)
farklı olarak, revize asla yeniden sınıflandırma yapmaz -- doğrudan
``SessionFocus.active_draft`` üzerinde çalışır, yani kullanıcının zaten
gördüğü ve değiştirilmesini istediği metin üzerinde. Artık koşullu olarak
mevzuatı yeniden getirebilir (bkz. ``app.ai.revision.retrieval``) ve eski
tek-çağrılı uygulamanın sahip olmadığı, ``draft_graph.verify_node``'un her
zaman sahip olduğu aynı doğrulama garantilerini taşır (KVK kapısı, yedek
yazışma-türü kapısı, few-shot sızıntı tespiti, sınırlı bir onarım döngüsü)::

    START -> parse -> retrieve_context -> rewrite -+-> verify -+-> repair -> rewrite (sınırlı)
                                                     \\-> end     |-> needs_input -> END
                                                                  \\-> audit -> END

Bu grafiğin asla ihlal etmediği iki değişmez kural:

1. **Kullanıcı talimatının üstünlüğü.** Talimat, başka hiçbir şey
   çalışmadan önce ``rewrite`` içinde harfiyen uygulanır. Sonrasındaki hiçbir
   adım (``verify``, ``repair``, ``audit``) bunu geri alamaz veya
   yumuşatamaz -- ``repair`` yalnızca *deterministik/yargıç kusurlarını*
   (desteklenmeyen iddialar, eksik yapı) düzeltir, asla kullanıcının kendi
   talebini değil; ``audit`` ise yalnızca uyarılar ekler (bkz.
   ``app.ai.revision.conflict`` modülünün ``applied_anyway`` değişmez
   kuralı).
2. **Yapısal kayma-yok garantisi.** Talimat, konumlandırılmış aralıklara
   ayrıştığında, her yeniden yazım ``_merge`` ile geri eklenir -- model,
   dokunulmamış çevre metni asla yeniden üretmez, dolayısıyla sessizce
   kayamaz (bkz. ``app.ai.revision.instruction`` modül dokümantasyonu).
   Birden fazla aralık, *orijinal* taslağa karşı sağdan sola uygulanır;
   böylece daha soldaki (erken) uzaklıklar, daha sonraki (sağdaki) bir
   eklemeyle asla geçersiz kılınmaz. Bunun yerine taslağın *tamamını*
   yeniden üreten iki yol (hedef aralık bulunamadığında; herhangi bir
   onarım-döngüsü geçişinde) geri dönecek bir eklemeye sahip değildir, bu
   yüzden onun yerine deterministik bir yedek alırlar -- ``verify``, her
   geçişte turun gerçek başlangıç taslağına karşı
   ``app.ai.revision.elision.detect_content_loss``'u çalıştırır ve gerçek
   (zaten doldurulmuş) içeriği bir üç nokta/kısaltma ile atlayan, onu
   yeniden üretmek yerine silen bir modeli yakalar.
"""

import asyncio
import logging
from typing import Any, Optional, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.ai.agents.conflict_auditor import ConflictAuditorAgent
from app.ai.agents.judge import JudgeAgent
from app.ai.agents.reviser import ReviserAgent
from app.ai.guardrails.injection import assert_no_prompt_leak, assert_no_scaffold_echo
from app.ai.guardrails.pii import find_pii
from app.ai.llms.base import BaseLLMClient
from app.ai.policy import get_policy
from app.ai.adapters.company_adapter import AdapterProvider, CompanyAdapter
from app.ai.adapters.company_rules import CompanyRuleSet, RulesProvider
from app.ai.adapters.injection import format_adapter_block, format_rules_block
from app.ai.identity.company_profile import CompanyProfile, ProfileProvider
from app.ai.identity.injection import format_identity_brief_section
from app.ai.policy.budget import node_budget
from app.ai.reasoning_levels import ReasoningLevelPreset, get_reasoning_level_preset
from app.ai.revision.changelog import RevisionChangelog, build_changelog
from app.ai.revision.conflict import (
    ConflictReport,
    assess_conflicts_llm,
    detect_conflicts_deterministic,
    merge_conflicts,
)
from app.ai.revision.elision import detect_content_loss
from app.ai.revision.instruction import (
    EditDirective,
    RevisionInstruction,
    TargetSpan,
    _merge,
    locate_target,
    parse_revision_instruction,
    resolve_merge_target,
    spans_overlap,
)
from app.ai.revision.retrieval import maybe_extend_context
from app.ai.session.focus import DraftVersion
from app.ai.workflows.attempt_tracking import best_of, snapshot_attempt
from app.ai.verification import (
    InfoQuestion,
    VerificationReport,
    apply_answers,
    build_missing_info_request,
    check_filler_sentences,
    check_meta_commentary,
    check_person_consistency,
    check_signature_block,
    fill_date_placeholders,
    judge_draft,
    merge_verdicts,
    normalize_role_placeholders,
    normalize_unfilled_markers,
    resolve_placeholders_from_brief,
    verify_draft,
)
from app.ai.verification.draft_verifier import LEGISLATION_PATTERN
from app.ai.workflows.correspondence import format_correspondence_profile, is_strict_sub_genre
from app.ai.workflows.events import (
    emit_node_end,
    emit_node_error,
    emit_node_skipped,
    emit_node_start,
    emit_notice,
)
from app.ai.workflows.resilience import IO_RETRY
from app.ai.workflows.writing_brief import AUTO_ANSWER, format_writing_brief
from app.core.config import settings
from app.core.enums.step_status import StepStatus
from app.observability.ai_metrics import DRAFT_REVISIONS, DRAFT_SCORE

logger = logging.getLogger(__name__)


class ReviseState(TypedDict, total=False):
    """Revizyon iş akışı için LangGraph durumu."""

    #: Girdi, çağıran tarafından bir kez ayarlanır ve hiçbir düğüm tarafından
    #: değiştirilmez.
    active_draft: DraftVersion
    instructions: str
    reasoning_level: str
    #: Bu revizyonun hangi kiracı (tenant) için olduğu -- `rewrite_node`
    #: tarafından bu şirketin çalışma zamanı üslup adaptörünü çözmek için
    #: okunur (Faz C2, bkz. `create_revise_graph` üzerindeki
    #: `adapter_provider`). Yok/boş, yapılandırılmış bir adaptör yokmuş gibi
    #: davranır, asla hata vermez.
    company_id: str
    #: Bugünün tarihi (bkz. app.ai.workflows.dates.today_tr),
    #: `verify_node`'un tarih-yer tutucu yedek mekanizması tarafından okunur
    #: -- bir revizyon, yapısı gereği orijinal taslağın tarihini değiştirmeden
    #: korur (bkz. bu modülün kendi tarih-değiştirme-karşıtı kuralı), bu
    #: yüzden bu yalnızca bir yeniden yazım geçişi bir "Tarih:" yer tutucusunu
    #: yeniden getirdiğinde devreye girer.
    today: str
    #: Taslak turundaki eksik-bilgi gate'inde çözülmüş / "Sen karar ver" ile
    #: ertelenmiş yer tutucu cevapları (`InfoQuestion.key` -> değer veya
    #: `AUTO_ANSWER`). `verify_node`, hem bunları hem de yerleşmiş yazım
    #: briefini kullanarak zaten bilinen bir yer tutucuyu kullanıcıya tekrar
    #: sormaz. Çağıran tarafından bir kez ayarlanır (bkz. `run_revise`).
    resolved_placeholder_answers: dict[str, Any]
    #: `draft_graph.DraftState.instruction_haystack`'in revizyon karşılığı:
    #: bu turun talimatı + önceki kullanıcı turları + yerleşmiş brief cevapları.
    #: `verify_node`, `verify_draft`'a bunu `instructions=` olarak geçirir --
    #: böylece kullanıcının önceki bir turda verdiği bir isim/tarih/kurum
    #: revizyonda `dayanaksiz_iddia` olarak puanlanmaz. Boşsa `instructions`'a
    #: düşer.
    instruction_haystack: str

    #: `parse` tarafından ayarlanır.
    instruction: RevisionInstruction
    directives: list[EditDirective]
    targets: list[Optional[TargetSpan]]
    #: Çoklu-direktif yolunun kullanımının güvenli olup olmadığı (her
    #: direktif bir aralık bulduysa) -- False, tek-cümlecik bir talimatın
    #: aldığı aynı güvenli varsayılana, tek bir tüm/ilk-direktif yeniden
    #: yazımına düşer.
    multi_directive_ok: bool
    correspondence_type: str
    correspondence_type_source: str
    correspondence_sub_genre: str

    #: `retrieve_context` tarafından ayarlanır.
    context: str
    retrieval_meta: dict[str, Any]

    #: `rewrite` tarafından ayarlanır.
    draft: str
    previous_draft: str
    attempts: int
    error: str
    #: Çözümlenmiş adaptör (`CompanyAdapter.to_dict()`), `verify`'ın
    #: `preferred_examples`'ı `style_examples`'ın zaten geçtiği aynı
    #: `ornek_sizintisi` sızıntı kontrolüne katabilmesi için, ikinci kez
    #: yeniden çözümlemeden taşınır.
    company_adapter: dict[str, Any]
    #: Çözümlenmiş zorunlu kural seti (`CompanyRuleSet.to_dict()`),
    #: `verify`'ın yargıç için aynı kurallar bloğunu yeniden çözümlemeden
    #: render edebilmesi için taşınır. Yok/boş, yapılandırılmış kural yokmuş
    #: gibi davranır.
    company_rules: dict[str, Any]
    #: Çözümlenmiş kimlik profili (`CompanyProfile.to_dict()`), `rewrite`
    #: tarafından bir kez ayarlanır ve `verify`'ın aynı değerleri
    #: `verify_draft`'a `trusted_facts` olarak yeniden çözümlemeden
    #: geçirebilmesi için taşınır -- draft_graph.DraftState'in aynı isimli
    #: kendi alanını yansıtır. Yok/boş, yapılandırılmış profil yokmuş gibi
    #: davranır, asla hata vermez.
    company_profile: dict[str, Any]

    #: `verify` tarafından ayarlanır.
    confidence_score: float
    combined_score: float
    requires_human_approval: bool
    requires_revision: bool
    evaluation_notes: str
    verification: dict[str, Any]
    judge: dict[str, Any]
    judge_available: bool
    repair_items: list[dict[str, Any]]
    pii_findings: list[dict[str, Any]]
    missing_information: list[dict[str, Any]]
    attempt_history: list[dict[str, Any]]
    #: draft_graph.DraftState'in aynı isimli kendi alanına bakın.
    applied_rules: list[dict[str, Any]]
    #: draft_graph.DraftState'in aynı isimli kendi alanına bakın (C2/C3,
    #: bkz. app.ai.workflows.attempt_tracking).
    best_attempt: dict[str, Any]
    #: draft_graph.DraftState'in aynı isimli kendi alanına bakın (C3).
    restored_from_best_attempt: bool

    #: `audit` tarafından ayarlanır.
    conflicts: list[dict[str, Any]]
    conflict_notes: str
    changelog: dict[str, Any]

    status: str


def _coerce_fields(classification: dict[str, Any]) -> dict[str, Any]:
    fields = (classification or {}).get("fields", {})
    if hasattr(fields, "model_dump"):
        return fields.model_dump()
    return fields if isinstance(fields, dict) else {}


def _build_brief(
    active_draft: DraftVersion, context: str, profile: Optional[CompanyProfile] = None
) -> str:
    """Bu turdaki her reviser/yargıç çağrısına verilen dayanak brief'i.

    ``context``'ten (önbelleklenmeden) yeniden oluşturulur, böylece koşullu
    bir yeniden getirim (bkz. ``app.ai.revision.retrieval``) yalnızca ilk
    değil, sonraki her prompt'a da yansır.

    Args:
        active_draft: Revize edilen sürüm.
        context: (Muhtemelen yeniden getirilmiş) mevzuat bağlamı.
        profile: İsteği yapan şirketin kimlik profili (bkz.
            ``app.ai.identity.company_profile.CompanyProfile``), veya None.
            Boş değilse kendi bölümü olarak render edilir (bkz.
            ``format_identity_brief_section``) -- ``draft_graph._build_brief``'in
            aynı bölümünü yansıtır, çünkü eksik bir antet/imza bloğu eklemesi
            gereken bir onarım geçişi, orijinal taslağın sahip olduğu aynı
            sistem-doğrulanmış kimliği hak eder, "biz" kimiz konusunda
            sessizlik değil.
    """
    fields = _coerce_fields(active_draft.classification)
    # draft_graph._build_brief'in kendi 3/4. bölüm "KARŞI TARAFA AİTTİR"
    # çerçevesini yansıtır -- bu olmadan, eksik bir yapısal öğe (bir antet,
    # bir imza bloğu) eklemesi istenen bir onarım geçişinin hiçbir taraf
    # modeli rehberliği olmazdı, çünkü _coerce_fields burada tanımlanmış
    # ama şimdiye kadar hiç kullanılmamıştı.
    party_note = (
        "3. GELEN EVRAKIN KİMLİK BİLGİLERİ -- KARŞI TARAFA AİTTİR (bu alanlar bizim "
        "antet/imza bloğumuza veya gönderen kurum alanımıza ASLA yazılamaz, yalnızca "
        "gövde metninde bir olgu olarak anılabilir):\n"
        f"   - Gönderen Kurum: {fields.get('gonderen_kurum') or '(belirtilmemiş)'}\n"
        "   - Muhatap (evrakın KENDİ muhatabı -- bizim yanıtımızın muhatabı değil, "
        f"bu bilgi Yazım Briefi'ndedir): {fields.get('muhatap') or '(belirtilmemiş)'}\n"
        f"   - İmza Sahibi (KARŞI TARAF): {fields.get('imza_sahibi') or '(belirtilmemiş)'}\n"
    )
    rejection_note = ""
    if active_draft.status == "REJECTED" and active_draft.rejection_reason:
        # `active_draft` daha önce reddedilmiş bir sürüm olabilir (bkz.
        # app.ai.session.focus'un _ARCHIVE_ONLY_DRAFT_STATUSES üzerindeki kendi
        # dokümantasyonu -- bir ret artık active_draft'ı temizlemez, revize
        # edilebilir kalır). Neden reddedildiğini göstermek, bu revizyonu tüm
        # metni şüpheli saymak yerine tam o tek şikayete odaklı tutar; bu da
        # reviser'ın kendi "yalnızca kusur listesindeki maddeleri gider"
        # sözleşmesinin zaten ondan beklediği şeydir.
        rejection_note = (
            "6. Önceki Sürümün Reddedilme Gerekçesi (YALNIZCA bu noktaya "
            f"odaklan; metnin geri kalanındaki doğru bilgiyi koru): "
            f"{active_draft.rejection_reason}\n"
        )
    identity_section = (
        format_identity_brief_section(profile, section_number=7)
        if profile is not None
        else ""
    )
    return (
        f"1. Önceki Taslak Sürümü: {active_draft.version}\n"
        f"2. Doğrulanmış Sınıflandırma: {active_draft.classification.get('summary', 'Özet yok.')}\n"
        f"{party_note}"
        f'4. Doğrulanmış Mevzuat Bağlamı:\n"""\n'
        f"{context or 'İlgili mevzuat bağlamı bulunamadı.'}\n\"\"\"\n"
        f"5. Yazım Briefi:\n{format_writing_brief(active_draft.writing_brief)}\n"
        f"{rejection_note}"
        f"{identity_section}"
    )


def _format_style_examples_flat(texts: tuple[str, ...]) -> str:
    """Taslağın kendi üslup örneklerini bir prompt bloğu olarak render eder.

    Yalnızca düz metin (draft_graph'ın daha zengin, örnek-başına metadata
    bloğunun aksine) -- DraftVersion yalnızca metinleri taşır (bkz.
    ``app.ai.session.focus``), bu da ``verify_draft``'ın sızıntı tespitinin
    ihtiyaç duyduğu ve bir revizyonun çok daha kısa prompt'larının da
    ihtiyaç duyduğu tek şeydir.
    """
    if not texts:
        return ""
    blocks = "\n\n".join(f"<ornek>\n{text}\n</ornek>" for text in texts)
    return (
        "\n\n### ÜSLUP REFERANS ÖRNEKLERİ:\n"
        "Bunlar bilgi kaynağı DEĞİLDİR, yalnızca üslup göstermek içindir. "
        "İçlerindeki hiçbir kurum, kişi, tarih veya sayıyı taslağa taşıma.\n\n"
        f"{blocks}"
    )


def _build_directive_prompt(
    *, source_draft: str, target: Optional[TargetSpan], directive: EditDirective,
    brief: str, correspondence_type: str, sub_genre: str, style_examples: tuple[str, ...],
    adapter_block: str = "", rules_block: str = "",
) -> str:
    """Reviser'ın bir direktif için prompt'unu oluşturur; bir hedef aralık
    bulunmuşsa ona göre kapsamlandırılır."""
    if target is not None:
        scope_rule = (
            f"### DEĞİŞTİRİLECEK BÖLÜM (yalnızca bunu yeniden yaz):\n{target.text}\n\n"
            "### KURAL:\nYalnızca yukarıdaki bölümü, aşağıdaki kullanıcı talimatına göre "
            "yeniden yaz. Taslağın geri kalanından hiçbir şey isteme veya tekrarlama; "
            "SADECE bu bölümün yeni halini döndür."
        )
    else:
        scope_rule = (
            "### KURAL:\nAşağıdaki kullanıcı talimatına göre TÜM taslağı yeniden yaz. "
            "Ne brief'te NE DE bu talimatta geçen bir yeni bilgi (kişi, kurum, tarih, "
            "sayı, mevzuat maddesi) ekleme -- ama talimatın kendisi bir isim/kurum/tarih "
            "belirtiyorsa (ör. \"muhatabı X Valiliği yap\") bunu doğrudan uygula, "
            "kullanıcının kendi belirttiği bilgi kaynak sayılır. Talimatta belirtilmeyen "
            "hiçbir alanda üslup/kapsam/uzunluk dışında bir değişiklik yapma. "
            "Talimatla ilgisi olmayan her cümleyi, önceki taslaktaki haliyle, KELİMESİ "
            "KELİMESİNE ve EKSİKSİZ olarak yeniden üret. '...', '(değişmedi)', '[aynı]' "
            "gibi kısaltma veya atlama ifadeleriyle hiçbir bölümü özetleme. Talimatla "
            "ilgisi olmayan, zaten doldurulmuş bilgileri (isim, kurum, tarih vb.) asla "
            "silme -- ANCAK talimat açıkça bir cümlenin/kısmın silinmesini, çıkarılmasını "
            "veya kaldırılmasını istiyorsa, o kısmı gerçekten sil; bu durumda '[...]' "
            "yer tutucusu bırakma, ilgili kısmı taslaktan tamamen çıkar."
        )

    return (
        "### GÖREV:\n"
        "Kullanıcı, mevcut bir resmî yazı taslağında hedefli bir değişiklik istiyor.\n\n"
        f"### BRIEF BELGESİ:\n{brief}\n\n"
        f"### YAZIŞMA TÜRÜ PROFİLİ:\n{format_correspondence_profile(correspondence_type, sub_genre)}\n\n"
        f"### MEVCUT TASLAK:\n{source_draft}\n\n"
        f"{scope_rule}\n\n"
        f"### KULLANICI TALİMATI:\n{directive.raw}\n\n"
        "### ÇIKTI:\nYalnızca istenen bölümün (veya kural tüm taslağı kapsıyorsa taslağın "
        "tamamının) yeni metnini döndür. Meta yorum, markdown kod bloğu veya açıklama ekleme."
        f"{_format_style_examples_flat(style_examples)}"
        f"{rules_block}"
        f"{adapter_block}"
    )


def _build_repair_prompt(
    *, brief: str, correspondence_type: str, sub_genre: str, previous_draft: str,
    repair_items: list[dict[str, Any]], style_examples: tuple[str, ...],
    adapter_block: str = "", rules_block: str = "",
) -> str:
    """`verify` deterministik/yargıç kusurları bulduktan sonra, ikinci ve
    sonraki denemeler için onarım prompt'unu oluşturur.
    draft_graph._build_repair_prompt'u yansıtır."""
    numbered = "\n".join(
        f"{index}. [{item.get('kind')}] {item.get('detail')}"
        + (f" -> Öneri: {item.get('suggested_fix')}" if item.get("suggested_fix") else "")
        for index, item in enumerate(repair_items, start=1)
    )
    return (
        "### GÖREV:\n"
        "Aşağıdaki önceki taslağı, YALNIZCA numaralı kusur listesindeki maddeleri "
        "gidererek düzelt. Listede olmayan hiçbir cümleyi değiştirme.\n\n"
        f"### BRIEF BELGESİ:\n{brief}\n\n"
        f"### YAZIŞMA TÜRÜ PROFİLİ:\n{format_correspondence_profile(correspondence_type, sub_genre)}\n\n"
        f"### ÖNCEKİ TASLAK:\n{previous_draft}\n\n"
        f"### DÜZELTİLMESİ GEREKEN KUSURLAR:\n{numbered or '(kusur listesi boş)'}\n\n"
        "### KURAL:\n"
        "Yalnızca listelenen kusurları düzelt. Başka hiçbir cümleyi değiştirme. "
        "`[...]` yer tutucularını olduğu gibi bırak. Listelenmeyen her cümleyi önceki "
        "taslaktaki haliyle, KELİMESİ KELİMESİNE ve EKSİKSİZ olarak geri döndür -- "
        "'...', '(değişmedi)', '[aynı]' gibi kısaltma veya atlama ifadeleriyle hiçbir "
        "bölümü özetleme; zaten doldurulmuş bilgileri asla silme."
        f"{_format_style_examples_flat(style_examples)}"
        f"{rules_block}"
        f"{adapter_block}"
    )


def _resolve_free_text_client(
    preset, llm_client: BaseLLMClient, fast_llm_client: Optional[BaseLLMClient]
) -> BaseLLMClient:
    if preset.model_tier == "fast" and fast_llm_client is not None:
        return fast_llm_client
    return llm_client


def create_revise_graph(
    llm_client: BaseLLMClient,
    fast_llm_client: Optional[BaseLLMClient] = None,
    mevzuat_retriever: Optional[Any] = None,
    adapter_provider: Optional[AdapterProvider] = None,
    rules_provider: Optional[RulesProvider] = None,
    profile_provider: Optional[ProfileProvider] = None,
):
    """Revizyon iş akışını oluşturur ve derler.

    Args:
        llm_client: Reviser ve yargıç tarafından kullanılan kalite katmanı LLM.
        fast_llm_client: Hızlı akıl yürütme seviyesi, yargıç ve çelişki
            denetçisi için isteğe bağlı hızlı katman istemcisi. Belirtilmezse
            ``draft_graph`` ile aynı şekilde ``llm_client``'a düşer.
        mevzuat_retriever: Koşullu mevzuat yeniden getirimi için isteğe bağlı
            retriever (bkz. ``app.ai.revision.retrieval``). None her zaman
            yeniden getirimi atlar, özellik-öncesi davranışı birebir yeniden
            üretir.
        adapter_provider: Bir şirketin çalışma zamanı üslup adaptörünü
            çözümleyen isteğe bağlı async çağrılabilir (Faz C2, bkz.
            ``app.domains.companies.provider.get_company_adapter``) --
            ``draft_graph``'ın kendi ``adapter_provider``'ı ile aynı şekilde
            enjekte edilir. None, özellik-öncesi davranışı birebir yeniden
            üretir (asla adaptör bloğu yok).
        rules_provider: Bir şirketin zorunlu yazım kurallarını çözümleyen
            isteğe bağlı async çağrılabilir (bkz.
            ``app.domains.companies.provider.get_company_rules``) --
            ``draft_graph``'ın kendi ``rules_provider``'ı ile aynı şekilde
            enjekte edilir. None, özellik-öncesi davranışı birebir yeniden
            üretir (asla kurallar bloğu yok).
        profile_provider: Bir şirketin kimlik profilini çözümleyen isteğe
            bağlı async çağrılabilir (bkz.
            ``app.domains.companies.provider.get_company_profile``) --
            ``draft_graph``'ın kendi ``profile_provider``'ı ile aynı şekilde
            enjekte edilir (Faz 6). Bundan önce, bir revizyonun şirketin
            kimliğine hiç erişimi yoktu, bu yüzden eksik bir antet/imza
            bloğu eklemesi istenen bir onarım geçişine "biz" kimiz diyen
            hiçbir şey söylenmiyordu ve şirketin kendi adı/antetli kağıdı
            güvenilir bir olgu yerine her tek revizyonda dayanaksız bir
            iddia olarak puanlanıyordu. None, özellik-öncesi davranışı
            birebir yeniden üretir (asla kimlik bölümü, asla trusted_facts
            yok).

    Returns:
        Derlenmiş LangGraph iş akışı.
    """
    judge_agent = JudgeAgent(fast_llm_client or llm_client)
    conflict_agent = ConflictAuditorAgent(fast_llm_client or llm_client)

    async def _resolve_adapter(state: ReviseState) -> CompanyAdapter:
        """Bu şirketin çalışma zamanı üslup adaptörü, ya da hiçbir
        ``adapter_provider`` yapılandırılmamışsa, bu turun durumunda
        ``company_id`` yoksa ya da çözümlemenin kendisi başarısız olursa boş
        bir adaptör -- aynı gerekçe için ``draft_graph``'ın özdeş yardımcı
        fonksiyonuna bakın."""
        company_id = state.get("company_id") or ""
        if not company_id or adapter_provider is None:
            return CompanyAdapter.empty(company_id)
        try:
            return await adapter_provider(company_id)
        except Exception:
            logger.warning("Company adapter resolution failed for %s", company_id, exc_info=True)
            return CompanyAdapter.empty(company_id)

    async def _resolve_rules(state: ReviseState) -> CompanyRuleSet:
        """Bu şirketin zorunlu yazım kuralları, ya da hiçbir
        ``rules_provider`` yapılandırılmamışsa, bu turun durumunda
        ``company_id`` yoksa ya da çözümlemenin kendisi başarısız olursa boş
        bir küme -- aynı gerekçe için ``draft_graph``'ın özdeş yardımcı
        fonksiyonuna bakın."""
        company_id = state.get("company_id") or ""
        if not company_id or rules_provider is None:
            return CompanyRuleSet.empty(company_id)
        try:
            return await rules_provider(company_id)
        except Exception:
            logger.warning("Company rules resolution failed for %s", company_id, exc_info=True)
            return CompanyRuleSet.empty(company_id)

    async def _resolve_profile(state: ReviseState) -> CompanyProfile:
        """Bu şirketin kimlik profili, ya da hiçbir ``profile_provider``
        yapılandırılmamışsa, bu turun durumunda ``company_id`` yoksa ya da
        çözümlemenin kendisi başarısız olursa boş bir profil --
        ``draft_graph``'ın özdeş yardımcı fonksiyonunu yansıtır (Faz 6)."""
        company_id = state.get("company_id") or ""
        if not company_id or profile_provider is None:
            return CompanyProfile.empty(company_id)
        try:
            return await profile_provider(company_id)
        except Exception:
            logger.warning("Company profile resolution failed for %s", company_id, exc_info=True)
            return CompanyProfile.empty(company_id)

    async def parse_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        active_draft = state["active_draft"]
        instructions = state["instructions"]
        await emit_node_start(
            config, "revise_parse", "Talimat Ayrıştırma",
            "Revizyon talimatı ayrıştırılıyor...",
        )

        if not instructions.strip():
            # C21: decompose_instruction(""), *boş* bir ham talimat taşıyan
            # tek bir scope="whole" direktifine çözümlenir -- modele neyi
            # değiştireceğini söyleyen hiçbir şey olmayan bir tüm-taslak
            # yeniden yazımı, bu ayrıştırıcının üretebileceği en tehlikeli
            # direktiftir, güvenli bir varsayılan değil. Bunun yerine no-op'a
            # kısa devre yapar: aktif taslak tamamen değiştirilmeden döner,
            # rewrite/verify'a hiç ulaşmaz.
            await emit_node_end(
                config, "revise_parse", "Talimat Ayrıştırma",
                "Talimat boş; taslak değiştirilmeden bırakıldı.", {},
            )
            return {
                "draft": active_draft.text,
                "correspondence_type": active_draft.correspondence_type,
                "correspondence_sub_genre": getattr(active_draft, "correspondence_sub_genre", ""),
                "confidence_score": 100.0,
                "combined_score": 100.0,
                "requires_human_approval": False,
                "requires_revision": False,
                "evaluation_notes": (
                    "Revizyon talimatı boş olduğu için taslak değiştirilmeden bırakıldı."
                ),
                "status": StepStatus.COMPLETED,
            }

        instruction = parse_revision_instruction(instructions)
        directives = list(instruction.directives)
        targets = [locate_target(active_draft.text, directive) for directive in directives]

        if (
            len(directives) > 1
            and all(t is not None for t in targets)
            and spans_overlap(targets)
        ):
            # C5: iki direktif çakışan (yalnızca bitişik değil) aralıklara
            # çözümlendi -- her ikisini de sağdan sola birleştirme ile
            # eklemek, bir aralığın uzaklıklarını diğerininkiyle bozardı.
            # Bulunamayan bir cümleciğin zaten aldığı aynı güvenli
            # tüm-taslak yeniden yazımına düşer (bkz. decompose_instruction'ın
            # kendi dokümantasyonu), böylece hiçbir direktifin kendi isteği
            # sessizce düşürülmez diye tam orijinal talimatı taşır.
            directives = [
                EditDirective(
                    scope="whole", operation="content", section_hint=None,
                    ordinal=None, raw=instructions, order=0,
                )
            ]
            targets = [None]

        multi_directive_ok = len(directives) > 1 and all(t is not None for t in targets)

        correspondence_type = active_draft.correspondence_type
        correspondence_type_source = getattr(active_draft, "correspondence_type_source", "")
        correspondence_sub_genre = getattr(active_draft, "correspondence_sub_genre", "")

        await emit_node_end(
            config, "revise_parse", "Talimat Ayrıştırma",
            f"{len(directives)} direktif tespit edildi." if multi_directive_ok
            else "Talimat tek parça olarak işlenecek.",
            {"directive_count": len(directives), "multi_directive": multi_directive_ok},
        )

        return {
            "instruction": instruction,
            "directives": directives,
            "targets": targets,
            "multi_directive_ok": multi_directive_ok,
            "correspondence_type": correspondence_type,
            "correspondence_type_source": correspondence_type_source,
            "correspondence_sub_genre": correspondence_sub_genre,
            "context": active_draft.context,
            "draft": active_draft.text,
            "attempts": 0,
            "status": "IN_PROGRESS",
        }

    def route_after_parse(state: ReviseState) -> str:
        # C21: parse_node'un kendi boş-talimat kısa devresi zaten
        # status=COMPLETED ve değiştirilmemiş taslağı ayarladı -- bir no-op
        # için sonrasındaki hiçbir şeyin (retrieval, rewrite, verify)
        # çalışması gerekmiyor.
        return "end" if state.get("status") == StepStatus.COMPLETED else "retrieve_context"

    async def retrieve_context_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        active_draft = state["active_draft"]
        instruction = state["instruction"]
        await emit_node_start(
            config, "revise_retrieve", "Mevzuat Kontrolü",
            "Talimatın mevzuat bağlamı yeniden getirim gerektirip gerektirmediği kontrol ediliyor...",
        )

        context, meta = await maybe_extend_context(
            instruction=instruction, active_draft=active_draft, retriever=mevzuat_retriever,
        )

        if meta["decision"] == "extended":
            await emit_node_end(
                config, "revise_retrieve", "Mevzuat Kontrolü",
                f"{meta['added']} yeni mevzuat alıntısı eklendi.", meta,
            )
        elif meta["decision"] == "failed":
            await emit_node_error(
                config, "revise_retrieve", "Mevzuat Kontrolü",
                "Mevzuat yeniden getirimi başarısız; mevcut bağlamla devam ediliyor.",
                fatal=False,
            )
        else:
            await emit_node_skipped(
                config, "revise_retrieve", "Mevzuat Kontrolü",
                "Bu talimat için yeniden getirim gerekmedi.",
            )

        return {"context": context, "retrieval_meta": meta}

    async def _generate_validated(
        agent: ReviserAgent, prompt: str, preset: ReasoningLevelPreset
    ) -> str:
        """Bir reviser çağrısını tamamen tamponlanmış olarak çalıştırır,
        istemciye herhangi bir şey ulaşmadan önce doğrular.

        Burada "revise" SSE düğümüne hiçbir şey yayınlanmaz -- nedeni için
        ``rewrite_node``'un kendi dokümantasyonuna bakın. Tek bir reviser
        çağrısı, tur başına birkaç kez çalışabilir (çoklu-direktif yolunda
        direktif başına bir kez, her onarım turunda tekrar), ve eski
        chunk-başına ``emit_token``, bu ham tamamlanmaların her birini
        canlı, doğrulanmamış olarak doğrudan sohbete akıtıyordu: kendi
        numaralı brief iskeletini yansıtan bir tamamlanma (böyle yoğun
        yapılandırılmış bir prompt verilen küçük yerel modellerin bilinen
        bir hata modu) ya da aynı turda basitçe iki kez çalışan bir çağrı,
        sohbette turlar arasında birleştirilmiş, aralarında sınır olmayan
        gerçek "1. ... 2. ..." çöpü olarak görünüyordu. Burada tamponlamak
        ve ``rewrite_node`` bir şey yayınlamadan önce doğrulamak, ikisini de
        yalnızca daha az olası değil, yapısal olarak imkansız kılar.

        Raises:
            ValueError: Boş tamamlanma.
            GuardrailViolation: Bir prompt enjeksiyonu veya iskelet-yansıması
                deseni tespit edildi (bkz. ``app.ai.guardrails.injection``).
        """
        chunks: list[str] = []
        async for chunk in agent.stream(
            messages=prompt, temperature=0.2, max_tokens=preset.draft_max_tokens,
            reasoning=preset.reasoning,
        ):
            chunks.append(chunk)
        rewritten = "".join(chunks).strip()
        if not rewritten:
            raise ValueError("Ajan boş bir revizyon döndürdü.")
        assert_no_prompt_leak(rewritten)
        assert_no_scaffold_echo(rewritten)
        return rewritten

    async def rewrite_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        """Taslağı yeniden yazar (veya onarır); modelin çıktısını, kullanıcıya
        herhangi bir şey gösterilmeden önce doğrulamadan geçene kadar
        tamponlar.

        Reviser'ın kendi prompt'ları (``_build_brief``, ``_build_directive_
        prompt``, ``_build_repair_prompt``) zorunlu olarak yoğun, numaralı
        iskeletlerdir -- bu şekli devam ettirmesi istenen daha küçük bir
        yerel model, bazen düz taslak nesri üretmek yerine bunu
        tamamlanmasında taklit eder. Eski uygulamanın yaptığı gibi bunu
        canlı, chunk chunk akıtmak, sızıntıyı herhangi bir kontrol
        çalışmadan önce ekrana koyardı. ``_generate_validated`` üzerinden
        tamponlamak ve ancak sonra *doğrulanmış* metni yayınlamak (bir kez,
        ``emit_node_end``'den hemen önce tek bir token olayı olarak), bu
        boşluğu, temiz bir çalışmada kullanıcının nihayetinde gördüğüne
        dokunmadan kapatır -- son taslak metni her iki durumda da aynıdır.
        """
        active_draft = state["active_draft"]
        attempt_number = state.get("attempts", 0) + 1
        is_repair = bool(state.get("previous_draft"))
        preset = get_reasoning_level_preset(state.get("reasoning_level"))
        client = _resolve_free_text_client(preset, llm_client, fast_llm_client)
        correspondence_type = state.get("correspondence_type") or active_draft.correspondence_type
        sub_genre = state.get("correspondence_sub_genre") or getattr(
            active_draft, "correspondence_sub_genre", ""
        )
        style_examples = active_draft.style_examples
        # Deneme başına bir kez çözümlenir (gerçek provider'da Redis'te
        # önbelleklenir, bkz. app.domains.companies.provider.get_company_adapter),
        # draft_graph.writer_node'un özdeş çağrısıyla aynı.
        adapter = await _resolve_adapter(state)
        adapter_block = format_adapter_block(adapter)
        company_ruleset = await _resolve_rules(state)
        rules_block = format_rules_block(company_ruleset)
        profile = await _resolve_profile(state)
        brief = _build_brief(active_draft, state.get("context", ""), profile)

        await emit_node_start(
            config, "revise", "Taslak Revizyonu",
            f"[Revizyon Ajanı] Taslak {attempt_number}. denemede "
            + ("düzeltiliyor..." if is_repair else "yeniden yazılıyor..."),
        )

        budget = node_budget("revise", preset.level)
        try:
            async with asyncio.timeout(budget):
                if is_repair:
                    prompt = _build_repair_prompt(
                        brief=brief, correspondence_type=correspondence_type,
                        sub_genre=sub_genre,
                        previous_draft=state.get("previous_draft", ""),
                        repair_items=state.get("repair_items") or [],
                        style_examples=style_examples,
                        adapter_block=adapter_block,
                        rules_block=rules_block,
                    )
                    agent = ReviserAgent(client)
                    merged_draft = await _generate_validated(agent, prompt, preset)
                else:
                    directives = state["directives"]
                    targets = state["targets"]
                    multi_directive_ok = state.get("multi_directive_ok", False)
                    agent = ReviserAgent(client)

                    if multi_directive_ok:
                        # Sağdan sola: aralıklar orijinal taslağa karşı
                        # hesaplandı, bu yüzden en sağdaki aralığı önce
                        # işlemek, henüz işlenmemiş (soldaki) her aralığın
                        # uzaklıklarının, kademeli olarak eklenen çalışma
                        # taslağına karşı geçerli kalması anlamına gelir
                        # (bkz. modül dokümantasyonu).
                        order = sorted(
                            range(len(directives)), key=lambda i: targets[i].start, reverse=True
                        )
                        working_draft = active_draft.text
                        for i in order:
                            prompt = _build_directive_prompt(
                                source_draft=active_draft.text, target=targets[i],
                                directive=directives[i], brief=brief,
                                correspondence_type=correspondence_type,
                                sub_genre=sub_genre,
                                style_examples=style_examples,
                                adapter_block=adapter_block,
                                rules_block=rules_block,
                            )
                            rewritten = await _generate_validated(agent, prompt, preset)
                            if resolve_merge_target(targets[i], rewritten, active_draft.text) is None:
                                # C22, çoklu-direktif durumu: aşağıdaki
                                # tek-direktif yolunun aksine, burada
                                # tüm-taslak değişimine düşmek, aynı
                                # sağdan-sola geçişte daha önce uygulanmış
                                # her diğer direktifin eklemesini atardı.
                                # Bunun yerine yalnızca bu direktifin riskli
                                # yeniden yazımını atla -- kendi aralığı
                                # olduğu gibi bırakılır, diğer, doğru
                                # kapsamlı direktifler yine de uygulanır.
                                logger.warning(
                                    "Directive %d's rewrite looked like a scope overrun; "
                                    "leaving its target span unchanged.", i,
                                )
                                continue
                            working_draft = _merge(working_draft, targets[i], rewritten)
                        merged_draft = working_draft
                    else:
                        # Tek cümlecik (yaygın durum) ya da her aralığı
                        # bulamayan çoklu-cümlecik bir talimat -- tek-cümlecik
                        # bir talimatın her zaman aldığı aynı güvenli
                        # tüm/ilk-direktif yeniden yazımına düşer.
                        directive = directives[0]
                        target = targets[0]
                        prompt = _build_directive_prompt(
                            source_draft=active_draft.text, target=target, directive=directive,
                            brief=brief, correspondence_type=correspondence_type,
                            sub_genre=sub_genre,
                            style_examples=style_examples,
                            adapter_block=adapter_block,
                            rules_block=rules_block,
                        )
                        rewritten = await _generate_validated(agent, prompt, preset)
                        effective_target = resolve_merge_target(target, rewritten, active_draft.text)
                        merged_draft = _merge(active_draft.text, effective_target, rewritten)
        except TimeoutError:
            logger.warning(
                "Revise rewrite node exceeded its %.0fs budget (attempt %d).", budget, attempt_number
            )
            if is_repair and state.get("best_attempt"):
                await emit_node_error(
                    config, "revise", "Taslak Revizyonu",
                    "Onarım denemesi süre sınırını aştı; önceki en iyi deneme korundu.",
                    fatal=False,
                )
                return recover_from_failed_attempt(
                    state["best_attempt"], attempt_number,
                    f"Onarım denemesi {budget:.0f} saniyelik süre sınırını aştı; "
                    "önceki en iyi deneme korundu.",
                )
            await emit_node_error(
                config, "revise", "Taslak Revizyonu",
                f"Revizyon {budget:.0f} saniyelik süre sınırını aştı.", fatal=True,
            )
            return {
                "draft": active_draft.text, "attempts": attempt_number,
                "confidence_score": 0.0, "combined_score": 0.0,
                "requires_human_approval": True, "status": StepStatus.FAILED,
                "error": f"Revizyon {budget:.0f} saniyelik süre sınırını aştı.",
            }
        except Exception as exc:
            logger.exception("Revise rewrite node failed (attempt %d)", attempt_number)
            if is_repair and state.get("best_attempt"):
                await emit_node_error(
                    config, "revise", "Taslak Revizyonu",
                    "Onarım denemesi başarısız oldu; önceki en iyi deneme korundu.",
                    detail=str(exc), fatal=False,
                )
                return recover_from_failed_attempt(
                    state["best_attempt"], attempt_number,
                    f"Onarım denemesi başarısız oldu ({exc}); önceki en iyi deneme korundu.",
                )
            await emit_node_error(
                config, "revise", "Taslak Revizyonu", "Revizyon üretilemedi.", detail=str(exc),
            )
            return {
                "draft": active_draft.text, "attempts": attempt_number,
                "confidence_score": 0.0, "combined_score": 0.0,
                "requires_human_approval": True, "status": StepStatus.FAILED,
                "error": f"Revizyon üretilemedi: {exc}",
            }

        # Burada hiçbir token yayınlanmaz -- bkz. _generate_validated'ın
        # dokümantasyonu. Doğrulanmış metin, tüm tur (verify, herhangi bir
        # onarım geçişi, guardrail'ler) nihai yanıtına karar verdikten sonra,
        # yalnızca bir kez chat_service._enqueue_terminal_event'ten
        # istemciye akıtılır.
        await emit_node_end(
            config, "revise", "Taslak Revizyonu", "Revizyon tamamlandı.", {"draft": merged_draft},
        )
        return {
            "draft": merged_draft,
            "attempts": attempt_number,
            "status": "IN_PROGRESS",
            "company_adapter": adapter.to_dict(),
            "company_rules": company_ruleset.to_dict(),
            "company_profile": profile.to_dict(),
        }

    def route_after_rewrite(state: ReviseState) -> str:
        if state.get("status") == StepStatus.FAILED:
            return "end"
        # restored_from_best_attempt (C3): bir onarım geçişi çöktü ve
        # rewrite_node zaten önceki, tamamen doğrulanmış bir denemeye düştü
        # -- "verify"e yeniden girmek, zaten kontrol edilmiş metni tekrar
        # kontrol eder ve kendisi de yeniden çökebilir. Doğrudan "end"
        # yerine "audit"e gider (audit'e denk bir adımı olmayan
        # draft_graph'ın aksine): parse_node'un kendi `instruction`/
        # `directives`'i zaten durumda, bu yüzden changelog/çelişki denetimi
        # geri yüklenen taslağa karşı yine de çalışabilir -- audit_node'un
        # kendi geniş try/except'i (bkz. kendi dokümantasyonu), geri
        # yüklenen durumla ilgili bir şey beklentilerine uymuyorsa bunu
        # zaten boş, yalnızca danışma niteliğinde bir sonuca indirger.
        if state.get("restored_from_best_attempt"):
            return "audit"
        return "verify"

    async def verify_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        active_draft = state["active_draft"]
        # draft_graph.verify_node ile aynı yedek mekanizma -- bir onarım/
        # yeniden yazım geçişi, orijinal yazarın bırakabileceği aynı gerçek
        # "bulunamadı"/"yok" işaretini bırakabilir, ve revize zaten hiçbir
        # zaman orijinal yazarın prompt'unu yeniden çalıştırmaz.
        draft_text, _ = normalize_unfilled_markers(state.get("draft", ""))
        draft_text, _ = fill_date_placeholders(draft_text, state.get("today", ""))
        correspondence_type = state.get("correspondence_type") or active_draft.correspondence_type
        sub_genre = state.get("correspondence_sub_genre") or getattr(
            active_draft, "correspondence_sub_genre", ""
        )
        # draft_graph.verify_node ile aynı yedek mekanizma -- kendi notuna
        # bakın.
        draft_text, _ = normalize_role_placeholders(
            draft_text, is_individual_petition="dilekçe" in sub_genre.lower()
        )
        # C16: draft_graph.verify_node'un özdeş korumasını yansıtır -- katı
        # bir alt tür (bkz. is_strict_sub_genre), türü other_official'a
        # çözümlense bile desteklenmeyen bir iddia üzerinde insan onayını
        # zorlamaya devam eder.
        strict = correspondence_type != "other_official" or is_strict_sub_genre(sub_genre)
        preset = get_reasoning_level_preset(state.get("reasoning_level"))

        await emit_node_start(
            config, "verify", "Taslak Doğrulama",
            "[Doğrulayıcı] Revize taslak kaynak evrak ve mevzuata karşı denetleniyor...",
        )

        # draft_graph.verify_node ile aynı katma -- adaptörün kendi
        # preferred_examples'ı, diğer her üslup örneğinin aldığı tam olarak
        # aynı ornek_sizintisi sızıntı kontrolünü alır (bkz. CompanyAdapter'ın
        # dokümantasyonu).
        adapter = CompanyAdapter.from_dict(
            state.get("company_id") or "", state.get("company_adapter")
        )
        # Faz 6: draft_graph.verify_node'un özdeş trusted_facts katmasını
        # yansıtır -- bu olmadan, aynı taslağın *orijinal* verify_draft
        # çağrısı (draft_graph'ta) hiç işaretlemese bile, şirketin kendi
        # adı/antetli kağıdı her tek revizyonda dayanaksız bir
        # dayanaksiz_iddia olarak puanlanıyordu.
        profile = CompanyProfile.from_dict(
            state.get("company_id") or "", state.get("company_profile")
        )
        trusted_facts = [
            value
            for value in (
                profile.display_name,
                profile.short_name,
                profile.letterhead,
                profile.default_signer_title,
                profile.default_signer_name,
            )
            if value
        ]
        def _run_verify(text: str) -> VerificationReport:
            return verify_draft(
                text,
                source_document=active_draft.source_document,
                context=state.get("context", ""),
                classification=active_draft.classification,
                # draft_graph.verify_node:1381 ile aynı -- yalnızca bu turun
                # ham talimatı değil, birikmiş haystack (önceki turlar +
                # yerleşmiş brief cevapları). Bu olmadan kullanıcının bir
                # önceki turda verdiği bir isim/tarih/kurum, revizyonda
                # dayanaksiz_iddia (-12) olarak puanlanıyordu.
                instructions=state.get("instruction_haystack") or state.get("instructions", ""),
                strict=strict,
                style_examples=list(active_draft.style_examples) + list(adapter.preferred_examples),
                is_individual_petition="dilekçe" in sub_genre.lower(),
                today=state.get("today", ""),
                trusted_facts=trusted_facts,
                # draft_graph.verify_node ile aynı katma -- bu olmadan,
                # orijinal taslağın getirilen bir belge parçasından meşru
                # olarak kopyaladığı bir olgu, onu ilk yazan taslakta olduğundan
                # her revizyonda kesinlikle daha zayıf bir dayanağa sahip
                # olurdu.
                source_chunks=active_draft.source_chunks,
            )

        report = _run_verify(draft_text)

        # Taslak turunda zaten çözülmüş yer tutucuları ve yerleşmiş yazım
        # briefinden doldurulabilecekleri, kullanıcıya tekrar sormak yerine
        # sessizce yerine koy. Bu, iki akış (taslak <-> revizyon) arasındaki
        # "aynı bilgiyi iki kez sorma" tutarsızlığının düzeltmesi;
        # apply_answers deterministik olduğu için taslak yeniden üretilmez.
        # "Sen karar ver" (AUTO_ANSWER) ile ertelenenler burada değil --
        # onlar metinde köşeli parantez olarak kalır (taslak akışıyla aynı),
        # yalnızca build_missing_info_request tarafından yeniden sorulmaz.
        resolved_real = {
            key: value
            for key, value in (state.get("resolved_placeholder_answers") or {}).items()
            if value and value != AUTO_ANSWER
        }
        brief_fills = resolve_placeholders_from_brief(draft_text, active_draft.writing_brief)
        known_fills = {**brief_fills, **resolved_real}  # açık cevap, brief'ten öne geçer
        if known_fills:
            draft_text, _ = apply_answers(draft_text, known_fills)
            report = _run_verify(draft_text)

        judge_on = (
            settings.DRAFT_JUDGE_ENABLED if preset.judge_enabled is None else preset.judge_enabled
        )
        verdict = None
        if judge_on:
            await emit_node_start(
                config, "judge", "Kalite Yargıcı",
                "[Yargıç] Revizyonun talebe uygunluğu değerlendiriliyor...",
            )
            company_ruleset = CompanyRuleSet.from_dict(
                state.get("company_id") or "", state.get("company_rules")
            )
            verdict = await judge_draft(
                judge_agent,
                draft=draft_text,
                brief=_build_brief(active_draft, state.get("context", ""), profile),
                correspondence_type=correspondence_type,
                instructions=state.get("instructions", ""),
                timeout_s=settings.DRAFT_JUDGE_TIMEOUT_SECONDS * preset.timeout_multiplier,
                sub_genre=sub_genre,
                company_rules_block=format_rules_block(company_ruleset),
            )
            if verdict is None:
                await emit_node_error(
                    config, "judge", "Kalite Yargıcı",
                    "Kalite yargıcı kullanılamadı; deterministik doğrulama sonucuna göre devam ediliyor.",
                    fatal=False,
                )
            else:
                await emit_node_end(
                    config, "judge", "Kalite Yargıcı", "Yargıç değerlendirmesi tamamlandı.",
                    verdict.model_dump(),
                )
        elif preset.judge_enabled is False:
            await emit_node_skipped(
                config, "judge", "Kalite Yargıcı", "Hızlı modda kalite yargıcı atlandı.",
            )

        missing_information: list[InfoQuestion] = []
        if report.placeholder_count > 0:
            missing_information = build_missing_info_request(
                draft_text,
                report,
                active_draft.classification,
                # AUTO_ANSWER girdileri de dahil: "Sen karar ver" ile
                # ertelenmiş bir yer tutucu revizyonda yeniden sorulmaz
                # (yine de doldurulmamis_yer_tutucu ile NEEDS_HUMAN_APPROVAL'a
                # taşınabilir -- taslak akışıyla birebir aynı davranış).
                resolved_keys=state.get("resolved_placeholder_answers") or {},
                writing_brief=active_draft.writing_brief,
            )

        # `_merge` üzerinden ekleme yapmadan `draft_text` üretebilen iki
        # yoldan (hedefi bulunamayan bir tüm-taslak yeniden yazımı, ya da
        # herhangi bir onarım-döngüsü geçişi -- bkz. rewrite_node) hiçbiri,
        # modelin değiştirmesi istenmeyen şeyi gerçekten yeniden ürettiğini
        # kontrol eden hiçbir şeye sahip değildi. Özellikle `active_draft.text`'e
        # karşı karşılaştırılır (turun gerçek başlangıç noktası, muhtemelen
        # zaten kayıp içeriği olan bir onarım denemesi değil), böylece
        # deneme 1'de tanıtılan bir kayıp, deneme 2'nin kontrolünde hâlâ
        # yakalanır, "daha fazla kayıp yok" olarak temizlenmez.
        content_loss = detect_content_loss(
            active_draft.text, draft_text, state.get("instructions", "")
        )
        if content_loss is not None:
            logger.warning("Revise rewrite dropped content: %s", content_loss.detail)

        # draft_graph.verify_node ile eşdeğerlik: KVK içeren, ya da tahmin
        # edilmiş (yedek) bir yazışma türünü devralan, ya da hiç mevzuat
        # dayanağı olmayan bir revizyon bir insanın gözüne ihtiyaç duyar --
        # eski tek-çağrılı run_revise bunların hiçbirini kontrol etmiyordu.
        pii_findings = [
            finding
            for finding in find_pii(draft_text)
            if finding.confidence >= get_policy().guardrail.pii_confidence_floor
        ]

        # Faz 6: style_checks bulguları, draft_graph.verify_node'un özdeş
        # bloğunun zaten yaptığı gibi (Faz 4) aynı onarım döngüsüne
        # beslenir -- bir kusuru düzelten ve kendi kişi/dolgu/imza-bloğu
        # kusurunu tanıtan bir onarım geçişi, taze bir taslağın aldığı aynı
        # kontrolü hak eder.
        style_findings = [
            *check_person_consistency(draft_text),
            *check_filler_sentences(draft_text),
            *check_signature_block(draft_text),
            *check_meta_commentary(draft_text),
        ]

        combined = merge_verdicts(
            report,
            verdict,
            missing_information=missing_information,
            pii_findings=pii_findings,
            correspondence_type_fallback=state.get("correspondence_type_source") == "fallback",
            has_context=bool(state.get("context")),
            cites_legislation=bool(LEGISLATION_PATTERN.search(draft_text)),
            content_loss=content_loss,
            judge_attempted=judge_on,
            style_findings=style_findings,
        )

        DRAFT_SCORE.labels(source="deterministic").observe(report.confidence_score)
        if verdict is not None:
            DRAFT_SCORE.labels(source="judge").observe(verdict.score)
        DRAFT_SCORE.labels(source="combined").observe(combined.combined_score)

        history_entry = {
            "attempt": state.get("attempts", 0),
            "deterministic_score": report.confidence_score,
            "judge_score": verdict.score if verdict is not None else None,
            "combined_score": combined.combined_score,
            "defect_count": len(combined.repair_items),
        }
        attempt_history = [*(state.get("attempt_history") or []), history_entry]

        if missing_information:
            status = StepStatus.NEEDS_INPUT
        elif combined.requires_human_approval:
            status = StepStatus.NEEDS_HUMAN_APPROVAL
        else:
            status = StepStatus.COMPLETED

        evaluation_notes = combined.notes
        if pii_findings:
            kinds = ", ".join(sorted({finding.kind for finding in pii_findings}))
            evaluation_notes = (
                f"{evaluation_notes} Taslakta {len(pii_findings)} adet kişisel veri "
                f"bulgusu tespit edildi ({kinds}); insan onayı gerekiyor."
            )
        if content_loss is not None:
            evaluation_notes = f"{evaluation_notes} {content_loss.detail}"

        update = {
            "draft": draft_text,
            "confidence_score": combined.combined_score,
            "combined_score": combined.combined_score,
            "requires_human_approval": combined.requires_human_approval,
            "requires_revision": combined.requires_revision,
            "evaluation_notes": evaluation_notes,
            "pii_findings": [finding.model_dump() for finding in pii_findings],
            "verification": report.model_dump(),
            "judge": verdict.model_dump() if verdict is not None else {},
            "judge_available": combined.judge_available,
            "repair_items": [item.model_dump() for item in combined.repair_items],
            "missing_information": [q.model_dump() for q in missing_information],
            "attempt_history": attempt_history,
            "status": status,
            "applied_rules": [rule.model_dump() for rule in combined.applied_rules],
        }

        # C2: draft_graph.verify_node'un özdeş kayıt tutmasını yansıtır
        # (bkz. app.ai.workflows.attempt_tracking) -- bu turun onarım
        # döngüsü boyunca en yüksek puanlı denemeyi takip et, ve döngü
        # kusurlar hâlâ açıkken deneme bütçesini tüketmek üzereyse, son
        # çalışan hangi deneme olursa olsun onun yerine bunu gönder.
        snapshot = snapshot_attempt(update, draft_text)
        best_attempt = best_of(snapshot, state.get("best_attempt"))
        update["best_attempt"] = best_attempt
        if (
            not missing_information
            and combined.requires_revision
            and state.get("attempts", 0) >= preset.max_draft_attempts
            and best_attempt is not snapshot
        ):
            update.update(best_attempt)

        await emit_node_end(
            config, "verify", "Taslak Doğrulama", "Taslak doğrulaması tamamlandı.",
            {"draft": draft_text, **update},
        )
        return update

    def route_after_verify(state: ReviseState) -> str:
        if state.get("status") == StepStatus.FAILED:
            return "end"
        if state.get("missing_information"):
            return "needs_input"
        if state.get("requires_revision"):
            preset = get_reasoning_level_preset(state.get("reasoning_level"))
            if state.get("attempts", 0) < preset.max_draft_attempts:
                return "repair"
        return "audit"

    async def repair_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        """Bir sonraki yeniden yazım geçişini hazırlar. Saf ve LLM'siz,
        draft_graph.revise_node ile aynı rol -- döngünün tek üretim maliyeti
        rewrite çağrısıdır, burada asla ikinci bir çağrı olmaz."""
        repair_items = state.get("repair_items") or []
        trigger = (
            "deterministic"
            if any(item.get("source") == "deterministic" for item in repair_items)
            else "judge"
        )
        DRAFT_REVISIONS.labels(trigger=trigger).inc()
        await emit_node_start(
            config, "revise_repair", "Revizyon Onarımı",
            f"{len(repair_items)} kusur tespit edildi; hedefli düzeltme hazırlanıyor...",
        )
        update = {"previous_draft": state.get("draft", "")}
        await emit_node_end(
            config, "revise_repair", "Revizyon Onarımı", "Düzeltme talimatları hazırlandı.",
            {"repair_items": repair_items},
        )
        return update

    async def audit_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        """Talimat-vs-mevzuat/kaynak çelişki denetimi ve değişiklik günlüğü.

        Yalnızca yerleşmiş, eksik-bilgi-olmayan bir sonuçta çalışır --
        kullanıcıya daha fazla soru sorulmak üzere olan bir taslağı
        denetlemenin bir anlamı yok (bkz. route_after_verify'ın bu düğümü
        tamamen atlayan `needs_input` kısayolu).

        Buradaki bir çelişki bulgusu danışma niteliğindedir, asla bir kapı
        değildir: ``ConflictReport.applied_anyway`` (bkz.
        ``app.ai.revision.conflict``'in modül dokümantasyonu) katı bir
        değişmez kuraldır, bu yüzden bu düğüm bir bulguyu, turun bir insan
        için duraklama nedenine dönüştürmemelidir. Eskiden dönüştürüyordu --
        ``conflict_report.requires_human_approval`` ayarlandığında
        ``status``'ü ``NEEDS_HUMAN_APPROVAL``'a yükseltiyordu -- bu da
        "Talimatınız uygulandı, ancak..." mesajını, gerçek bir düşük-kaliteli
        taslağın aldığı aynı engelleyici onay popup'ının arkasına koyan, run'ın
        kullanıcıdan ihtiyaç duyduğu gerçek bir karardan ayırt edilemeyen
        şeydi. Bir çelişki artık yalnızca kendi sohbet mesajı olarak render
        edilen, engellemeyen bir ``notice`` olayı üretir (bkz.
        ``emit_notice``); buradaki ``status`` yalnızca ``verify_node``'un
        zaten karar verdiği şeyi yansıtır.
        """
        active_draft = state["active_draft"]
        instruction = state["instruction"]
        draft_text = state.get("draft", "")
        preset = get_reasoning_level_preset(state.get("reasoning_level"))

        await emit_node_start(
            config, "revise_audit", "Çelişki Denetimi",
            "Talimat mevzuat ve kaynak evrakla karşılaştırılıyor...",
        )

        # Bu düğümün kendi dokümantasyonu, buradaki bir bulgunun danışma
        # niteliğinde olduğunu, asla bir kapı olmadığını açıkça belirtir --
        # bu yüzden bir bulgu *üretememe* de danışma niteliğinde olmalıdır.
        # Bu koruma olmadan, buradaki herhangi bir istisna (bozuk bir
        # `verification` sözlüğü, uzun bir talimatta veya kurum adları
        # zincirinde kendi `max_length`ini aşan bir `ConflictFinding`/
        # `ChangeEntry` alanı, ...) düğümün dışına, `graph.ainvoke`'un
        # dışına ve `run_revise`'ın dış `except Exception`'ına (bkz.
        # `revise.py`) yayılıyordu; bu da tüm revizyonu -- metin,
        # doğrulama, her şeyi -- atıyor ve `rewrite_node`/`verify_node` iki
        # düğüm önce iyi bir taslağı zaten üretip doğrulamış olsa bile
        # `FAILED` bildiriyordu. Boş, engellemeyen bir rapora indirgemek,
        # bu düğümün *çelişki* bulgusu için ifade ettiği tam sözleşmedir;
        # *denetleyememe* için de aynı sözleşme olmalıdır.
        try:
            report = VerificationReport(**state.get("verification", {}))
            deterministic = detect_conflicts_deterministic(
                instruction=instruction, context=state.get("context", ""),
                source_document=active_draft.source_document, report=report,
            )

            judge_on = (
                settings.DRAFT_JUDGE_ENABLED if preset.judge_enabled is None else preset.judge_enabled
            )
            llm_findings = []
            if settings.REVISION_CONFLICT_AUDIT_ENABLED and judge_on:
                llm_findings = await assess_conflicts_llm(
                    conflict_agent, instruction=instruction.raw, revised_draft=draft_text,
                    context=state.get("context", ""), source_document=active_draft.source_document,
                    timeout_s=settings.DRAFT_JUDGE_TIMEOUT_SECONDS * preset.timeout_multiplier,
                )

            conflict_report = merge_conflicts(deterministic, llm_findings)
            changelog = build_changelog(active_draft.text, draft_text, state.get("directives") or [])
        except Exception:
            logger.exception(
                "Revise audit node failed; degrading to an empty, advisory-only result "
                "rather than failing the (already successful) revision."
            )
            conflict_report = ConflictReport()
            changelog = RevisionChangelog(
                entries=[], summary="Değişiklik özeti oluşturulamadı."
            )

        # Yalnızca danışma niteliğinde -- bu düğümün kendi dokümantasyonuna
        # bakın. Turun bir insan için duraklayıp duraklamayacağı tamamen
        # verify_node'un kararıdır; bir çelişki bulgusu buna asla katkıda
        # bulunmaz.
        requires_approval = bool(state.get("requires_human_approval"))
        status = state.get("status")

        if conflict_report.conflicts:
            severity_label = {"critical": "Kritik", "major": "Önemli", "minor": "Küçük"}
            lines = "\n".join(
                f"- [{severity_label.get(f.severity, f.severity)}] {f.detail}"
                for f in conflict_report.conflicts
            )
            await emit_notice(
                config,
                node="revise_audit",
                title="Talimat uygulandı, ancak bir çelişki tespit edildi",
                message=(
                    "Talimatınız taslağa uygulandı; ancak mevzuat veya kaynak "
                    f"evrakla şu noktalarda çelişiyor:\n{lines}"
                ),
            )

        await emit_node_end(
            config, "revise_audit", "Çelişki Denetimi", conflict_report.notes,
            {"conflicts": [f.model_dump() for f in conflict_report.conflicts]},
        )
        return {
            "conflicts": [f.model_dump() for f in conflict_report.conflicts],
            "conflict_notes": conflict_report.notes,
            "changelog": changelog.model_dump(),
            "requires_human_approval": requires_approval,
            "status": status,
        }

    builder = StateGraph(ReviseState)
    builder.add_node("parse", parse_node)
    builder.add_node("retrieve_context", retrieve_context_node, retry_policy=IO_RETRY)
    builder.add_node("rewrite", rewrite_node)
    builder.add_node("verify", verify_node)
    builder.add_node("repair", repair_node)
    builder.add_node("audit", audit_node)

    builder.add_edge(START, "parse")
    builder.add_conditional_edges(
        "parse", route_after_parse, {"retrieve_context": "retrieve_context", "end": END}
    )
    builder.add_edge("retrieve_context", "rewrite")
    builder.add_conditional_edges(
        "rewrite", route_after_rewrite, {"verify": "verify", "audit": "audit", "end": END}
    )
    builder.add_conditional_edges(
        "verify", route_after_verify,
        {"repair": "repair", "needs_input": END, "audit": "audit", "end": END},
    )
    builder.add_edge("repair", "rewrite")
    builder.add_edge("audit", END)

    return builder.compile()
