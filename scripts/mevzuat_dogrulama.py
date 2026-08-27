"""Üretilen vakalardaki mevzuat atıflarını mevzuat.gov.tr'ye karşı doğrular.

``scripts/generate_yazisma_vaka_pilotu.py`` içinden ayrı bir modüle çıkarıldı:
buradaki mantığın tamamı saf/çevrimdışı test edilebilir (satır ayrıştırma,
tür eşlemesi, başlık karşılaştırması) ve Aşama 6'nın QA adımı da aynı
doğrulamayı üretilmiş vakalar üzerinde yeniden çalıştıracak.

Neden gerekli: pilot turunda Evren'in ürettiği 22 mevzuat atfından 2'si
(%9) GERÇEK bir kanun numarası taşıyıp UYDURMA bir başlık veriyordu
(5615 -> "Sosyal Yardımlaşma Kanunu" iddiası, gerçekte "Gelir Vergisi
Kanunu..."; 5403 -> "Köy Kanunu" iddiası, gerçekte "Toprak Koruma ve Arazi
Kullanımı Kanunu"). Numara var olduğu için "numara çözümlendi mi?" biçiminde
bir kontrol bu hatanın ikisini de KAÇIRIR -- bu yüzden doğrulama, resmî
başlığı da karşılaştırmak zorundadır.

Tasarım kararları (VAKA_URETIMI_240_PROMPT.md Aşama 3.2):

* **Tür-farkındalıklı arama.** Her atıf koşulsuz ``mevzuat_tur="KANUN"`` ile
  aranmaz. ``search_mevzuat``'ın kendi tür sözlüğü (aşağıdaki
  ``_TUR_FILTRELERI``) canlı sunucunun araç şemasından alındı. Tek bir
  "yönetmelik" kavramı sunucuda dört ayrı kovaya dağılmıştır
  (``YONETMELIK``/``CB_YONETMELIK``/``KKY``/``UY``) -- 2646 sayılı Resmî
  Yazışmalar Yönetmeliği yalnız ``CB_YONETMELIK`` altında bulunur, tek bir
  tahmin yanlış olurdu; bu yüzden tür başına virgülle ayrılmış bir ADAY
  KÜMESİ gönderilir.
* **Filtresiz yedek arama YOK.** ``app.mcp.mevzuat_client.resolve_and_fetch``
  bulamazsa filtresiz tekrar dener; bu, asistanın canlı arama aracı için
  doğru davranıştır (kullanıcıya bir şey göstermek hiç göstermemekten
  iyidir) ama BURADA yanlıştır: "5615 sayılı Sosyal Yardımlaşma Kanunu"
  iddiası, 5615 numaralı BAŞKA bir kanunla eşleşip doğrulanmış gibi
  görünürdü. Bu yüzden bu modül kendi çözümleyicisini kullanır.
* **Fail-closed.** Tanınmayan tür, eşleşmeyen numara, uyuşmayan başlık,
  metinde bulunmayan madde ve mülga kayıt -- hepsi ``False`` döner. Atıfın
  doğruluğu kanıtlanamıyorsa vaka reddedilir (Aşama 3.2: "Doğrulanamayan
  mevzuatı kabul etme").
* **Altyapı hatası != atıf hatası.** MCP zaman aşımı/ağ hatası ayrı bir
  sonuç türüdür (``MevzuatAltyapiHatasi``). Bunu "atıf yanlış" saymak,
  sunucu düştüğünde iyi vakaları sessizce elemek ve sonunda mevzuatsız bir
  veri seti üretmek olurdu.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.config import settings
from app.mcp.manager import mcp_manager
from app.mcp.mevzuat_client import text_of
from app.mcp.registry import MEVZUAT_SERVER

#: LLM'in yazdığı serbest tür metnini ``search_mevzuat``'ın tür sözlüğüne
#: eşler. Değerler virgülle ayrılmış ADAY kümeleridir (sunucu çoklu türü
#: destekler); tek bir kavramın birden fazla kovaya dağıldığı yerlerde
#: hepsi birden denenir. ``MULGA`` bilerek hiçbir kümede yoktur -- yürürlükten
#: kalkmış bir metni gerekçe göstermek bu projenin önlemek için var olduğu
#: hatanın ta kendisidir.
_TUR_FILTRELERI: dict[str, str] = {
    "kanun": "KANUN",
    "khk": "KHK",
    "yonetmelik": "YONETMELIK,CB_YONETMELIK,KKY,UY",
    "cb_kararname": "CB_KARARNAME",
    "cb_karar": "CB_KARAR",
    "genelge": "CB_GENELGE",
    "teblig": "TEBLIGLER",
    "tuzuk": "TUZUK",
}

#: LLM'in tür alanına yazması muhtemel serbest ifadeleri kanonik anahtara
#: indirger. Sıra ÖNEMLİDİR: uzun/özel ifadeler önce gelir, aksi halde
#: "cumhurbaşkanlığı kararnamesi" içindeki "karar" ya da "kanun hükmünde
#: kararname" içindeki "kanun" yanlış kovaya düşer.
_TUR_ESLEMELERI: tuple[tuple[str, str], ...] = (
    ("kanun hukmunde kararname", "khk"),
    ("khk", "khk"),
    ("cumhurbaskanligi kararnamesi", "cb_kararname"),
    ("cumhurbaskani kararnamesi", "cb_kararname"),
    ("cb kararnamesi", "cb_kararname"),
    ("kararname", "cb_kararname"),
    ("cumhurbaskanligi genelgesi", "genelge"),
    ("cumhurbaskani karari", "cb_karar"),
    ("genelge", "genelge"),
    ("yonetmelik", "yonetmelik"),
    ("teblig", "teblig"),
    ("tuzuk", "tuzuk"),
    ("kanun", "kanun"),
)

#: Başlık karşılaştırmasında ayırt edici olmayan, her ikinci mevzuatın
#: adında geçen jenerik sözcükler. Bunlar atıldıktan sonra geriye kalan
#: sözcükler, iddia edilen başlığın gerçekten o mevzuatı mı yoksa başka
#: bir konuyu mu tarif ettiğini belirler.
_JENERIK_BASLIK_SOZCUKLERI: frozenset[str] = frozenset(
    {
        "kanun",
        "kanunu",
        "kanununun",
        "kanunlarda",
        "yonetmelik",
        "yonetmeligi",
        "teblig",
        "tebligi",
        "genelge",
        "genelgesi",
        "kararname",
        "kararnamesi",
        "karar",
        "karari",
        "tuzuk",
        "tuzugu",
        "hakkinda",
        "hakkindaki",
        "dair",
        "iliskin",
        "ve",
        "ile",
        "sayili",
        "bazi",
        "usul",
        "usulu",
        "esaslar",
        "esaslari",
        "uygulanacak",
        "yapilmasina",
        "degisiklik",
        "numarasi",
    }
)

#: ``- [4982] BİLGİ EDİNME HAKKI KANUNU (Kanunlar) | mevzuatId: 103705 | RG: ...``
_SONUC_SATIRI = re.compile(
    r"^-\s*\[(?P<no>[^\]]+)\]\s*(?P<baslik>.*?)\s*\|\s*mevzuatId:\s*(?P<id>\d+)"
)

#: Mülga eş kayıt işaretleri. Tür filtresi ``MULGA``'yı dışlasa da aynı
#: numarayı taşıyan "YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ" kayıtları normal
#: tür kovalarında da görünebilir (bkz. 657 örneği, mevzuat_client).
_MULGA_ISARETLERI = ("mulga", "yururlukten kaldirilmis")

#: ``MADDE 5``, ``Madde 5``, ``EK MADDE 3``, ``GEÇİCİ MADDE 1`` -- hepsi
#: aynı sayı yakalamasıyla toplanır; madde doğrulaması yalnız "bu numarada
#: bir madde var mı" sorusunu sorar, hangi kovada olduğunu sormaz.
_MADDE_NO = re.compile(r"MADDE\s+(\d+)", re.IGNORECASE)

#: Türkçe harfleri ASCII'ye indirger. ``str.casefold()`` tek başına yetmez:
#: "İ".casefold() -> "i" + U+0307 (birleşen nokta) üretir ve saf bir
#: karşılaştırmayı sessizce bozar (bkz. prepare_resmi_yazisma_markdown._fold_tr).
_ASCII_ESLEME = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
        "â": "a",
        "Â": "a",
        "î": "i",
        "Î": "i",
        "û": "u",
        "Û": "u",
        "̇": "",
    }
)

#: Türkçe eklerin başlık eşleşmesini bozmaması için: iki sözcük, biri
#: diğerinin ön eki ise ve ortak kısım bu uzunluktaysa aynı sayılır
#: ("vergi"/"vergisi", "hak"/"hakki"). Daha kısa bir eşik "kanun"/"kanunlar"
#: gibi çiftleri değil, "koy"/"koyun" gibi ALAKASIZ çiftleri de eşleştirmeye
#: başlar.
_ONEK_ESIK = 5


class MevzuatAltyapiHatasi(RuntimeError):
    """MCP sunucusuna ulaşılamadı/zaman aşımına uğradı.

    Bir atfın YANLIŞ olduğu anlamına GELMEZ; çağıran bunu ayrı ele almalı
    (vakayı elemek yerine üretimi durdurmalı).
    """


@dataclass(frozen=True)
class MevzuatAtfi:
    """LLM'in ürettiği tek bir mevzuat referansı."""

    tur: str
    numara: str
    baslik: str
    madde: str = ""


@dataclass
class DogrulamaSonucu:
    """Tek bir atfın doğrulama çıktısı."""

    gecerli: bool
    gerekce: str = ""
    resmi_baslik: str = ""
    mevzuat_id: str = ""
    kanonik_tur: str = ""
    kayit: dict[str, Any] = field(default_factory=dict)


def normalize_ascii(value: str) -> str:
    """Türkçe metni karşılaştırılabilir ASCII'ye indirger."""
    return value.translate(_ASCII_ESLEME).lower()


def kanonik_tur(raw: str) -> Optional[str]:
    """LLM'in yazdığı serbest tür ifadesini kanonik anahtara indirger.

    Args:
        raw: ``"Kanun"``, ``"Cumhurbaşkanlığı Kararnamesi"``, ``"yönetmelik"``...

    Returns:
        ``_TUR_FILTRELERI`` anahtarı, ya da tür tanınmıyorsa None (fail-closed:
        çağıran bunu doğrulanamamış sayar).
    """
    folded = normalize_ascii(raw)
    for needle, key in _TUR_ESLEMELERI:
        if needle in folded:
            return key
    return None


def _baslik_temizle(raw: str) -> str:
    """Sonuç satırındaki başlıktan sondaki tür etiketini at.

    ``"CUMHURBAŞKANLIĞI TEŞKİLATI ... (KARARNAME NUMARASI: 1) (Cumhurbaşkanı
    Kararnameleri)"`` -> yalnız SON parantez atılır; içerideki "(KARARNAME
    NUMARASI: 1)" başlığın gerçek parçasıdır.
    """
    return re.sub(r"\s*\([^()]*\)\s*$", "", raw).strip()


def _ayirt_edici_sozcukler(baslik: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", normalize_ascii(baslik))
    return {t for t in tokens if t not in _JENERIK_BASLIK_SOZCUKLERI and len(t) > 2}


def _sozcuk_eslesir(claimed: str, official_tokens: set[str]) -> bool:
    if claimed in official_tokens:
        return True
    for token in official_tokens:
        ortak = min(len(claimed), len(token))
        if ortak >= _ONEK_ESIK and (claimed.startswith(token) or token.startswith(claimed)):
            return True
    return False


def baslik_uyusuyor(iddia: str, resmi: str) -> bool:
    """İddia edilen başlık, resmî başlıkla aynı mevzuatı mı tarif ediyor?

    Tam dize eşitliği aranamaz: LLM "Bilgi Edinme Hakkı Kanunu" yazar, resmî
    kayıt "BİLGİ EDİNME HAKKI KANUNU"dur; 5615'in resmî adı ise "GELİR
    VERGİSİ KANUNU VE BAZI KANUNLARDA DEĞİŞİKLİK YAPILMASINA DAİR KANUN"
    gibi uzun bir dizedir. Kural: iddianın JENERIK OLMAYAN her sözcüğü
    resmî başlıkta (Türkçe eke toleranslı olarak) bulunmalıdır.

    Bu yön KASITLIDIR (iddia ⊆ resmî, tersi değil): resmî başlığın fazladan
    sözcük taşıması normaldir ("...VE BAZI KANUNLARDA DEĞİŞİKLİK..."), ama
    iddianın resmî başlıkta hiç geçmeyen bir konu sözcüğü taşıması ("SOSYAL
    YARDIMLAŞMA", "KÖY") tam olarak yakalamak istediğimiz uydurmadır.
    """
    iddia_tokens = _ayirt_edici_sozcukler(iddia)
    if not iddia_tokens:
        # Yalnız jenerik sözcüklerden ibaret bir iddia ("Kanun", "İlgili
        # Yönetmelik") hiçbir şeyi kanıtlamaz -- fail-closed.
        return False
    resmi_tokens = _ayirt_edici_sozcukler(resmi)
    return all(_sozcuk_eslesir(token, resmi_tokens) for token in iddia_tokens)


def sonuc_satirindan_sec(cikti: str, numara: str) -> Optional[tuple[str, str]]:
    """Arama çıktısından numarası TAM eşleşen, mülga olmayan kaydı seç.

    Args:
        cikti: ``search_mevzuat`` yanıtının ham metni.
        numara: Aranan resmî mevzuat numarası.

    Returns:
        ``(mevzuat_id, resmi_baslik)``, ya da tam eşleşen yürürlükteki bir
        kayıt yoksa None. Mülga kayıt bilerek YEDEK OLARAK DA kullanılmaz:
        eğitim verisine gerekçe olarak yalnız yürürlükteki metin girebilir.
    """
    hedef = numara.strip()
    for line in cikti.splitlines():
        match = _SONUC_SATIRI.match(line.strip())
        if not match or match.group("no").strip() != hedef:
            continue
        folded = normalize_ascii(line)
        if any(isaret in folded for isaret in _MULGA_ISARETLERI):
            continue
        return match.group("id"), _baslik_temizle(match.group("baslik"))
    return None


async def _cagir(arac: str, argumanlar: dict[str, Any]) -> str:
    """MCP aracını proje zaman aşımı politikasıyla çağır.

    ``mevzuat_client``'ın kendi belgesi zaman aşımının çağrı noktasına ait
    olduğunu söyler; toplu üretim, tek bir asılı çağrının 240 vakalık turu
    kilitlemesini göze alamaz.
    """
    try:
        result = await asyncio.wait_for(
            mcp_manager.call_tool(MEVZUAT_SERVER, arac, argumanlar),
            timeout=settings.MEVZUAT_MCP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise MevzuatAltyapiHatasi(f"{arac}: zaman asimi") from exc
    except Exception as exc:  # ağ/süreç/protokol -- hepsi altyapı hatasıdır
        raise MevzuatAltyapiHatasi(f"{arac}: {type(exc).__name__}") from exc
    return text_of(result)


class MevzuatDogrulayici:
    """Atıfları doğrular ve çözümlemeleri süreç boyunca önbelleğe alır.

    Önbellek, 240 vakalık bir turda kaçınılmaz olan tekrarları (4982 sayılı
    Bilgi Edinme Kanunu onlarca vakada geçer) tek bir MCP çağrısına indirir;
    madde kontrolü için gereken tam metin getirme çok daha pahalı olduğundan
    ayrıca önbelleklenir.
    """

    def __init__(self) -> None:
        self._arama: dict[tuple[str, str], Optional[tuple[str, str]]] = {}
        self._maddeler: dict[str, set[int]] = {}
        self._metinler: dict[str, str] = {}

    async def _cozumle(self, tur: str, numara: str) -> Optional[tuple[str, str]]:
        key = (tur, numara)
        if key not in self._arama:
            cikti = await _cagir(
                "search_mevzuat",
                {"mevzuat_no": numara, "mevzuat_tur": _TUR_FILTRELERI[tur], "page_size": 10},
            )
            self._arama[key] = sonuc_satirindan_sec(cikti, numara)
        return self._arama[key]

    async def _madde_numaralari(self, mevzuat_id: str) -> set[int]:
        if mevzuat_id not in self._maddeler:
            metin = await self._tam_metin(mevzuat_id)
            self._maddeler[mevzuat_id] = {int(n) for n in _MADDE_NO.findall(metin)}
        return self._maddeler[mevzuat_id]

    async def _tam_metin(self, mevzuat_id: str) -> str:
        if mevzuat_id not in self._metinler:
            self._metinler[mevzuat_id] = await _cagir(
                "get_mevzuat_content", {"mevzuat_id": mevzuat_id}
            )
        return self._metinler[mevzuat_id]

    async def madde_metni(self, mevzuat_id: str, madde_raw: str) -> str:
        """Resmî tam metinden tek madde bloğunu semantik hakem için çıkar."""
        madde_no = re.search(r"\d+", madde_raw)
        if madde_no is None:
            return ""
        metin = await self._tam_metin(mevzuat_id)
        pattern = re.compile(
            rf"(?ims)^\s*(?:EK\s+|GEÇİCİ\s+)?MADDE\s+{int(madde_no.group())}\b.*?"
            r"(?=^\s*(?:EK\s+|GEÇİCİ\s+)?MADDE\s+\d+\b|\Z)"
        )
        match = pattern.search(metin)
        return match.group(0).strip()[:8000] if match else ""

    async def numaradan_dogrula(
        self, tur_raw: str, numara_raw: str, madde_raw: str = ""
    ) -> DogrulamaSonucu:
        """Başlığı yalnız kısaltma olan atfı numarayla resmî kayda çöz.

        Bu yol yalnız taslakta açık bir ``NNNN sayılı KVKK`` benzeri atıf
        bulunduğunda çağrılır. Resmî başlık modelden alınmaz; MCP arama
        sonucundan gelir. Madde varsa tam metinde ayrıca doğrulanır.
        """
        tur = kanonik_tur(tur_raw)
        if tur is None:
            return DogrulamaSonucu(False, f"taninmayan_tur:{tur_raw[:40]}")
        numara = numara_raw.strip()
        if not numara:
            return DogrulamaSonucu(False, "numarasiz_atif")
        bulunan = await self._cozumle(tur, numara)
        if bulunan is None:
            return DogrulamaSonucu(False, f"bulunamadi:{tur}/{numara}")
        mevzuat_id, resmi_baslik = bulunan

        madde = ""
        if madde_raw.strip():
            madde_no = re.search(r"\d+", madde_raw)
            if madde_no is None:
                return DogrulamaSonucu(False, f"okunamayan_madde:{madde_raw[:20]}")
            mevcut = await self._madde_numaralari(mevzuat_id)
            if mevcut and int(madde_no.group()) not in mevcut:
                return DogrulamaSonucu(
                    False,
                    f"madde_yok:{tur}/{numara}/{madde_no.group()}",
                    resmi_baslik=resmi_baslik,
                    mevzuat_id=mevzuat_id,
                    kanonik_tur=tur,
                )
            madde = madde_raw.strip()

        return DogrulamaSonucu(
            True,
            resmi_baslik=resmi_baslik,
            mevzuat_id=mevzuat_id,
            kanonik_tur=tur,
            kayit={
                "type": tur,
                "number": numara,
                "title": resmi_baslik,
                "article": madde,
                "verification_source": f"mevzuat-mcp:{mevzuat_id}",
                "verification_status": "dogrulandi",
            },
        )

    async def dogrula(self, atif: MevzuatAtfi) -> DogrulamaSonucu:
        """Tek bir atfı doğrula.

        Raises:
            MevzuatAltyapiHatasi: MCP'ye ulaşılamadığında. Bu, atfın yanlış
                olduğu anlamına gelmez.
        """
        tur = kanonik_tur(atif.tur)
        if tur is None:
            return DogrulamaSonucu(False, f"taninmayan_tur:{atif.tur[:40]}")
        numara = atif.numara.strip()
        if not numara:
            return DogrulamaSonucu(False, "numarasiz_atif")

        bulunan = await self._cozumle(tur, numara)
        if bulunan is None:
            return DogrulamaSonucu(False, f"bulunamadi:{tur}/{numara}")
        mevzuat_id, resmi_baslik = bulunan

        if not baslik_uyusuyor(atif.baslik, resmi_baslik):
            return DogrulamaSonucu(
                False,
                f"baslik_uyusmazligi:{tur}/{numara}",
                resmi_baslik=resmi_baslik,
                mevzuat_id=mevzuat_id,
                kanonik_tur=tur,
            )

        madde = ""
        if atif.madde.strip():
            madde_no = re.search(r"\d+", atif.madde)
            if madde_no is None:
                return DogrulamaSonucu(False, f"okunamayan_madde:{atif.madde[:20]}")
            mevcut = await self._madde_numaralari(mevzuat_id)
            if mevcut and int(madde_no.group()) not in mevcut:
                return DogrulamaSonucu(
                    False,
                    f"madde_yok:{tur}/{numara}/{madde_no.group()}",
                    resmi_baslik=resmi_baslik,
                    mevzuat_id=mevzuat_id,
                    kanonik_tur=tur,
                )
            madde = atif.madde.strip()

        return DogrulamaSonucu(
            True,
            resmi_baslik=resmi_baslik,
            mevzuat_id=mevzuat_id,
            kanonik_tur=tur,
            kayit={
                # Aşama 3.2'nin yapısal legal_basis şeması. ``title`` LLM'in
                # iddiası değil, RESMÎ başlıktır -- eğitim verisine giren
                # metin doğrulanmış olanıdır.
                "type": tur,
                "number": numara,
                "title": resmi_baslik,
                "article": madde,
                "verification_source": f"mevzuat-mcp:{mevzuat_id}",
                "verification_status": "dogrulandi",
            },
        )


def atif_metni(kayit: dict[str, Any]) -> str:
    """Doğrulanmış bir kaydı, insan/RAG tarafında okunabilir tek satıra çevir.

    ``legal_basis`` yapısal hale geldiği için (eskiden ``list[str]``'ti),
    metin bekleyen tüketiciler ve gözden geçirme arayüzleri için türetilmiş
    bir ``legal_basis_text`` alanı üretilir.
    """
    parca = f"{kayit['number']} sayılı {kayit['title']}"
    if kayit.get("article"):
        parca += f", madde {kayit['article']}"
    return parca
