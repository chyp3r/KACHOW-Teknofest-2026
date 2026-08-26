"""Serbest metin bir mevzuat atfını bir (kanun, madde) çiftine çözer.

Hem `REQUIRED_FIELD_RULES` (`field_rule.py`) hem de LLM'nin
`mevzuat_references`'ı mevzuata düzyazı olarak atıfta bulunur -- "Resmî
Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik MADDE 15- (3)",
"RYUEHY m.14", "Devlet Memurları Kanunu" -- hiçbir yerde sabit bir kimlik
olmadan. Bu modül, böyle bir string'i bir bilgi grafiği düğümünün ihtiyaç
duyduğu iki tanımlayıcıya çeviren tek yerdir.

`canonical_legislation` (`app.ai.verification.normalizers`) *kanonikleştirme*
yarısını zaten yapar -- "madde 11" / "m. 11" / "m.11" hepsi aynı "madde:11"e
indirgenir -- ama bu, düzyazıyı değil tek başına izole bir aralığı eşleştirir
ve kanunu ile maddeyi kasıtlı olarak ayrı isim alanlarında tutar (*herhangi
bir şeyin* 4982 sayılı maddesine atıf yapan bir taslak, 4982 sayılı kanundan
bahseden bir kaynak tarafından dayanaklandırılmış olmaz). Bir bilgi grafiği
bunun tersini ister: ikisi arasındaki birleşimi. `resolve_citation`, düzyazı
içindeki aralık başına kanonikleştirme için `canonical_legislation`'ı ve bu
aralıkları düzyazı içinde bulmak için `LEGISLATION_PATTERN`'i
(`draft_verifier.py`) yeniden kullanarak bu birleşimi sağlar -- bir belge
numarasının kuyruğuna karşı geri bakış korumasının ("E-22222222-903-118
sayılı yazınız") burada da önemi var, çünkü `ilgi`- ve `mevzuat`-tarzı
string'ler belge numaralarıyla doludur.

`citation_support`, aynı birleşimin farklı bir soru için ikinci tüketicisidir:
"bu atıf neye atıfta bulunuyor" değil, "atıfta bulunduğu şey modele verilen
alıntılarda gerçekten var mı". Bu, `suggest_mevzuat_node`'un
(`document_analysis_graph.py`) bir öneriyi API yanıtına ulaşmadan önce
kontrol ettiği şeydir -- alıntılar modelin gördüğü tek mevzuat metnidir, bu
yüzden hiçbirinde bulunmayan bir kanun veya madde adlandıran bir atıf,
alınan metinden hiç okunmamıştır.
"""

from dataclasses import dataclass
from typing import Optional, Sequence

from langchain_core.documents import Document

from app.ai.verification.draft_verifier import LEGISLATION_PATTERN
from app.ai.verification.normalizers import _fold, canonical_legislation

#: `app.ai.retrieval.mcp_mevzuat.CURATED_LEGISLATION`'dan import edilmek
#: yerine kopyalandı: o modül langchain, BM25 ve MCP kayıt defterini de
#: beraberinde getiriyor, ve kendi docstring'i "Never touches compliance."
#: (Uygunluğa asla dokunmaz) diyor. Bir eşitleme testiyle (bkz.
#: test_mevzuat_citation.py) kopyalama, bu repo'nun tam olarak bu ödünleşim
#: için kendi yerleşik cevabıdır -- `_LegislationRef`'in docstring'i, bir
#: seviye daha dışarıda aynı şeyi aynı nedenle yaptığını belgeler.
#:
#: Hem `LAW_TITLES`'in (indirgenmiş başlık -> numara, eşleştirme için) hem de
#: `KANUN_TITLE`'ın (numara -> görüntülenen başlık, bir grafik düğümünün
#: etiketi için) türetildiği tek kaynak, böylece başlık string'i asla iki kez
#: yazılmaz.
_CURATED_LAW: tuple[tuple[str, str], ...] = (
    ("2646", "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik"),
    ("3071", "Dilekçe Hakkının Kullanılmasına Dair Kanun"),
    ("4982", "Bilgi Edinme Hakkı Kanunu"),
    ("657", "Devlet Memurları Kanunu"),
    ("6698", "Kişisel Verilerin Korunması Kanunu"),
    ("7201", "Tebligat Kanunu"),
    ("5070", "Elektronik İmza Kanunu"),
)

#: İndirgenmiş başlık -> kanun numarası; indirgenmiş bir atıf string'i bunlardan
#: birini alt-dize olarak içerip içermediği için kontrol edilir, bu yüzden
#: `RYUEHY`'nin başlığı (içinde hiç numara yok) tıpkı "3071 sayılı ..." başlığı
#: gibi çözülür.
LAW_TITLES: dict[str, str] = {_fold(title): number for number, title in _CURATED_LAW}

#: Kanun numarası -> görüntülenen başlık, bir Kanun grafik düğümünü etiketlemek için.
KANUN_TITLE: dict[str, str] = dict(_CURATED_LAW)

#: Gerçek `mevzuat_references` çıktısında gözlemlenen, kanunun kendi
#: başlığında hiçbir yerde geçmeyen kısaltmalar; bu yüzden bir başlık-alt-dize
#: eşleşmesi bunları asla yakalayamaz.
LAW_ALIASES: dict[str, str] = {
    _fold("RYUEHY"): "2646",
}


@dataclass(frozen=True)
class CitationRef:
    """Bir atıf string'inden çözülen kanun numarası ve madde numarası.

    Her ikisi de düz tanımlayıcılardır (``"2646"``, ``"17"``),
    `canonical_legislation`'ın döndürdüğü önekli ``"kanun:2646"``/``"madde:17"``
    biçiminde değil -- bilgi grafiği oluşturucusu bunları tek bir düğüm
    kimliğinde (`madde:{kanun}:{madde}`) birleştirir; bu da kanun numarasının
    önekli bir string'den yeniden ayrıştırılmak yerine düz bir değer olarak
    mevcut olmasını gerektirir.
    """

    kanun: Optional[str]
    madde: Optional[str]


def _resolve_kanun(text: str, folded: str) -> Optional[str]:
    """Bir atfın referans verdiği kanun numarasını bulur; en açık sinyali
    önce dener: metindeki gerçek bir "N sayılı" numarası bir başlık
    eşleşmesinden, o da bir kısaltmadan önce gelir."""
    for match in LEGISLATION_PATTERN.finditer(text):
        canonical = canonical_legislation(match.group(0))
        if canonical and canonical.startswith("kanun:"):
            return canonical.removeprefix("kanun:")

    for title, number in LAW_TITLES.items():
        if title in folded:
            return number

    for alias, number in LAW_ALIASES.items():
        if alias in folded:
            return number

    return None


def _resolve_madde(text: str) -> Optional[str]:
    for match in LEGISLATION_PATTERN.finditer(text):
        canonical = canonical_legislation(match.group(0))
        if canonical and canonical.startswith("madde:"):
            return canonical.removeprefix("madde:")
    return None


def _resolve_all_madde(text: str) -> set[str]:
    """Daha uzun bir pasajda herhangi bir yerde bahsedilen her madde numarasını toplar.

    `_resolve_madde` kasıtlı olarak ilk eşleşmede durur -- kısa, tek atıflı
    bir string için doğru, ama genellikle birkaç ardışık maddeyi kapsayan
    tüm bir alıntı için yanlış. `citation_support`, sadece ilkine değil bir
    alıntının bahsettiği her birine ihtiyaç duyar.
    """
    found: set[str] = set()
    for match in LEGISLATION_PATTERN.finditer(text):
        canonical = canonical_legislation(match.group(0))
        if canonical and canonical.startswith("madde:"):
            found.add(canonical.removeprefix("madde:"))
    return found


def resolve_citation(text: str) -> CitationRef:
    """Serbest metin bir mevzuat atfını bir kanun ve madde numarasına çözer.

    Args:
        text: Yazıldığı şekliyle atıf, ör. `FieldRule.mevzuat`'tan veya
            LLM tarafından üretilmiş bir `mevzuat_references[].mevzuat`
            string'inden.

    Returns:
        Atfın o yarısı çözülemediğinde ilgili alanı `None` olan bir
        `CitationRef` -- asla hata fırlatmaz, çünkü kaynak metin her zaman ya
        elle yazılmış bir sabittir (ki test_mevzuat_citation.py'deki kural
        tablosu sözleşme testi bunu tam çözünürlüğe zorunlu tutar) ya da
        güvenilmez model çıktısıdır (ki bunun bazen başarısız olması
        beklenir).
    """
    folded = _fold(text)
    return CitationRef(kanun=_resolve_kanun(text, folded), madde=_resolve_madde(text))


@dataclass(frozen=True)
class CitationSupport:
    """Bir atfın kanunu ve maddesinin, alınan bir mevzuat alıntıları
    kümesinde gerçekten mevcut olup olmadığı.

    Atıf hiç madde adlandırmadığında ``article_supported`` anlamsız biçimde
    ``True``'dur -- yalnızca kanun adlandıran bir atıf ("Devlet Memurları
    Kanunu") alıntıların başarısız olabileceği bir madde düzeyinde iddia
    içermez, bu yüzden çelişecek bir şey yoktur. Sadece birleşik sonuca
    ihtiyaç duyan çağıranlar tek bir bayrak yerine `grounded`'ı kullanmalıdır.
    """

    law_supported: bool
    article_supported: bool

    @property
    def grounded(self) -> bool:
        """Tek geçti/kaldı sonucu: atfın her iki yarısı da geçerli."""
        return self.law_supported and self.article_supported


def citation_support(citation: str, excerpts: Sequence[Document]) -> CitationSupport:
    """Bir mevzuat atfını, güya kendisinden çıkarıldığı alıntılara karşı kontrol eder.

    Atfı, `resolve_citation`'ın diğer her atıf string'ini çözdüğü gibi çözer.
    Her alıntıyı bağımsız olarak çözer: kanununu `metadata["mevzuat"]`'tan
    (külliyatın kendi başlığı, `_resolve_kanun`'un düzyazı için zaten yaptığı
    aynı başlık/kısaltma eşleştirmesi üzerinden) ve `page_content`'inde
    herhangi bir yerde bahsedilen *her* madde numarasını (`_resolve_all_madde`
    -- bir alıntı parçası, kısa bir atıf string'inin aksine genellikle
    birkaç ardışık maddeyi kapsar).

    Args:
        citation: Bir `mevzuat_references[].mevzuat` tarzı atıf string'i.
        excerpts: Bu belge için alınan mevzuat pasajları -- atfın meşru
            olarak gelebileceği tek kaynak.

    Returns:
        Atfın kanununun ve maddesinin her birinin en az bir alıntıyla
        desteklenip desteklenmediğini bildiren `CitationSupport`. Ne bir
        kanuna ne de bir maddeye çözülen bir atıf (`resolve_citation`
        kontrol edilebilir hiçbir şey bulamadı) alıntılardan bağımsız olarak
        tamamen desteklenmemiş olarak raporlanır -- karşılaştırılacak
        hiçbir otorite adlandırmaz.
    """
    ref = resolve_citation(citation)
    if ref.kanun is None and ref.madde is None:
        return CitationSupport(law_supported=False, article_supported=False)

    excerpt_refs = [
        (_resolve_kanun(document.metadata.get("mevzuat", ""), _fold(document.metadata.get("mevzuat", ""))),
         _resolve_all_madde(document.page_content))
        for document in excerpts
    ]

    law_supported = ref.kanun is not None and any(
        excerpt_kanun == ref.kanun for excerpt_kanun, _ in excerpt_refs
    )
    if ref.madde is None:
        article_supported = True
    else:
        article_supported = any(
            excerpt_kanun == ref.kanun and ref.madde in excerpt_maddeler
            for excerpt_kanun, excerpt_maddeler in excerpt_refs
        )

    return CitationSupport(law_supported=law_supported, article_supported=article_supported)
