"""Çıktı tarafı guardrail geçidi: bir yanıt kullanıcıya ulaşmadan önceki son kontrol.

``app.ai.response.builder``'ı genelleştirir (o modül hâlâ
:func:`evaluate_response` etrafında ince, geriye dönük uyumlu bir sarmalayıcı
olarak var). Bu modülden önce, assist/chat yolundaki tek çıktı tarafı
kontrolü ``assert_no_prompt_leak``'ti -- bir yanıtın bu turda gerçekten
alınan içeriğe dayanıp dayanmadığını kontrol eden hiçbir şey yoktu, ve bir
yanıtın, isteği yapanın görmeye yetkili olmayabileceği bir belgeden kişisel
veri yansıtıp yansıtmadığını kontrol eden hiçbir şey yoktu. Bu, kullanıcının
"db'den saçma sapan bilgi vermemeliyiz" endişesinin doğrudan adlandırdığı
boşluktur: bir dayanaklılık hatası bir halüsinasyon riskidir, yetkisiz bir
PII yansıması bir sızıntı riskidir, ve bu modül var olmadan önce ikisi de
kontrol edilmiyordu.

Sırayla çalışan üç kontrol vardır, her biri verdikti daha ağır bir seviyeye
yükseltebilir:

1. ``assert_no_prompt_leak`` -- değişmedi, hâlâ anında sert bir engelleme.
2. Dayanaklılık (``app.ai.verification.draft_verifier.check_groundedness``,
   yeniden uygulanmadı, yeniden kullanıldı) -- dayanaksız bir iddia, yanıtın
   tamamının yerine geçmek yerine yanıttan kırpılarak kaldırılır, çünkü
   "kaç sayfa bu belge" sorusuna kısmen uydurulmuş bir yanıt, uydurulan
   kısım kaldırılmış haliyle genel bir reddedişle değiştirilmesinden daha
   kullanışlıdır.
3. PII sızıntısı (``app.ai.guardrails.pii.redact_pii``) -- yalnızca bu
   turda gerçekten bir belge eklendiğinde devreye girer (``sensitivity is
   not None``); kullanıcının konuşmaya kendisinin yazdığı PII şeklindeki bir
   metin parçası bu geçidin dokunduğu bir şey değildir. Bir belge eklendiğinde
   ve içeriği PII olarak yanıta yansıdığında, o metin parçası maskelenir.
   Eğer o belge kendisi gizlilik damgalıysa
   (``SensitivityAssessment.requires_review``) ve isteği yapanın yetkisi
   bunu kapsamıyorsa (veya RBAC aşaması gerçek bir yetki bağlayana kadar bu
   sistemin varsayılan-güvenli duruşu olan hiç yetki bilinmiyorsa), yanıt
   bunun yerine tamamen engellenir -- çözümlenmiş politikadaki "yetkisiz
   sızıntı" katmanı, sıradan "maskele ve devam et" katmanı değil.
"""

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.ai.guardrails.injection import GuardrailViolation, assert_no_prompt_leak
from app.ai.guardrails.llm_nuance import GuardrailJudgeVerdict
from app.ai.guardrails.pii import redact_pii
from app.ai.guardrails.sensitivity import SensitivityAssessment
from app.ai.policy import GuardrailPolicy, get_policy
from app.ai.verification.draft_verifier import check_groundedness
from app.core.enums.sensitivity_level import SensitivityLevel

logger = logging.getLogger(__name__)

FALLBACK_REPLY = (
    "Bu yanıt bir güvenlik kontrolünden geçemediği için gösterilemiyor. "
    "Sorunuzu farklı bir şekilde tekrar sorar mısınız?"
)

#: `check_groundedness`'in bu turun kaynaklarına dayandıramadığı bir iddia
#: yerine geçen Türkçe yer tutucu.
_UNGROUNDED_MARKER = "[doğrulanamayan ifade kaldırıldı]"

GateAction = Literal["pass", "redact", "block"]


class GateVerdict(BaseModel):
    """Çıktı geçidinin bir yanıt için verdiği karar."""

    action: GateAction = Field(description="'pass' | 'redact' | 'block'.")
    text: str = Field(description="Kullanıcıya gösterilecek metin.")
    reasons: list[str] = Field(default_factory=list)


def _redact_unsupported_claims(text: str, claims: list) -> str:
    """Her dayanaksız iddianın metnini bir kırpma işaretiyle değiştir.

    En iyi çaba string değiştirme: ``UnsupportedClaim.value``,
    ``draft_verifier._findall`` tarafından boşluk normalize edilmiştir ve bu
    yüzden orijinalde düzensiz boşluklama olduğunda ``text``'teki tam
    aralıkla bayt bazında eşleşmeyebilir. Bulunamayan bir iddia tahmin
    edilmek yerine olduğu gibi bırakılır -- yine de ``reasons``'da görünür,
    böylece kaçırılma sessiz değil, görünür olur.
    """
    redacted = text
    for claim in claims:
        if claim.value and claim.value in redacted:
            redacted = redacted.replace(claim.value, _UNGROUNDED_MARKER)
    return redacted


def evaluate_response(
    reply: str,
    *,
    source_materials: str = "",
    sensitivity: Optional[SensitivityAssessment] = None,
    requester_clearance: Optional[SensitivityLevel] = None,
    policy: Optional[GuardrailPolicy] = None,
    judge_verdict: Optional[GuardrailJudgeVerdict] = None,
) -> GateVerdict:
    """Üretilen bir yanıtı, kullanıcıya ulaşmadan önce doğrula ve kesinleştir.

    Args:
        reply: Ham, zaten üretilmiş yanıt metni.
        source_materials: Bu turun gerçekten yararlandığı güvenilir
            materyal -- araç sonuçları ve önbelleğe alınmış belge metni,
            birleştirilmiş. Boş olması "karşılaştırılacak kaynak yok"
            anlamına gelir; bu meşru bir durumdur (belgesiz ve araç
            çağrısı olmayan bir sohbet turu) ve her şeyi işaretlemek yerine
            basitçe hiçbir dayanaksız iddia bulmaz, çünkü *dayanaksız
            olunacak* hiçbir şeyi olmayan bir yanıt, uydurma kanıtı değildir.
        sensitivity: Bir belge eklendiğinde bu turun kaynak belgesinin
            girdi tarafı değerlendirmesi (bkz.
            ``app.ai.guardrails.sensitivity.assessment_from_analysis``).
            Belge yoksa None.
        requester_clearance: İsteği yapanın yetki seviyesi. None, "hiçbir
            yetki bilinmiyor" anlamına gelir -- RBAC aşaması kimliği
            doğrulanmış bir kullanıcıdan gerçek bir yetki bağlayana kadar
            bu her zaman geçerlidir, ve geçit bunu "her şeyi kapsıyor" ile
            aynı değil, "kaynağın seviyesini kapsamıyor" ile aynı şekilde
            ele alır. Güvenli tarafta başarısız ol, açık tarafta değil.
        policy: Karşı geçit yapılacak guardrail politikası. Varsayılan
            olarak süreç politikası.
        judge_verdict: Guardrail nüans katmanının bu yanıt hakkındaki
            görüşü (bkz.
            ``app.ai.guardrails.llm_nuance.judge_output_leakage``), zaten
            çağıran tarafından hesaplanmış -- bu fonksiyon kendi başına
            hiçbir I/O yapmaz, ``draft_graph.verify_node``'un
            ``verify_draft`` (senkron) ile ``judge_draft`` (asenkron)
            arasında koruduğu ayrımla aynı. Hakem devre dışıysa, bozulduysa
            veya sorulmadıysa (belge eklenmemiş, dolayısıyla sızıntı için
            yargılanacak bir şey yok) ``None``.

    Returns:
        Geçidin verdikti: ``pass`` (yanıt değişmedi), ``redact`` (yanıt
        yerinde düzenlendi), veya ``block`` (tamamen
        :data:`FALLBACK_REPLY` ile değiştirildi).
    """
    if not reply:
        return GateVerdict(action="pass", text=reply)

    active_policy = policy or get_policy().guardrail

    try:
        assert_no_prompt_leak(reply)
    except GuardrailViolation:
        logger.warning("Reply flagged by the prompt-leak guardrail; blocked.")
        return GateVerdict(action="block", text=FALLBACK_REPLY, reasons=["prompt_leak_or_injection_echo"])

    reasons: list[str] = []
    redacted = reply

    unsupported = check_groundedness(reply, source_materials=source_materials)
    if unsupported:
        redacted = _redact_unsupported_claims(redacted, unsupported)
        reasons.append(f"{len(unsupported)} doğrulanamayan ifade kaldırıldı")

    # PII işleme yalnızca bu turda gerçekten bir belge eklendiğinde devreye
    # girer (`sensitivity is not None`). Belge yoksa, tespit edilen
    # PII-şeklindeki bir metin parçası kullanıcının kendisinin konuşmaya
    # yazdığı bir şeydir -- bunu ona geri maskeleyerek göstermek koruyucu
    # değil, şaşırtıcıdır. Belge varsa, yanıtın yansıttığı herhangi bir
    # PII, gizlilik damgası taşısın taşımasın, o belgeye kadar izlenir.
    if sensitivity is not None:
        _preview, pii_findings = redact_pii(reply, confidence_floor=active_policy.pii_confidence_floor)
        # Hakem, hiçbir kalıbın yakalayamadığını yakalar: hiç harfiyen bir
        # PII string'i üretmeden bir kaynağın anlamını ifşa eden bir yanıt.
        # Yalnızca hakem judge_promotion_confidence eşiğini aştığında
        # güvenilir -- düşük güvenli bir "belki hassas" tahmini,
        # checksum ile doğrulanmış bir TCKN eşleşmesiyle aynı ağırlığı
        # taşımamalı ve asla tek başına bir yanıtı tamamen engelleyebilecek
        # bir güce sahip olmamalıdır (aşağıdaki engelleme koşuluna bakın):
        # yalın bir LLM tahmini, Görev'in bug raporunun adlandırdığı
        # açıklanamayan "mesajda PII var, kısıldı" yanlış pozitiflerini
        # üreten tam olarak budur.
        semantic_leak = bool(
            judge_verdict
            and judge_verdict.sensitive
            and judge_verdict.confidence >= active_policy.judge_promotion_confidence
        )

        if pii_findings or semantic_leak:
            cleared = (
                requester_clearance is not None
                and requester_clearance >= sensitivity.effective_level
            )
            # Sert engelleme HEM deterministik bir bulguyu (gerçek,
            # checksum/kalıp eşleşmeli bir PII metin parçası, asla sadece
            # hakem değil) HEM DE kaynak belgenin kendi gizlilik damgasını
            # (`sensitivity.requires_review`, yani GİZLİ/ÇOK GİZLİ) gerektirir.
            # Damgasız veya belirsiz bir belgeye karşı yalnızca-anlamsal bir
            # hakem sinyali, hiçbir zaman tamamen engellemek yerine aşağıdaki
            # daha yumuşak maskele/kısalt yollarına düşer.
            if sensitivity.requires_review and pii_findings and not cleared:
                rule_ids = sorted({finding.rule_id for finding in pii_findings if finding.rule_id})
                logger.warning(
                    "Reply blocked: %d PII finding(s) (rules=%s) against a "
                    "%s-marked source with insufficient/unknown requester clearance.",
                    len(pii_findings),
                    rule_ids,
                    sensitivity.effective_level.value,
                )
                kinds = sorted({finding.kind for finding in pii_findings})
                block_reason = f"yetkisiz kişisel veri sızıntısı tespit edildi ({', '.join(kinds)})"
                return GateVerdict(
                    action="block",
                    text=FALLBACK_REPLY,
                    reasons=reasons + [block_reason],
                )

            if pii_findings:
                # Gizlilik damgalı değil, veya isteği yapan bunun için
                # yetkili -- yine de derinlemesine savunma olarak PII'nin
                # kendisini maskele. `redacted`'e uygulanır (orijinal
                # `reply`'e değil), böylece yukarıdaki bir dayanaklılık
                # kırpması ile buradaki bir PII maskesi, biri diğerini
                # sessizce silmek yerine aynı çıktıda buluşur.
                redacted, _findings = redact_pii(redacted, confidence_floor=active_policy.pii_confidence_floor)
                kinds = sorted({finding.kind for finding in pii_findings})
                reasons.append(f"{len(pii_findings)} pii bulgusu maskelendi ({', '.join(kinds)})")
            elif semantic_leak:
                # Maskelenecek belirli bir metin parçası yok -- hakem,
                # konumlandırılabilir bir string değil, yanıtın anlamını
                # bir bütün olarak işaretledi, dolayısıyla tam yanıttan
                # daha dar kırpılacak bir şey yok. sensitivity.requires_review
                # ve pii_findings ikisi de geçerliyken asla buraya
                # ulaşılmaz (o, yukarıdaki engelleme dalıdır), dolayısıyla
                # bu ya damgasız bir kaynak ya da damgalı bir kaynağa karşı
                # yalnızca-anlamsal bir sinyaldir -- ikisi de tam bir
                # engellemeyi hak etmez.
                redacted = (
                    "Bu yanıt, kaynağın ifşa etmemesi gereken bir bilgiyi "
                    "içerebileceği için kısaltıldı."
                )
                reasons.append(f"llm-judge anlam bazlı hassasiyet: {judge_verdict.reason}")

    if redacted != reply:
        return GateVerdict(action="redact", text=redacted, reasons=reasons)

    return GateVerdict(action="pass", text=reply)


def classify_reason_kind(reasons: list[str]) -> str:
    """Bir :class:`GateVerdict`'in gerekçelerini tek bir
    ``GuardrailEventModel.kind``'e eşle.

    En iyi çaba: tek bir verdikt aynı çağrıda bir dayanaklılık kırpmasını
    ve bir PII maskesini birleştirebilir, ama denetim izinin satır başına
    tam olarak bir ``kind``'e ihtiyacı vardır -- bu, birleşik bir kararı
    tek değerli bir sütunda temsil etmeye çalışmak yerine en özgül/ciddi
    eşleşmeyi seçer.

    Args:
        reasons: Bir verdiktin ``reasons`` listesi.

    Returns:
        ``"leakage"``, ``"pii"``, ``"llm_judge"``, ``"groundedness"``,
        ``"injection"`` değerlerinden biri, veya daha özgül bir şey
        eşleşmediyse genel ``"output_gate"``.
    """
    joined = " ".join(reasons)
    if "yetkisiz" in joined:
        return "leakage"
    if "pii" in joined:
        return "pii"
    if "llm-judge" in joined:
        return "llm_judge"
    if "doğrulanamayan" in joined:
        return "groundedness"
    if "prompt_leak" in joined or "injection" in joined:
        return "injection"
    return "output_gate"
