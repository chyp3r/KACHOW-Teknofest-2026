"""Alan kabul kontrolü: bu istek sistemle ilgili mi, ilgili değil mi?

Router (:mod:`app.ai.workflows.planner`) bir mesajın sistemin akışlarından
*hangisini* istediğini yanıtlar. Mesajın bunlardan *herhangi birini*
isteyip istemediğini hiçbir zaman yanıtlamamıştır. Bunlar farklı sorulardır
ve ikisini birbirine karıştırmak, "Çiğköfte kampanyası için bir metin yaz"
ifadesinin taslak hazırlama boru hattına ulaşmasına izin veren şeydir:
bu ifade ``draft.explicit_request``'in ``"metni yaz"`` yüzeyiyle doğrudan
eşleşir, bu yüzden alt akıştaki her katman -- füzyon, model çekişme
bozucusu, yazar ajanı -- bunun bir *taslak hazırlama* isteği olduğu
konusunda doğru şekilde hemfikir olur ve itaatkâr bir şekilde bir pazarlama
metni üretir. Hiçbir niyet tablosu ayarı bunu düzeltemez, çünkü niyet hiç
yanlış değildi.

Bu yüzden kapsam ayrı olarak çözülür ve konuları kara listeye almak yerine
*olumlu kanıt gerektirerek* çözülür. Alan dışı konuların ("çiğköfte", "hava
durumu", "futbol") bir izin verilmeyenler listesi, yapısı gereği sınırsızdır
ve kimsenin düşünmediği ilk konuda başarısız olur. Buradaki kural bunun
tersidir:

* Küçük sohbet, nezaket, asistan hakkında meta sorular ve bu konuşma
  hakkındaki sorular **her zaman** kapsam içindedir -- bir kullanıcının
  herhangi bir asistanla konuşma şekli budur ve bunları reddetmek,
  :mod:`app.ai.workflows.intent_rules` içindeki selamlama kurallarının
  zaten önlemek için var olduğu başarısızlıktır.
* Bir şey *üzerinde eyleme geçen* bir istek -- taslak hazırlama, analiz
  etme, revize etme -- yalnızca bir yere bağlıysa kapsam içindedir: ekli
  belgeye, açık taslağa veya resmî yazışma/mevzuat alanı kelime dağarcığına.
  Bağlantısız bir üretim isteği, ne kadar güvenle ``draft`` gibi okunsa da
  kapsam dışıdır.

``assess_scope_deterministic`` ücretsizdir, yeniden üretilebilirdir ve
turların büyük çoğunluğunu çözer. Yalnızca gerçekten bağlantısız üretim
istekleri -- bir çağrı harcamaya değecek asıl durum --
``classify_scope_with_model``'e ulaşır; bu da router'ın kendi çekişme
bozucusunun kullandığı aynı hızlı katmandır ve herhangi bir hatada, meşru
bir isteği bir sağlayıcı kesintisinin arkasında engellemek yerine
deterministik karara geri düşer.
"""

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.intent_scorer import normalize
from app.ai.workflows.topic_words import content_words

logger = logging.getLogger(__name__)

__all__ = [
    "CAPABILITY_MANIFEST",
    "ScopeVerdict",
    "assess_scope_deterministic",
    "build_refusal_reply",
    "classify_scope_with_model",
    "resolve_scope",
]

#: Bir mesajın neden kabul edildiği veya reddedildiği. Bir üretim reddinin,
#: ``PlanDecision.evidence``'ın bir niyeti izlediği gibi, onu üreten kurala
#: kadar izlenebilmesi için her kararda kaydedilir.
ScopeReason = Literal[
    "conversational",
    "system_question",
    "bare_command",
    "anchored_document",
    "anchored_draft",
    "domain_vocabulary",
    "model_admitted",
    "model_refused",
    "unanchored_request",
    "degraded",
]

#: Kullanıcı adına bir şey *üreten* niyetler. Yalnızca bunlar bağlanma
#: gerekliliğine tabidir -- ``assist`` sorulara cevap verir ve bağlantısız
#: bir soru bir asistana sorulacak normal bir şeydir.
PRODUCTION_INTENTS = frozenset({"draft", "analyze", "revise"})

#: Resmî yazışma ve kamu idaresi kelime dağarcığı. Bunlardan herhangi birini
#: taşıyan bir üretim isteği, hiçbir şey ekli olmasa bile ("resmi yazı
#: şablonu nasıl olur") bu sistemin konusundan bahsediyordur, bu yüzden
#: model çağrısı olmadan kabul edilir.
#:
#: Kasıtlı olarak bir konu sınıflandırıcısı *değildir*: alan içindeki her
#: konuyu değil, yalnızca üslubu tanımaya çalışır. Gerçekten alan içinde
#: olan ama bunlardan hiçbiri kullanılmadan ifade edilen bir istek, bir
#: sözlük kaçırması yüzünden reddedilmek yerine yine de model çağrısını
#: alır.
DOMAIN_SURFACES: tuple[str, ...] = (
    "resmi yazi", "resmi yazisma", "ust yazi", "alt yazi", "evrak", "belge",
    "dilekce", "genelge", "tebligat", "teblig", "muzekkere", "tezkere",
    "mukabele", "olur", "onay yazisi", "cevap yazisi", "bilgilendirme yazisi",
    "kurum", "kurumsal", "idare", "idari", "kamu", "bakanlik", "mudurluk",
    "mudurlugu", "baskanlik", "baskanligi", "daire", "birim", "mudur",
    "mevzuat", "kanun", "yonetmelik", "yonerge", "teblig", "madde", "fikra",
    "bend", "sayili kanun", "hukuk", "hukuki", "yasal", "yasal dayanak",
    "basvuru", "sikayet", "talep", "itiraz", "bilgi edinme", "kvkk",
    "gizlilik derecesi", "tasnif disi", "hizmete ozel", "gelen evrak",
    "giden evrak", "havale", "sevk", "arz ederim", "rica ederim",
    "sayin", "muhatap", "konu satiri", "imza blogu", "ek listesi",
    "personel", "memur", "izin", "atama", "gorevlendirme", "yazisma",
)

#: Bir mesajı herhangi bir konu hakkında değil, *bu sistem* veya *bu
#: konuşma* hakkında yapan ifadeler. Her zaman kabul edilir -- bunlar
#: tam olarak asistanın ne için var olduğudur ve zaten mevcut ``assist.*``
#: kanıt kuralları bunları birinci sınıf olarak ele alır.
SYSTEM_SURFACES: tuple[str, ...] = (
    "ne yapabilirsin", "neler yapabilirsin", "yeteneklerin", "yetenekleri",
    "ne ise yararsin", "ne ise yarar", "nasil calisirsin", "nasil calisiyorsun",
    "nasil calisir", "sen kimsin", "kimsin", "sen nesin", "adin ne",
    "seni kim yapti", "hangi modeli", "sistem ne yapiyor", "bu sistem",
    "bu sistemde", "bu uygulama", "bu asistan", "nasil kullanilir",
    "nasil kullanabilirim", "yardim eder misin", "yardimci olur musun",
    "ne sordum", "ne demistim", "ne konustuk", "konusma gecmisi",
    "az once", "daha once", "onceki mesaj", "hatirliyor musun",
)

#: Salt sosyal alışveriş. İçeriğe göre değil, çağıran tarafından uzunluğa
#: göre kapılanır: "selam" küçük sohbettir, "Selam, çiğköfte kampanyası
#: için metin yazar mısın?" ise nezaketle başlayan bir üretim isteğidir.
CONVERSATIONAL_SURFACES: tuple[str, ...] = (
    "merhaba", "selam", "gunaydin", "iyi gunler", "iyi aksamlar",
    "iyi calismalar", "kolay gelsin", "nasilsin", "tesekkur", "tesekkurler",
    "sagol", "sag ol", "eyvallah", "rica ederim", "gorusuruz", "hosca kal",
    "gorusmek uzere", "peki", "tamam", "anladim", "evet", "hayir",
)

#: Bu sistemin ne yaptığının, kullanıcının kendi terimleriyle sınırlı
#: listesi. Yalnızca ``prompts/templates/assistant.md`` yerine burada
#: tutulur, çünkü reddetme yolu bunu deterministik olarak oluşturur -- bir
#: reddetme asla bir üretim olmamalıdır, yoksa model az önce yapmaması
#: söylenen şeyi yapmak için bir şans daha elde eder.
CAPABILITY_MANIFEST: tuple[str, ...] = (
    "Yüklediğiniz evrakın türünü tespit edip üst verilerini (tarih, sayı, konu, "
    "muhatap) çıkarabilir ve resmî yazışma kurallarına uygunluğunu denetleyebilirim.",
    "Evrakın konusuyla ilgili kanun, yönetmelik ve mevzuat maddelerini tarayabilirim.",
    "Evraka resmî ve kurumsal bir Türkçe cevap taslağı hazırlayabilirim.",
    "Hazırlanan taslağı talimatınıza göre revize edebilirim.",
    "Taslağın kurum içinde hangi birime sevk edilmesi gerektiğini gerekçesiyle "
    "önerebilirim.",
    "Yüklü evrakın içeriğine dair sorularınızı doğrudan evrak metnine dayanarak "
    "yanıtlayabilirim.",
)

#: Yalnızca sohbet yüzeyinin gücüyle hâlâ saf sosyal alışveriş sayılan en
#: uzun mesaj. "Selam" ve "iyi çalışmalar" bunun içindedir; üzerine gerçek
#: bir istek eklenmiş bir selamlama içinde değildir ve diğer her istek gibi
#: bağlanma testine düşer.
_CONVERSATIONAL_WORD_LIMIT = 6


@dataclass(frozen=True)
class ScopeVerdict:
    """Bir mesajın bu sistemi ilgilendirip ilgilendirmediği ve nedeni.

    Attributes:
        in_scope: Yalnızca istek hiç çalıştırılmamalıysa False. Bir reddetme
            gerçek bir sonuçtur, bir hata değil -- bkz. ``build_refusal_reply``.
        reason: Hangi kuralın buna karar verdiği (bkz. ``ScopeReason``).
        source: ``"deterministic"`` veya ``"model"``; bu paketteki diğer her
            karar katmanının rapor ettiği ayrımı yansıtır.
        detail: Denetim izi için kısa Türkçe not. Kullanıcıya asla olduğu
            gibi gösterilmez; reddetme metni ayrıca oluşturulur.
    """

    in_scope: bool
    reason: ScopeReason
    source: Literal["deterministic", "model"] = "deterministic"
    detail: str = ""


class ScopeOutput(BaseModel):
    """Hızlı katman modelinin bağlantısız bir üretim isteği hakkındaki kararı."""

    in_scope: bool = Field(
        description=(
            "Bu istek bir resmî evrak/yazışma karar destek sisteminin görev "
            "alanına giriyor mu? Resmî yazışma, evrak, mevzuat, kamu idaresi "
            "ile ilgiliyse true. Pazarlama metni, reklam, sosyal medya içeriği, "
            "yaratıcı yazarlık, genel kültür, kod yazma gibi konularsa false."
        )
    )


def _contains(normalized: str, surfaces: tuple[str, ...]) -> bool:
    """Zaten normalleştirilmiş mesajda herhangi bir yüzeyin görünüp görünmediği."""
    padded = f" {normalized} "
    return any(f" {surface}" in padded for surface in surfaces)


def assess_scope_deterministic(
    message: str,
    intent: str,
    *,
    has_document: bool,
    has_active_draft: bool,
) -> ScopeVerdict:
    """Mümkün olduğunda kapsamı yalnızca mesajdan karara bağlar.

    Args:
        message: Kullanıcının ham mesajı.
        intent: Router'ın onun için çözdüğü niyet. Yalnızca
            ``PRODUCTION_INTENTS`` bağlanma gerekliliğine tabidir.
        has_document: Bu turda bir belge ekli olup olmadığı.
        has_active_draft: ``SessionFocus.active_draft``'ın ayarlı olup
            olmadığı.

    Returns:
        Bir karar. Nedeni ``"unanchored_request"`` olan ``in_scope=False``,
        çağıranın doğrudan üzerine hareket etmek yerine bir modele
        yükseltmek isteyebileceği tek sonuçtur (bkz. ``resolve_scope``);
        diğer her sonuç kesindir.
    """
    normalized = normalize(message)

    if not normalized:
        return ScopeVerdict(True, "conversational", detail="Boş mesaj.")

    if _contains(normalized, SYSTEM_SURFACES):
        return ScopeVerdict(
            True, "system_question", detail="Sistemin kendisi hakkında bir soru."
        )

    if intent not in PRODUCTION_INTENTS:
        # Bir `assist` turu bir sorudur ve bir soru görünüşte kabul edilir.
        # Alan dışı bir soruyu *yanıtlamayı* reddeden şey asistanın kendi
        # promptudur; burada da reddetmek, bir kullanıcının sistemin neyi
        # kapsadığını bile soramaması anlamına gelirdi.
        if len(normalized.split()) <= _CONVERSATIONAL_WORD_LIMIT and _contains(
            normalized, CONVERSATIONAL_SURFACES
        ):
            return ScopeVerdict(True, "conversational", detail="Selamlama/nezaket.")
        return ScopeVerdict(True, "conversational", detail="Soru/sohbet turu.")

    # Buradan itibaren mesaj sistemden bir şey *üretmesini* istedi, bu yüzden
    # bir bağlantıya ihtiyacı var.
    if intent == "revise" and has_active_draft:
        return ScopeVerdict(
            True, "anchored_draft", detail="Açık taslak üzerinde revizyon."
        )

    # Taslak hazırlama/revizyon komutunun kendisinden *başka hiçbir şey
    # olmayan* bir mesaj ("Cevap yaz.") bu sistemin kendi konusundan başka
    # bir şey hakkında olduğuna dair hiçbir kanıt taşımaz -- alan dışı
    # *olacak* fazladan bir isim öbeği kalmamıştır. Bu, router'ın kendi modül
    # docstring'inin belirsiz olmayan bir taslak isteği örneği olarak
    # kullandığı salt emir kipini kapının reddetmesini önleyen şeydir; yalnızca
    # üzerine başka bir şey eklenmiş bir komut ("Cevap yaz, çiğköfte
    # kampanyası için") aşağıdaki bağlanma kontrollerine ulaşır.
    if not content_words(message):
        return ScopeVerdict(
            True, "bare_command", detail="Salt üretim komutu; ek bir konu içermiyor."
        )

    if _contains(normalized, DOMAIN_SURFACES):
        return ScopeVerdict(
            True, "domain_vocabulary", detail="Resmî yazışma/mevzuat terminolojisi."
        )

    if has_document:
        # Bir belge bir bağlantıdır, ama tek başına zayıf bir bağlantı:
        # isteği, belge hakkında olduğunu kanıtlamadan *makul biçimde* belge
        # hakkında yapar. İsteği belgenin içeriğiyle gerçekten karşılaştıran
        # kontrol `app.ai.workflows.relevance`'dır ve sınıflandırma
        # karşılaştırılacak bir özet ürettikten sonra çalışır -- bu da
        # kesinlikle buradan sonradır.
        return ScopeVerdict(
            True, "anchored_document", detail="Yüklü belge bağlamında üretim isteği."
        )

    return ScopeVerdict(
        False,
        "unanchored_request",
        detail=(
            "Üretim isteği; ne yüklü bir belgeye, ne açık bir taslağa, ne de "
            "resmî yazışma/mevzuat alanına bağlanıyor."
        ),
    )


async def classify_scope_with_model(
    llm_client: BaseLLMClient, message: str
) -> Optional[bool]:
    """Bağlantısız bir isteğin alan içinde olup olmadığını hızlı katmana sorar.

    Args:
        llm_client: Router'ın çekişme bozucusunun kullandığı aynı hızlı
            katman istemcisi.
        message: Kullanıcının mesajı.

    Returns:
        Modelin kararı, veya çağrının kendisi başarısız olduğunda ``None``
        -- tam olarak ``classify_intent_with_model``'in ``"model_failed"``'i
        gibi, kasıtlı olarak ``False``'tan ayrı: bir sağlayıcı kesintisi bir
        reddetme olarak okunmamalıdır.
    """
    from app.ai.agents.base import BaseAgent

    agent = BaseAgent(
        llm_client=llm_client,
        name="ScopeClassifier",
        description="Decides whether a request falls inside the EKDS domain.",
        system_prompt=(
            "Sen bir Evrak Karar Destek Sistemi'nin kapsam denetleyicisisin. "
            "Sana verilen isteğin bu sistemin görev alanına girip girmediğine "
            "karar ver. Yalnızca yapılandırılmış JSON döndür.\n"
            "Görev alanı: resmî yazışma, evrak analizi, dilekçe/genelge/tebligat, "
            "kamu idaresi süreçleri, mevzuat ve bunlara dair taslak hazırlama.\n"
            "Görev alanı DIŞI: pazarlama/reklam/kampanya metni, sosyal medya "
            "içeriği, yaratıcı yazarlık (şiir, hikâye), genel kültür, haber, "
            "yemek/tarif, spor, kod yazma, kişisel yazışma.\n"
            "Kararsızsan görev alanına girmediğini varsayma; yalnızca açıkça "
            "alan dışıysa false döndür."
        ),
    )

    try:
        result: ScopeOutput = await agent.run_structured(
            messages=f'İstek: "{message}"\n\nBu istek görev alanına giriyor mu?',
            response_model=ScopeOutput,
            temperature=0.0,
            max_retries=1,
        )
        return result.in_scope
    except Exception:
        logger.warning("Scope classification failed; falling back to deterministic verdict.")
        return None


async def resolve_scope(
    message: str,
    intent: str,
    *,
    has_document: bool,
    has_active_draft: bool,
    llm_client: Optional[BaseLLMClient] = None,
) -> ScopeVerdict:
    """Kapsamı çözer, yalnızca bir model çağrısının iyileştirebileceği durumu yükseltir.

    Args:
        message: Kullanıcının mesajı.
        intent: Router'ın çözdüğü niyet.
        has_document: Bu turda bir belge ekli olup olmadığı.
        has_active_draft: Bir taslağın açık olup olmadığı.
        llm_client: Hızlı katman istemcisi. Verilmemesi, deterministik
            kararın tek başına geçerli olduğu anlamına gelir -- bu *bozuk*
            değil, *daha katı* bir sistemdir: bağlantısız bir üretim isteği,
            modele kabul etme şansı verilmeden reddedilir.

    Returns:
        Nihai karar.
    """
    verdict = assess_scope_deterministic(
        message, intent, has_document=has_document, has_active_draft=has_active_draft
    )
    if verdict.in_scope or llm_client is None:
        return verdict

    admitted = await classify_scope_with_model(llm_client, message)
    if admitted is None:
        # Bozulan çağrıydı, istek değil. Deterministik reddi korumak bir
        # Ollama kesintisini "sistem hiçbir şey taslak yazmayı reddediyor"a
        # dönüştürürdü, bu yüzden bunun yerine kabul edilir ve sıradan boru
        # hattının (ve yazarın kendi zemin gereksinimlerinin) bunu ele
        # almasına izin verilir.
        return ScopeVerdict(
            True,
            "degraded",
            source="model",
            detail="Kapsam modeli yanıt vermedi; istek kapsam içi sayıldı.",
        )
    if admitted:
        return ScopeVerdict(
            True, "model_admitted", source="model", detail="Model kapsam içi buldu."
        )
    return ScopeVerdict(
        False, "model_refused", source="model", detail="Model kapsam dışı buldu."
    )


def build_refusal_reply(document_summary: str = "") -> str:
    """Kapsam dışı yanıtı oluşturur. Deterministiktir, asla üretilmez.

    Az önce alan dışı metni yazması istenen aynı model tarafından üretilen
    bir reddetme, bir kaçış kapısı olan bir reddetmedir. Bunun yerine bu,
    ``CAPABILITY_MANIFEST``'ten oluşturulur; böylece sistemin ne
    yapabileceğini iddia ettiği şey her seferinde aynı dizedir ve gerçekte
    yaptığından sapamaz.

    Args:
        document_summary: Bir belge ekliyse, o belgenin özeti. Bir belge
            yükleyip sonra alakasız bir şey soran kullanıcının yüklemenin
            kaydedilip kaydedilmediğini merak etmemesi için eklenmiştir.

    Returns:
        Türkçe yanıt.
    """
    lines = [
        "Bu istek benim görev alanımın dışında kalıyor. Ben bir **Evrak Karar "
        "Destek Sistemi** asistanıyım ve yalnızca resmî yazışma, evrak ve "
        "mevzuat işlerinde yardımcı olabiliyorum.",
        "",
        "Yapabileceklerim:",
        *(f"- {item}" for item in CAPABILITY_MANIFEST),
    ]
    if document_summary:
        lines += [
            "",
            f"Bu arada, yüklü olan belgenin özeti şu: {document_summary}",
        ]
    return "\n".join(lines)
