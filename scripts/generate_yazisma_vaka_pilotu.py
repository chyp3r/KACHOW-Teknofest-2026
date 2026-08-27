"""Az-temsil-edilen karar türleri için pilot gelen-evrak/karar/cevap vaka üretimi.

Bkz. ``datasets/resmi_yazisma/VAKA_URETIM_PLAYBOOK.md`` (nasıl kullanılır) ve
``datasets/resmi_yazisma/GELEN_EVRAK_KARAR_CEVAP_VERI_PLANI.md`` (şema/gerekçe).

Bu betik kasıtlı olarak ``scripts/scrape_open_sources.py``'nin (OS-* serisi)
yaptığının tersini yapar: rastgele kurum/konu/cümle havuzlarından birleştirme
YOKTUR. Bunun yerine hedef karar türü başına gerçek, anonimleştirilmiş
korpus kartları few-shot örnek olarak Evren'e (``llm-large``) verilir ve
çıktı ``generate_structured`` ile bir Pydantic şemasına karşı doğrulanır.

Üretilen her vaka, yazılmadan önce aynı anonimleştirme/denetim hattından
(``prepare_resmi_yazisma_markdown.semantic_anonymize`` +
``_audit_privacy_findings``) geçirilir; otomatik-düzeltilebilir bir bulgu
kalan vaka yazılmaz. Ayrıca her mevzuat atfı ``mevzuat_dogrulama`` ile
mevzuat.gov.tr'ye karşı doğrulanır; doğrulanamayan tek bir atıf vakayı
geçersiz kılar. Çıktı üretim ``ornekler.jsonl``'e asla otomatik karışmaz --
ayrı bir klasöre, ``review_status: "taslak"`` ile yazılır.

Kullanım:
    python scripts/generate_yazisma_vaka_pilotu.py --dry-run
    python scripts/generate_yazisma_vaka_pilotu.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.append(os.path.dirname(__file__))

from pydantic import BaseModel, Field  # noqa: E402

from app.ai.llms import get_llm_client  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.mcp.registry import MEVZUAT_SERVER, is_registered, register_servers  # noqa: E402
from mevzuat_dogrulama import (  # noqa: E402
    MevzuatAltyapiHatasi,
    MevzuatAtfi,
    MevzuatDogrulayici,
    atif_metni,
)
from prepare_resmi_yazisma_markdown import (  # noqa: E402
    CORPUS_ROOT,
    _audit_privacy_findings,
    _INSTITUTION_LINE,
    read_text,
    semantic_anonymize,
    split_front_matter,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Pilot'un kendi çıktısı (20 vaka, TARGET_DECISIONS'ın eski 3-türlü hali
#: ile üretildi) -- artık bu betik tarafından yazılmıyor, yalnız tarihsel
#: referans olarak kalıyor. Ana 240 vakalık üretim ayrı, kalıcı bir
#: klasöre yazılır (VAKA_URETIMI_240_PROMPT.md Aşama 3.6).
PILOT_ROOT = REPO_ROOT / "datasets" / "resmi_yazisma_vakalar_pilot"
PILOT_OUTPUT = PILOT_ROOT / "vakalar-taslak.jsonl"

MAIN_ROOT = REPO_ROOT / "datasets" / "resmi_yazisma_vakalar"
MAIN_OUTPUT = MAIN_ROOT / "vakalar.jsonl"
MAIN_MANIFEST = MAIN_ROOT / "vaka-manifesti.jsonl"
MAIN_ERRORS = MAIN_ROOT / "vaka-hatalari.jsonl"

#: Kanonik karar sonucu kümesi -- GELEN_EVRAK_KARAR_CEVAP_VERI_PLANI.md'nin
#: 8'li ``decision`` enum'u. ``itiraz`` bu kümede YOKTUR: itiraz bir gelen
#: evrak türüdür (``incoming_type``), kararı yine bu 8 değerden biridir.
#: İlk pilot turunda ``itiraz`` yanlışlıkla ayrı bir decision değeri gibi
#: üretilmişti; 5 vaka da gerçekte "itirazın kabulü" olduğu için
#: ``tam_kabul``'e taşındı (bkz. CHANGELOG). TARGET_DECISIONS'ın her
#: anahtarı bu kümenin bir üyesi olmak zorundadır -- aşağıdaki assert bunu
#: import zamanında garanti eder.
ALLOWED_DECISIONS: frozenset[str] = frozenset(
    {
        "tam_kabul",
        "ret",
        "kismi_kabul",
        "eksik_belge",
        "yetkisizlik",
        "yalnizca_bilgilendirme",
        "belirsiz_basvuru",
        "coklu_talep",
    }
)

# Aşama 2: VAKA_URETIMI_240_PROMPT.md'deki kota tablosu. Gerçek korpusta
# zaten bol olan alt-niyetlerden (bilgi_edinme cevabı, olağan cevap
# yazısı gibi) üretmek sahte bir hacim artışı olur; kotalar gerçek
# örnek sayısı düşük olan türlere ağırlık verir (bkz. tablo notları).
TARGET_DECISIONS: dict[str, dict[str, Any]] = {
    "tam_kabul": {
        "adet": 35,
        "aciklama": (
            "Başvuru talebi tamamen kabul edilmiştir; kurum talep edilen "
            "işlemi olduğu gibi gerçekleştirir."
        ),
        "few_shot_glob": "02_cevap_yazisi/06_olumlu_cevap/*.md",
    },
    "ret": {
        "adet": 35,
        "aciklama": (
            "Başvuru talebi tamamen reddedilmiştir; kurum gerekçeli bir "
            "ret cevabı verir. Bu, KISMİ kabulden FARKLIDIR -- burada "
            "hiçbir talep karşılanmaz."
        ),
        "few_shot_glob": "02_cevap_yazisi/07_ret_kismen_kabul/*.md",
        "niyet_filter": "ret",
    },
    "kismi_kabul": {
        "adet": 30,
        "aciklama": (
            "Başvuru talebinin bir kısmı kabul edilmiş, bir kısmı "
            "reddedilmiştir; kurum hangi kısmın neden kabul/ret edildiğini "
            "ayrı ayrı gerekçelendirir."
        ),
        "few_shot_glob": "02_cevap_yazisi/07_ret_kismen_kabul/*.md",
        "niyet_filter": "ret_kismen_kabul",
    },
    "eksik_belge": {
        "adet": 30,
        "aciklama": (
            "Başvuru, eksik belge/bilgi nedeniyle sonuçlandırılamıyor; "
            "kurum başvurandan somut, isimlendirilmiş bir belge/bilgi "
            "talep ediyor. Bu, YETKİSİZLİK'ten FARKLIDIR -- burada kurum "
            "yetkilidir, yalnızca eksik belge var."
        ),
        "few_shot_glob": "02_cevap_yazisi/08_eksik_belge_yetkisizlik/*.md",
    },
    "yetkisizlik": {
        "adet": 30,
        "aciklama": (
            "Başvuru, muhatap kurumun görev alanına girmiyor; başvuru "
            "sahibi doğru kuruma yönlendiriliyor. Bu, eksik belge "
            "bildiriminden FARKLI bir karardır -- burada eksik olan belge "
            "değil, yetkidir."
        ),
        # Var olan en yakın gerçek örnekler biçim/üslup referansı için
        # kullanılır; bu klasördeki kartların çoğu "eksik_belge" ile
        # karışık olsa da resmî ret/yönlendirme dilini taşır.
        "few_shot_glob": "02_cevap_yazisi/08_eksik_belge_yetkisizlik/*.md",
    },
    "yalnizca_bilgilendirme": {
        "adet": 25,
        "aciklama": (
            "Gelen evrak bir karar talep etmiyor (duyuru/bilgi paylaşımı "
            "niteliğinde) veya kurum, başvuruya ilişkin yalnız mevcut "
            "durumu/süreci bilgilendiriyor; KARAR üretmiyor. decision "
            "burada 'bir işlemin sonucu' değil, 'karar gerektirmeyen "
            "bilgilendirme' anlamına gelir."
        ),
        "few_shot_glob": "03_bilgilendirme_metni/*/*.md",
    },
    "belirsiz_basvuru": {
        "adet": 30,
        "aciklama": (
            "Başvuru talebi belirsiz veya çelişkili; kurum karar vermek "
            "yerine ek açıklama/bilgi talep ediyor. Cevap bir karar "
            "değil, bir sorudur."
        ),
        "few_shot_glob": "02_cevap_yazisi/03_bilgi_edinme/*.md",
    },
    "coklu_talep": {
        "adet": 25,
        "aciklama": (
            "Tek başvuru yazısında birden fazla, birbirinden bağımsız "
            "talep var; kurum her talebi ayrı ayrı sonuçlandırıyor "
            "(biri kabul, biri ret, biri yönlendirme gibi)."
        ),
        "few_shot_glob": "02_cevap_yazisi/*/*.md",
    },
}

assert TARGET_DECISIONS.keys() == ALLOWED_DECISIONS, (
    "TARGET_DECISIONS tam olarak ALLOWED_DECISIONS'ın 8 üyesini kapsamalı "
    f"-- eksik: {ALLOWED_DECISIONS - TARGET_DECISIONS.keys()}, "
    f"fazla: {TARGET_DECISIONS.keys() - ALLOWED_DECISIONS}"
)

TOTAL_TARGET_CASES = sum(spec["adet"] for spec in TARGET_DECISIONS.values())
assert TOTAL_TARGET_CASES == 240, f"Toplam kota 240 olmalı, şu an: {TOTAL_TARGET_CASES}"

FEW_SHOT_PER_TYPE = 3

#: ``--seed`` ile geçersiz kılınabilir (bkz. main()); ``_load_few_shots``
#: bu değeri okur. Evren'in kendi örnekleme sıcaklığı deterministik
#: değildir (LLM çıktısı), bu tohum yalnız BİZİM tarafımızdaki tek
#: rastgelelik kaynağını -- few-shot örnek seçimini -- kontrol eder.
_FEW_SHOT_SEED = 42
MAX_EXAMPLE_CHARS = 2200

#: İtiraz artık ayrı bir karar türü değil -- her kotanın İÇİNDE,
#: ``incoming_type: "itiraz"`` olarak, kotanın kendi decision değeriyle
#: üretilir. Toplamın ~%15-20'si itiraz olmalı ve her karar türünde en az
#: 3 itiraz örneği bulunmalı (VAKA_URETIMI_240_PROMPT.md Aşama 2).
INCOMING_TYPE_ITIRAZ = "itiraz"
ITIRAZ_MIN_SHARE = 0.15
ITIRAZ_MAX_SHARE = 0.20
ITIRAZ_MIN_PER_DECISION = 3

#: Kurum çeşitliliği: en az 25 farklı kurum, tek bir kurum 240'ın en fazla
#: %8'i (19 vaka). İlk 25 vaka tamamlanmadan sınır uygulanmaz -- aksi
#: halde erken üretimde rastgele tekrar eden bir kurum, henüz hiçbir
#: alternatif üretilmemişken kalıcı olarak yasaklanabilir.
INSTITUTION_MIN_COUNT = 25
INSTITUTION_MAX_SHARE = 19 / 240
INSTITUTION_WARMUP_CASES = 25


#: Üst üste bu kadar MCP altyapı hatası görülürse tur durdurulur. Sunucu
#: düştüğünde her vakayı 3 kez deneyip elemek, 240 vakalık bir turda
#: yüzlerce Evren çağrısını boşa harcayıp sonunda mevzuatsız/eksik bir veri
#: seti bırakırdı -- erken ve gürültülü durmak doğrusudur.
MEVZUAT_ALTYAPI_HATA_ESIGI = 5


class _LegalReference(BaseModel):
    """LLM'in ürettiği tek bir mevzuat atfı (Aşama 3.2 yapısal şeması).

    ``verification_source``/``verification_status`` bilerek BURADA YOK:
    onları LLM değil, ``mevzuat_dogrulama`` doldurur. Modelin kendi
    çıktısını "doğrulanmış" diye işaretlemesine izin vermek, doğrulamanın
    tamamını anlamsız kılardı.
    """

    type: str = Field(
        description=(
            "Mevzuat türü: kanun | khk | yonetmelik | cb_kararname | "
            "cb_karar | genelge | teblig | tuzuk"
        )
    )
    number: str = Field(description="Resmî mevzuat numarası, ör. '4982'")
    title: str = Field(description="Mevzuatın resmî adı, ör. 'Bilgi Edinme Hakkı Kanunu'")
    article: str = Field(default="", description="Madde numarası; emin değilsen boş bırak")


class _GeneratedCase(BaseModel):
    """Evren'in doldurduğu alanlar -- ``case_id``/``provenance``/``split``
    gibi üretim-sonrası alanlar betik tarafından ayrıca eklenir, LLM'e
    bırakılmaz (deterministik ve izlenebilir kalsın diye)."""

    incoming_document: str = Field(description="Anonim, tam gelen evrak metni")
    incoming_type: str
    requested_action: str
    decision_reason: str = Field(description="Kararın gerekçesi, tek paragraf")
    outgoing_correspondence_type: str = Field(
        description="ust_yazi | cevap_yazisi | bilgilendirme_metni | diger_resmi_yazisma"
    )
    required_facts: list[str] = Field(
        description="Gelen evraktan taslağa taşınması gereken olgular"
    )
    missing_information: list[str] = Field(default_factory=list)
    expected_questions: list[str] = Field(default_factory=list)
    gold_draft: str = Field(description="Referans cevap taslağının tam metni")
    must_include: list[str] = Field(description="Taslakta mutlaka geçmesi gereken ifadeler")
    must_not_invent: list[str] = Field(
        description="Gelen evrakta OLMAYAN, taslağın asla üretmemesi gereken değerler"
    )
    legal_basis: list[_LegalReference] = Field(
        default_factory=list,
        description=(
            "Yalnız GERÇEKTEN var olduğundan emin olduğun, numaralı ve resmî "
            "adını doğru bildiğin mevzuat. Emin değilsen listeyi BOŞ bırak -- "
            "her atıf mevzuat.gov.tr'ye karşı otomatik doğrulanır ve "
            "doğrulanamayan bir atıf tüm vakayı geçersiz kılar."
        ),
    )
    used_person_names: list[str] = Field(
        description=(
            "incoming_document ve gold_draft içinde geçen HER kurgusal kişi "
            "adını (ad soyad, yalnız ad, yalnız soyad -- unvan/rol kelimeleri "
            "hariç) tek tek listele. Bu liste, metin yazıldıktan sonra ayrı "
            "bir anonimleştirme katmanının hangi adları maskeleyeceğini "
            "belirler -- eksik bırakılan bir ad maskelenmeden kalabilir."
        )
    )


@dataclass
class FewShotExample:
    baslik: str
    kategori: str
    body_excerpt: str


def _load_few_shots(
    pattern: str, count: int, *, niyet_filter: str | None = None
) -> list[FewShotExample]:
    """Gerçek, zaten anonimleştirilmiş kartlardan üslup referansı seç.

    Yalnız kalite kapısını geçmiş (``candidate``) kartlar kullanılır --
    reddedilmiş/bozuk bir kartı örnek göstermek üretimi bozar.

    Args:
        pattern: ``CORPUS_ROOT``'a göreli glob (ör. ``"02_cevap_yazisi/*.md"``).
        count: En fazla kaç örnek döndürüleceği.
        niyet_filter: Verilirse, yalnız ``niyet`` alanı bu değere TAM eşit
            olan kartlar seçilir -- ör. ``07_ret_kismen_kabul/`` klasörü
            hem "ret" hem "ret_kismen_kabul" niyetli kartları birlikte
            barındırır, bu ikisi filtre olmadan ayırt edilemez.
    """
    candidates = sorted(CORPUS_ROOT.glob(pattern))
    random.Random(_FEW_SHOT_SEED).shuffle(candidates)  # deterministik ama çeşitli seçim
    examples: list[FewShotExample] = []
    for path in candidates:
        meta, body = split_front_matter(read_text(path))
        if meta.get("rag_status") != "candidate":
            continue
        if niyet_filter is not None and meta.get("niyet") != niyet_filter:
            continue
        examples.append(
            FewShotExample(
                baslik=meta.get("baslik", path.stem),
                kategori=meta.get("kategori", ""),
                body_excerpt=body[:MAX_EXAMPLE_CHARS],
            )
        )
        if len(examples) >= count:
            break
    return examples


def _build_messages(
    decision: str,
    spec: dict[str, Any],
    examples: list[FewShotExample],
    *,
    avoid_institutions: list[str] | None = None,
    force_itiraz: bool = False,
    rejected_refs: list[str] | None = None,
) -> list[dict]:
    example_blocks = "\n\n".join(
        f"[ÜSLUP ÖRNEĞİ {i + 1} -- {ex.kategori}: {ex.baslik}]\n{ex.body_excerpt}"
        for i, ex in enumerate(examples)
    )
    system = (
        "Sen Türkçe resmî yazışma eğitim verisi üreten bir asistansın. "
        "Görevin TAMAMEN KURGUSAL bir vaka üretmektir -- gerçek bir kişiyi "
        "veya gerçek bir kurum-içi olayı ASLA kullanma, tamamen uydur.\n\n"
        "ÇOK ÖNEMLİ -- köşeli parantez yer tutucusu YAZMA: Aşağıdaki üslup "
        "örnekleri, PII'sı temizlenmiş gerçek belgelerdir; bu yüzden içlerinde "
        "``[EVRAK SAYISI]``, ``[KİŞİ ADI]`` gibi köşeli parantezli alanlar "
        "görürsün. Sen bunu TAKLİT ETME. Senin ürettiğin metin, o "
        "temizlemeden ÖNCEKİ hâle karşılık gelir: isim, tarih, evrak "
        "sayısı gibi her alana somut, akla yatkın, TAMAMEN UYDURMA bir "
        "değer yaz (ör. 'Ahmet Yıldız', '14.03.2026', 'E-2026/4521') -- "
        "hiçbir zaman köşeli parantez içinde bir yer tutucu etiketi ("
        "``[...]``) üretme. Anonimleştirme, sen bu metni yazdıktan SONRA "
        "ayrı bir işlemle otomatik yapılacak; senin işin gerçekçi ve "
        "tutarlı bir kurgu yazmak.\n\n"
        "Aşağıdaki üslup örnekleri yalnız BİÇİM ve TON referansıdır; "
        "içeriklerini kopyalama veya hafifçe değiştirerek yeniden üretme, "
        "tamamen yeni bir olay kurgula. Kamu kurumu adı için SOMUT ve "
        "GERÇEKÇİ, TAMAMEN UYDURMA bir kurum-il/ilçe birleşimi yaz (ör. "
        "'T.C. Sivas Valiliği', 'T.C. Bornova Kaymakamlığı') -- kurum "
        "TÜRÜ gerçek ve tanınabilir olmalı, ama ilini/ilçesini/tam adını "
        "her vakada değiştir; aynı kurumu tekrar tekrar kullanma.\n\n"
        "MEVZUAT (legal_basis) -- EN SIK YAPILAN HATA: Bir mevzuat "
        "NUMARASINI doğru hatırlayıp o numaraya YANLIŞ BİR AD yakıştırmak "
        "(ör. 5615'i 'Sosyal Yardımlaşma Kanunu' sanmak; gerçekte Gelir "
        "Vergisi Kanunu'dur). Her atıf mevzuat.gov.tr'ye karşı OTOMATİK "
        "doğrulanır: numara, tür ve RESMÎ AD birlikte tutmalıdır; madde "
        "verirsen o maddenin gerçekten var olduğu da kontrol edilir. Tek bir "
        "hatalı atıf, kusursuz olsa bile TÜM vakayı çöpe atar. Bu yüzden: "
        "yalnız resmî adını da numarasını da KESİN bildiğin, herkesçe "
        "bilinen genel mevzuata atıf yap (ör. type='kanun', number='4982', "
        "title='Bilgi Edinme Hakkı Kanunu'); numaralandırılmamış kurum içi "
        "genelge/tebliğe atıf YAPMA; emin değilsen legal_basis'i BOŞ BIRAK. "
        "Boş bırakmak bir eksiklik DEĞİLDİR -- resmî yazışmaların çoğu "
        "mevzuat atfı içermez. Madde numarasından emin değilsen article'ı "
        "boş bırak; atfın geri kalanı yine değerlendirilir. "
        "must_not_invent listesine, bir "
        "taslak yazma modelinin bu vakada uydurmaya en çok eğilimli "
        "olacağı 2-4 somut değeri yaz (ör. 'gerçekte belirtilmeyen bir "
        "evrak sayısı', 'gerçekte belirtilmeyen bir tarih'). "
        "used_person_names ÇOK ÖNEMLİ: incoming_document ve gold_draft'ta "
        "adı geçen HER kurgusal kişiyi (başvuran, vekil, üçüncü bir "
        "kişiden bahsederken kullandığın isim -- hepsini) eksiksiz "
        "listele; bu liste metni ayrıca maskeleyecek bir güvenlik "
        "katmanının girdisidir, unutulan bir isim maskelenmeden kalır."
    )
    avoid_block = ""
    if avoid_institutions:
        avoid_block = (
            "\n\nKURUM ÇEŞİTLİLİĞİ: aşağıdaki kurumlar bu üretim turunda "
            "zaten yeterince kullanıldı, YENİDEN KULLANMA, farklı bir "
            f"kurum uydur: {', '.join(avoid_institutions)}."
        )
    itiraz_block = ""
    if force_itiraz:
        itiraz_block = (
            "\n\nBu vaka bir İTİRAZ olmalı: incoming_document, kurumun "
            "DAHA ÖNCE verdiği bir karara karşı yapılan bir itiraz "
            "dilekçesi olsun (incoming_type alanına 'itiraz' yaz). "
            f"decision_reason, itirazın neden '{decision}' sonucuna "
            "bağlandığını, önceki kararla ilişkisini kurarak açıklamalı."
        )
    # Aynı (decision, index) yeniden denenirken önceki turda DOĞRULAMAYI
    # GEÇEMEYEN atıflar modele geri bildirilir; aksi halde model, sıcaklık
    # 0.8'de bile aynı yanlış numara/ad eşleşmesini ısrarla üretebilir.
    reddedilen_block = ""
    if rejected_refs:
        reddedilen_block = (
            "\n\nÖNCEKİ DENEMEDE DOĞRULANAMAYAN MEVZUAT ATIFLARI -- bunları "
            "TEKRAR KULLANMA, ya farklı ve kesin bildiğin bir mevzuata atıf "
            f"yap ya da legal_basis'i boş bırak: {'; '.join(rejected_refs)}."
        )
    user = (
        f"Hedef karar türü: {decision}\n"
        f"Vaka tanımı: {spec['aciklama']}\n\n"
        f"{example_blocks}\n\n"
        "Yukarıdaki üslup örneklerine benzer resmiyette, ama TAMAMEN YENİ "
        "bir gelen evrak + kurum kararı + cevap yazısı vakası üret. "
        "incoming_document başvuranın yazdığı evrakın tam metni olmalı; "
        "gold_draft kurumun buna verdiği resmî cevabın tam metni olmalı."
        f"{avoid_block}{itiraz_block}{reddedilen_block}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _extract_institution(text: str) -> str | None:
    """Gövdeden antet kurumunu çıkar (kurum çeşitliliği sayacı için)."""
    match = _INSTITUTION_LINE.search(text[:600])
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip(" .,'’")


def _scrub_reported_names(text: str, names: list[str]) -> str:
    """Bir öz-bildirilen kurgusal adın metinde kalan her izini maskele.

    ``semantic_anonymize``'ın isim dedektörleri (``_LABELLED_NAME``,
    ``_HONORIFIC_PERSON``, imza bloğu sezgisi...) gerçek bürokratik
    belgelere göre ayarlandı -- bunlar neredeyse hiç etiketsiz, ortasında
    üçüncü bir kişiden bahsetmez. LLM'in serbest anlatı üretimi bunu
    sıkça yapar (``"...personel Mehmet Demir'e başvurdum..."``) ve hiçbir
    etiket/bağlam sezgisi bunu yakalamaz. Bu yüzden üretim adımı kendi
    kullandığı adları (``used_person_names``) bildirir; burada o listedeki
    her ad, ``semantic_anonymize`` sonrası kalan her ham geçtiği yerde
    ayrıca maskelenir (rol-etiketli geçtiği yerler zaten doğru semantik
    yer tutucuyla değişmiş olur, bu yalnız artakalanı temizler).
    """
    for name in names:
        name = name.strip()
        if len(name) < 2:
            continue
        pattern = re.compile(
            r"\b" + re.escape(name) + r"(?:'[A-Za-zÇĞİÖŞÜçğıöşüâîû]+)?\b"
        )
        text = pattern.sub("[KİŞİ ADI]", text)
    return text


def _anonymization_findings(text: str) -> list[dict]:
    """Zaten anonimleştirilmiş/temizlenmiş metinde otomatik-düzeltilebilir
    kalan bulguları döndür (boşsa vaka güvenli demektir)."""
    findings = _audit_privacy_findings(text)
    return [f for f in findings if f["otomatik_duzeltilebilir"]]


def _case_id(decision: str, index: int) -> str:
    return f"GKC-{decision.upper()}-{index:03d}"


def _itiraz_count_for(adet: int) -> int:
    """Bu kararın kotasından kaç vaka itiraz olmalı (Aşama 2: ~%17,5 hedef,
    her türde en az ITIRAZ_MIN_PER_DECISION)."""
    return max(ITIRAZ_MIN_PER_DECISION, round(adet * 0.175))


async def _generate_one(
    decision: str,
    spec: dict[str, Any],
    index: int,
    *,
    dogrulayici: MevzuatDogrulayici,
    avoid_institutions: list[str] | None = None,
    force_itiraz: bool = False,
    rejected_refs: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str, list[str]]:
    """Tek bir vaka üretmeyi dener.

    Returns:
        ``(vaka ya da None, başarısızlık kategorisi, doğrulanamayan atıflar)``.
        Boş kategori başarı demektir. Üçüncü öğe, bir sonraki denemenin
        prompt'una geri beslenecek atıf özetlerini taşır. Hata mesajı hiçbir
        ham hassas değer taşımaz, yalnız kategori etiketi taşır (bkz.
        MAIN_ERRORS).

    Raises:
        MevzuatAltyapiHatasi: MCP sunucusuna ulaşılamadığında. Bu bilerek
            yakalanmaz -- bir altyapı arızasını "vaka kötü" diye kaydetmek,
            sunucu düştüğünde tüm turu sessizce mevzuatsız bırakırdı.
    """
    examples = _load_few_shots(
        spec["few_shot_glob"], FEW_SHOT_PER_TYPE, niyet_filter=spec.get("niyet_filter")
    )
    if not examples:
        return None, "few_shot_bulunamadi", []

    client = get_llm_client(
        provider="evren", model=settings.EVREN_LLM_LARGE_MODEL, temperature=0.8
    )
    messages = _build_messages(
        decision,
        spec,
        examples,
        avoid_institutions=avoid_institutions,
        force_itiraz=force_itiraz,
        rejected_refs=rejected_refs,
    )
    try:
        result = await client.generate_structured(messages=messages, response_model=_GeneratedCase)
    except Exception as exc:  # keep the batch auditable, not fatal
        return None, f"llm_hatasi:{type(exc).__name__}", []

    anonymized_incoming = _scrub_reported_names(
        semantic_anonymize(result.incoming_document), result.used_person_names
    )
    anonymized_draft = _scrub_reported_names(
        semantic_anonymize(result.gold_draft), result.used_person_names
    )
    bad_incoming = _anonymization_findings(anonymized_incoming)
    bad_draft = _anonymization_findings(anonymized_draft)
    if bad_incoming or bad_draft:
        kinds = sorted({f["bulgu_turu"] for f in [*bad_incoming, *bad_draft]})
        return None, f"anonimlestirme:{','.join(kinds)}", []

    # Aşama 3.2: mevzuat atıfları mevzuat.gov.tr'ye karşı doğrulanır.
    # Pilotta bu adım elle yapılmıştı ve 22 atıftan 2'si (%9) yanlış
    # çıkmıştı; otomatikleştirilmeden 240'lık üretim ~20 hatalı atıf
    # taşırdı. TEK bir doğrulanamayan atıf vakayı geçersiz kılar --
    # kısmen doğru bir gerekçe listesi eğitim verisi olarak yanlış olandan
    # daha tehlikelidir, çünkü hatayı gözden geçirenden gizler.
    dogrulanmis: list[dict[str, Any]] = []
    reddedilenler: list[str] = []
    gerekceler: list[str] = []
    for ref in result.legal_basis:
        sonuc = await dogrulayici.dogrula(
            MevzuatAtfi(tur=ref.type, numara=ref.number, baslik=ref.title, madde=ref.article)
        )
        if sonuc.gecerli:
            dogrulanmis.append(sonuc.kayit)
            continue
        reddedilenler.append(f"{ref.type} {ref.number} ({ref.title})")
        gerekceler.append(sonuc.gerekce.split(":", 1)[0])
    if reddedilenler:
        return None, f"mevzuat_dogrulanamadi:{','.join(sorted(set(gerekceler)))}", reddedilenler

    case_id = _case_id(decision, index)
    source_group = hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:16]
    institution = _extract_institution(anonymized_incoming) or _extract_institution(
        anonymized_draft
    )
    case = {
        "case_id": case_id,
        "incoming_document": anonymized_incoming,
        "incoming_type": result.incoming_type,
        "requested_action": result.requested_action,
        "decision": decision,
        "decision_reason": result.decision_reason,
        "outgoing_correspondence_type": result.outgoing_correspondence_type,
        "required_facts": result.required_facts,
        "missing_information": result.missing_information,
        "expected_questions": result.expected_questions,
        "gold_draft": anonymized_draft,
        "must_include": result.must_include,
        "must_not_invent": result.must_not_invent,
        # Yapısal (Aşama 3.2) + türetilmiş okunabilir biçim. ``title``
        # LLM'in iddiası değil, MCP'den gelen RESMÎ addır.
        "legal_basis": dogrulanmis,
        "legal_basis_text": [atif_metni(kayit) for kayit in dogrulanmis],
        "source_origin": "sentetik_kurgu",
        "provenance": {
            "uretim_yontemi": "evren_llm_large_few_shot",
            "uslup_referanslari": [ex.baslik for ex in examples],
            "kurum_tahmini": institution,
        },
        "review_status": "taslak",
        "source_group": source_group,
        "dataset_split": "n/a",
    }
    return case, "", []


def _load_existing_case_ids(path: Path) -> set[str]:
    """--resume için: dosyada zaten yazılı case_id'leri oku."""
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            ids.add(json.loads(line)["case_id"])
    return ids


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Checkpoint yazımı: her başarılı vaka HEMEN diske eklenir (atomik --
    aç/yaz/kapat tek satırlık append, yarım satır bırakmaz)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


async def _run(
    *, apply: bool, resume: bool, max_cases: int | None, max_retries: int = 3
) -> list[dict[str, Any]]:
    total_quota = sum(spec["adet"] for spec in TARGET_DECISIONS.values())
    already_done = _load_existing_case_ids(MAIN_OUTPUT) if (apply and resume) else set()
    if already_done:
        print(f"--resume: {len(already_done)} vaka zaten mevcut, atlanacak.")

    institution_counts: dict[str, int] = {}
    total_generated_this_run = 0
    cases: list[dict[str, Any]] = []
    dogrulayici = MevzuatDogrulayici()
    ardisik_altyapi_hatasi = 0

    for decision, spec in TARGET_DECISIONS.items():
        itiraz_quota = _itiraz_count_for(spec["adet"])
        print(f"Üretiliyor: {decision} ({spec['adet']} vaka, {itiraz_quota} itiraz)")
        for index in range(1, spec["adet"] + 1):
            if max_cases is not None and total_generated_this_run >= max_cases:
                print(f"--max-cases={max_cases} sınırına ulaşıldı, durduruluyor.")
                return cases

            case_id = _case_id(decision, index)
            if case_id in already_done:
                continue

            total_this_run = sum(institution_counts.values())
            avoid = None
            if total_this_run + len(already_done) >= INSTITUTION_WARMUP_CASES:
                cap = round(INSTITUTION_MAX_SHARE * total_quota)
                avoid = sorted(k for k, v in institution_counts.items() if v >= cap) or None

            force_itiraz = index <= itiraz_quota

            case: dict[str, Any] | None = None
            reason = ""
            rejected_refs: list[str] = []
            for attempt in range(1, max_retries + 1):
                try:
                    case, reason, rejected_refs = await _generate_one(
                        decision,
                        spec,
                        index,
                        dogrulayici=dogrulayici,
                        avoid_institutions=avoid,
                        force_itiraz=force_itiraz,
                        rejected_refs=rejected_refs,
                    )
                except MevzuatAltyapiHatasi as exc:
                    ardisik_altyapi_hatasi += 1
                    print(
                        f"  [deneme {attempt}/{max_retries}] {case_id}: "
                        f"mevzuat_altyapi_hatasi ({exc}) "
                        f"[{ardisik_altyapi_hatasi}/{MEVZUAT_ALTYAPI_HATA_ESIGI}]"
                    )
                    if ardisik_altyapi_hatasi >= MEVZUAT_ALTYAPI_HATA_ESIGI:
                        raise RuntimeError(
                            "mevzuat-mcp sunucusuna üst üste "
                            f"{ardisik_altyapi_hatasi} kez ulaşılamadı; üretim "
                            "durduruldu. Sunucuyu düzeltip --resume ile devam "
                            "edin -- yazılmış vakalar korunur."
                        ) from exc
                    continue
                ardisik_altyapi_hatasi = 0
                if case:
                    break
                print(f"  [deneme {attempt}/{max_retries}] {case_id}: {reason}")
                if apply:
                    _append_jsonl(
                        MAIN_ERRORS,
                        {
                            "case_id": case_id,
                            "decision": decision,
                            "index": index,
                            "attempt": attempt,
                            "basarisizlik_kategorisi": reason,
                        },
                    )

            if not case:
                print(f"  [BAŞARISIZ] {case_id}: {max_retries} denemede de üretilemedi ({reason})")
                continue

            cases.append(case)
            total_generated_this_run += 1
            institution = case["provenance"]["kurum_tahmini"]
            if institution:
                institution_counts[institution] = institution_counts.get(institution, 0) + 1
            preview = case["incoming_document"][:140].replace("\n", " ")
            itiraz_tag = " [itiraz]" if force_itiraz else ""
            print(f"  [tamam] {case_id}{itiraz_tag}: {preview}...")

            if apply:
                _append_jsonl(MAIN_OUTPUT, case)

    grand_total = len(already_done) + total_generated_this_run
    print(f"\nBu çalıştırmada üretilen: {total_generated_this_run}")
    print(f"Toplam (resume dahil): {grand_total}/{total_quota}")
    print(f"Kurum çeşitliliği (bu çalıştırma): {len(institution_counts)} farklı kurum")
    atifli = sum(1 for case in cases if case["legal_basis"])
    atif_sayisi = sum(len(case["legal_basis"]) for case in cases)
    print(f"Doğrulanmış mevzuat atfı: {atif_sayisi} adet, {atifli} vakada")

    if apply and cases:
        print(f"Yazıldı (checkpoint, satır satır): {MAIN_OUTPUT.relative_to(REPO_ROOT).as_posix()}")
        print(
            "Not: bu dosya üretim ornekler.jsonl'e otomatik KARIŞMAZ. "
            "Sıradaki adımlar için VAKA_URETIMI_240_PROMPT.md Aşama 4'e bakın."
        )
    elif not apply:
        print("(--dry-run: hiçbir dosya yazılmadı)")

    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Üret ama diske yazma.")
    mode.add_argument(
        "--apply", action="store_true", help="Üret ve vakalar.jsonl'e satır satır ekle."
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="vakalar.jsonl'de zaten var olan case_id'leri atla, kalanları üret.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Bu çalıştırmada üretilecek en fazla YENİ vaka sayısı (küçük parti/doğrulama batch'i için).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Few-shot örnek seçiminin deterministik tohumu (varsayılan: 42).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not settings.EVREN_API_KEY:
        print(
            "HATA: EVREN_API_KEY tanımlı değil. Bu betik yalnız Evren "
            "(llm-large) ile çalışacak şekilde tasarlandı -- bkz. "
            "VAKA_URETIM_PLAYBOOK.md 'Ön koşullar'.",
            file=sys.stderr,
        )
        return 2
    # Aşama 3.2: mevzuat doğrulaması ZORUNLUDUR, isteğe bağlı bir ek değil.
    # Sunucu kayıtlı değilken üretmeye devam etmek, doğrulanmamış atıflar
    # taşıyan bir veri seti üretip bunu "doğrulanmış" klasörüne yazmak
    # olurdu; bu yüzden burada fail-closed durulur.
    register_servers()
    if not is_registered(MEVZUAT_SERVER):
        print(
            "HATA: mevzuat-mcp sunucusu kayıtlı değil, mevzuat atıfları "
            "doğrulanamaz. MEVZUAT_MCP_ENABLED=true veya MEVZUAT_SOURCE=mcp "
            "ayarlayın (bkz. app/mcp/registry.py).",
            file=sys.stderr,
        )
        return 2
    global _FEW_SHOT_SEED
    _FEW_SHOT_SEED = args.seed
    asyncio.run(_run(apply=args.apply, resume=args.resume, max_cases=args.max_cases))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
