"""Ana iş akışı için niyet (intent) çözümlemesi.

Sistemin akışları arasındaki seçim eskiden bir orkestratör prompt'una karşı
tam yapılandırılmış bir LLM çağrısıydı, ardından sıralı bir anahtar kelime
kademesi (cascade), ardından da üç basamaklı bir merdiven (lexical skor ->
semantik prototip -> hızlı katman modeli) oldu; burada hangi basamak önce
cevap verirse tek başına karar veriyordu ve diğerlerine hiç danışılmıyordu.
Merdiven, kademenin "tablo sırası kararı belirler" hatasını düzeltti, ama
kendi hatasını getirdi: lexical katmanın marj testi *her şeyi* kapıda
bekletiyordu, açık bir emir kipinin doğrudan sonuçlandırması gereken
mesajlar dahil. "Cevap yaz." ifadesi `draft=3.0` (açık bir istek) puanını
`assist=2.0` (belge eklenmemiş kısa mesaj yapısal ipucu) puanına karşı
alıyor -- 1.0'lık bir marj, eski merdivenin 1.2 eşiğinin hemen altında --
ve kullanıcıya asla sorulmaması gereken bir açıklayıcı soruya düşüyordu.
Marj testi, ikisi de aynı niyet-başına toplama katıldıktan sonra açık bir
emir kipini zayıf bir yapısal ipuçundan ayırt edemez; basamakları yeniden
sıralamak bunu düzeltmez, tıpkı kademeyi yeniden sıralamanın *onun*
hatasını hiç düzeltmemesi gibi.

Bu modül artık her sinyal kaynağını ayrı tutuyor (bkz.
:mod:`app.ai.workflows.router_features`) ve bunları, bir basamağın kendi iç
testinin diğerlerini kapıda bekletmesine izin vermek yerine, kalibre
edilmiş doğrusal bir modelle (:mod:`app.ai.workflows.router_fusion`,
katsayılar :mod:`app.ai.policy.router_weights` içinde, çevrimdışı olarak
``scripts/fit_router.py`` tarafından uydurulmuş) birleştiriyor. Sonuç,
niyet başına bir olasılıktır ve karar politikası şudur:

* ``tau_high`` değerinde veya üzerinde, **ve** yalnızca yapısal bir
  dolgudan fazlasına dayanıyorsa (bkz. ``_WEAK_EVIDENCE_IDS``) -- doğrudan
  sonuçlandırılır (``source="fused"`` / ``"fused_semantic"``). Yalnızca
  "mesaj kısaydı" veya "bir belge eklenmiş" ile desteklenen bir kazanım,
  kanıtla değil varsayılan olarak kazanılmıştır ve tartışmalı sayılır.
* Aksi halde, hızlı katman bir model kullanılabilir olduğunda -- artık
  kaynaşmış (fused) olasılık ne kadar düşük olursa olsun beraberliği
  bozması için çağrılır (``source="model"``). Zayıf bir kaynaşmış sinyal,
  tam olarak bir model çağrısının hakkını verdiği durumdur; merdiven bir
  kaynaşmaya dönüştüğünde çağrıyı atlamanın bir gerekçesi olmaktan çıktı
  (``tau_low`` altında atlamak, eski basamak-sırası tasarımından kalan bir
  artıktı; orada düşük bir *lexical* marj, henüz başka hiçbir şeyin
  çalışmadığı anlamına geliyordu -- burada her sinyal zaten çalışmış
  durumda). Modelin kendi ``unclear`` (belirsiz) kararı, yalnızca
  kaynaşmış ilk iki niyet birbirine ``clarify_margin`` kadar yakınsa *ve*
  kaynaşmış en yüksek olasılık kendisi ``tau_low`` altındaysa gerçek bir
  beraberlik olarak kabul edilir -- ve bir açıklayıcı soruya dönüştürülür;
  aksi halde kaynaşmış en yüksek niyet, modelin bozmayı reddettiği
  beraberliği kazanır (``source="model_unclear"``).
* Hiç model kullanılamıyorsa (yalnızca testlerde ve matcher/LLM'siz
  dağıtımlarda) -- ``tau_low`` hâlâ doğrudan bir açıklama isteğini
  eskisi gibi kapıda bekletir.

Kaynaşmadan (fusion) *sonra* çalışan ve bunların hepsini geçersiz
kılabilen tek bir şey vardır: alan kapsamı kapısı
(:mod:`app.ai.workflows.scope`). Kaynaşma, mesajın hangi akışı istediğini
yanıtlar; mesajın herhangi bir akış isteyip istemediğini yanıtlamanın bir
yolu yoktur ve buradaki her katman "Çiğköfte kampanyası için bir metin
yaz" ifadesini güvenle ``draft``'a yönlendirir, çünkü niyet açısından tam
olarak budur. Bu yüzden ``resolve_plan`` önce niyeti çözer, sonra onu kabul
eder -- bkz. ``_apply_scope_gate``.

İki şey kasıtlı olarak kaynaşmadan hiç geçmez:

* Bir **bileşik (compound)** istek (hem ``draft`` hem ``analyze``
  bağımsız olarak iyi kanıtlanmışsa), kaynaşma çalışmadan *önce* ham
  toplamsal lexical skorlar üzerinden kontrol edilir. Bir softmax'ın
  sınıfları, doğası gereği olasılık kütlesi için yarışır, dolayısıyla
  "iki okuma da bağımsız olarak güçlü" durumunu temsil edemez -- eğitimin
  bu durumları öğretmeye çalışmak yerine neden dışladığı için bkz.
  ``scripts/fit_router.py``'nin modül docstring'i.
* Bir **açık açıklayıcı sorunun cevabı**, mesaj hiç puanlanmadan önce,
  bekleyen sorunun kendi seçeneklerine göre çözülür -- aksi halde "evet,
  hazırla" gibi bir onay, (neredeyse) hiçbir şeyden yeniden puanlanmış
  olurdu.
"""

import logging
import time
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, Optional

from pydantic import BaseModel, Field

from app.core.config import settings
from app.observability.ai_metrics import ROUTER_STAGE_DURATION

from app.ai.context.compress import truncate_with_marker
from app.ai.llms.base import BaseLLMClient
from app.ai.policy import get_policy
from app.ai.policy.router_weights import ROUTER_WEIGHTS
from app.ai.session.focus import SessionFocus
from app.ai.workflows.intent_rules import CONTINUATION_SURFACES, Intent
from app.ai.workflows.intent_scorer import COMPOUND_FLOOR, IntentScores, normalize, score_intents
from app.ai.workflows.router_features import RouterSignals, extract_features
from app.ai.workflows.router_fusion import predict_proba
from app.ai.workflows.scope import ScopeVerdict, resolve_scope

if TYPE_CHECKING:  # pragma: no cover - yalnızca içe aktarma döngüsünden kaçınmak için
    from app.ai.semantic.prototype_matcher import PrototypeMatcher

logger = logging.getLogger(__name__)

__all__ = [
    "Intent",
    "IntentOutput",
    "PLAN_BY_INTENT",
    "PlanDecision",
    "classify_intent_with_model",
    "normalize",
    "resolve_plan",
]

#: Niyet başına adım dizileri.
#:
#: Draft akışında ayrı bir ``rag`` adımının bulunmadığına dikkat edin.
#: Sınıflandırma alt grafiği zaten belge için mevzuatı getirip
#: ``mevzuat_documents`` içine koyuyor; RAG grafiğini sonradan çalıştırmak
#: aynı getirmeyi ekstra bir sorgu-yeniden-yazma LLM çağrısının arkasında
#: tekrarlıyor ve ilk sonucu çöpe atıyordu.
#:
#: ``revise``, kasıtlı olarak ``draft``'ın bir varyantı değil, kendi başına
#: tek adımlı bir plandır: sınıflandırmayı asla yeniden çalıştırmaz ve
#: mevzuatı asla yeniden getirmez, yalnızca zaten aktif olan taslağın
#: hedeflenen kısmını yeniden yazan tek bir LLM çağrısı yapar (bkz.
#: ``app.ai.workflows.revise``). ``clarify`` hiçbir şeye mal olmaz --
#: ``PlanDecision.clarification``'dan bir soru render eder ve turu orada
#: bitirir.
#: ``refuse``, yetenek manifestosunu render edip turu bitiren tek
#: deterministik bir adımdır (bkz. ``planning_graph._step_refuse``).
#: Kasıtlı olarak hiçbir model çağrısına mal olmaz -- bir ret bir üretim
#: (generation) olmamalıdır, yoksa konu dışı metni yazmaması az önce
#: söylenen model, onu yine de yazmak için bir fırsat daha bulur.
#: `transfer` (Faz 4, #201) kasıtlı olarak bunlardan biri DEĞİLDİR --
#: hiçbir zaman çözülebilir bir üst düzey niyet değildir. Bu, assist
#: adımının kendi modelinin konuşma sırasında çağırabileceği bir araçtır
#: (`app.ai.tools.transfer_tools.build_transfer_tools`, `_run_assist`
#: içinde bağlanmış), tıpkı `search_document` gibi; planlayıcı bir mesajı
#: ona hiçbir zaman doğrudan yönlendirmez.
#: `transfer_execute` (bunun hâlâ yol açabileceği tek adım, bir insan
#: onayladıktan sonra), araç gerçekten bekleyen bir öneri ürettiğinde
#: `_step_assist` tarafından `plan_steps`'e dinamik olarak eklenir -- bkz.
#: bunun için `step_graph.STEP_SPECS`'in kendi girdisi.
PLAN_BY_INTENT: dict[str, list[str]] = {
    "draft": ["classification", "brief", "draft", "routing"],
    "analyze": ["classification"],
    "assist": ["assist"],
    "revise": ["revise"],
    "clarify": ["clarify"],
    "refuse": ["refuse"],
}

REASONING_BY_INTENT: dict[str, str] = {
    "draft": "Resmî yazı talebi tespit edildi: evrak analizi, taslak üretimi ve birim yönlendirmesi çalıştırılacak.",
    "analyze": "Evrak analizi talebi tespit edildi: sınıflandırma ve uygunluk denetimi çalıştırılacak.",
    "assist": "Genel bir soru veya belge hakkında bir soru tespit edildi: asistan yanıtı hazırlanacak.",
    "revise": "Mevcut taslakta bir revizyon talebi tespit edildi: hedefli düzeltme çalıştırılacak.",
    "clarify": "İstek belirsiz olduğu için kullanıcıya açıklayıcı bir soru soruldu.",
    "refuse": "İstek sistemin görev alanı dışında kaldığı için hiçbir üretim akışı çalıştırılmadı.",
}

#: Kanonik çalıştırma sırası; iki niyetin adım listelerini birleştirirken
#: birleştirmenin kendi sırasını uydurmasına izin vermemek için kullanılır.
#: ``clarify`` kasıtlı olarak yoktur: bileşik bir planda asla görünmez
#: (bkz. ``COMPOUND_PAIR``).
STEP_ORDER: tuple[str, ...] = (
    "classification",
    "brief",
    "draft",
    "revise",
    "routing",
    "assist",
)

#: Her niyetin Türkçe açıklaması; bir açıklayıcı soruyu "revise" gibi
#: dahili bir isim yerine kullanıcının tanıyacağı terimlerle ifade etmek
#: için kullanılır.
_CLARIFY_LABELS: dict[str, str] = {
    "draft": "bir taslak hazırlama isteği",
    "revise": "mevcut taslakta bir revizyon isteği",
    "analyze": "bir evrak analizi isteği",
    "assist": "genel bir soru veya sohbet",
}

#: Açıklayıcı bir soruya çıplak bir onay, onun en önde gelen seçeneğini
#: seçer -- devam kuralının *kararlı* bir turu onaylamak için zaten
#: kullandığı aynı kısa-onay kelime dağarcığı, burada *kararsız* bir turu
#: onaylamak için yeniden kullanılıyor.
_AFFIRMATIVE_SURFACES = CONTINUATION_SURFACES

#: Tek bir plan olarak çalıştırmaya değer tek çift. ``draft`` zaten
#: ``classification`` ile başlıyor, dolayısıyla "incele ve cevap yaz" iki
#: değil tek bir hattır. Tartışmalı diğer her çift gerçek bir belirsizliktir
#: ve bunun yerine yükseltilir (escalate) -- ``assist``'i ``draft``'a
#: birleştirmek hem konuşarak cevap verir *hem de* bir taslak hazırlama
#: çalıştırması başlatır ki bu, mesajın ne şekilde okunursa okunsun
#: istediği şey değildir.
COMPOUND_PAIR = frozenset({"draft", "analyze"})

#: Niyete özgü sinyal değil, yapısal dolgu olan kanıt id'leri -- "bir
#: belge eklenmişken bir soru geldi" ifadesi mesajın şeklini tarif eder,
#: ne istediğini değil, ve *farklı* bir niyetin (örn. bir taslak da açıksa
#: `revise`) gerçekte sorulan şey olup olmadığı hakkında hiçbir şey
#: söylemez. Bkz. `intent_scorer.score_intents`'in
#: `assist.question_with_document` kuralı. Kazanan niyeti *yalnızca* bu
#: kümedeki id'lerle desteklenen kaynaşmış bir karar, doğrudan
#: sonuçlandırılmak yerine modele yükseltilir -- bkz.
#: `_has_only_weak_evidence`.
#:
#: `assist.short_message` kasıtlı olarak burada yok: bir taslak açıkken
#: zaten tetiklenemiyor (`intent_scorer.score_intents` bunu
#: `not has_active_draft` üzerinden kapıyor; kısalığının "giriş kısmını
#: yumuşat" gibi gerçek bir kısa revizyon talimatından daha yüksek puan
#: aldığı tek durum buydu). Açık bir taslak yokken ve başka hiçbir şey
#: eklenmemişken, yalnızca kendi kısalığıyla desteklenen kısa bir mesaj --
#: örneğin devam ettirilemeyen bir turdan sonra çıplak bir "Evet" --
#: kaybedebileceği rakip bir okumaya sahip değildir, dolayısıyla bu
#: kapının koruyacağı hiçbir şey kalmaz; yine de yükseltmek, belirsiz
#: olmayan bir "başka hiçbir şey uygulanmıyor" varsayılanını gereksiz bir
#: soruya çevirmekten başka bir işe yaramaz.
_WEAK_EVIDENCE_IDS = frozenset({"assist.question_with_document"})

#: Model tarafından bozulan bir beraberlik için ve modelin kendi çağrısı
#: başarısız olduğunda kullanılan güvenli varsayılan için raporlanan
#: güven değeri. Kaynaşma katmanının kendi `top_probability`'si değil (o
#: sayı kaynaşmanın belirsizliğidir, bunu ilk etapta bir beraberlik yapan
#: tam olarak o şeydir -- onu *modelin* güveni olarak geri raporlamak
#: döngüsel olurdu) ve gerçek model çıktısına karşı da ölçülmemiştir,
#: çünkü bu, varsayılan, tamamen çevrimdışı `make eval`'in kasıtlı olarak
#: hiç yapmadığı canlı bir Ollama çağrısı gerektirir (bkz.
#: `evaluation.harness.intent_suite`'in modül docstring'i). `make eval-llm`
#: (`evaluation/harness/intent_suite.py::run_with_model`) bu sabitin
#: sonunda yerini alması gereken isteğe bağlı, opt-in ölçümdür.
_MODEL_CONFIDENCE = 0.75

#: Hızlı katman model çağrısına verilen ham turlar, en yenisi sonda.
#: Kasıtlı olarak küçük -- bu bir etiketleme çağrısıdır, assist adımının
#: kendi üretimi değil, dolayısıyla yalnızca kısa bir mesajın
#: belirsizliğini gidermeye yetecek kadar konuşma şekline ihtiyacı var
#: ("selam" bir revizyon turundan sonra mı yoksa sessizlikten sonra mı),
#: assist adımının bütçelediği tam pencereye değil.
_MODEL_HISTORY_TURNS = 4


class PlanDecision(NamedTuple):
    """Bir kullanıcı mesajı için çözümlenmiş çalıştırma planı.

    Attributes:
        steps: Sırayla çalıştırılacak alt iş akışları.
        intent: Çözümlenmiş niyet.
        reasoning: Kullanıcıya gösterilen Türkçe gerekçe.
        source: Hangi mekanizmanın karar verdiği. Birleştirilmiş bir plan
            için ``compound`` (bkz. ``COMPOUND_PAIR``), bekleyen bir sorunun
            cevabı bunu sonuçlandırdığında ``clarification_resolved``,
            kalibre edilmiş kaynaşma olasılığı ``tau_high``'ı kendi başına
            geçtiğinde ``fused``, beraberliği bozmak için hızlı katman
            modeline ihtiyaç duyulduğunda ``model``/``model_failed``, bu
            bile mümkün ya da gerekli olmadığında ``clarify``.
        confidence: Kararın kendi güveni, [0, 1] aralığında. ``fused`` ve
            ``clarify`` için bu, kaynaşma katmanının kazanan/önde giden
            niyet için kendi kalibre edilmiş olasılığıdır -- kaynaşma
            öncesi merdivenin aynı alan altında raporladığı üç uyumsuz
            ölçekten (lexical marj, ham kosinüs benzerliği, sabit
            kodlanmış bir 1.0) farklı olarak artık her kaynak arasında
            doğrudan karşılaştırılabilir.
        evidence: Tetiklenen lexical kuralların id'leri, varsa. Üretimdeki
            bir kararın sonradan açıklanabilmesi için kaydedilir.
        alternatives: Kaynaşmış olasılıklarıyla birlikte, en yükseği önde,
            ikinci sıradaki niyetler.
        clarification: Yalnızca ``intent == "clarify"`` iken ayarlanır: soru
            ve seçenekleri (``[{"intent", "label"}, ...]``),
            ``SessionFocus.pending_clarification`` içine yazılır ki bir
            sonraki turun cevabı hiçbir şeyden yeniden puanlanmak yerine
            aynı seçeneklere göre çözülebilsin (bkz.
            ``_try_resolve_pending_clarification``).
        scope_reason: Bu turu hangi alan-kabul kuralının sonuçlandırdığı
            (bkz. ``app.ai.workflows.scope.ScopeReason``). Yalnızca
            reddedilenlerde değil, *her* kararda kaydedilir, böylece "bu
            neden çalıştı" da "bu neden reddedildi" kadar izlenebilir olur.
    """

    steps: list[str]
    intent: Intent
    reasoning: str
    source: str
    confidence: float = 1.0
    evidence: tuple[str, ...] = ()
    alternatives: tuple[tuple[str, float], ...] = ()
    clarification: Optional[dict[str, Any]] = None
    scope_reason: str = ""


class IntentOutput(BaseModel):
    """Tek etiketli niyet sınıflandırması, yalnızca gerçekten tartışmalı mesajlar için kullanılır.

    Dört değil beş etiket: ``unclear`` gerçek, birinci sınıf bir cevaptır,
    bir hata yolu değil. Bundan önce modelin seçebileceği yalnızca
    ``draft``/``analyze``/``assist`` vardı -- kaynaşma katmanının zaten
    tartışmalı bulduğu bir mesaj hakkında sorulduğunda "ben de emin
    değilim" deme yolu yoktu ve tahminini üç kutudan birine zorlamak
    zorundaydı, bunlardan birini (``revise``) adlandıramadığı halde bile.
    """

    intent: Literal["draft", "analyze", "assist", "revise", "unclear"] = Field(
        description=(
            "Kullanıcının niyeti. draft: resmi yazı/taslak hazırlanması isteniyor. "
            "analyze: evrakın analiz edilmesi isteniyor. "
            "revise: mevcut (aktif) taslakta bir değişiklik isteniyor. "
            "assist: yukarıdakilerin hiçbiri; genel sohbet veya yüklü bir belge hakkında soru. "
            "unclear: bunlardan hangisi olduğu senin için de belirsizse, tahmin etme -- "
            "bunu seç."
        )
    )


def _merge_steps(intents: frozenset[str]) -> list[str]:
    """İki niyetin adım listelerinin birleşimini alır, kanonik çalıştırma sırasını korur.

    Args:
        intents: Birleştirilecek niyetler.

    Returns:
        Birleştirilmiş adım listesi.
    """
    merged = {step for intent in intents for step in PLAN_BY_INTENT[intent]}
    return [step for step in STEP_ORDER if step in merged]


def _has_only_weak_evidence(intent: str, lexical: IntentScores, has_active_draft: bool) -> bool:
    """``intent``'in kazanımının yalnızca yapısal dolguya mı dayandığı.

    Args:
        intent: Kaynaşma katmanının kazanan niyeti.
        lexical: Mesajın lexical kanıtı.
        has_active_draft: Bu turda bir taslağın açık olup olmadığı.
            ``assist.question_with_document``'a güvenmemenin tek sebebi,
            aynı mesajın bir `revise` okumasını bastırıyor olabilmesidir
            ("Bu daha iyi mi görünüyor?" hem bir belge *hem de* açık bir
            taslakla) -- açık bir taslak yokken mesajın makul olarak
            başka anlama gelebileceği bir şey yoktur, dolayısıyla çıplak
            bir belge-sorusu kazanımı, çözülecek hiçbir şeyi olmayan bir
            yükseltme gidiş-dönüşüne gönderilmek yerine doğrudan muaf
            tutulur. `intent_scorer.score_intents` aynı gerekçeyi zaten
            `assist.short_message`'a, bunun yerine kural düzeyinde
            ``not has_active_draft`` üzerinden kapılayarak uyguluyor.

    Returns:
        *Bu niyet için* tetiklenen her lexical kural ``_WEAK_EVIDENCE_IDS``
        içindeyse True -- hiçbirinin tetiklenmediği durum dahil, yani
        kazanımın yalnızca semantik katmandan veya kaynaşma modelinin
        önselinden (prior) geldiği, bir dolgu kuralından bile daha zayıf
        olduğu durum.
    """
    if intent == "assist" and not has_active_draft:
        return False
    strong = [
        rule_id
        for rule_id in lexical.evidence
        if rule_id.startswith(f"{intent}.") and rule_id not in _WEAK_EVIDENCE_IDS
    ]
    return not strong


def _try_compound(lexical: IntentScores) -> Optional[PlanDecision]:
    """Ham lexical skorlardan bileşik bir draft+analyze isteğini tespit eder.

    Kaynaşma hiç çalışmadan önce kontrol edilir -- bir softmax'ın bu
    durumu neden toplamsal bir skorun temsil edebildiği şekilde temsil
    edemediği için modül docstring'ine bakın.

    Args:
        lexical: Mesajın zaten puanlanmış lexical kanıtı.

    Returns:
        Birleştirilmiş bir ``draft``+``analyze`` planı, ya da mesaj her
        ikisi için de bağımsız olarak iyi kanıtlanmamışsa None.
    """
    present = {intent: score for intent, score in lexical.ranked if score >= COMPOUND_FLOOR}
    if not COMPOUND_PAIR.issubset(present):
        return None

    return PlanDecision(
        steps=_merge_steps(COMPOUND_PAIR),
        intent="draft",
        reasoning=(
            REASONING_BY_INTENT["draft"] + " (hem inceleme hem taslak istendiği tespit edildi)"
        ),
        source="compound",
        confidence=round(lexical.confidence, 3),
        evidence=tuple(lexical.evidence),
        alternatives=tuple(lexical.ranked[1:3]),
    )


def _fused_decision(
    intent: str,
    probs: dict[str, float],
    ranked: list[tuple[str, float]],
    lexical: IntentScores,
    source: str,
) -> PlanDecision:
    """Kaynaşma olasılığının sonuçlandırdığı bir niyet için karar oluşturur."""
    return PlanDecision(
        steps=list(PLAN_BY_INTENT[intent]),
        intent=intent,  # type: ignore[arg-type]
        reasoning=REASONING_BY_INTENT[intent],
        source=source,
        confidence=round(probs[intent], 3),
        evidence=tuple(lexical.evidence),
        alternatives=tuple(ranked[1:3]),
    )


def _build_clarify_decision(ranked: list[tuple[str, float]]) -> PlanDecision:
    """Kaynaşmış olasılıklardan bir açıklayıcı soru oluşturur.

    Kaynaşmış dağılım sonuçlandırmak için çok düz olduğunda (``tau_low``
    altında) veya tartışmalıydı ve beraberliği bozacak bir model
    kullanılamadığında çağrılır (bkz. ``resolve_plan``). Bu fonksiyonun
    kaynaşma öncesi merdivendeki versiyonundan farklı olarak, ele alınacak
    "yalnızca tek bir aday var" özel durumu yoktur: softmax her zaman dört
    niyetin tamamı üzerinde tam bir dağılım üretir, dolayısıyla sorunun
    ikinci seçeneği olarak sunulacak bir ikinci sıradaki her zaman
    mevcuttur.

    Args:
        ranked: Kaynaşmış olasılığa göre sıralanmış niyetler, en yükseği
            önde.

    Returns:
        Soruyu ve seçeneklerini ``clarification`` içinde taşıyan bir
        ``clarify`` kararı.
    """
    top_two = ranked[:2]
    options = [
        {"intent": intent, "label": _CLARIFY_LABELS.get(intent, intent)}
        for intent, _ in top_two
    ]
    question = (
        f"Bu isteğinizi {options[0]['label']} olarak mı, yoksa "
        f"{options[1]['label']} olarak mı değerlendirmemi istersiniz?"
    )

    return PlanDecision(
        steps=list(PLAN_BY_INTENT["clarify"]),
        intent="clarify",
        reasoning=REASONING_BY_INTENT["clarify"],
        source="clarify",
        confidence=round(top_two[0][1], 3),
        evidence=(),
        alternatives=tuple(top_two),
        clarification={"question": question, "options": options},
    )


def _try_resolve_pending_clarification(
    message: str, pending: Optional[dict[str, Any]]
) -> Optional[PlanDecision]:
    """Bir cevabı, eğer soruyu yanıtlıyorsa, açık bir açıklayıcı soruya göre çözer.

    Kaynaşma kararı hiç çalışmadan önce kontrol edilir: "taslak mı,
    revizyon mu?" sorusuna verilen açık bir cevap hiçbir şeyden yeniden
    puanlanmamalıdır; burada kısa bir cevap kendi başına kolayca
    düşük-sinyalli olarak okunabilir.

    Args:
        message: Kullanıcının yeni mesajı.
        pending: ``SessionFocus.pending_clarification``, ya da açık
            hiçbir şey yoksa ``None``/boş.

    Returns:
        Cevabın seçtiği seçenek için bir karar, ya da mesaj soruyu açıkça
        yanıtlamıyorsa ``None`` -- çağıran daha sonra normal karara düşer
        ve eskimiş açıklama, alakasız yeni bir mesaja zorlanmak yerine
        geçersiz kılınır.
    """
    if not pending:
        return None
    options = pending.get("options") or []
    if not options:
        return None

    normalized = normalize(message)
    words = normalized.split()

    selected: Optional[str] = None
    via_affirmative = False
    if len(words) <= 4 and any(
        f" {surface} " in f" {normalized} " for surface in _AFFIRMATIVE_SURFACES
    ):
        selected = options[0]["intent"]
        via_affirmative = True
    else:
        # Kullanıcının makul biçimde geri yansıtabileceği Türkçe etikete
        # göre eşleştirilir ("Bir taslak hazırlama isteği."), dahili
        # İngilizce niyet adına göre değil -- bu bir Türkçe cevapta hiç
        # görünmez, dolayısıyla onu kontrol etmek yalnızca fazladan bir
        # yedek varmış gibi yanlış bir izlenim veriyordu.
        for option in options:
            label = option.get("label") or ""
            if label and normalize(label) in normalized:
                selected = option.get("intent")
                break

    if not selected or selected not in PLAN_BY_INTENT:
        return None

    if via_affirmative:
        chosen_label = next(
            (option["label"] for option in options if option["intent"] == selected), selected
        )
        suffix = f" ({chosen_label} olarak ilerliyorum)"
    else:
        suffix = " (açıklayıcı soruya verilen yanıtla çözüldü)"

    return PlanDecision(
        steps=list(PLAN_BY_INTENT[selected]),
        intent=selected,  # type: ignore[arg-type]
        reasoning=REASONING_BY_INTENT[selected] + suffix,
        source="clarification_resolved",
        confidence=1.0,
        evidence=("clarification.resolved",),
    )


async def classify_intent_with_model(
    llm_client: BaseLLMClient,
    message: str,
    document_id: Optional[str],
    focus: Optional[SessionFocus] = None,
    previous_intent: Optional[str] = None,
    history: Optional[list[dict[str, str]]] = None,
) -> str:
    """Tek etiketli bir model çağrısıyla bir kaynaşma beraberliğini bozar.

    Args:
        llm_client: Hızlı katman LLM istemcisi.
        message: Kullanıcının mesajı.
        document_id: Eklenmiş bir belge varsa onun depolama yolu.
        focus: Bilindiğinde oturumun kalıcı odağı -- zaten açık bir
            taslak olup olmadığını ve türünü (artı metninden bir alıntı
            ve oturumun birikmiş amacını) sağlar; bu, çıplak bir
            etiketleme çağrısının başka türlü göremeyeceği bir bağlamdır.
            Kaynaşma katmanı da `has_active_draft`'ı bir özellik değeri
            olarak görür, ama bu prompt aynı gerçeği kelimelerle açıkça
            yazmak zorundadır -- ve kaynaşma katmanından farklı olarak
            taslağın *ne dediğini* de gösterebilir, ki bu tam olarak "son
            cümle bana biraz sert geldi" gibi bir mesajın karşısında
            çözülmesi gereken şeydir.
        previous_intent: Bilindiğinde önceki tur için çözümlenmiş niyet.
        history: Bilindiğinde bu konuşmanın son birkaç ham turu, en
            eskisi önde. Bu çağrı artık dar bir orta bant yerine
            kaynaşmayla tartışmalı bulunan *her* mesaj için yedek yol
            olduğundan, assist adımının zaten aldığı türden aynı
            konuşmasal temellendirmeye ihtiyaç duyar -- çıplak bir
            "selam" veya "yarın devam ederiz" ancak kendinden önceki
            tur ışığında sohbet olarak okunur.

    Returns:
        ``PLAN_BY_INTENT``'in anahtarlarından biri, ya da
        ``"unclear"``/``"model_failed"`` -- çağıranın sonucu bir plan
        olarak ele almadan önce işlemesi gereken iki ayrı niyet-olmayan
        değer: ``"unclear"`` modelin kendi bilinçli yargısıyla o da
        bilmediğidir (bkz. ``IntentOutput``); ``"model_failed"`` çağrının
        kendisinin bozulduğu (zaman aşımı, hatalı biçimli çıktı, denemeler
        tükendi) ve hiçbir zaman bir yargı üretmediği anlamına gelir. İkisini
        birbirine karıştırmak, gerçek bir kesintiyi modelin dürüst
        belirsizliğinin ürettiği aynı etiketin arkasına gizlerdi.
    """
    from app.ai.agents.base import BaseAgent

    agent = BaseAgent(
        llm_client=llm_client,
        name="IntentClassifier",
        description="Classifies a user message into one of five workflow intents.",
        system_prompt=(
            "Kullanıcı mesajını beş niyetten birine ata. Yalnızca yapılandırılmış "
            "JSON döndür, açıklama yazma.\n"
            "- draft: resmî yazı, cevap yazısı, üst yazı veya taslak hazırlanması isteniyor.\n"
            "- analyze: bir evrakın analiz edilmesi, sınıflandırılması veya eksiklerinin "
            "bulunması isteniyor.\n"
            "- revise: aşağıda 'açık bir taslak var' diye belirtilmişse, o taslakta bir "
            "değişiklik isteniyor.\n"
            "- assist: yukarıdakilerin hiçbiri; genel sohbet, sistem hakkında soru veya "
            "yüklü bir belgenin içeriği hakkında soru.\n"
            "- unclear: yukarıdakilerden hangisi olduğundan emin değilsen, tahmin etme."
        ),
    )

    active_draft = focus.active_draft if focus else None
    objective = (focus.objective if focus else "") or ""
    context_lines = [
        f"Sisteme yüklü bir belge var mı: {'evet' if document_id else 'hayır'}",
        (
            f"Açık bir taslak var, türü: {active_draft.correspondence_type}.\n"
            f"Taslağın başı: \"{truncate_with_marker(active_draft.text, 60)}\""
            if active_draft is not None
            else "Açık (üzerinde çalışılan) bir taslak yok"
        ),
        f"Önceki turun niyeti: {previous_intent or 'yok'}",
    ]
    if objective:
        context_lines.append(f"Bu oturumda kullanıcının amacı (özet): {objective}")

    if history:
        recent = history[-_MODEL_HISTORY_TURNS:]
        turns_text = "\n".join(
            f"{turn.get('role')}: {truncate_with_marker(turn.get('content', ''), 40)}"
            for turn in recent
        )
        context_lines.append(f"Son konuşma turları:\n{turns_text}")

    context_lines.append(f'Son mesaj: "{message}"')
    prompt = "\n".join(context_lines) + "\n\nSon mesajın niyetini belirle."

    try:
        result: IntentOutput = await agent.run_structured(
            messages=prompt,
            response_model=IntentOutput,
            temperature=0.0,
            max_retries=1,
        )
        return result.intent
    except Exception:
        logger.warning("Intent classification failed.")
        return "model_failed"


def _clarify_or_fallback(
    ranked: list[tuple[str, float]],
    probs: dict[str, float],
    lexical: IntentScores,
    focus: Optional[SessionFocus],
) -> PlanDecision:
    """Önceki tur zaten bir soru sormadıysa bir açıklayıcı soru sorar.

    Son açıklayıcı soruyu açıkça yanıtlamamış (bkz.
    ``_try_resolve_pending_clarification``) ve ardından karar katmanının
    da belirsiz bulduğu başka bir mesaj gönderen bir kullanıcıya, aksi
    halde art arda ikinci bir soru sorulurdu -- bu kendi başına can
    sıkıcıdır ve kullanıcı için sistemin ilk cevabını görmezden gelmesinden
    ayırt edilemez. Kaynaşmış en yüksek niyeti sonuçlandırmak daha iyi bir
    başarısızlık türüdür: bazen yanlış, ama asla yalnızca soru soran bir
    konuşma değil.

    Args:
        ranked: Kaynaşmış olasılığa göre sıralanmış niyetler, en yükseği
            önde.
        probs: Her niyet için kaynaşmış olasılık.
        lexical: Mesajın lexical kanıtı.
        focus: Bilindiğinde oturumun kalıcı odağı.

    Returns:
        Bir açıklayıcı karar, ya da önceki tur zaten bir clarify ise
        kaynaşmış en yüksek niyet için sonuçlandırılmış bir karar.
    """
    if focus is not None and focus.last_intent == "clarify":
        top_intent, _ = ranked[0]
        logger.info(
            "Previous turn was already a clarify; committing to the fused top "
            "intent instead of asking a second time in a row: intent=%s",
            top_intent,
        )
        return _fused_decision(top_intent, probs, ranked, lexical, "clarify_repeat_guard")
    return _build_clarify_decision(ranked)


def _apply_scope_gate(decision: PlanDecision, verdict: ScopeVerdict) -> PlanDecision:
    """Bir kapsam kararını zaten çözümlenmiş bir plana katar.

    Args:
        decision: Niyeti çözümlenmiş plan.
        verdict: Aynı mesaj için alan-kabul kararı.

    Returns:
        Kabul edildiğinde ``scope_reason`` kaydedilmiş ``decision``;
        edilmediğinde tek adımlı bir ``refuse`` planı. Orijinal niyet,
        atılmak yerine ``evidence`` içinde tutulur
        (``scope.refused_intent:<name>``) -- neyi reddettiğini kaybeden bir
        ret gözden geçirilemez, ve çevrimdışı test düzeneği retleri,
        yerini aldıkları niyete göre puanlar.
    """
    if verdict.in_scope:
        return decision._replace(scope_reason=verdict.reason)

    return PlanDecision(
        steps=list(PLAN_BY_INTENT["refuse"]),
        intent="refuse",  # type: ignore[arg-type]
        reasoning=REASONING_BY_INTENT["refuse"],
        source=f"scope_{verdict.source}",
        confidence=decision.confidence,
        evidence=(*decision.evidence, f"scope.refused_intent:{decision.intent}"),
        alternatives=decision.alternatives,
        scope_reason=verdict.reason,
    )


async def resolve_plan(
    message: str,
    document_id: Optional[str],
    llm_client: Optional[BaseLLMClient] = None,
    previous_intent: Optional[str] = None,
    matcher: Optional["PrototypeMatcher"] = None,
    focus: Optional[SessionFocus] = None,
    history: Optional[list[dict[str, str]]] = None,
) -> PlanDecision:
    """Çalıştırma planını çözer, ardından kapsamına göre kabul eder (ya da reddeder).

    Niyet çözümlemesi (``_resolve_intent``) ve alan kabulü
    (``app.ai.workflows.scope``), tek bir büyütülmüş sınıflandırıcı yerine
    kasıtlı olarak aynı mesaj üzerinden iki ayrı geçiştir: "bu hangi akışı
    istiyor" ve "bu herhangi bir akış istiyor mu" farklı kanıtlara, farklı
    başarısızlık türlerine ve yanlış yapıldığında farklı maliyetlere
    sahiptir. Bunları birleştirmek, beşinci bir niyet etiketinin yapacağı
    şeydir, ve beşinci bir etiket, dört gerçek etiketi veto etmek yerine
    onlarla softmax kütlesi için yarışır.

    Args ve Returns, ``_resolve_intent``'inkiyle aynıdır, tek bir ekleme
    ile birlikte: döndürülen karar, niyet katmanının vardığı sonuçtan bağımsız
    olarak bir ``refuse`` planı olabilir.
    """
    decision = await _resolve_intent(
        message,
        document_id,
        llm_client=llm_client,
        previous_intent=previous_intent,
        matcher=matcher,
        focus=focus,
        history=history,
    )

    # Çözümlenmiş bir açıklayıcı soru, kullanıcının *bize* cevap vermesidir;
    # onu yeniden kabul etmek, sorunun sorulduğu anda kapsamı zaten
    # kararlaştırılmış bir turu yeniden tartışmaya açmak olurdu.
    if decision.source == "clarification_resolved":
        return decision._replace(scope_reason="clarification_resolved")

    _scope_start = time.perf_counter()
    verdict = await resolve_scope(
        message,
        decision.intent,
        has_document=document_id is not None,
        has_active_draft=bool(focus and focus.active_draft is not None),
        llm_client=llm_client,
    )
    ROUTER_STAGE_DURATION.labels(stage="scope").observe(time.perf_counter() - _scope_start)

    if not verdict.in_scope:
        logger.info(
            "Request refused as out of domain: intent=%s reason=%s (%s)",
            decision.intent,
            verdict.reason,
            verdict.detail,
        )
    return _apply_scope_gate(decision, verdict)


async def _resolve_intent(
    message: str,
    document_id: Optional[str],
    llm_client: Optional[BaseLLMClient] = None,
    previous_intent: Optional[str] = None,
    matcher: Optional["PrototypeMatcher"] = None,
    focus: Optional[SessionFocus] = None,
    history: Optional[list[dict[str, str]]] = None,
) -> PlanDecision:
    """Bir mesajın sistemin akışlarından hangisini istediğini çözer.

    Args:
        message: Kullanıcının mesajı.
        document_id: Eklenmiş bir belge varsa onun depolama yolu.
        llm_client: Kaynaşma doğrudan sonuçlandırmadığında (``tau_high`` ve,
            yalnızca dolguyla kazanmak kendi başına yeterli olmadığından,
            yanındaki kanıt kontrolü) danışılan hızlı katman istemcisi.
            Verilmediğinde aynı durum, bir model çağrısı yerine bir
            açıklayıcı soruya düşer.
        previous_intent: Bilindiğinde bu iş parçacığının önceki turu için
            çözümlenmiş niyet -- kısa-onay devam kuralını etkinleştirir ve
            kaynaşma katmanının ``prev_*`` özelliklerini besler.
        matcher: Etiket başına semantik benzerlik sağlayan prototip
            eşleştirici. Verilmediğinde veya kullanılamadığında, kaynaşma
            semantik katman var olmadan önceki gibi bu özellikler olmadan
            çalışır.
        focus: Oturumun kalıcı odağı. Bir taslağın aktif olup olmadığını
            (``revise``'ı kapılar) ve açık herhangi bir açıklayıcı soruyu
            (kaynaşma hiç çalışmadan önce ilk kontrol edilir) sağlar.
        history: Bilindiğinde bu iş parçacığının ham önceki turları, en
            eskisi önde -- değiştirilmeden ``classify_intent_with_model``'a
            iletilir. Kaynaşmanın kendisi bunu hiç okumaz (kaynaşmış
            özellikleri yalnızca ``previous_intent`` besler); yalnızca model
            çağrısı yükseltmesinin assist adımının aldığı aynı konuşmasal
            temellendirmeye sahip olması için vardır.

    Returns:
        Çalıştırma planı ve kullanıcıya gösterilen gerekçe.
    """
    if focus is not None and focus.pending_clarification:
        resolved = _try_resolve_pending_clarification(
            message, focus.pending_clarification
        )
        if resolved is not None:
            logger.info(
                "Plan resolved via pending clarification: intent=%s", resolved.intent
            )
            return resolved

    has_active_draft = bool(focus and focus.active_draft is not None)
    _lexical_start = time.perf_counter()
    lexical = score_intents(message, document_id, previous_intent, has_active_draft)
    ROUTER_STAGE_DURATION.labels(stage="lexical").observe(time.perf_counter() - _lexical_start)

    compound = _try_compound(lexical)
    if compound is not None:
        logger.info("Plan resolved as compound: %s", compound.steps)
        return compound

    policy = get_policy().intent

    def _fuse(semantic: Optional[dict[str, float]]):
        signals = RouterSignals(
            lexical=lexical,
            semantic=semantic,
            has_document=document_id is not None,
            has_active_draft=has_active_draft,
            previous_intent=previous_intent,
        )
        features = extract_features(message, signals)
        probs = predict_proba(features, ROUTER_WEIGHTS)
        ranked = sorted(probs.items(), key=lambda item: (-item[1], item[0]))
        return probs, ranked

    # Önce yalnızca-lexical kaynaşma, tıpkı eski merdivenin en ucuz basamağı
    # gibi: yalnızca lexical kanıtın zaten sonuçlandırdığı bir mesaj,
    # ihtiyacı olmayan bir embedding çağrısının bedelini ödememeli.
    probs, ranked = _fuse(None)
    top_intent, top_probability = ranked[0]
    source = "fused"

    if top_probability < policy.tau_high and matcher is not None:
        _semantic_start = time.perf_counter()
        semantic = await matcher.label_similarities(message, "intent")
        ROUTER_STAGE_DURATION.labels(stage="semantic").observe(
            time.perf_counter() - _semantic_start
        )
        if semantic:
            probs, ranked = _fuse(semantic)
            top_intent, top_probability = ranked[0]
            source = "fused_semantic"

    # Zayıf kanıt kapısı yalnızca sadece-lexical bir sonuçlandırmaya
    # uygulanır: semantik geçiş çalışıp ibreyi oynattıktan sonra
    # (`source == "fused_semantic"`), embedding benzerliği, bir dolgu
    # kuralının başka yerlerde yerini tuttuğu gerçek sinyalin ta kendisidir,
    # ve burada onu yeniden sorgulamak, semantik katmanın kendi oyunu
    # görmezden gelmenin daha yavaş bir yolundan başka bir şey olmazdı.
    weak = source == "fused" and _has_only_weak_evidence(top_intent, lexical, has_active_draft)
    decisive = top_probability >= policy.tau_high and not weak
    # LOCAL_MODE=false iken semantik katman zaten ölü (PrototypeMatcher,
    # aktif embedding modeli komitli vektörlerin damgasıyla -- nomic-embed-
    # text -- uyuşmadığı için hiçbir aile yüklemiyor, bkz. planning_graph.py'
    # deki ROUTER_SEMANTIC_AVAILABLE ERROR logu). Bu, kendinden emin ama
    # yanlış bir sözcüksel/füzyon sonucunu düzeltecek hiçbir mekanizma
    # bırakmıyor -- semantik yeniden-füzyonun normalde oynadığı "ikinci
    # görüş" rolünü LLM üstlenir: kararlı bir sonuç bile bulut modunda LLM'e
    # doğrulatılır, sonucu gerekirse geçersiz kılar.
    force_llm_confirmation = decisive and not settings.LOCAL_MODE and llm_client is not None
    if decisive and not force_llm_confirmation:
        logger.info(
            "Plan resolved via %s: intent=%s p=%.3f", source, top_intent, top_probability
        )
        return _fused_decision(top_intent, probs, ranked, lexical, source)

    if llm_client is not None:
        _model_start = time.perf_counter()
        result = await classify_intent_with_model(
            llm_client,
            message,
            document_id,
            focus=focus,
            previous_intent=previous_intent,
            history=history,
        )
        ROUTER_STAGE_DURATION.labels(stage="model").observe(time.perf_counter() - _model_start)

        if result == "model_failed":
            if force_llm_confirmation:
                logger.warning(
                    "LOCAL_MODE=false: forced confirmation call failed for an "
                    "otherwise-decisive fused result (p=%.3f); defaulting to assist.",
                    top_probability,
                )
            else:
                logger.warning(
                    "Fused probability %.3f contested; model call failed, defaulting to assist.",
                    top_probability,
                )
            return PlanDecision(
                steps=list(PLAN_BY_INTENT["assist"]),
                intent="assist",
                reasoning=REASONING_BY_INTENT["assist"],
                source="model_failed",
                confidence=_MODEL_CONFIDENCE,
                evidence=tuple(lexical.evidence),
            )

        if result == "unclear" or result not in PLAN_BY_INTENT:
            top_two_margin = ranked[0][1] - ranked[1][1]
            if top_probability < policy.tau_low and top_two_margin < policy.clarify_margin:
                logger.info(
                    "Fused probability %.3f contested; model was unclear too and the "
                    "top two intents are within %.3f of each other. Asking instead.",
                    top_probability,
                    top_two_margin,
                )
                return _clarify_or_fallback(ranked, probs, lexical, focus)
            logger.info(
                "Model was unclear, but the fused top intent (%s, p=%.3f, margin=%.3f) "
                "already leads clearly; committing to it instead of asking again.",
                top_intent,
                top_probability,
                top_two_margin,
            )
            return _fused_decision(top_intent, probs, ranked, lexical, "model_unclear")

        if force_llm_confirmation:
            if result == top_intent:
                logger.info(
                    "LOCAL_MODE=false: model confirmed the decisive fused result "
                    "(p=%.3f): intent=%s",
                    top_probability,
                    result,
                )
            else:
                logger.info(
                    "LOCAL_MODE=false: model overrode the decisive fused result "
                    "(p=%.3f, fused=%s): intent=%s",
                    top_probability,
                    top_intent,
                    result,
                )
        else:
            logger.info(
                "Fused probability %.3f contested; model broke the tie: intent=%s",
                top_probability,
                result,
            )
        return PlanDecision(
            steps=list(PLAN_BY_INTENT[result]),
            intent=result,  # type: ignore[arg-type]
            reasoning=REASONING_BY_INTENT[result],
            source="model",
            confidence=_MODEL_CONFIDENCE,
            evidence=tuple(lexical.evidence),
        )

    logger.info(
        "Fused probability %.3f (%s) not decisive enough to act on and no model "
        "available; asking instead.",
        top_probability,
        top_intent,
    )
    return _clarify_or_fallback(ranked, probs, lexical, focus)
