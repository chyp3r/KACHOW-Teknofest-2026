"""Aşama 3.2 -- mevzuat atıf doğrulamasının saf mantığı.

Canlı MCP çağrısı yok: arama katmanı sahtelenir, geri kalan her şey
(tür eşlemesi, sonuç satırı ayrıştırma, başlık karşılaştırması, madde
kontrolü) gerçek koddur. Sahtelenen çıktılar, canlı ``mevzuat-mcp``
sunucusundan alınan GERÇEK yanıt satırlarıdır.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import mevzuat_dogrulama as md  # noqa: E402

# Canlı sunucudan alınmış gerçek yanıt biçimleri.
BILGI_EDINME = (
    "Browse | Type: KANUN\nResults: 1 total (page 1)\n\n"
    "- [4982] BİLGİ EDİNME HAKKI KANUNU (Kanunlar) | mevzuatId: 103705 | RG: 2003-10-24"
)
YAZISMA_YONETMELIGI = (
    "Browse | Type: CB_YONETMELIK\nResults: 1 total (page 1)\n\n"
    "- [2646] RESMÎ YAZIŞMALARDA UYGULANACAK USUL VE ESASLAR HAKKINDA YÖNETMELİK  "
    "(Cumhurbaşkanı Yönetmelikleri) | mevzuatId: 116932 | RG: 2020-06-10"
)
GELIR_VERGISI_5615 = (
    "Browse | Type: KANUN\nResults: 1 total (page 1)\n\n"
    "- [5615] GELİR VERGİSİ KANUNU VE BAZI KANUNLARDA DEĞİŞİKLİK YAPILMASINA "
    "DAİR KANUN (Kanunlar) | mevzuatId: 104711"
)
KARARNAME_1 = (
    "Browse | Type: CB_KARARNAME\nResults: 1 total (page 1)\n\n"
    "- [1] CUMHURBAŞKANLIĞI TEŞKİLATI HAKKINDA CUMHURBAŞKANLIĞI KARARNAMESİ "
    "(KARARNAME NUMARASI: 1) (Cumhurbaşkanı Kararnameleri) | mevzuatId: 114832"
)


class _SahteDogrulayici(md.MevzuatDogrulayici):
    """MCP çağrılarını önceden verilmiş yanıtlarla değiştirir."""

    def __init__(self, aramalar: dict[str, str], metinler: dict[str, str] | None = None) -> None:
        super().__init__()
        self.aramalar = aramalar
        self.metinler = metinler or {}
        self.arama_sayaci = 0
        self.son_tur_filtresi: str | None = None

    async def _cozumle(self, tur, numara):
        key = (tur, numara)
        if key not in self._arama:
            self.arama_sayaci += 1
            self.son_tur_filtresi = md._TUR_FILTRELERI[tur]
            self._arama[key] = md.sonuc_satirindan_sec(self.aramalar.get(numara, ""), numara)
        return self._arama[key]

    async def _madde_numaralari(self, mevzuat_id):
        if mevzuat_id not in self._maddeler:
            metin = self.metinler.get(mevzuat_id, "")
            self._maddeler[mevzuat_id] = {int(n) for n in md._MADDE_NO.findall(metin)}
        return self._maddeler[mevzuat_id]


# --- tür eşlemesi -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "beklenen"),
    [
        ("Kanun", "kanun"),
        ("kanun", "kanun"),
        ("4982 sayılı Kanun", "kanun"),
        ("Yönetmelik", "yonetmelik"),
        ("yonetmelik", "yonetmelik"),
        ("Cumhurbaşkanlığı Kararnamesi", "cb_kararname"),
        ("Cumhurbaşkanı Kararı", "cb_karar"),
        ("Cumhurbaşkanlığı Genelgesi", "genelge"),
        ("Tebliğ", "teblig"),
        ("Tüzük", "tuzuk"),
    ],
)
def test_kanonik_tur_serbest_ifadeyi_dogru_kovaya_indirger(raw, beklenen):
    assert md.kanonik_tur(raw) == beklenen


def test_kanonik_tur_ic_ice_gecen_ifadeleri_karistirmaz():
    """"Kanun hükmünde kararname" içinde hem "kanun" hem "kararname" geçer;
    "Cumhurbaşkanı Kararı" içinde "karar" geçer. Sıra yanlış olsaydı ikisi
    de yanlış kovaya düşerdi."""
    assert md.kanonik_tur("Kanun Hükmünde Kararname") == "khk"
    assert md.kanonik_tur("KHK") == "khk"
    assert md.kanonik_tur("Cumhurbaşkanlığı Kararnamesi") == "cb_kararname"


def test_kanonik_tur_taninmayan_ifade_icin_fail_closed():
    """Tanınmayan tür None döner -- doğrulayıcı bunu "doğrulanamadı" sayar.
    Sessizce KANUN'a düşmek, tam olarak Aşama 0'da düzeltilen fail-open
    hatasının tekrarı olurdu."""
    assert md.kanonik_tur("Bakanlık İç Genelgesi No 7") == "genelge"
    assert md.kanonik_tur("kurum içi talimat") is None
    assert md.kanonik_tur("") is None


def test_yonetmelik_tek_bir_kovaya_sabitlenmez():
    """2646 sayılı Resmî Yazışmalar Yönetmeliği YONETMELIK altında DEĞİL,
    CB_YONETMELIK altındadır; tek bir tahmin onu bulamazdı."""
    filtre = md._TUR_FILTRELERI["yonetmelik"]
    assert "CB_YONETMELIK" in filtre
    assert "YONETMELIK" in filtre
    assert "KKY" in filtre


def test_hicbir_tur_filtresi_mulga_kovasini_icermez():
    for filtre in md._TUR_FILTRELERI.values():
        assert "MULGA" not in filtre.split(",")


# --- sonuç satırı ayrıştırma ------------------------------------------


def test_sonuc_satirindan_sec_numarayi_tam_eslestirir():
    assert md.sonuc_satirindan_sec(BILGI_EDINME, "4982") == (
        "103705",
        "BİLGİ EDİNME HAKKI KANUNU",
    )


def test_sonuc_satirindan_sec_farkli_numarayi_kabul_etmez():
    """Arama, istenen numarayı taşımayan bir komşu kayda kayarsa
    doğrulama BUNU kabul etmemeli -- sessizce yanlış mevzuat alıntılamak
    projenin önlemek için var olduğu hatadır."""
    assert md.sonuc_satirindan_sec(BILGI_EDINME, "4983") is None


def test_sonuc_satirindan_sec_mulga_kaydi_yedek_olarak_bile_kullanmaz():
    """657 araması gerçek kanunun ÜSTÜNDE mülga eş kaydı döndürebilir.
    Asistanın canlı aracı mülgayı yedek olarak kullanır; eğitim verisi
    üretimi kullanamaz."""
    cikti = (
        "- [657] DEVLET MEMURLARI KANUNUNUN YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ "
        "(Kanunlar) | mevzuatId: 335559"
    )
    assert md.sonuc_satirindan_sec(cikti, "657") is None


def test_sonuc_satirindan_sec_yalniz_sondaki_tur_etiketini_atar():
    """Kararname başlığının kendi içinde "(KARARNAME NUMARASI: 1)"
    parantezi vardır; bu başlığın gerçek parçasıdır, atılmamalı."""
    _, baslik = md.sonuc_satirindan_sec(KARARNAME_1, "1")
    assert baslik == (
        "CUMHURBAŞKANLIĞI TEŞKİLATI HAKKINDA CUMHURBAŞKANLIĞI KARARNAMESİ "
        "(KARARNAME NUMARASI: 1)"
    )


# --- başlık karşılaştırması -------------------------------------------


def test_baslik_uyusuyor_buyuk_kucuk_harf_ve_turkce_farkini_yutar():
    assert md.baslik_uyusuyor("Bilgi Edinme Hakkı Kanunu", "BİLGİ EDİNME HAKKI KANUNU")
    assert md.baslik_uyusuyor(
        "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik",
        "RESMÎ YAZIŞMALARDA UYGULANACAK USUL VE ESASLAR HAKKINDA YÖNETMELİK",
    )


def test_baslik_uyusuyor_resmi_baslikta_fazladan_sozcuge_izin_verir():
    """Resmî ad çoğu zaman iddiadan uzundur ("...VE BAZI KANUNLARDA
    DEĞİŞİKLİK..."); bu bir uyuşmazlık değildir."""
    assert md.baslik_uyusuyor(
        "Gelir Vergisi Kanunu",
        "GELİR VERGİSİ KANUNU VE BAZI KANUNLARDA DEĞİŞİKLİK YAPILMASINA DAİR KANUN",
    )


@pytest.mark.parametrize(
    ("iddia", "resmi"),
    [
        # Pilotta gerçekten üretilen iki hatalı atıf: numara doğru, ad uydurma.
        (
            "Sosyal Yardımlaşma Kanunu",
            "GELİR VERGİSİ KANUNU VE BAZI KANUNLARDA DEĞİŞİKLİK YAPILMASINA DAİR KANUN",
        ),
        ("Köy Kanunu", "TOPRAK KORUMA VE ARAZİ KULLANIMI KANUNU"),
    ],
)
def test_baslik_uyusuyor_pilotta_yakalanan_uydurma_adlari_reddeder(iddia, resmi):
    assert not md.baslik_uyusuyor(iddia, resmi)


def test_baslik_uyusuyor_yalniz_jenerik_sozcukten_ibaret_iddiayi_reddeder():
    """"Kanun" ya da "İlgili Yönetmelik" hiçbir şeyi kanıtlamaz; ayırt
    edici sözcük kalmıyorsa fail-closed."""
    assert not md.baslik_uyusuyor("Kanun", "BİLGİ EDİNME HAKKI KANUNU")
    assert not md.baslik_uyusuyor("İlgili Yönetmelik", "RESMÎ YAZIŞMALAR YÖNETMELİĞİ")


def test_baslik_uyusuyor_turkce_ekleri_uyusmazlik_saymaz():
    assert md.baslik_uyusuyor("Gelir Vergi Kanunu", "GELİR VERGİSİ KANUNU")


# --- uçtan uca doğrulama ----------------------------------------------


@pytest.mark.asyncio
async def test_dogrula_gecerli_atfi_yapisal_kayda_cevirir():
    dogrulayici = _SahteDogrulayici({"4982": BILGI_EDINME})

    sonuc = await dogrulayici.dogrula(
        md.MevzuatAtfi("Kanun", "4982", "Bilgi Edinme Hakkı Kanunu")
    )

    assert sonuc.gecerli
    assert sonuc.kayit == {
        "type": "kanun",
        "number": "4982",
        # LLM'in yazdığı değil, RESMÎ başlık kaydedilir.
        "title": "BİLGİ EDİNME HAKKI KANUNU",
        "article": "",
        "verification_source": "mevzuat-mcp:103705",
        "verification_status": "dogrulandi",
    }


@pytest.mark.asyncio
async def test_dogrula_dogru_numara_yanlis_ad_kombinasyonunu_reddeder():
    """Aşama 3.2'nin varlık sebebi: "numara çözümlendi mi?" kontrolü bu
    hatayı KAÇIRIR, çünkü 5615 gerçekten vardır."""
    dogrulayici = _SahteDogrulayici({"5615": GELIR_VERGISI_5615})

    sonuc = await dogrulayici.dogrula(
        md.MevzuatAtfi("Kanun", "5615", "Sosyal Yardımlaşma ve Dayanışma Kanunu")
    )

    assert not sonuc.gecerli
    assert sonuc.gerekce.startswith("baslik_uyusmazligi")


@pytest.mark.asyncio
async def test_dogrula_yonetmeligi_kanun_kovasinda_aramaz():
    dogrulayici = _SahteDogrulayici({"2646": YAZISMA_YONETMELIGI})

    sonuc = await dogrulayici.dogrula(
        md.MevzuatAtfi(
            "Yönetmelik",
            "2646",
            "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik",
        )
    )

    assert sonuc.gecerli, sonuc.gerekce
    assert dogrulayici.son_tur_filtresi == md._TUR_FILTRELERI["yonetmelik"]


@pytest.mark.asyncio
async def test_dogrula_taninmayan_turu_reddeder():
    dogrulayici = _SahteDogrulayici({"7": BILGI_EDINME})

    sonuc = await dogrulayici.dogrula(md.MevzuatAtfi("kurum içi talimat", "7", "Bir Şey"))

    assert not sonuc.gecerli
    assert sonuc.gerekce.startswith("taninmayan_tur")


@pytest.mark.asyncio
async def test_dogrula_numarasiz_atfi_reddeder():
    dogrulayici = _SahteDogrulayici({})

    sonuc = await dogrulayici.dogrula(md.MevzuatAtfi("Genelge", "  ", "Bir Genelge"))

    assert not sonuc.gecerli
    assert sonuc.gerekce == "numarasiz_atif"


@pytest.mark.asyncio
async def test_dogrula_bulunamayan_numarayi_reddeder():
    dogrulayici = _SahteDogrulayici({"9999": "Results: 0 total (page 1)"})

    sonuc = await dogrulayici.dogrula(md.MevzuatAtfi("Kanun", "9999", "Uydurma Kanun"))

    assert not sonuc.gecerli
    assert sonuc.gerekce.startswith("bulunamadi")


@pytest.mark.asyncio
async def test_dogrula_metinde_olmayan_maddeyi_reddeder():
    dogrulayici = _SahteDogrulayici(
        {"4982": BILGI_EDINME}, {"103705": "MADDE 1 ...\nMADDE 2 ...\nMADDE 3 ..."}
    )

    sonuc = await dogrulayici.dogrula(
        md.MevzuatAtfi("Kanun", "4982", "Bilgi Edinme Hakkı Kanunu", madde="97")
    )

    assert not sonuc.gecerli
    assert sonuc.gerekce.startswith("madde_yok")


@pytest.mark.asyncio
async def test_dogrula_var_olan_maddeyi_kayda_yazar():
    dogrulayici = _SahteDogrulayici(
        {"4982": BILGI_EDINME}, {"103705": "MADDE 1 ...\nMADDE 11 ..."}
    )

    sonuc = await dogrulayici.dogrula(
        md.MevzuatAtfi("Kanun", "4982", "Bilgi Edinme Hakkı Kanunu", madde="11")
    )

    assert sonuc.gecerli, sonuc.gerekce
    assert sonuc.kayit["article"] == "11"


@pytest.mark.asyncio
async def test_dogrula_ayni_mevzuati_tekrar_aramaz():
    """240 vakalık bir turda 4982 onlarca kez geçer; her seferinde MCP'ye
    gitmek turu gereksiz yere saatlerce uzatırdı."""
    dogrulayici = _SahteDogrulayici({"4982": BILGI_EDINME})
    atif = md.MevzuatAtfi("Kanun", "4982", "Bilgi Edinme Hakkı Kanunu")

    await dogrulayici.dogrula(atif)
    await dogrulayici.dogrula(atif)

    assert dogrulayici.arama_sayaci == 1


def test_atif_metni_okunabilir_tek_satir_uretir():
    kayit = {"number": "4982", "title": "BİLGİ EDİNME HAKKI KANUNU", "article": "11"}
    assert md.atif_metni(kayit) == "4982 sayılı BİLGİ EDİNME HAKKI KANUNU, madde 11"

    kayit_maddesiz = {"number": "4982", "title": "BİLGİ EDİNME HAKKI KANUNU", "article": ""}
    assert md.atif_metni(kayit_maddesiz) == "4982 sayılı BİLGİ EDİNME HAKKI KANUNU"
