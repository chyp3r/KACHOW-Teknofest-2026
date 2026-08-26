"""Bir taslağın güven skorunun hesaplandığı tek, deterministik, denetlenebilir
kural tablosu.

Bu modülden önce skor, tek bir şeymiş gibi görünen iki ayrı şeydi: deterministik
bir ceza (desteklenmeyen iddialar + eksik yapı) ``0.6/0.4`` oranıyla hızlı
katmandaki bir LLM yargıcının kendi serbest 0-100 görüşüyle karıştırılıyordu
(``app.ai.verification.llm_judge.merge_verdicts``, refaktörden önce). Bundan
üç sorun doğuyordu:

1. **Tekrarlanabilir değil.** Aynı taslak iki kez skorlandığında iki farklı
   sayı dönebiliyordu -- yargıç ayağı bir model çağrısı ve ``temperature=0.0``
   olsa bile yerel bir model iki kez bit-birebir aynı çıktıyı garanti etmiyor.
2. **Süreksiz.** Yargıç çağrısı bozulduğunda (zaman aşımı, yankı, devre dışı),
   skor sessizce *sadece* deterministik ayağa *sıçrıyordu* -- 0.4 ağırlığı
   yeniden dağıtılmak veya hesaba katılmak yerine aritmetikten olduğu gibi
   kayboluyordu.
3. **Bazı gerçek kusurlar kapıyı hareket ettiriyor ama sayıyı etkilemiyordu.**
   Bir üslup-örneği sızıntısı veya doldurulmamış bir yer tutucu insan onayını
   zorunlu kılıyordu ama *skoru* dokunulmamış bırakıyordu (100.0); yani çok
   farklı nedenlerle incelemeye ihtiyaç duyan iki taslak -- biri tek bir
   sızmış kurum adı dışında kusursuz, diğeri doldurulmamış yer tutucularla
   dolu -- aynı güven sayısını gösteriyordu.

Bu modül, skoru adlandırılmış kural bulgularından oluşan bir listenin saf bir
fonksiyonu haline getirerek üç sorunu da çözer: aynı bulgular girer, her
zaman aynı skor çıkar. Yargıcın hâlâ bir işi var -- bir regex'in göremeyeceği
kusurları (kayıt/üslup, kapanış yönü, talebe uygunluk) işaretlemek -- ama
bunu artık ortalamaya katılan bir sayı yerine bulgulara katkıda bulunarak
yapıyor (``forces_approval`` üzerinden kapı geçişi sağlanır, skor ağırlığı
sıfırdır). Bir yargıç kararının bulgulara nasıl çevrildiğini görmek için
``app.ai.verification.llm_judge.merge_verdicts``'e bakın.
"""

from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field

RuleCategory = Literal["yapi", "dayanak", "gizlilik", "belirsizlik", "butunluk"]


@dataclass(frozen=True)
class ConfidenceRule:
    """Adlandırılmış, cezalandırılan bir kusur kategorisi.

    Attributes:
        id: Sabit kimlik. Her ``AppliedRule`` üzerinde raporlanır, böylece
            bir skorun tam olarak hangi kurallardan üretildiği izlenebilir --
            skoru bir kara kutu olmaktan çıkarıp denetlenebilir kılan şey
            budur.
        label: Kullanıcıya gösterilen Türkçe etiket (örn. "bu neden 62?"
            dökümünde).
        category: Görüntüleme için geniş gruplama -- yapısal, dayanaklılık,
            gizlilik, çözülmemişlik veya genel bütünlük.
        penalty: Düşülen puan. ``per_occurrence`` ayarlıysa her tekrar için,
            değilse bu kuralı kaç bulgunun tetiklediğinden bağımsız olarak
            tek bir sabit düşüş.
        per_occurrence: ``penalty``'nin bu kuralı tetikleyen bulgu sayısıyla
            çarpılıp çarpılmayacağı.
        cap: Bu kuralın kendi toplam düşüşü için tavan; böylece tek tür
            küçük sorunları çok olan bir taslak, yapısal olarak baştan
            bozuk olan bir taslaktan hâlâ daha yüksek puan alır -- bu iki
            başarısızlık modu aynı sayıya çökmemelidir. ``None`` tavansız
            demektir (sadece ``per_occurrence`` ile birlikte anlamlıdır;
            per_occurrence olmayan bir kuralın tek ``penalty``'si zaten
            kendi tavanıdır).
        forces_approval: Bu kuralın tek başına, sayısal skordan bağımsız
            olarak, taslak gönderilmeden önce bir insanı gerektirip
            gerektirmediği. Tek bir bulgu doğru olabilir (kopyalanan değer
            gerçekten doğrudur) ve yine de bu belirli yerde yasak olabilir
            (bkz. ``gelen_sayi_sizintisi``) -- bu tam olarak neden bunun
            skordan türetilmek yerine ayrı bir bayrak olduğunun nedenidir.
    """

    id: str
    label: str
    category: RuleCategory
    penalty: float
    per_occurrence: bool = False
    cap: Optional[float] = None
    forces_approval: bool = True


#: Kural tablosu. Zaten var olan yerlerde önceki deterministik ağırlıkları
#: birebir üretecek şekilde kalibre edilmiştir (beş yapısal kontrol,
#: desteklenmeyen-iddia cezası/tavanı) -- ve daha önce sadece onay kapısını
#: çevirip sayıyı hiç etkilemeyen kusurlara (``ornek_sizintisi``,
#: ``doldurulmamis_yer_tutucu`` ve ``merge_verdicts``'in deterministik
#: doğrulayıcının dışından kattığı her şey: ``pii_bulgusu``,
#: ``tur_tahmini``, ``mevzuat_baglami_yok``, ``icerik_kaybi``) ilk kez
#: gerçek bir skor ağırlığı verir. İki yargıç-kaynaklı kural tasarım gereği
#: sıfır ceza taşır -- yargıcın artık neden skoru değil sadece kapıyı
#: hareket ettirdiğini görmek için bu modülün docstring'ine bakın.
RULES: dict[str, ConfidenceRule] = {
    rule.id: rule
    for rule in (
        ConfidenceRule("eksik_konu_satiri", "Eksik Konu satırı", "yapi", 8.0),
        ConfidenceRule("eksik_sayi_satiri", "Eksik Sayı satırı", "yapi", 6.0),
        ConfidenceRule("eksik_tarih", "Eksik Tarih bilgisi", "yapi", 4.0),
        ConfidenceRule("eksik_kapanis", "Eksik kapanış ifadesi", "yapi", 8.0),
        ConfidenceRule("eksik_imza_blogu", "Eksik imza bloğu", "yapi", 4.0),
        ConfidenceRule(
            "dayanaksiz_iddia", "Kaynakta doğrulanamayan iddia", "dayanak",
            12.0, per_occurrence=True, cap=60.0,
        ),
        ConfidenceRule(
            "ornek_sizintisi", "Üslup referans örneğinden sızıntı", "dayanak",
            20.0, per_occurrence=True, cap=40.0,
        ),
        ConfidenceRule(
            "gelen_sayi_sizintisi", "Gelen evrakın sayısı kendi Sayı alanına sızmış",
            "dayanak", 25.0,
        ),
        # Taraf-modeli kuralları (bkz. app.ai.identity.parties ve
        # draft_verifier._check_identity_slot_leaks): karşı tarafın kendi
        # kimliğinin BİZİM kimlik alanlarımızdan birine sızması. İki ayrı id
        # var çünkü bunlar iki farklı karışıklık, aynı şeyin iki kez
        # yazılması değil -- hangisinin hangisi olduğunu görmek için
        # _check_identity_slot_leaks'in kendi docstring'ine bakın.
        ConfidenceRule(
            "gonderen_muhatap_karisikligi", "Gönderen kurum muhatap/antet karışıklığı",
            "butunluk", 30.0,
        ),
        ConfidenceRule(
            "karsi_taraf_kimlik_sizintisi", "Karşı tarafın kimliği bizim kimlik alanımızda",
            "dayanak", 30.0,
        ),
        # Üslup/kayıt kuralları (bkz. app.ai.verification.style_checks) --
        # kural id'leri diğer her kuralla birlikte burada tanımlanır, tespit
        # mantığı ise yapısal/dayanaklılık tespitinin draft_verifier.py'de
        # yaşadığı gibi kendi modülünde yaşar. İki örüntü-sezgisel kural
        # (kisi_tutarsizligi, dolgu_ifade) tek başına onayı zorunlu kılmaz:
        # yine de skordan puan götürürler ve onarım döngüsünü beslemeye
        # devam ederler (bkz. llm_judge.merge_verdicts), ama tek başına bir
        # sezgisel eşleşme, doğrulanmış bir kimlik/dayanaklılık kusurunun
        # yaptığı gibi aksi hâlde temiz bir taslağı insan incelemesinde
        # mahsur bırakmamalıdır. imza_blogu_uydurma tablonun varsayılanını
        # (forces_approval=True) korur -- imza bloğunda tam, çıplak-etiket
        # eşleşmesi, gelen_sayi_sizintisi/karsi_taraf_kimlik_sizintisi kadar
        # yüksek kesinliktedir.
        ConfidenceRule(
            "kisi_tutarsizligi", "Kişi/hitap tutarsızlığı", "butunluk",
            8.0, per_occurrence=True, cap=24.0, forces_approval=False,
        ),
        ConfidenceRule(
            "dolgu_ifade", "İçerik taşımayan dolgu ifadesi", "butunluk",
            4.0, per_occurrence=True, cap=16.0, forces_approval=False,
        ),
        ConfidenceRule(
            "meta_yorum", "Kendi analiz sürecine dair üst-yorum", "butunluk",
            4.0, per_occurrence=True, cap=16.0, forces_approval=False,
        ),
        ConfidenceRule("imza_blogu_uydurma", "İmza bloğunda uydurma/meta değer", "yapi", 10.0),
        ConfidenceRule(
            "doldurulmamis_yer_tutucu", "Doldurulmamış yer tutucu", "belirsizlik",
            5.0, per_occurrence=True, cap=30.0,
        ),
        ConfidenceRule("tur_tahmini", "Yazışma türü tahmin edildi", "belirsizlik", 10.0),
        ConfidenceRule("mevzuat_baglami_yok", "Doğrulanmış mevzuat bağlamı yok", "dayanak", 8.0),
        ConfidenceRule(
            "pii_bulgusu", "Kişisel veri bulgusu", "gizlilik",
            15.0, per_occurrence=True, cap=30.0,
        ),
        ConfidenceRule("icerik_kaybi", "İçerik kaybı (revizyonda elenmiş metin)", "butunluk", 25.0),
        # Tasarım gereği sıfır ceza -- bkz. modül docstring'i.
        ConfidenceRule("yargic_kritik_bulgu", "Kalite yargıcı: kritik bulgu", "butunluk", 0.0),
        ConfidenceRule("talebi_karsilamiyor", "Kalite yargıcı: talebi karşılamıyor", "butunluk", 0.0),
        # Aynı tasarım-gereği-sıfır-ceza mantığı: bir şirket kuralı ihlali
        # (app.ai.adapters.company_rules) onayı kapılar ve onarım döngüsünü
        # kendi JudgeFinding(kind="kurum_kurali") kayıtları üzerinden yönetir
        # (bkz. llm_judge.REVISABLE_JUDGE_KINDS); bu kural sadece ihlalin,
        # yargıcın eşleşen bir yapılandırılmış bulgu olmadan
        # violated_rule_ids raporladığı nadir turda bile, denetlenebilir
        # applied_rules dökümüne düşmesi için var.
        ConfidenceRule("sirket_kurali_ihlali", "Şirket kuralı ihlali", "butunluk", 0.0),
    )
}


@dataclass(frozen=True)
class RuleFinding:
    """Bir kuralın belirli bir kanıt üzerinde tetiklendiği tek bir örnek.

    Attributes:
        rule_id: ``RULES`` içinde bir anahtar olmalıdır.
        detail: Bu örneğin kısa, spesifik açıklaması (örn. desteklenmeyen
            tam değer), skorla birlikte görüntülenmek üzere.
        forces_approval: Ayarlandığında kuralın kendi varsayılanını bu
            belirli örnek için geçersiz kılar. Bugün tam olarak tek bir
            durum için var: gevşek (``strict=False``) bir yazışma türü
            altında desteklenmeyen bir iddia yine de skordan puan götürür,
            ama tek başına, sıkı bir tür altında yaptığı gibi bir insanı
            döngüye zorlamaz (bkz.
            ``app.ai.verification.draft_verifier.verify_draft``'ın kendi
            ``strict`` parametresi).
    """

    rule_id: str
    detail: str = ""
    forces_approval: Optional[bool] = None


class AppliedRule(BaseModel):
    """Bir kuralın nihai skora toplu katkısı.

    Bir çağıranın kullanıcıya "bu skor neden 62?" için gösterdiği şey --
    her bireysel bulgu için değil, en az bir kez tetiklenen her kural için
    bir satır. (Modülün geri kalanının aksine) bir pydantic modeli, çünkü
    bu modülün ``VerificationReport``'a geçen ve
    kalıcılaştırılan/serileştirilen
    (``draft_result["verification"]["applied_rules"]``) tek parçasıdır.
    """

    rule_id: str
    label: str
    category: RuleCategory
    occurrences: int = Field(ge=1)
    penalty_applied: float = Field(ge=0.0)
    forces_approval: bool


@dataclass(frozen=True)
class ConfidenceOutcome:
    """Bir bulgu listesinin ``RULES``'a karşı skorlanma sonucu.

    ``combine_outcomes``'un iki sonucu doğru şekilde toplayabilmesi için
    (sadece ``score`` değil) ``total_penalty`` açıkça taşınır -- ``100 - a``
    ve ``100 - b``, skorların kendisi toplanarak ``100 - (a + b)``'ye
    birleşmez, ancak önce cezalar toplanarak birleşir.
    """

    total_penalty: float
    forces_approval: bool
    applied_rules: tuple[AppliedRule, ...]

    @property
    def score(self) -> float:
        return max(0.0, round(100.0 - self.total_penalty, 1))


def score_findings(findings: list[RuleFinding]) -> ConfidenceOutcome:
    """Bir kural bulguları listesini ``RULES``'a karşı skorlar.

    Saf ve toplamlı: aynı bulgu listesi, onları neyin ürettiğinden veya
    hangi sırayla toplandığından bağımsız olarak her zaman aynı sonucu
    üretir -- modül docstring'inin geri kalanının "tekrarlanabilir değil"
    şikayetinin düzeltmeye çalıştığı özellik budur.

    Args:
        findings: Bir taslak için her kaynaktan (deterministik
            dayanaklılık/yapı, PII, yazışma türü çözümlemesi, mevzuat
            bağlamı, yargıç bulguları) toplanan her kural bulgusu.

    Returns:
        Birleştirilmiş sonuç.
    """
    by_rule: dict[str, list[RuleFinding]] = {}
    for finding in findings:
        by_rule.setdefault(finding.rule_id, []).append(finding)

    applied: list[AppliedRule] = []
    total_penalty = 0.0
    forces_approval = False

    for rule_id, occurrences in by_rule.items():
        rule = RULES[rule_id]
        count = len(occurrences)
        raw_penalty = rule.penalty * count if rule.per_occurrence else rule.penalty
        penalty = min(raw_penalty, rule.cap) if rule.cap is not None else raw_penalty
        total_penalty += penalty

        rule_forces = any(
            (occurrence.forces_approval if occurrence.forces_approval is not None else rule.forces_approval)
            for occurrence in occurrences
        )
        if rule_forces:
            forces_approval = True

        applied.append(
            AppliedRule(
                rule_id=rule_id,
                label=rule.label,
                category=rule.category,
                occurrences=count,
                penalty_applied=round(penalty, 1),
                forces_approval=rule_forces,
            )
        )

    return ConfidenceOutcome(
        total_penalty=round(total_penalty, 1),
        forces_approval=forces_approval,
        applied_rules=tuple(sorted(applied, key=lambda rule: rule.rule_id)),
    )


def combine_outcomes(*outcomes: ConfidenceOutcome) -> ConfidenceOutcome:
    """Ayrı ayrı hesaplanan sonuçları (örn. deterministik doğrulayıcının
    kendi geçişi ile ``merge_verdicts``'in PII/yazışma-türü/mevzuat/yargıç
    tarafından kattığı ek bulgular) tek bir sonuçta birleştirir.

    Args:
        outcomes: Daha önce hesaplanmış herhangi sayıda sonuç. Deterministik
            doğrulayıcının kendi kuralları ile ``merge_verdicts``'in
            eklediği kurallar arasında hiçbir kural id çakışması yoktur, bu
            yüzden düz bir toplam kesindir -- bu, ``score_findings``'in ham
            bulgular üzerinde yaptığı gibi kural id'sine göre yeniden
            gruplama gerektirmez.

    Returns:
        Birleştirilmiş sonuç.
    """
    return ConfidenceOutcome(
        total_penalty=round(sum(outcome.total_penalty for outcome in outcomes), 1),
        forces_approval=any(outcome.forces_approval for outcome in outcomes),
        applied_rules=tuple(rule for outcome in outcomes for rule in outcome.applied_rules),
    )
