"""Hibrit kalite kapısı: deterministik doğrulayıcı artı hızlı katman bir LLM yargıcı.

``draft_verifier.verify_draft`` uydurma sayıları, tarihleri, kurumları ve
alıntıları yakalar ve yapısal bütünlüğü kontrol eder -- tamamı küme üyeliği
ve regex, tamamı yeniden üretilebilir, tamamı ücretsiz. Ancak bir taslağın
gerçek talebi karşılayıp karşılamadığını, muhatap hiyerarşisi için doğru
arz/rica yönünü kullanıp kullanmadığını, resmî yazışma Türkçesi gibi okunup
okunmadığını veya kime hitap ettiği konusunda tutarlı kalıp kalmadığını
değerlendiremez. Bunlar dizge eşleştirmesi değil akıl yürütme gerektirir, bu
yüzden bu modül bunlar için hızlı katman modele tek, küçük, yapılandırılmış
bir çağrı ekler.

Yargıcın taslağı yeniden üretmesine kasıtlı olarak izin verilmez: kararındaki
her dizge alanı uzunluk sınırlıdır ve doğrulama sonrası bir koruma, metni
değerlendirdiği taslakla güçlü şekilde örtüşen bir kararı reddeder. Taslağı
geri yansıtan bir model onu değerlendirmiyor demektir ve tekrar denemesini
istemek yalnızca ikinci bir yankı üretir -- bu yüzden bir yankı, tekrar
deneme değil bozulmuş bir yargıç çağrısı olarak ele alınır.

``merge_verdicts`` eskiden yargıcın kendi 0-100 ``score``'unu son sayıyla
harmanlıyordu (``0.6 * deterministik + 0.4 * yargıç``). Bu, skoru tekrar
üretilemez (aynı taslak iki yargıç çağrısı arasında farklı skorlanabiliyordu)
ve süreksiz (bozulmuş bir yargıç çağrısı, 0.4 ağırlığını yeniden dağıtmak
yerine sessizce düşürüyordu) hale getiriyordu. Yargıç artık bir sayıya katkı
sağlamıyor: bulguları, ``app.ai.verification.confidence_rules``'ın her şey
için kullandığı aynı tek tabloda, sıfır skor ağırlığında ``RuleFinding``lara
dönüşüyor (bkz. o modülün docstring'i) -- yargıç hâlâ onayı kapılıyor ve
hâlâ tamir döngüsünü yönlendiriyor, sadece artık sayıyı asla hareket
ettirmiyor.
"""

import asyncio
import logging
from typing import Literal, Optional, Sequence

from pydantic import BaseModel, Field

from app.ai.agents.judge import JudgeAgent
from app.ai.guardrails.pii import PiiFinding
from app.ai.policy import get_policy
from app.ai.revision.elision import ContentLossFinding
from app.ai.verification.confidence_rules import AppliedRule, RuleFinding, score_findings
from app.ai.verification.draft_verifier import (
    MIN_AUTOMATED_CONFIDENCE_SCORE,
    VerificationReport,
    _fold,
)
from app.ai.verification.missing_info import InfoQuestion
from app.ai.workflows.correspondence import format_correspondence_profile
from app.core.config import settings
from app.observability.ai_metrics import JUDGE_FAILURES

logger = logging.getLogger(__name__)

#: Yalnızca metin üzerinde çalışan bir revizyon geçişinin gerçekten
#: düzeltebileceği yargıç bulguları. "mevzuat" (yanlış mevzuat alıntı
#: eşleşmesi) veya "tutarlilik" (geniş kapsamlı iç tutarsızlık) türündeki
#: bulgular raporlanır ve insan onayını zorunlu kılabilir, ama kasıtlı olarak
#: buraya dahil edilmez -- bir yeniden yazma, yeni bir retrieval olmadan
#: kötü bir alıntı eşleşmesini düzeltemez ve "daha tutarlı yap" bir 9B
#: modele aşırı düzeltme riski almadan verilemeyecek kadar belirsiz bir
#: revizyon talimatıdır. "kurum_kurali" (bir şirketin kendi zorunlu yazım
#: kuralı, bkz. app.ai.adapters.company_rules) dahil edilir -- mevzuat/
#: tutarlilik'ten farklı olarak bir kural ihlali, tam olarak bir tamir
#: geçişinin düzeltebileceği türde hedefli, metinsel bir kusurdur (örn.
#: "kapanışı 'Arz ederim' yap"), mevcut kapanis/uslup bulgularıyla aynı
#: şekildedir.
REVISABLE_JUDGE_KINDS = frozenset({"kapanis", "uslup", "talep", "muhatap", "kurum_kurali"})

#: Bir yargıç kararının kendi belirteçlerinin (token) taslakta görünen kesri
#: bu eşiğin üzerindeyse, kararı taslağın bir değerlendirmesi değil bir
#: yankısı olarak ele al.
_ECHO_OVERLAP_THRESHOLD = get_policy().verification.judge_echo_overlap_threshold

#: Her stil-kontrolü kural kimliği için tamir rehberliği (bkz.
#: ``app.ai.verification.style_checks``); zira her kural revizör için farklı
#: bir talimat gerektirir -- kendi ``suggested_fix``'ini zaten taşıyan
#: yargıcın bulgularının aksine.
_STYLE_FINDING_SUGGESTED_FIXES: dict[str, str] = {
    "kisi_tutarsizligi": (
        "Aynı kişiye tek ve tutarlı bir hitap biçimi kullan -- ya 'Sayın X' ya "
        "'X Bey/Hanım', aynı taslakta ikisi birden değil."
    ),
    "dolgu_ifade": (
        "Tekrarlanan cümleyi kaldır; her paragraf yeni bir olgu veya adım "
        "taşımalı, önceki paragrafta söyleneni yeniden ifade etmemeli."
    ),
    "meta_yorum": (
        "Kendi analiz/inceleme sürecine dair soyut üst-yorumu ('sadece verilen "
        "kayıt incelenmiştir' gibi) kaldır veya brief'teki somut bir olguya "
        "bağla (örn. 'incelenmiştir' yerine '[X talebiniz] incelenmiştir')."
    ),
    "imza_blogu_uydurma": (
        "İmza bloğundaki çıplak yer tutucu etiketini brief'teki gerçek "
        "değerle değiştir; değer yoksa köşeli parantezli haline döndür "
        "(örn. '[İmzalayacak yetkilinin adı ve soyadı]')."
    ),
}


class JudgeFinding(BaseModel):
    """Yargıcın bulduğu, belirli bir düzeltmesi olan tek somut bir kusur."""

    kind: Literal[
        "hitap", "kapanis", "talep", "uslup", "muhatap", "mevzuat", "tutarlilik", "kurum_kurali"
    ]
    severity: Literal["critical", "major", "minor"]
    detail: str = Field(max_length=200)
    suggested_fix: str = Field(max_length=200)


class DraftJudgeVerdict(BaseModel):
    """Yargıcın yapılandırılmış değerlendirmesi. Hiçbir alan taslak metni taşıyamaz."""

    addresses_request: bool = Field(
        description="Taslak, gelen evrakın veya kullanıcının asıl talebini karşılıyor mu."
    )
    register_ok: bool = Field(description="Resmî üslup korunuyor mu.")
    closing_direction: Literal["arz", "rica", "arz_ve_rica", "bilgilendirme", "yok"] = Field(
        description="Taslakta fiilen kullanılan kapanışın yönü."
    )
    closing_correct: bool = Field(
        description="Kapanış yönü muhatap hiyerarşisiyle uyumlu mu."
    )
    muhatap_consistent: bool = Field(
        description="Başlık, gövde hitabı ve kapanış yönü birbiriyle tutarlı mı."
    )
    company_rules_ok: bool = Field(
        default=True,
        description=(
            "Taslak, verilen şirket kurallarının tamamına uyuyor mu. Kural "
            "verilmemişse true."
        ),
    )
    violated_rule_ids: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="İhlal edilen kuralların kimlikleri (örn. ['K2', 'K5']).",
    )
    score: float = Field(ge=0.0, le=100.0)
    findings: list[JudgeFinding] = Field(default_factory=list, max_length=5)
    rationale: str = Field(max_length=400)


class RepairItem(BaseModel):
    """Revizöre geri verilen, hedefli tek bir talimat."""

    kind: str
    detail: str
    suggested_fix: str = ""
    source: Literal["deterministic", "judge"]


class CombinedVerdict(BaseModel):
    """Draft grafiğinin router'ının üzerine hareket ettiği birleşmiş sonuç."""

    combined_score: float
    requires_human_approval: bool
    requires_revision: bool
    repair_items: list[RepairItem] = Field(default_factory=list)
    missing_information: list[InfoQuestion] = Field(default_factory=list)
    judge_available: bool
    notes: str = ""
    applied_rules: list[AppliedRule] = Field(
        default_factory=list,
        description=(
            "report.applied_rules artı bu birleştirmenin katlayarak eklediği "
            "her ek kural bulgusu (PII, yazışma türü tahmini, mevzuat bağlamı "
            "yokluğu, içerik kaybı, yargıç bulguları) -- combined_score'un "
            "arkasındaki tam, denetlenebilir döküm."
        ),
    )


def _reject_draft_echo(verdict: DraftJudgeVerdict, draft: str) -> bool:
    """Taslağı değerlendirmek yerine yankılayan bir yargıç kararını tespit eder.

    Args:
        verdict: Aday karar.
        draft: Değerlendirmesi beklenen taslak metni.

    Returns:
        Kararın metni taslakla güvenilemeyecek kadar güçlü örtüştüğünde True.
    """
    draft_tokens = set(_fold(draft).split())
    if not draft_tokens:
        return False

    fields = [verdict.rationale, *(f"{f.detail} {f.suggested_fix}" for f in verdict.findings)]
    text_tokens = [token for token in _fold(" ".join(fields)).split() if len(token) > 2]
    if len(text_tokens) < 8:
        return False

    overlap = sum(1 for token in text_tokens if token in draft_tokens) / len(text_tokens)
    return overlap > _ECHO_OVERLAP_THRESHOLD


async def judge_draft(
    agent: JudgeAgent,
    *,
    draft: str,
    brief: str,
    correspondence_type: str,
    instructions: str,
    timeout_s: float | None = None,
    sub_genre: str = "",
    company_rules_block: str = "",
) -> DraftJudgeVerdict | None:
    """Hızlı katman yargıçtan bir taslağı değerlendirmesini ister. Asla exception fırlatmaz.

    Args:
        agent: Kurulmuş bir :class:`JudgeAgent` (hızlı katman istemcisi).
        draft: Değerlendirilecek taslak.
        brief: Yazara verilen dayanak brief'i.
        correspondence_type: Çözümlenmiş :class:`CorrespondenceType` değeri.
        instructions: Kullanıcının taslak talimatları.
        timeout_s: Sert zaman aşımı; varsayılan ``settings.DRAFT_JUDGE_TIMEOUT_SECONDS``.
        sub_genre: Taslak, dört spesifik türün dışında belirli bir türü
            hedeflediğinde ("itiraz dilekçesi") serbest metin tür etiketi --
            bkz. ``app.ai.workflows.correspondence.format_correspondence_profile``.
        company_rules_block: İstekte bulunan şirketin zorunlu kuralları,
            zaten render edilmiş (bkz.
            ``app.ai.adapters.injection.format_rules_block``). Hiçbir kural
            yapılandırılmadığında boş -- ``judge.md``'nin kendi 5. kriteri
            bu durumda kendini atlar.

    Returns:
        Karar, ya da zaman aşımı, şema hatası, sağlayıcı hatası veya tespit
        edilen bir yankı durumunda ``None`` -- bunların hepsi kalite kapısını
        taslak akışını engellemek yerine deterministik skora düşürür.
    """
    timeout = timeout_s if timeout_s is not None else settings.DRAFT_JUDGE_TIMEOUT_SECONDS
    prompt = (
        "### BRIEF BELGESİ:\n"
        f"{brief}\n\n"
        "### YAZIŞMA TÜRÜ:\n"
        f"{format_correspondence_profile(correspondence_type, sub_genre)}\n\n"
        "### KULLANICI TALİMATLARI:\n"
        f"{instructions or '(talimat verilmedi)'}\n\n"
        "### ŞİRKET KURALLARI:\n"
        f"{company_rules_block or '(kural verilmedi)'}\n\n"
        "### DEĞERLENDİRİLECEK TASLAK:\n"
        f"{draft}"
    )

    try:
        verdict: DraftJudgeVerdict = await asyncio.wait_for(
            agent.run_structured(
                messages=prompt,
                response_model=DraftJudgeVerdict,
                temperature=0.0,
                max_retries=1,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Draft judge timed out after %.0fs; degrading.", timeout)
        JUDGE_FAILURES.labels(reason="timeout").inc()
        return None
    except Exception:
        logger.exception("Draft judge call failed; degrading.")
        JUDGE_FAILURES.labels(reason="exception").inc()
        return None

    if _reject_draft_echo(verdict, draft):
        logger.warning("Draft judge verdict echoed the draft; treating as degraded.")
        JUDGE_FAILURES.labels(reason="echo").inc()
        return None

    return verdict


def merge_verdicts(
    report: VerificationReport,
    verdict: DraftJudgeVerdict | None,
    *,
    missing_information: list[InfoQuestion] | None = None,
    pii_findings: Optional[Sequence[PiiFinding]] = None,
    correspondence_type_fallback: bool = False,
    has_context: bool = True,
    cites_legislation: bool = False,
    content_loss: Optional[ContentLossFinding] = None,
    judge_attempted: bool = False,
    style_findings: Sequence[RuleFinding] = (),
) -> CombinedVerdict:
    """Bir taslak hakkındaki her sinyali tek bir deterministik sonuçta birleştirir.

    Skor harmanlanmaz, toplanır: ``report``'un kendi deterministik cezası
    (``100 - report.confidence_score`` olarak geri elde edilir, çünkü rapor
    kendi ham cezasını dışa açmaz) artı bu fonksiyonun tek başına bildiği her
    şey üzerinden bir kural tablosu geçişi daha (``app.ai.verification.confidence_rules``)
    -- PII, tahmin edilmiş bir yazışma türü, eksik bir mevzuat bağlamı,
    revizyon içerik kaybı ve yargıcın kendi bulguları. Yargıcın sayısal
    ``verdict.score``'u burada asla okunmaz (bkz. bu modülün docstring'i)
    -- yalnızca ``verdict.findings`` ve ``verdict.addresses_request`` tabloyu
    besler, ikisi de kural tablosunun kendi sıfır-cezalı
    ``yargic_kritik_bulgu``/``talebi_karsilamiyor`` satırlarında, böylece
    kritik bir yargıç bulgusu sayıyı hareket ettirmeden onayı kapılar.

    Args:
        report: Deterministik doğrulama raporu.
        verdict: Yargıcın kararı, ya da yargıç çağrısı bozulduysa ``None``.
        missing_information: Taslağın varsa, önceden oluşturulmuş yer
            tutucu soruları. Bu fonksiyonun girdileri üzerinde saf bir
            birleştirme olarak kalması için burada türetilmek yerine
            açık bir parametre olarak tutulur.
        pii_findings: Taslaktaki kişisel veri bulguları (bkz.
            ``app.ai.guardrails.pii.find_pii``), varsa.
        correspondence_type_fallback: Yazışma türünün açık bir sinyalden
            çözümlenmek yerine tahmin edilip edilmediği (bkz.
            ``app.ai.workflows.correspondence.resolve_correspondence_type``).
        has_context: Bu taslağı destekleyen doğrulanmış bir mevzuat alıntısı
            olup olmadığı. ``False``, sistemin dayanacağı hiçbir şeyi
            olmadığı anlamına gelir.
        cites_legislation: Taslağın kendi metninin gerçekten bir mevzuat
            madde/numarasına atıfta bulunup bulunmadığı (bkz.
            ``draft_verifier.LEGISLATION_PATTERN``). ``mevzuat_baglami_yok``
            yalnızca bu da doğru olduğunda tetiklenir -- hiçbir şeye atıfta
            bulunmayı denememiş bir taslağın (çoğu ön yazı/bilgilendirme
            notu) hiçbir şey getirilmediği için eksik-bağlam sorunu yoktur;
            bundan önce, getirilmiş bir mevzuat bağlamı olmayan her taslak,
            hiç mevzuata atıfta bulunup bulunmadığına bakılmaksızın cezayı
            koşulsuz olarak ödüyordu.
        content_loss: Bu bir revizyon geçişiyse ve bir tane bulunduysa, bu
            taslak ile revize ettiği sürüm arasında tespit edilen bir
            silinme (bkz. ``app.ai.revision.elision.detect_content_loss``).
        judge_attempted: Yargıcın bu turda gerçekten çalışması gerekip
            gerekmediği (çağrı yerindeki ``judge_on``), kasıtlı olarak
            atlanmasının (FAST akıl yürütme seviyesi veya bunu tamamen
            devre dışı bırakan şirket/dağıtım ayarı) aksine. İkisini
            ayırt etmek önemlidir çünkü tek başına ``verdict is None``
            bunu yapamaz: *denenmiş* ama zaman aşımına uğrayan veya hata
            veren bir çağrı ``judge_available = False`` ayarlar ve artık
            ayrıca ``requires_human_approval``'ı da zorunlu kılar -- bundan
            önce, yargıç çağrısı bozulmuş bir taslak, yargıcın gerçekten
            temiz geçtiği bir taslakla aynı şekilde skorlanıp onaylanıyordu,
            kalite kapısını tam da en çok önem taşıdığı anda sessizce
            düşürüyordu. *Kasıtlı olarak atlanmış* bir yargıç
            (``judge_attempted=False``), yalnızca çalıştırması hiç
            istenmemiş bir kontrolü atladığı için her tek FAST-modu
            taslağında onayı zorunlu kılmamalıdır.
        style_findings: ``app.ai.verification.style_checks``'ten üslup/
            tutarlılık bulguları (kişi-hitabı tutarlılığı, tekrarlanan
            dolgu cümleleri, imza bloğunda bırakılmış çıplak bir yer
            tutucu etiketi), varsa. PII/mevzuat bulgularıyla aynı şekilde
            skora, yargıç bulgularıyla aynı şekilde ``repair_items``'a
            katlanır -- bunlar tam olarak mevcut tamir döngüsünün zaten
            düzeltmeyi bildiği türde hedefli, metinsel kusurlardır, bu
            yüzden bunlar için yeni bir döngü eklenmez.

    Returns:
        Draft grafiğinin router'ının üzerine hareket ettiği birleşmiş karar.
    """
    judge_available = verdict is not None

    repair_items: list[RepairItem] = [
        RepairItem(
            kind="unsupported_claim",
            source="deterministic",
            detail=f"{claim.kind}: '{claim.value}' -- {claim.explanation}",
            suggested_fix="Kaynakta doğrulanamayan bu ifadeyi kaldır veya yer tutucuyla değiştir.",
        )
        for claim in report.unsupported_claims
    ]
    repair_items.extend(
        RepairItem(
            kind="missing_structure",
            source="deterministic",
            detail=f"Eksik yapısal unsur: {label}",
            suggested_fix=f"Brief'teki ilgili bilgiyi kullanarak '{label}' unsurunu ekle.",
        )
        for label in report.missing_structure
    )
    # example_leaks'ten farklı olarak (asla tamire beslenmez -- bir tamir
    # geçişi tam olarak aynı stil örneklerini görür ve aynı sızıntıyı tekrar
    # üretebilir), bu düz bir silmedir: taslağın kendi Sayı: değerini,
    # olması gereken yer tutucuyla değiştir. Bir tamir geçişinin burada
    # sızıntıyı *tekrar üretebileceği* hiçbir şey yoktur -- gelen numara
    # bu satırda hiçbir şekilde bulunmamalıdır.
    repair_items.extend(
        RepairItem(
            kind="incoming_number_leak",
            source="deterministic",
            detail=(
                f"Taslağın kendi Sayı: satırı gelen evrakın sayısını taşıyor: "
                f"'{leak.value}'."
            ),
            suggested_fix=(
                "Kendi Sayı: satırını '[Belge Sayısı]' yer tutucusuyla değiştir; "
                "gelen evrakın sayısını yalnızca İlgi satırında bırak."
            ),
        )
        for leak in report.incoming_number_leaks
    )

    # Yalnızca bu fonksiyonun sorumlu olduğu her bulgu -- deterministik
    # doğrulayıcının zaten skorladığı her şey bunun yerine
    # `report.applied_rules`'da yaşar, burada yeniden türetilmek yerine
    # aşağıda birleştirilir.
    additional_findings: list[RuleFinding] = [
        RuleFinding(rule_id="pii_bulgusu", detail=finding.kind) for finding in (pii_findings or [])
    ]
    if correspondence_type_fallback:
        additional_findings.append(RuleFinding(rule_id="tur_tahmini"))
    if not has_context and cites_legislation:
        additional_findings.append(RuleFinding(rule_id="mevzuat_baglami_yok"))
    if content_loss is not None:
        additional_findings.append(RuleFinding(rule_id="icerik_kaybi", detail=content_loss.detail))
        repair_items.append(
            RepairItem(
                kind="content_loss",
                source="deterministic",
                detail=content_loss.detail,
                suggested_fix=content_loss.suggested_fix,
            )
        )
    additional_findings.extend(style_findings)
    repair_items.extend(
        RepairItem(
            kind=finding.rule_id,
            source="deterministic",
            detail=finding.detail,
            suggested_fix=_STYLE_FINDING_SUGGESTED_FIXES.get(
                finding.rule_id, "Belirtilen kusuru brief'teki mevcut bilgiyle düzelt."
            ),
        )
        for finding in style_findings
    )

    if judge_available:
        for finding in verdict.findings:
            if finding.severity == "critical":
                additional_findings.append(
                    RuleFinding(rule_id="yargic_kritik_bulgu", detail=finding.detail)
                )
            if finding.severity in {"critical", "major"} and finding.kind in REVISABLE_JUDGE_KINDS:
                repair_items.append(
                    RepairItem(
                        kind=f"judge:{finding.kind}",
                        source="judge",
                        detail=finding.detail,
                        suggested_fix=finding.suggested_fix,
                    )
                )
        if not verdict.company_rules_ok and verdict.violated_rule_ids:
            additional_findings.append(
                RuleFinding(
                    rule_id="sirket_kurali_ihlali",
                    detail=", ".join(verdict.violated_rule_ids),
                )
            )
        if not verdict.addresses_request:
            additional_findings.append(RuleFinding(rule_id="talebi_karsilamiyor"))
            repair_items.append(
                RepairItem(
                    kind="judge:talep",
                    source="judge",
                    detail="Taslak, gelen evrakın veya kullanıcının asıl talebini karşılamıyor.",
                    suggested_fix="Taslağı gelen evrakın/kullanıcının asıl talebine göre yeniden odakla.",
                )
            )

    additional_outcome = score_findings(additional_findings)
    # `report.confidence_score` zaten `max(0, 100 - ceza)` -- bu, elle
    # oluşturulmuş bir raporun (bir test, ya da `verify_draft`'ı atlayan
    # gelecekteki herhangi bir çağıran) doldurmamış olabileceği
    # `report.applied_rules`'dan yeniden türetmek yerine bu cezayı geri
    # elde eder.
    deterministic_penalty = 100.0 - report.confidence_score
    combined_penalty = round(deterministic_penalty + additional_outcome.total_penalty, 1)
    combined_score = max(0.0, round(100.0 - combined_penalty, 1))

    requires_human_approval = (
        report.requires_human_approval
        or additional_outcome.forces_approval
        or combined_score < MIN_AUTOMATED_CONFIDENCE_SCORE
        or (judge_attempted and not judge_available)
    )
    requires_revision = bool(repair_items)

    notes_parts = [report.evaluation_notes]
    if judge_available:
        notes_parts.append(f"Yargıç değerlendirmesi: {verdict.rationale}")
    else:
        notes_parts.append(
            "Kalite yargıcı kullanılamadı; yalnızca deterministik doğrulama sonucuna göre karar verildi."
        )
    notes = " ".join(part for part in notes_parts if part)

    return CombinedVerdict(
        combined_score=combined_score,
        requires_human_approval=requires_human_approval,
        requires_revision=requires_revision,
        repair_items=repair_items,
        missing_information=list(missing_information or []),
        judge_available=judge_available,
        notes=notes,
        applied_rules=[*report.applied_rules, *additional_outcome.applied_rules],
    )
