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
2. Dayanaklılık (``app.ai.verification.draft_verifier.groundedness_report``,
   yeniden uygulanmadı, yeniden kullanıldı) -- yanıttan çıkarılan somut
   iddiaların getirilen kaynağa kadar izlenebilen payı çözülmüş politikanın
   ``output_groundedness_threshold``'unun altındaysa, yanıtın tamamının
   yerine geçmek yerine dayanaksız iddiayı İÇEREN CÜMLE komple çıkarılıp
   ``[Bu bilgi doğrulanamadığı için kaldırıldı]`` ile değiştirilir (çünkü
   uydurulan kısmı kaldırılmış bir yanıt, genel bir reddedişten daha
   kullanışlıdır) ve kaldırılan her cümle ``reasons``'a eklenerek
   kullanıcının gördüğü güvenlik uyarısında gösterilir.
   Eşiği geçen -- yani büyük ölçüde kaynaklı -- bir yanıt olduğu gibi bırakılır:
   yığında bulunan MCP mevzuat metninden alınmış ama token-örtüşme
   eşleştiricisinin ya da 6000 karakterlik alıntı sınırının kaçırdığı birkaç
   ifade, tüm yanıtı sansürlemeye yetmez. Bu kalıp-bazlı kontrolün yanı
   sıra, bir belge eklendiğinde ``groundedness_verdict`` (bkz.
   ``app.ai.guardrails.llm_nuance.judge_reply_groundedness``) DÜZ CÜMLE
   evrak halüsinasyonunu -- ne sayı ne tarih içeren, kalıpların hiç
   bakmadığı uydurma ifadeleri -- yüksek güvenle işaretlerse, o cümleler
   de aynı şekilde çıkarılır.
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
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.ai.guardrails.injection import GuardrailViolation, assert_no_prompt_leak
from app.ai.guardrails.llm_nuance import GroundednessJudgeVerdict, GuardrailJudgeVerdict
from app.ai.guardrails.pii import redact_pii
from app.ai.guardrails.sensitivity import SensitivityAssessment
from app.ai.policy import GuardrailPolicy, get_policy
from app.ai.verification.draft_verifier import _fold, groundedness_report
from app.core.enums.sensitivity_level import SensitivityLevel

logger = logging.getLogger(__name__)

FALLBACK_REPLY = (
    "Bu yanıt bir güvenlik kontrolünden geçemediği için gösterilemiyor. "
    "Sorunuzu farklı bir şekilde tekrar sorar mısınız?"
)

#: `check_groundedness`'in bu turun kaynaklarına dayandıramadığı bir iddia
#: içeren CÜMLENİN tamamı yerine geçen Türkçe yer tutucu. Kullanıcıya
#: gösterilen cevabın içine gömülür, dolayısıyla bir cümle gibi büyük harfle
#: başlar. Yalnızca tek bir sayıyı/tarihi işaretle değiştirmek, modelin o
#: değerin etrafına ördüğü uydurma bağlamın (ör. "... tarihli yazınıza
#: istinaden ...") cümlede kalmasına izin veriyordu; artık dayanaksız bilgi
#: içeren cümle komple çıkarılır.
_UNGROUNDED_MARKER = "[Bu bilgi doğrulanamadığı için kaldırıldı]"

#: Cümle sınırı: nokta/soru/ünlem/üç nokta + boşluk, ya da bir veya daha çok
#: satır sonu. Ham `re.split` ayırıcıyı düşürür; bu yüzden aşağıda cümleler
#: tek boşlukla yeniden birleştirilir -- bir sohbet yanıtı için kabul
#: edilebilir bir biçim kaybı.
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?…])\s+|\n+")

GateAction = Literal["pass", "redact", "block"]


class GateVerdict(BaseModel):
    """Çıktı geçidinin bir yanıt için verdiği karar."""

    action: GateAction = Field(description="'pass' | 'redact' | 'block'.")
    text: str = Field(description="Kullanıcıya gösterilecek metin.")
    reasons: list[str] = Field(default_factory=list)


def _redact_unsupported_claims(text: str, claims: list) -> tuple[str, list[str]]:
    """Dayanaksız iddia içeren her CÜMLEYİ bir kırpma işaretiyle değiştir.

    Modelin emin olmadığı bir bilgi, çevresine ördüğü cümleyle birlikte
    kaldırılır: tek başına "E-99..." sayısını maskelemek, "... sayılı ve
    ... tarihli yazınıza istinaden" gibi aynı ölçüde uydurma olan bağlamı
    yanıtta bırakıyordu.

    En iyi çaba: ``UnsupportedClaim.value``, ``draft_verifier._findall``
    tarafından boşluk normalize edilmiştir ve orijinalde düzensiz
    boşluklama varsa cümle metniyle bayt bazında eşleşmeyebilir. Hiçbir
    cümle iddiayı harfiyen içermiyorsa, dayanaksız değer yine de yanıtta
    kalmasın diye eski değer-bazlı değiştirmeye düşülür.

    Returns:
        ``(kırpılmış metin, kaldırılan özgün cümleler)``. İkinci öğe
        ``evaluate_response`` tarafından ``reasons``'a eklenir; böylece
        hangi cümlenin neden çıkarıldığı kullanıcıya gösterilen güvenlik
        uyarısında görünür.
    """
    values = [claim.value for claim in claims if claim.value]
    if not values:
        return text, []

    removed: list[str] = []
    rebuilt: list[str] = []
    matched_any = False
    for segment in _SENTENCE_SPLIT_PATTERN.split(text):
        if segment and any(value in segment for value in values):
            matched_any = True
            stripped = segment.strip()
            if stripped:
                removed.append(stripped)
            rebuilt.append(_UNGROUNDED_MARKER)
        elif segment:
            rebuilt.append(segment)

    if matched_any:
        return " ".join(rebuilt), removed

    # Whitespace-normalization mismatch -- no sentence contained a value
    # verbatim. Fall back to the old value-level replacement so the
    # ungrounded span is still removed even if its sentence isn't.
    redacted = text
    for value in values:
        if value in redacted:
            redacted = redacted.replace(value, _UNGROUNDED_MARKER)
    return redacted, []


#: LLM hakemi bir cümleyi birebir üretmeyebilir; eşleşmenin güvenilir olması
#: için katlanmış (folded) parçanın en az bu kadar karakter olması gerekir --
#: daha kısası masum bir cümleyle rastgele örtüşüp onu da silebilir.
_MIN_FLAGGED_FRAGMENT_LEN = 15


def _redact_flagged_sentences(text: str, fragments: list[str]) -> tuple[str, list[str]]:
    """LLM dayanaklılık hakeminin işaretlediği cümleleri yanıttan çıkar.

    ``_redact_unsupported_claims``'in kalıp tarafındaki ikizi, ama eşleşme
    katlanmış alt dizge içermesine göre yapılır: hakem cümleyi yanıtta
    geçtiği gibi birebir vermeyebilir (araya boşluk/noktalama farkı girebilir
    ya da ucundan kırpabilir).

    Args:
        text: Kullanıcıya gösterilecek (kısmen kırpılmış olabilen) yanıt.
        fragments: ``GroundednessJudgeVerdict.ungrounded_sentences`` --
            hakemin dayanaksız dediği cümleler.

    Returns:
        ``(kırpılmış metin, kaldırılan özgün cümleler)``. Hiçbir cümle
        eşleşmezse ``(text, [])`` -- çağıran bunu "hakem işaretledi ama
        konumlandıramadı" durumu olarak ele alır.
    """
    needles = [
        folded
        for fragment in fragments
        if len(folded := _fold(fragment)) >= _MIN_FLAGGED_FRAGMENT_LEN
    ]
    if not needles:
        return text, []

    removed: list[str] = []
    rebuilt: list[str] = []
    for segment in _SENTENCE_SPLIT_PATTERN.split(text):
        if not segment:
            continue
        folded_segment = _fold(segment)
        if folded_segment and any(
            needle in folded_segment or folded_segment in needle for needle in needles
        ):
            stripped = segment.strip()
            if stripped:
                removed.append(stripped)
            rebuilt.append(_UNGROUNDED_MARKER)
        else:
            rebuilt.append(segment)

    if not removed:
        return text, []
    return " ".join(rebuilt), removed


def evaluate_response(
    reply: str,
    *,
    source_materials: str = "",
    sensitivity: Optional[SensitivityAssessment] = None,
    requester_clearance: Optional[SensitivityLevel] = None,
    policy: Optional[GuardrailPolicy] = None,
    judge_verdict: Optional[GuardrailJudgeVerdict] = None,
    groundedness_verdict: Optional[GroundednessJudgeVerdict] = None,
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
        groundedness_verdict: LLM dayanaklılık hakeminin görüşü (bkz.
            ``app.ai.guardrails.llm_nuance.judge_reply_groundedness``), yine
            çağıran tarafından hesaplanmış. Yalnızca bir belge eklendiğinde
            sorulur; ``grounded=False`` ve güven ``judge_promotion_confidence``
            eşiğinin üzerindeyse, hakemin işaretlediği dayanaksız cümleler
            deterministik kalıp kontrolünün göremediği düz-cümle
            halüsinasyonu olsalar bile yanıttan çıkarılır. Devre dışı,
            bozulmuş veya belgesiz turda ``None``.

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

    # Dayanaklılık: yanıttan çıkarılan somut iddiaların (sayı/tarih/mevzuat/
    # kurum/tutar) getirilen kaynak materyale kadar izlenebilen payı, çözülmüş
    # politikanın `output_groundedness_threshold`'unun (bkz.
    # GuardrailPolicy) altına düşerse dayanaksız iddialar kırpılır. Eşiği
    # geçen bir yanıt olduğu gibi bırakılır: MCP mevzuat aracından gelen ve
    # yığında bulunan ama 6000 karakterlik alıntı sınırı ya da Türkçe hukuk
    # metninde token-örtüşme eşleştiricisinin kaçırdığı bir "madde 125" gibi
    # birkaç ifade yüzünden, büyük ölçüde kaynaklı bir yanıtın cümlelerinin
    # `[Bu bilgi doğrulanamadığı için kaldırıldı]` ile değiştirilmesini önler.
    unsupported, total_claims = groundedness_report(
        reply, source_materials=source_materials
    )
    grounded_share = 1.0 if total_claims == 0 else 1.0 - len(unsupported) / total_claims
    if unsupported and grounded_share < active_policy.output_groundedness_threshold:
        redacted, removed_sentences = _redact_unsupported_claims(redacted, unsupported)
        reasons.append(f"{len(unsupported)} doğrulanamayan ifade kaldırıldı")
        # Her kaldırılan cümle kendi `reasons` satırı olarak yüzeye çıkar --
        # kullanıcının gördüğü "Maskelendi" uyarısında hangi cümlenin neden
        # çıkarıldığı yazsın diye. Bunlar uydurma (dayanaksız) içeriktir, bir
        # kaynaktan gelen hassas değer değil; `emit_guardrail_event`'in "ham
        # hassas değer asla" kuralını ihlal etmez.
        for sentence in removed_sentences:
            reasons.append(f'Kaldırılan cümle: "{sentence}"')

    # LLM dayanaklılık hakemi: kalıp-bazlı kontrolün göremediği DÜZ CÜMLE
    # halüsinasyonunu yakalar (ör. "evrakta X biriminden söz ediliyor" -- ne
    # sayı ne tarih, ama evrakta böyle bir şey yok). Yalnızca yüksek güvenli
    # (>= judge_promotion_confidence, semantic-leak yükseltmesiyle aynı eşik)
    # bir "dayanaksız" verdikti işleme alınır -- yalın, düşük güvenli bir LLM
    # tahmini bir yanıtı tek başına değiştiremez.
    if (
        groundedness_verdict is not None
        and not groundedness_verdict.grounded
        and groundedness_verdict.confidence >= active_policy.judge_promotion_confidence
    ):
        flagged = [
            sentence
            for sentence in groundedness_verdict.ungrounded_sentences
            if sentence and sentence.strip()
        ]
        judged_text, judged_removed = _redact_flagged_sentences(redacted, flagged)
        if judged_removed:
            redacted = judged_text
            reasons.append(
                f"{len(judged_removed)} doğrulanamayan cümle kaldırıldı (model değerlendirmesi)"
            )
            for sentence in judged_removed:
                reasons.append(f'Kaldırılan cümle: "{sentence}"')
        elif redacted == reply:
            # Hakem "dayanaksız" dedi, konumlandırılabilir bir cümle veremedi
            # VE yukarıdaki kalıp-bazlı kontrol de bir şey kırpmadı -- yani
            # elde targeted olarak çıkarılacak bir şey yok. Semantic-leak
            # yolundaki gibi tüm yanıtı güvenli bir nota indir.
            redacted = (
                "Bu yanıt, yüklü evrakla doğrulanamayan bilgiler içerdiği için kaldırıldı. "
                "Lütfen sorunuzu evraka atıfla yeniden sorar mısınız?"
            )
            reasons.append(
                "model değerlendirmesi: doğrulanamayan evrak bilgisi "
                f"({groundedness_verdict.reason})"
            )
        # else: kalıp-bazlı kontrol zaten bir cümle kırpmış ve hakem büyük
        # olasılıkla aynı cümleyi işaret ediyor -- ikinci kez kırpacak bir
        # şey yok, tüm yanıtı da indirmeye gerek yok.

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
                reasons.append(f"{len(pii_findings)} PII bulgusu maskelendi ({', '.join(kinds)})")
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
    # Küçük harfe katlanır: reason dizeleri kullanıcıya gösterilen metinlerdir
    # ("PII", "Doğrulanamayan ...") ve büyük/küçük harf değişebilir; sınıflama
    # anahtar kelimeleri buna karşı dayanıklı kalmalı. "Kaldırılan cümle:"
    # satırları hariç tutulur -- bunlar modelin ürettiği serbest metindir ve
    # içlerinde geçen "pii"/"yetkisiz" gibi bir kelime kararın türünü
    # yanlış sınıflandırmamalı.
    joined = " ".join(
        reason for reason in reasons if not reason.startswith("Kaldırılan cümle:")
    ).lower()
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
