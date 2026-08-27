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
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

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
MAIN_REJECTED = MAIN_ROOT / "rejected" / "vaka-reddedilenler.jsonl"

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


class _RequiredFact(BaseModel):
    """Gelen evraktan cevap taslağına taşınması gereken izlenebilir olgu."""

    alan: str
    deger: str
    kaynak_satir: str = Field(description="Olgunun incoming_document içindeki kaynak cümlesi")


class _MissingInformation(BaseModel):
    """Başvurunun sonuçlandırılması için eksik olan bilgi veya belge."""

    alan: str
    neden: str


class _GeneratedCase(BaseModel):
    """Evren'in doldurduğu alanlar -- ``case_id``/``provenance``/``split``
    gibi üretim-sonrası alanlar betik tarafından ayrıca eklenir, LLM'e
    bırakılmaz (deterministik ve izlenebilir kalsın diye)."""

    incoming_document: str = Field(description="Anonim, tam gelen evrak metni")
    incoming_type: Literal[
        "dilekce",
        "bilgi_edinme_basvurusu",
        "ust_yazi",
        "sikayet",
        "itiraz",
        "kurum_talebi",
        "soru_onergesi",
    ]
    requested_action: str
    decision_reason: str = Field(description="Kararın gerekçesi, tek paragraf")
    outgoing_correspondence_type: Literal[
        "ust_yazi", "cevap_yazisi", "bilgilendirme_metni", "diger_resmi_yazisma"
    ]
    required_facts: list[_RequiredFact] = Field(
        description="Gelen evraktan taslağa taşınması gereken izlenebilir olgular"
    )
    missing_information: list[_MissingInformation] = Field(default_factory=list)
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
    used_organization_names: list[str] = Field(
        default_factory=list,
        description=(
            "incoming_document ve gold_draft içinde kurgulanan özel şirket, "
            "dernek, vakıf ve benzeri başvuran/tüzel kişi adlarını eksiksiz "
            "listele. Kamu kurumu antetlerini listeleme. Bu değerler ayrı "
            "anonimleştirme katmanında [KURUM ADI] ile maskelenir."
        ),
    )


class _ExtractedLegalBasis(BaseModel):
    """Taslakta açıkça geçen atıfların ikinci-pass yapılandırılmış çıktısı."""

    references: list[_LegalReference] = Field(default_factory=list)


class _RecoveredQualityMetadata(BaseModel):
    """Belge gövdelerine dokunmadan ikinci-pass çıkarılan yardımcı anotasyonlar."""

    required_facts: list[_RequiredFact]
    missing_information: list[_MissingInformation] = Field(default_factory=list)
    expected_questions: list[str] = Field(default_factory=list)
    must_include: list[str]


class _LegalRelevanceResult(BaseModel):
    """Resmî madde metni ile vaka iddiası arasındaki semantik uygunluk."""

    relevant: bool
    reason_code: str


class _DraftGroundednessResult(BaseModel):
    """Cevap taslağındaki somut olguların gelen evraka dayanma durumu."""

    grounded: bool
    reason_code: str
    unsupported_claims: list[str] = Field(default_factory=list)


class _InstitutionCompetenceResult(BaseModel):
    """Kurumun varlığı, idari coğrafyası ve somut görev uygunluğu."""

    valid: bool
    reason_code: str


class _CaseQualityReviewResult(BaseModel):
    """Tek çağrıda olgu dayanağı ile kurum/yetki uygunluğu denetimi."""

    grounded: bool
    institution_valid: bool
    reason_code: str
    unsupported_claims: list[str] = Field(default_factory=list)


@dataclass
class FewShotExample:
    baslik: str
    kategori: str
    body_excerpt: str
    card_id: str = ""
    source_path: str = ""
    card_sha256: str = ""
    source_group: str = ""


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
        card_text = read_text(path)
        meta, body = split_front_matter(card_text)
        if meta.get("rag_status") != "candidate":
            continue
        if niyet_filter is not None and meta.get("niyet") != niyet_filter:
            continue
        source_path = path.relative_to(REPO_ROOT).as_posix()
        source_identity = (
            meta.get("kaynak_sha256")
            or meta.get("kaynak_url")
            or meta.get("kaynak")
            or source_path
        )
        examples.append(
            FewShotExample(
                baslik=meta.get("baslik", path.stem),
                kategori=meta.get("kategori", ""),
                body_excerpt=body[:MAX_EXAMPLE_CHARS],
                card_id=meta.get("id", path.stem),
                source_path=source_path,
                card_sha256=hashlib.sha256(card_text.encode("utf-8")).hexdigest(),
                source_group=hashlib.sha256(str(source_identity).encode("utf-8")).hexdigest()[
                    :16
                ],
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
    quality_feedback: list[str] | None = None,
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
        "katmanının girdisidir, unutulan bir isim maskelenmeden kalır. "
        "used_organization_names alanına da kurguladığın özel şirket, dernek, "
        "vakıf ve benzeri tüzel kişi adlarını eksiksiz yaz; kamu kurumu "
        "antetlerini yazma.\n\n"
        "İZLENEBİLİRLİK SÖZLEŞMESİ -- çıktının kabul edilmesi için bunların "
        "TAMAMI zorunludur: required_facts yalnız cevaba gerçekten taşınması "
        "gereken olguları içersin; her required_facts[].kaynak_satir değeri "
        "incoming_document'tan EKSİKSİZ ve KELİMESİ KELİMESİNE kopyalanmış "
        "bir alt dize olsun (üç nokta ile kısaltma/parafraz yapma); her "
        "required_facts[].deger hem incoming_document hem gold_draft içinde "
        "kelimesi kelimesine geçsin. must_include içindeki her ifade "
        "gold_draft'tan kelimesi kelimesine kopyalanmış bir alt dize olsun. "
        "decision eksik_belge veya belirsiz_basvuru ise missing_information "
        "ve expected_questions listeleri boş OLAMAZ; en az bir somut eksik "
        "alan ve bunu tamamlatacak açık soru yaz.\n\n"
        "KARAR ANLAMI SÖZLEŞMESİ: kismi_kabul vakasında en az bir talep "
        "açıkça KABUL, en az bir başka talep açıkça RET edilmeli; tüm parçaları "
        "kabul ederek kısmi kabul deme. coklu_talep vakasında yalnız farklı "
        "gerekçeler değil, en az iki bağımsız İSTEM bulunmalı ve cevap her "
        "istemi ayrı sonuçlandırmalı. yalnizca_bilgilendirme vakasında yeni "
        "kabul/ret/iptal kararı verme; gelen evrak da esasen durum veya süreç "
        "bilgisi istemeli. yetkisizlikte doğru ve somut yetkili merciyi yaz. "
        "eksik_belgede yalnız gerçekten eksik olan adlandırılmış belge/bilgiyi "
        "iste. Kurum adı için gerçek idari coğrafyaya uygun bir birim kullan "
        "(ör. merkez il için uydurma 'İzmir Kaymakamlığı' yazma; gerçek bir "
        "ilçe adıyla Kaymakamlık kullan). Cevabın yeni tarihini gelen evraktaki "
        "en son tarihten en fazla 90 gün sonrasına koy; cevap tarihi ve yeni "
        "evrak sayısı dışında gelen evrakta bulunmayan tarih, tutar, oran, süre, "
        "belge teslimi, sistem kaydı veya inceleme sonucu UYDURMA.\n\n"
        "Taslağın imza makamı cevap veren kamu kurumunun gerçekçi yetkilisi "
        "olmalı; başvuranı, başvuran vekilini veya şirket yöneticisini kurum "
        "cevabının imza makamı olarak yazma. Gelen evrakta bulunmayan ödeme "
        "süresi, itiraz/dava süresi, yüzde veya destek programı kuralı ekleme.\n\n"
        "MEVZUAT UYGULANABİLİRLİĞİ: Var olan bir kanunu konuya ilgisiz biçimde "
        "kullanmak da yanlış atıftır. Örneğin hayvancılık destek başvurusundaki "
        "eksik belgeleri 657 sayılı Devlet Memurları Kanunu'na dayandırma. "
        "Taslakta yazdığın HER numaralı kanun legal_basis içinde bulunmalı; "
        "taslakta madde numarası yazarsan aynı madde legal_basis.article "
        "alanında da aynen yer almalı. Maddenin içeriğini ve olaya doğrudan "
        "uygulanışını kesin bilmiyorsan maddeyi ve atfı hiç yazma. ÇEKİRDEK "
        "KALİTE EVRESİ KESİN KURALI: hiçbir kanun, yönetmelik, tebliğ veya "
        "madde adı/numarası yazma; legal_basis alanını daima [] döndür. Kararı "
        "yalnız gelen evraktaki olgular ve açık idari gerekçe ile açıkla. "
        "Doğrulanmış mevzuat çeşitliliği sonraki ayrı evrede eklenecektir."
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
    kalite_block = ""
    if quality_feedback:
        kalite_block = (
            "\n\nÖNCEKİ DENEME İÇERİK KAPISINDAN GEÇMEDİ. Aşağıdaki hata "
            "kodlarının tümünü bu yeni vakada düzelt: "
            f"{', '.join(quality_feedback)}. Özellikle "
            "taslak_mevzuat_yapisal_kayit_yok varsa taslaktaki her 'NNNN "
            "sayılı' atfı legal_basis'e ekle veya taslaktan tamamen çıkar; "
            "taslak_madde_yapisal_kayit_uyusmazligi varsa taslak maddesiyle "
            "legal_basis.article birebir aynı olsun."
        )
    user = (
        f"Hedef karar türü: {decision}\n"
        f"Vaka tanımı: {spec['aciklama']}\n\n"
        f"{example_blocks}\n\n"
        "Yukarıdaki üslup örneklerine benzer resmiyette, ama TAMAMEN YENİ "
        "bir gelen evrak + kurum kararı + cevap yazısı vakası üret. "
        "incoming_document başvuranın yazdığı evrakın tam metni olmalı; "
        "gold_draft kurumun buna verdiği resmî cevabın tam metni olmalı."
        f"{avoid_block}{itiraz_block}{reddedilen_block}{kalite_block}"
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


def _scrub_reported_organizations(text: str, organizations: list[str]) -> str:
    """Öz-bildirilen kurgusal özel tüzel kişi adlarını semantik maskele."""
    for organization in organizations:
        organization = organization.strip()
        if len(organization) < 3:
            continue
        pattern = re.compile(
            r"(?<!\w)" + re.escape(organization) + r"(?:'[A-Za-zÇĞİÖŞÜçğıöşüâîû]+)?(?!\w)",
            flags=re.IGNORECASE,
        )
        text = pattern.sub("[KURUM ADI]", text)
    return text


_PUBLIC_INSTITUTION_SUFFIX = re.compile(
    r"\b(?:BAKANLIĞI|VALİLİĞİ|KAYMAKAMLIĞI|BELEDİYESİ|BELEDİYE BAŞKANLIĞI|"
    r"BAŞKANLIĞI|İL MÜDÜRLÜĞÜ|İLÇE MÜDÜRLÜĞÜ)\b",
    re.IGNORECASE,
)


def _private_organization_names(organizations: list[str]) -> list[str]:
    """Model yanlışlıkla bildirse bile kamu antetlerini özel şirket gibi maskeleme."""
    return [
        organization
        for organization in organizations
        if not _PUBLIC_INSTITUTION_SUFFIX.search(organization)
    ]


def _anonymization_findings(text: str) -> list[dict]:
    """Zaten anonimleştirilmiş/temizlenmiş metinde otomatik-düzeltilebilir
    kalan bulguları döndür (boşsa vaka güvenli demektir)."""
    findings = _audit_privacy_findings(text)
    return [f for f in findings if f["otomatik_duzeltilebilir"]]


def _sanitize_generated_value(
    value: Any, names: list[str], organizations: list[str] | None = None
) -> Any:
    """LLM'den gelen tüm serbest metin alanlarını aynı PII hattından geçir."""
    organizations = organizations or []
    if isinstance(value, str):
        sanitized = semantic_anonymize(value)
        sanitized = _scrub_reported_organizations(sanitized, organizations)
        return _scrub_reported_names(sanitized, names)
    if isinstance(value, list):
        return [_sanitize_generated_value(item, names, organizations) for item in value]
    if isinstance(value, dict):
        return {
            key: _sanitize_generated_value(item, names, organizations)
            for key, item in value.items()
        }
    return value


_QUALITY_PLACEHOLDER = re.compile(r"\[[^\]\n]+\]")
MIN_TRACEABLE_FACTS = 1
MIN_MUST_INCLUDE = 1


def _normalized_quality_text(value: str) -> str:
    """Olgu izlenebilirliği için noktalama bağımsız, sayı-korumalı biçim."""
    value = value.casefold()
    value = _QUALITY_PLACEHOLDER.sub("[alan]", value)
    value = re.sub(r"[^a-zçğıöşü0-9\[\] ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _content_validation_codes(
    *,
    decision: str,
    incoming_document: str,
    gold_draft: str,
    required_facts: list[dict[str, Any]],
    missing_information: list[dict[str, Any]],
    expected_questions: list[str],
    must_include: list[str],
    must_not_invent: list[str] | None = None,
    legal_basis: list[dict[str, Any]] | None = None,
) -> list[str]:
    """LLM çıktısını yazılmadan önce deterministik içerik kapısından geçir."""
    codes: list[str] = []
    incoming = _normalized_quality_text(incoming_document)
    draft = _normalized_quality_text(gold_draft)

    if len(required_facts) < MIN_TRACEABLE_FACTS:
        codes.append("required_facts_yetersiz")
    if len(must_include) < MIN_MUST_INCLUDE:
        codes.append("must_include_listesi_yetersiz")
    for phrase in must_include:
        normalized = _normalized_quality_text(str(phrase))
        if not normalized or normalized not in draft:
            codes.append("must_include_eksik")
    for phrase in must_not_invent or []:
        normalized = _normalized_quality_text(str(phrase))
        if normalized and normalized in draft:
            codes.append("must_not_invent_ihlali")
    codes.extend(_draft_citation_contract_codes(gold_draft, legal_basis or []))
    for fact in required_facts:
        value = _normalized_quality_text(str(fact.get("deger", "")))
        source_line = _normalized_quality_text(str(fact.get("kaynak_satir", "")))
        if not value or value not in incoming:
            codes.append("olgu_gelen_evrakta_yok")
        if not value or value not in draft:
            codes.append("olgu_taslagina_tasinmadi")
        if not source_line or source_line not in incoming:
            codes.append("kaynak_satir_bulunamadi")

    codes.extend(_chronology_validation_codes(incoming_document, gold_draft))
    codes.extend(_institution_plausibility_codes(incoming_document, gold_draft))
    codes.extend(_unsupported_numeric_claim_codes(incoming_document, gold_draft))

    if decision in {"eksik_belge", "belirsiz_basvuru"}:
        if not missing_information:
            codes.append("eksik_bilgi_listesi_bos")
        if not expected_questions:
            codes.append("beklenen_soru_listesi_bos")
    return codes


_FULL_DATE = re.compile(r"\b(?P<day>0[1-9]|[12]\d|3[01])[.](?P<month>0[1-9]|1[0-2])[.](?P<year>20\d{2})\b")
_ELECTRONIC_DOCUMENT_YEAR = re.compile(r"\bE-(?P<year>20\d{2})[/\-]")
_MAX_RESPONSE_DELAY = timedelta(days=90)


def _chronology_validation_codes(incoming_document: str, gold_draft: str) -> list[str]:
    """Gelen evraktan kopan yıl/tarih sıçramalarını deterministik yakala.

    Taslak yeni bir cevap tarihi ve evrak sayısı üretebilir; ancak bunlar gelen
    evraktaki en son tarihten en fazla 90 gün sonraya ait olabilir. Gelen
    evrakta hiç tam tarih yoksa bu kural uygulanmaz.
    """

    def parsed_dates(text: str) -> list[datetime]:
        values: list[datetime] = []
        for match in _FULL_DATE.finditer(text):
            try:
                values.append(datetime.strptime(match.group(0), "%d.%m.%Y"))
            except ValueError:
                continue
        return values

    codes: list[str] = []
    for match in _FULL_DATE.finditer(gold_draft):
        try:
            datetime.strptime(match.group(0), "%d.%m.%Y")
        except ValueError:
            codes.append("taslak_takvim_tarihi_gecersiz")

    incoming_dates = parsed_dates(incoming_document)
    if not incoming_dates:
        return sorted(set(codes))
    # Başvuru metnindeki en büyük tarih gelecekteki etkinlik/teslim tarihi
    # olabilir. Resmî dilekçelerde imza tarihi çoğunlukla metindeki son tam
    # tarihtir; cevap kronolojisini bu belge tarihine göre kur.
    latest_incoming = incoming_dates[-1]
    latest_allowed = latest_incoming + _MAX_RESPONSE_DELAY
    incoming_values = {value.date() for value in incoming_dates}
    new_draft_dates: set[Any] = set()
    for value in parsed_dates(gold_draft):
        if value.date() in incoming_values:
            continue
        new_draft_dates.add(value.date())
        if value < latest_incoming or value > latest_allowed:
            codes.append("taslak_tarih_kronolojisi_gecersiz")
    if len(new_draft_dates) > 1:
        codes.append("taslak_desteksiz_ek_tarih")

    allowed_years = set(range(latest_incoming.year, latest_allowed.year + 1))
    for match in _ELECTRONIC_DOCUMENT_YEAR.finditer(gold_draft):
        if int(match.group("year")) not in allowed_years:
            codes.append("taslak_evrak_yili_gecersiz")
    return sorted(set(codes))


_METROPOLITAN_PROVINCES = {
    "adana", "ankara", "antalya", "aydın", "balıkesir", "bursa", "denizli",
    "diyarbakır", "erzurum", "eskişehir", "gaziantep", "hatay", "istanbul",
    "izmir", "kahramanmaraş", "kayseri", "kocaeli", "konya", "malatya",
    "manisa", "mardin", "mersin", "muğla", "ordu", "sakarya", "samsun",
    "şanlıurfa", "tekirdağ", "trabzon", "van",
}

_MONEY_CLAIM = re.compile(
    r"\b\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})?\s*TL\b", re.IGNORECASE
)
_PERCENT_CLAIM = re.compile(r"%\s*\d+(?:[.,]\d+)?")
_DURATION_CLAIM = re.compile(
    r"\b\d+\s+(?:iş\s+)?gün(?:lük|ü)?(?:\s+içinde)?\b", re.IGNORECASE
)


def _unsupported_numeric_claim_codes(
    incoming_document: str, gold_draft: str
) -> list[str]:
    """Taslağa sonradan eklenen tutar, yüzde ve gün sürelerini reddet."""
    incoming = _normalized_quality_text(incoming_document)
    codes: list[str] = []
    for pattern, code in (
        (_MONEY_CLAIM, "taslak_desteksiz_tutar"),
        (_PERCENT_CLAIM, "taslak_desteksiz_yuzde"),
        (_DURATION_CLAIM, "taslak_desteksiz_gun_suresi"),
    ):
        for match in pattern.finditer(gold_draft):
            if _normalized_quality_text(match.group(0)) not in incoming:
                codes.append(code)
    return sorted(set(codes))


def _institution_plausibility_codes(
    incoming_document: str, gold_draft: str
) -> list[str]:
    """Bilinen kaldırılmış büyükşehir il özel idaresi birleşimlerini reddet."""
    combined = (
        f"{incoming_document}\n{gold_draft}"
        .replace("İ", "i")
        .replace("I", "ı")
        .casefold()
    )
    if "il özel idaresi" not in combined:
        return []
    if any(province.casefold() in combined for province in _METROPOLITAN_PROVINCES):
        return ["kaldirilmis_buyuksehir_il_ozel_idaresi"]
    return []


_LEGAL_KIND_LOOKAHEAD = (
    r"(?=[^\n.]{0,150}\b(?:Kanunu|Kanun|Yönetmeliği|Yönetmelik|Tebliği|"
    r"Tebliğ|Kararnamesi|Kararname|KHK|KVKK|İYUK|VUK|TCK|CMK|HMK)\b)"
)
_DRAFT_LAW_NUMBER = re.compile(
    rf"\b(?P<number>\d{{3,5}})\s+sayılı\b\s*{_LEGAL_KIND_LOOKAHEAD}",
    re.IGNORECASE,
)
_DRAFT_LAW_ARTICLE = re.compile(
    rf"\b(?P<number>\d{{3,5}})\s+sayılı\b\s*{_LEGAL_KIND_LOOKAHEAD}"
    r".{0,180}?\b(?P<article>\d+)\s*\.\s*madde",
    re.IGNORECASE | re.DOTALL,
)
_DRAFT_LAW_WITH_TITLE = re.compile(
    r"\b(?P<number>\d{3,5})\s+sayılı\s+"
    r"(?P<title>[A-ZÇĞİÖŞÜa-zçğıöşü0-9İıâîûÂÎÛ .,'’()\-/]{2,140}?"
    r"(?:Kanunu|Kanun))\b",
    re.IGNORECASE,
)
def _merge_draft_legal_references(
    gold_draft: str, structured: list[_LegalReference]
) -> list[_LegalReference]:
    """Taslakta açıkça yazılı kanun/madde atıflarını yapısal listeye çıkar.

    Bu yalnız metadata onarımıdır; eklenen atıflar da aşağıdaki zorunlu MCP
    doğrulamasından geçer. Başlığı açıkça çıkarılamayan bir numara burada
    eklenmez ve içerik sözleşmesi tarafından reddedilir.
    """
    merged = [reference.model_copy() for reference in structured]
    articles_by_number: dict[str, set[str]] = {}
    for match in _DRAFT_LAW_ARTICLE.finditer(gold_draft):
        articles_by_number.setdefault(match.group("number"), set()).add(
            match.group("article")
        )

    for match in _DRAFT_LAW_WITH_TITLE.finditer(gold_draft):
        number = match.group("number")
        title = re.sub(r"\s+", " ", match.group("title")).strip(" .,;:")
        articles = articles_by_number.get(number) or {""}
        for article in sorted(articles):
            if any(
                reference.number == number and reference.article.strip() == article
                for reference in merged
            ):
                continue
            merged.append(
                _LegalReference(
                    type="kanun", number=number, title=title, article=article
                )
            )
    return merged


async def _recover_missing_draft_references(
    client: Any,
    gold_draft: str,
    references: list[_LegalReference],
) -> list[_LegalReference]:
    """Regex'in başlığını çıkaramadığı açık atıfları ikinci LLM geçişiyle yapılandır.

    Modelin döndürdüğü numara taslakta birebir yoksa koşulsuz atılır. Sonuç
    yine ``MevzuatDogrulayici`` kapısından geçeceği için bu adım doğrulama
    yerine geçmez; yalnız yapılandırılmış aday üretir.
    """
    if "taslak_mevzuat_yapisal_kayit_yok" not in _draft_citation_contract_codes(
        gold_draft, [reference.model_dump() for reference in references]
    ):
        return references
    draft_numbers = {
        match.group("number") for match in _DRAFT_LAW_NUMBER.finditer(gold_draft)
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Verilen anonim Türkçe resmî taslaktaki HER 'NNNN sayılı' "
                "mevzuat atfını yapılandır. Yalnız metinde açıkça geçen "
                "numaraları döndür. Resmî başlığı kesin bilmiyorsan yine "
                "metindeki açık adı kullan; madde yazılıysa article alanına "
                "yalnız madde numarasını yaz, yoksa boş bırak."
            ),
        },
        {"role": "user", "content": gold_draft},
    ]
    try:
        extracted = await client.generate_structured(
            messages=messages, response_model=_ExtractedLegalBasis
        )
    except Exception:
        return references
    recovered = [
        reference
        for reference in extracted.references
        if reference.number.strip() in draft_numbers
    ]
    return _merge_draft_legal_references(gold_draft, [*references, *recovered])


async def _recover_quality_metadata(
    client: Any,
    *,
    decision: str,
    incoming_document: str,
    gold_draft: str,
) -> _RecoveredQualityMetadata | None:
    """İyi belge gövdelerinin eksik/yanlış yardımcı anotasyonlarını yeniden çıkar."""
    messages = [
        {
            "role": "system",
            "content": (
                "Yalnız verilen iki anonim metinden yardımcı kalite metadata'sı "
                "çıkar; metinleri yeniden yazma. En az bir required_fact üret. "
                "Her deger hem gelen evrak hem cevapta birebir geçsin; her "
                "kaynak_satir gelen evraktan birebir cümle olsun. En az bir "
                "must_include ifadesi cevap taslağından birebir alt dize olsun. "
                "Karar eksik_belge veya belirsiz_basvuru ise somut "
                "missing_information ve bunları tamamlatan expected_questions "
                "listeleri boş olamaz. Metinlerde olmayan hiçbir olgu ekleme."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "decision": decision,
                    "incoming_document": incoming_document,
                    "gold_draft": gold_draft,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        return await client.generate_structured(
            messages=messages, response_model=_RecoveredQualityMetadata
        )
    except Exception:
        return None


async def _judge_legal_relevance(
    client: Any,
    *,
    requested_action: str,
    decision_reason: str,
    gold_draft: str,
    official_reference: dict[str, Any],
    official_article_text: str,
) -> bool:
    """Atıf yapılan resmî düzenleme vaka iddiasını gerçekten destekliyor mu?"""
    article = str(official_reference.get("article") or official_reference.get("madde") or "").strip()
    if article and not official_article_text.strip():
        return False
    messages = [
        {
            "role": "system",
            "content": (
                "Türk mevzuatı atıf denetçisisin. Madde numarası varsa yalnız "
                "verilen RESMÎ madde metnine dayan. Madde numarası yoksa resmî "
                "düzenleme başlığının vaka konusunu doğrudan düzenleyip "
                "düzenlemediğini denetle; yalnız genel kamu/idare çağrışımı "
                "yeterli değildir. Taslak düzenlemeye onda olmayan bir şart, "
                "süre, yetki veya sonuç yüklüyorsa relevant=false döndür. "
                "Şüphede fail-closed false döndür."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "requested_action": requested_action,
                    "decision_reason": decision_reason,
                    "gold_draft": gold_draft,
                    "official_reference": official_reference,
                    "official_article_text": official_article_text,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        result = await client.generate_structured(
            messages=messages, response_model=_LegalRelevanceResult
        )
    except Exception:
        return False
    return result.relevant


async def _judge_draft_groundedness(
    client: Any,
    *,
    incoming_document: str,
    requested_action: str,
    decision: str,
    decision_reason: str,
    gold_draft: str,
) -> bool:
    """Taslağın, idari karar dışında yeni somut olgu uydurmadığını denetle."""
    messages = [
        {
            "role": "system",
            "content": (
                "Türkçe resmî yazışma veri seti olgu denetçisisin. Cevap "
                "taslağındaki her somut tarih, evrak numarası, tutar, oran, "
                "süre, kişi/kurum durumu, teslim/sistem kaydı ve inceleme "
                "bulgusunu gelen evrakla karşılaştır. Kurumun verilen decision "
                "ve decision_reason kapsamındaki kararı, yeni cevap tarihi, "
                "yeni cevap evrak sayısı, standart hitap ve kapanış yeni olgu "
                "sayılmaz. Ancak 'kontrolde belgenin eksik olduğu görüldü', "
                "'dosya şu tarihte birime sevk edildi', 'kurul gündemine şu "
                "tarihte alındı', 'sistemde şu sonuç tespit edildi' gibi kurum "
                "içi işlem/bulgu iddiaları karar değildir ve gelen evrakta "
                "dayanağı yoksa kesinlikle unsupported claim sayılır. Gelen "
                "evrak belgelerin sunulduğunu söylüyorsa cevap bunların eksik "
                "olduğunu yeni bir inceleme sonucu gibi varsayamaz. Bunların "
                "dışında gelen evrakta açıkça bulunmayan tek "
                "bir somut iddia varsa grounded=false döndür ve kısa biçimde "
                "unsupported_claims alanına yaz. Parafraz kabul edilir; çıkarım "
                "ve varsayım kabul edilmez. Şüphede fail-closed false döndür."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "incoming_document": incoming_document,
                    "requested_action": requested_action,
                    "decision": decision,
                    "decision_reason": decision_reason,
                    "gold_draft": gold_draft,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        result = await client.generate_structured(
            messages=messages, response_model=_DraftGroundednessResult
        )
    except Exception:
        return False
    return bool(getattr(result, "grounded", False))


async def _judge_institution_competence(
    client: Any,
    *,
    institution: str,
    incoming_document: str,
    decision: str,
    decision_reason: str,
    gold_draft: str,
) -> bool:
    """Kurum yapısı ve vakada iddia edilen görev/yetki makul mü?"""
    messages = [
        {
            "role": "system",
            "content": (
                "Türkiye kamu idaresi kurum ve görev denetçisisin. Kurumun "
                "2026 itibarıyla gerçek ve idari coğrafyaya uygun bir birim "
                "olup olmadığını; taslaktaki somut işi yapma, karar verme veya "
                "başka mercie yönlendirme yetkisinin makul olup olmadığını "
                "denetle. Büyükşehirlerde kaldırılmış il özel idarelerini, il "
                "adıyla uydurulmuş kaymakamlıkları, yanlış bakanlık/belediye "
                "görevlerini, varlığı doğrulanmayan isimlendirilmiş kamu destek "
                "programlarını ve doğrulanamayan kesin yetki dağılımlarını "
                "valid=false yap. Yalnız kurum adı gerçek diye yetkiyi doğru "
                "sayma. Şüphede fail-closed false döndür."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "institution": institution,
                    "incoming_document": incoming_document,
                    "decision": decision,
                    "decision_reason": decision_reason,
                    "gold_draft": gold_draft,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        result = await client.generate_structured(
            messages=messages, response_model=_InstitutionCompetenceResult
        )
    except Exception:
        return False
    return bool(getattr(result, "valid", False))


async def _review_case_quality(
    client: Any,
    *,
    institution: str,
    incoming_document: str,
    requested_action: str,
    decision: str,
    decision_reason: str,
    gold_draft: str,
) -> _CaseQualityReviewResult | None:
    """Olgu ve kurum/yetki denetimini tek, düşük sıcaklıklı çağrıda yap."""
    messages = [
        {
            "role": "system",
            "content": (
                "Türkçe resmî yazışma veri seti kalite denetçisisin. İki kapıyı "
                "aynı anda değerlendir. (1) grounded: cevap taslağındaki somut "
                "tarih, tutar, oran, süre, belge durumu, sistem/inceleme bulgusu "
                "gelen evrakta açıkça desteklenmeli. Yalnız verilen karar, yeni "
                "cevap tarihi/evrak sayısı ve standart kapanış istisnadır. "
                "Başvuruda 'belge sunuldu' denirken cevapta 'eksik bulundu' "
                "denmesi; yeni sevk, kurul gündemi veya sistem tarihi üretilmesi "
                "grounded=false nedenidir. (2) institution_valid: kurum 2026 "
                "itibarıyla gerçek, coğrafi olarak doğru ve somut işte yetkili "
                "olmalı. Büyükşehirde il özel idaresi, il adıyla kaymakamlık, "
                "uydurma kamu programı, yanlış sosyal yardım/ruhsat/izin mercii "
                "ve doğrulanamayan kesin yetki dağılımı false nedenidir. Her iki "
                "kapıda da şüphede fail-closed false döndür."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "institution": institution,
                    "incoming_document": incoming_document,
                    "requested_action": requested_action,
                    "decision": decision,
                    "decision_reason": decision_reason,
                    "gold_draft": gold_draft,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        result = await client.generate_structured(
            messages=messages, response_model=_CaseQualityReviewResult
        )
    except Exception:
        return None
    return result if isinstance(result, _CaseQualityReviewResult) else None


def _add_uncovered_number_references(
    gold_draft: str, references: list[_LegalReference]
) -> list[_LegalReference]:
    """Başlığı çıkarılamayan açık kanun numaralarını resmî çözüm adayına çevir."""
    merged = [reference.model_copy() for reference in references]
    covered = {reference.number.strip() for reference in merged}
    articles_by_number = {
        match.group("number"): match.group("article")
        for match in _DRAFT_LAW_ARTICLE.finditer(gold_draft)
    }
    for match in _DRAFT_LAW_NUMBER.finditer(gold_draft):
        number = match.group("number")
        if number in covered:
            continue
        merged.append(
            _LegalReference(
                type="kanun",
                number=number,
                title="",
                article=articles_by_number.get(number, ""),
            )
        )
        covered.add(number)
    return merged


def _draft_citation_contract_codes(
    gold_draft: str, legal_basis: list[dict[str, Any]]
) -> list[str]:
    """Taslakta yazılı her kanun/madde atfının yapısal kayıtta izini zorunlu kıl."""
    codes: list[str] = []
    basis_by_number: dict[str, list[dict[str, Any]]] = {}
    for reference in legal_basis:
        basis_by_number.setdefault(str(reference.get("number", "")).strip(), []).append(
            reference
        )

    for match in _DRAFT_LAW_NUMBER.finditer(gold_draft):
        if match.group("number") not in basis_by_number:
            codes.append("taslak_mevzuat_yapisal_kayit_yok")
    for match in _DRAFT_LAW_ARTICLE.finditer(gold_draft):
        references = basis_by_number.get(match.group("number"), [])
        if not any(str(reference.get("article", "")).strip() == match.group("article") for reference in references):
            codes.append("taslak_madde_yapisal_kayit_uyusmazligi")
    return codes


def _align_must_not_invent(
    incoming_document: str, must_not_invent: list[str]
) -> list[str]:
    """Gelen evrakta zaten bulunan olguları uydurma-yasağı listesinden çıkar."""
    incoming = _normalized_quality_text(incoming_document)
    return [
        phrase
        for phrase in must_not_invent
        if _normalized_quality_text(str(phrase))
        and _normalized_quality_text(str(phrase)) not in incoming
    ]


def _source_segments(text: str) -> list[str]:
    """Kaynak cümlesi için satır ve cümle sınırlarında aday alt dizeler üret."""
    segments: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"(?<=[.!?])\s+", line)
        segments.extend(part.strip() for part in parts if part.strip())
    return segments


def _align_traceability_fields(
    *,
    incoming_document: str,
    gold_draft: str,
    required_facts: list[dict[str, Any]],
    must_include: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Modelin yardımcı etiketlerini belge metinlerindeki gerçekle hizala.

    Belge gövdeleri değiştirilmez. Cevaba gerçekten taşınmayan olgular ve
    taslakta bulunmayan ``must_include`` iddiaları atılır; parafraz edilmiş
    ``kaynak_satir`` ise aynı olguyu içeren gerçek kaynak cümlesiyle onarılır.
    Böylece yanlış anotasyon kabul edilmezken doğru vaka metni boşa atılmaz.
    """
    incoming = _normalized_quality_text(incoming_document)
    draft = _normalized_quality_text(gold_draft)
    source_segments = _source_segments(incoming_document)

    aligned_facts: list[dict[str, Any]] = []
    for fact in required_facts:
        value = _normalized_quality_text(str(fact.get("deger", "")))
        if not value or value not in incoming or value not in draft:
            continue
        source_line = str(fact.get("kaynak_satir", ""))
        if _normalized_quality_text(source_line) not in incoming:
            source_line = next(
                (
                    segment
                    for segment in source_segments
                    if value in _normalized_quality_text(segment)
                ),
                "",
            )
        if not source_line:
            continue
        aligned_facts.append({**fact, "kaynak_satir": source_line})

    aligned_must_include = [
        phrase
        for phrase in must_include
        if _normalized_quality_text(str(phrase))
        and _normalized_quality_text(str(phrase)) in draft
    ]
    return aligned_facts, aligned_must_include


def _collect_placeholders(value: Any) -> list[str]:
    """JSON liste/dict ayraçlarını değil, yalnız metin yer tutucularını topla."""
    found: set[str] = set()
    if isinstance(value, str):
        found.update(re.findall(r"\[[^\]\n]{2,80}\]", value))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_placeholders(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.update(_collect_placeholders(item))
    return sorted(found)


def _case_template_group(incoming_document: str, gold_draft: str) -> str:
    """Kurum+konu/şablon ailesini vaka kimliğinden bağımsız parmakizle."""
    text = f"{incoming_document}\n{gold_draft}".casefold()
    text = re.sub(r"\[[^\]]+\]", "[alan]", text)
    text = re.sub(r"\b\d+(?:[./:-]\d+)*\b", "[sayi]", text)
    text = re.sub(r"[^a-zçğıöşü\[\] ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return f"tpl-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def _case_id(decision: str, index: int) -> str:
    return f"GKC-{decision.upper()}-{index:03d}"


def _iter_case_targets():
    """Karar türlerini round-robin sırada üret.

    ``--max-cases`` küçük doğrulama partileri için kullanılıyor. Karar
    türlerini dış döngüye koymak ilk 16 vakanın tamamını ``tam_kabul``
    yapıyordu; bu da Aşama 4'te istenen dengeli kalite kapısını anlamsız
    kılıyordu. İndeksi dış döngüye almak ilk 8 hedefi sekiz farklı karar
    türüne dağıtırken 240'lık nihai kotaları değiştirmez.
    """
    max_quota = max(spec["adet"] for spec in TARGET_DECISIONS.values())
    for index in range(1, max_quota + 1):
        for decision, spec in TARGET_DECISIONS.items():
            if index <= spec["adet"]:
                yield decision, spec, index


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
    quality_feedback: list[str] | None = None,
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
        quality_feedback=quality_feedback,
    )
    try:
        result = await client.generate_structured(messages=messages, response_model=_GeneratedCase)
    except Exception as exc:  # keep the batch auditable, not fatal
        return None, f"llm_hatasi:{type(exc).__name__}", []

    if force_itiraz and result.incoming_type != INCOMING_TYPE_ITIRAZ:
        return None, "incoming_type_itiraz_bekleniyor", []
    if not force_itiraz and result.incoming_type == INCOMING_TYPE_ITIRAZ:
        return None, "incoming_type_itiraz_kota_disi", []

    private_organizations = _private_organization_names(result.used_organization_names)
    anonymized_incoming = _scrub_reported_organizations(
        semantic_anonymize(result.incoming_document), private_organizations
    )
    anonymized_incoming = _scrub_reported_names(
        anonymized_incoming, result.used_person_names
    )
    anonymized_draft = _scrub_reported_organizations(
        semantic_anonymize(result.gold_draft), private_organizations
    )
    anonymized_draft = _scrub_reported_names(anonymized_draft, result.used_person_names)
    sanitized_fields = _sanitize_generated_value(
        {
            "requested_action": result.requested_action,
            "decision_reason": result.decision_reason,
            "required_facts": [fact.model_dump() for fact in result.required_facts],
            "missing_information": [item.model_dump() for item in result.missing_information],
            "expected_questions": result.expected_questions,
            "must_include": result.must_include,
            "must_not_invent": result.must_not_invent,
        },
        result.used_person_names,
        private_organizations,
    )
    (
        sanitized_fields["required_facts"],
        sanitized_fields["must_include"],
    ) = _align_traceability_fields(
        incoming_document=anonymized_incoming,
        gold_draft=anonymized_draft,
        required_facts=sanitized_fields["required_facts"],
        must_include=sanitized_fields["must_include"],
    )
    sanitized_fields["must_not_invent"] = _align_must_not_invent(
        anonymized_incoming, sanitized_fields["must_not_invent"]
    )
    preliminary_codes = _content_validation_codes(
        decision=decision,
        incoming_document=anonymized_incoming,
        gold_draft=anonymized_draft,
        required_facts=sanitized_fields["required_facts"],
        missing_information=sanitized_fields["missing_information"],
        expected_questions=sanitized_fields["expected_questions"],
        must_include=sanitized_fields["must_include"],
        must_not_invent=sanitized_fields["must_not_invent"],
    )
    repairable_codes = {
        "required_facts_yetersiz",
        "must_include_listesi_yetersiz",
        "eksik_bilgi_listesi_bos",
        "beklenen_soru_listesi_bos",
    }
    if repairable_codes.intersection(preliminary_codes):
        recovered = await _recover_quality_metadata(
            client,
            decision=decision,
            incoming_document=anonymized_incoming,
            gold_draft=anonymized_draft,
        )
        if recovered is not None:
            repaired_fields = _sanitize_generated_value(
                {
                    "required_facts": [
                        fact.model_dump() for fact in recovered.required_facts
                    ],
                    "missing_information": [
                        item.model_dump() for item in recovered.missing_information
                    ],
                    "expected_questions": recovered.expected_questions,
                    "must_include": recovered.must_include,
                },
                result.used_person_names,
                private_organizations,
            )
            (
                repaired_fields["required_facts"],
                repaired_fields["must_include"],
            ) = _align_traceability_fields(
                incoming_document=anonymized_incoming,
                gold_draft=anonymized_draft,
                required_facts=repaired_fields["required_facts"],
                must_include=repaired_fields["must_include"],
            )
            sanitized_fields.update(repaired_fields)
    legal_references = _merge_draft_legal_references(
        anonymized_draft, result.legal_basis
    )
    legal_references = await _recover_missing_draft_references(
        client, anonymized_draft, legal_references
    )
    legal_references = _add_uncovered_number_references(
        anonymized_draft, legal_references
    )
    bad_incoming = _anonymization_findings(anonymized_incoming)
    bad_draft = _anonymization_findings(anonymized_draft)
    bad_metadata = _anonymization_findings(
        json.dumps(sanitized_fields, ensure_ascii=False, sort_keys=True)
    )
    if bad_incoming or bad_draft or bad_metadata:
        kinds = sorted(
            {f["bulgu_turu"] for f in [*bad_incoming, *bad_draft, *bad_metadata]}
        )
        return None, f"anonimlestirme:{','.join(kinds)}", []

    content_codes = _content_validation_codes(
        decision=decision,
        incoming_document=anonymized_incoming,
        gold_draft=anonymized_draft,
        required_facts=sanitized_fields["required_facts"],
        missing_information=sanitized_fields["missing_information"],
        expected_questions=sanitized_fields["expected_questions"],
        must_include=sanitized_fields["must_include"],
        must_not_invent=sanitized_fields["must_not_invent"],
        legal_basis=[reference.model_dump() for reference in legal_references],
    )
    if content_codes:
        return None, f"icerik_kapisi:{','.join(sorted(set(content_codes)))}", []

    institution = _extract_institution(anonymized_incoming) or _extract_institution(
        anonymized_draft
    )
    if not institution or "[" in institution or "]" in institution:
        return None, "icerik_kapisi:kurum_anteti_bulunamadi", []

    quality_judge_client = get_llm_client(
        provider="evren",
        model=settings.EVREN_LLM_LARGE_MODEL,
        temperature=0.0,
    )
    quality_review = await _review_case_quality(
        quality_judge_client,
        institution=institution,
        incoming_document=anonymized_incoming,
        requested_action=sanitized_fields["requested_action"],
        decision=decision,
        decision_reason=sanitized_fields["decision_reason"],
        gold_draft=anonymized_draft,
    )
    if quality_review is None or not quality_review.grounded:
        return None, "icerik_kapisi:taslak_desteksiz_olgu", []
    if not quality_review.institution_valid:
        return None, "icerik_kapisi:kurum_yetki_uygunsuz", []

    # Aşama 3.2: mevzuat atıfları mevzuat.gov.tr'ye karşı doğrulanır.
    # Pilotta bu adım elle yapılmıştı ve 22 atıftan 2'si (%9) yanlış
    # çıkmıştı; otomatikleştirilmeden 240'lık üretim ~20 hatalı atıf
    # taşırdı. TEK bir doğrulanamayan atıf vakayı geçersiz kılar --
    # kısmen doğru bir gerekçe listesi eğitim verisi olarak yanlış olandan
    # daha tehlikelidir, çünkü hatayı gözden geçirenden gizler.
    dogrulanmis: list[dict[str, Any]] = []
    reddedilenler: list[str] = []
    gerekceler: list[str] = []
    for ref in legal_references:
        if ref.title.strip():
            sonuc = await dogrulayici.dogrula(
                MevzuatAtfi(
                    tur=ref.type,
                    numara=ref.number,
                    baslik=ref.title,
                    madde=ref.article,
                )
            )
        else:
            sonuc = await dogrulayici.numaradan_dogrula(
                ref.type, ref.number, ref.article
            )
        if sonuc.gecerli:
            article_text = ""
            if ref.article.strip():
                article_text = await dogrulayici.madde_metni(
                    sonuc.mevzuat_id, ref.article
                )
            relevant = await _judge_legal_relevance(
                quality_judge_client,
                requested_action=sanitized_fields["requested_action"],
                decision_reason=sanitized_fields["decision_reason"],
                gold_draft=anonymized_draft,
                official_reference={**sonuc.kayit, "article": ref.article},
                official_article_text=article_text,
            )
            if not relevant:
                reddedilenler.append(
                    f"{ref.type} {ref.number} ({sonuc.resmi_baslik})"
                    + (f" madde {ref.article}" if ref.article.strip() else "")
                )
                gerekceler.append(
                    "madde_uygulanamaz" if ref.article.strip() else "mevzuat_uygulanamaz"
                )
                continue
            dogrulanmis.append(sonuc.kayit)
            continue
        reddedilenler.append(f"{ref.type} {ref.number} ({ref.title})")
        gerekceler.append(sonuc.gerekce.split(":", 1)[0])
    if reddedilenler:
        return None, f"mevzuat_dogrulanamadi:{','.join(sorted(set(gerekceler)))}", reddedilenler

    case_id = _case_id(decision, index)
    source_group = _case_template_group(anonymized_incoming, anonymized_draft)
    placeholders = _collect_placeholders(
        {
            "incoming_document": anonymized_incoming,
            "gold_draft": anonymized_draft,
            **sanitized_fields,
        }
    )
    references = [
        {
            "kaynak_kart_id": ex.card_id,
            "kaynak_yolu": ex.source_path,
            "kaynak_sha256": ex.card_sha256,
            "source_group": ex.source_group,
        }
        for ex in examples
    ]
    case = {
        "case_id": case_id,
        "incoming_document": anonymized_incoming,
        "incoming_type": result.incoming_type,
        "requested_action": sanitized_fields["requested_action"],
        "decision": decision,
        "decision_reason": sanitized_fields["decision_reason"],
        "outgoing_correspondence_type": result.outgoing_correspondence_type,
        "required_facts": sanitized_fields["required_facts"],
        "missing_information": sanitized_fields["missing_information"],
        "expected_questions": sanitized_fields["expected_questions"],
        "gold_draft": anonymized_draft,
        "must_include": sanitized_fields["must_include"],
        "must_not_invent": sanitized_fields["must_not_invent"],
        # Yapısal (Aşama 3.2) + türetilmiş okunabilir biçim. ``title``
        # LLM'in iddiası değil, MCP'den gelen RESMÎ addır.
        "legal_basis": dogrulanmis,
        "legal_basis_text": [atif_metni(kayit) for kayit in dogrulanmis],
        "source_origin": "sentetik_kurgu",
        "provenance": {
            "uretim_yontemi": "evren_llm_large_few_shot",
            "uslup_referanslari": references,
            "kurum_tahmini": institution,
        },
        "evidence": [
            {"tur": "uslup_referansi", **reference} for reference in references
        ],
        "anonymization": {
            "yontem": "semantic_anonymize+reported_name_scrub+privacy_audit",
            "yer_tutucular": placeholders,
            "denetim_durumu": "uygun",
        },
        "review_status": "taslak",
        "source_group": source_group,
        "dataset_split": "n/a",
    }
    return case, "", []


def _load_existing_cases(path: Path) -> list[dict[str, Any]]:
    """Checkpoint dosyasındaki doğrulanmış kayıtları yükle."""
    if not path.exists():
        return []
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    return cases


def _load_existing_case_ids(path: Path) -> set[str]:
    """--resume için: dosyada zaten yazılı case_id'leri oku."""
    return {case["case_id"] for case in _load_existing_cases(path)}


def _institution_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    """Resume sonrasında kurum kotasını önceki partilerle birlikte say."""
    counts: dict[str, int] = {}
    for case in cases:
        institution = case.get("provenance", {}).get("kurum_tahmini")
        if institution:
            counts[institution] = counts.get(institution, 0) + 1
    return counts


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Checkpoint yazımı: her başarılı vaka HEMEN diske eklenir (atomik --
    aç/yaz/kapat tek satırlık append, yarım satır bırakmaz)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _repair_checkpoint_cases(
    cases: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Eski checkpoint kayıtlarını güncel içerik sözleşmesine göre ayır."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    last_index_by_id = {
        str(case.get("case_id", "")): index for index, case in enumerate(cases)
    }
    for index, original in enumerate(cases):
        case_id = str(original.get("case_id", ""))
        if last_index_by_id.get(case_id) != index:
            rejected.append(
                {
                    "case_id": case_id,
                    "basarisizlik_kategorileri": ["tekrar_case_id_eski_checkpoint"],
                    "case": original,
                }
            )
            continue
        case = json.loads(json.dumps(original, ensure_ascii=False))
        case["must_not_invent"] = _align_must_not_invent(
            case["incoming_document"], case.get("must_not_invent", [])
        )
        codes = _content_validation_codes(
            decision=case["decision"],
            incoming_document=case["incoming_document"],
            gold_draft=case["gold_draft"],
            required_facts=case["required_facts"],
            missing_information=case["missing_information"],
            expected_questions=case["expected_questions"],
            must_include=case["must_include"],
            must_not_invent=case["must_not_invent"],
            legal_basis=case.get("legal_basis", []),
        )
        institution = case.get("provenance", {}).get("kurum_tahmini")
        if not institution or "[" in str(institution) or "]" in str(institution):
            codes.append("kurum_anteti_bulunamadi")
        if codes:
            rejected.append(
                {
                    "case_id": case.get("case_id"),
                    "basarisizlik_kategorileri": sorted(set(codes)),
                    "case": original,
                }
            )
        else:
            accepted.append(case)
    return accepted, rejected


def _write_jsonl_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    """JSONL dosyasını aynı klasörde geçici dosya üzerinden atomik değiştir."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def _repair_existing_checkpoint() -> int:
    """Mevcut checkpoint'i yedekleyip güncel kapıyla yeniden kürate et."""
    cases = _load_existing_cases(MAIN_OUTPUT)
    if not cases:
        print(f"HATA: onarılacak checkpoint yok: {MAIN_OUTPUT}", file=sys.stderr)
        return 2
    digest = hashlib.sha256(MAIN_OUTPUT.read_bytes()).hexdigest()[:16]
    backup = MAIN_ROOT / "audit" / f"checkpoint-before-repair-{digest}.jsonl"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy2(MAIN_OUTPUT, backup)

    accepted, rejected = _repair_checkpoint_cases(cases)
    _write_jsonl_atomic(MAIN_OUTPUT, accepted)
    for record in rejected:
        _append_jsonl(MAIN_REJECTED, record)
    print(f"Checkpoint onarıldı: {len(accepted)} kabul, {len(rejected)} ret")
    print(f"Denetim yedeği: {backup.relative_to(REPO_ROOT).as_posix()}")
    if rejected:
        print(f"Ret arşivi: {MAIN_REJECTED.relative_to(REPO_ROOT).as_posix()}")
    return 0


def _partition_manual_rejections(
    cases: list[dict[str, Any]], reasons_by_id: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    """Manuel incelemede reddedilen kayıtları kayıpsız biçimde ayır."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    found: set[str] = set()
    for case in cases:
        case_id = str(case.get("case_id", ""))
        if case_id not in reasons_by_id:
            accepted.append(case)
            continue
        found.add(case_id)
        rejected.append(
            {
                "case_id": case_id,
                "basarisizlik_kategorileri": ["manuel_inceleme"],
                "manuel_ret_nedeni": reasons_by_id[case_id],
                "case": case,
            }
        )
    return accepted, rejected, found


def _quarantine_existing_cases(reasons_by_id: dict[str, str]) -> int:
    """Belirli checkpoint kayıtlarını denetim yedeğiyle ret arşivine taşı."""
    cases = _load_existing_cases(MAIN_OUTPUT)
    accepted, rejected, found = _partition_manual_rejections(cases, reasons_by_id)
    missing = sorted(reasons_by_id.keys() - found)
    if missing:
        print(f"HATA: checkpoint'te bulunmayan vaka: {', '.join(missing)}", file=sys.stderr)
        return 2
    digest = hashlib.sha256(MAIN_OUTPUT.read_bytes()).hexdigest()[:16]
    backup = MAIN_ROOT / "audit" / f"checkpoint-before-manual-review-{digest}.jsonl"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy2(MAIN_OUTPUT, backup)
    _write_jsonl_atomic(MAIN_OUTPUT, accepted)
    for record in rejected:
        _append_jsonl(MAIN_REJECTED, record)
    print(f"Manuel inceleme uygulandı: {len(accepted)} kabul, {len(rejected)} ret")
    print(f"Denetim yedeği: {backup.relative_to(REPO_ROOT).as_posix()}")
    print(f"Ret arşivi: {MAIN_REJECTED.relative_to(REPO_ROOT).as_posix()}")
    return 0


async def _run(
    *,
    apply: bool,
    resume: bool,
    max_cases: int | None,
    max_retries: int = 3,
    only_case_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    total_quota = sum(spec["adet"] for spec in TARGET_DECISIONS.values())
    existing_cases = _load_existing_cases(MAIN_OUTPUT) if (apply and resume) else []
    already_done = {case["case_id"] for case in existing_cases}
    if already_done:
        print(f"--resume: {len(already_done)} vaka zaten mevcut, atlanacak.")

    institution_counts = _institution_counts(existing_cases)
    total_generated_this_run = 0
    cases: list[dict[str, Any]] = []
    dogrulayici = MevzuatDogrulayici()
    ardisik_altyapi_hatasi = 0

    for decision, spec in TARGET_DECISIONS.items():
        itiraz_quota = _itiraz_count_for(spec["adet"])
        print(f"Üretiliyor: {decision} ({spec['adet']} vaka, {itiraz_quota} itiraz)")

    for decision, spec, index in _iter_case_targets():
        if max_cases is not None and total_generated_this_run >= max_cases:
            print(f"--max-cases={max_cases} sınırına ulaşıldı, durduruluyor.")
            return cases

        case_id = _case_id(decision, index)
        if only_case_ids is not None and case_id not in only_case_ids:
            continue
        if case_id in already_done:
            continue

        total_completed = len(already_done) + total_generated_this_run
        avoid = None
        if total_completed >= INSTITUTION_WARMUP_CASES:
            cap = round(INSTITUTION_MAX_SHARE * total_quota)
            avoid = sorted(k for k, v in institution_counts.items() if v >= cap) or None

        force_itiraz = index <= _itiraz_count_for(spec["adet"])

        case: dict[str, Any] | None = None
        reason = ""
        rejected_refs: list[str] = []
        quality_feedback: list[str] = []
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
                    quality_feedback=quality_feedback,
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
            if reason.startswith("icerik_kapisi:"):
                quality_feedback = reason.split(":", 1)[1].split(",")
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

        if apply and case_id in _load_existing_case_ids(MAIN_OUTPUT):
            print(f"  [checkpoint-atlandı] {case_id}: kimlik başka süreçte yazılmış")
            already_done.add(case_id)
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
    print(f"Kurum çeşitliliği (toplam): {len(institution_counts)} farklı kurum")
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
    mode.add_argument(
        "--repair-existing",
        action="store_true",
        help="Mevcut checkpoint'i yedekleyip güncel içerik kapısıyla yeniden kürate et.",
    )
    mode.add_argument(
        "--quarantine-existing",
        action="store_true",
        help="--case-id/--reason çiftlerindeki vakaları manuel ret arşivine taşı.",
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
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Her vaka için azami üretim denemesi (varsayılan: 2).",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=None,
        help=(
            "Yalnız verilen planlı vaka kimliğini üret; başarısız checkpoint "
            "kayıtlarını dağılımı bozmadan onarmak için tekrarlanabilir."
        ),
    )
    parser.add_argument(
        "--reason",
        action="append",
        default=None,
        help="--quarantine-existing için karşılık gelen manuel ret nedeni.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repair_existing:
        return _repair_existing_checkpoint()
    if args.quarantine_existing:
        case_ids = args.case_id or []
        reasons = args.reason or []
        if not case_ids or len(case_ids) != len(reasons):
            print(
                "HATA: --quarantine-existing eşit sayıda --case-id ve --reason ister.",
                file=sys.stderr,
            )
            return 2
        return _quarantine_existing_cases(dict(zip(case_ids, reasons, strict=True)))
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
    only_case_ids = set(args.case_id) if args.case_id else None
    if only_case_ids is not None:
        planned_case_ids = {
            _case_id(decision, index)
            for decision, _spec, index in _iter_case_targets()
        }
        unknown = sorted(only_case_ids - planned_case_ids)
        if unknown:
            print(f"HATA: plan dışı --case-id: {', '.join(unknown)}", file=sys.stderr)
            return 2
    asyncio.run(
        _run(
            apply=args.apply,
            resume=args.resume,
            max_cases=args.max_cases,
            max_retries=args.max_retries,
            only_case_ids=only_case_ids,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
