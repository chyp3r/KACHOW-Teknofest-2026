# Görev 1 Şartname Skor Kartı

> Şartnamenin altı maddesi -- her biri bir metriğe, bir korpusa ve o metriği
> yeniden üreten komuta bağlı. `POST /api/v1/documents/analyze`'in altı
> yeteneğe nasıl karşılık geldiği için [docs/api/documents.md](../api/documents.md)'e bakın.

## Özet tablo

| # | Şartname maddesi | Uygulama | Metrik | Değer | Korpus | Komut |
|---|---|---|---|---|---|---|
| 1 | OCR veya doğrudan metin okuma | `FallbackDocumentExtractor` zinciri | Yönlendirme doğruluğu | **1.0000** (35/35) | 12 sentetik + 23 gerçek tarama | `make eval` (`evrak` suite) |
| 2 | Evrak türünü belirleme | `analyze_node` (birleşik yapılandırılmış çağrı) | Tür doğruluğu | **1.0000** gerçek (23/23) · **0.9167** sentetik (11/12) | 12 sentetik + 23 gerçek tarama | `python scripts/evaluate_classification.py` |
| 3 | Önemli bilgi unsurlarını çıkarma | `parse_labelled_fields` (deterministik, model öncesi) | Doğru alan oranı | **0.7571** (53/70) | 12 sentetik (yalnız) | `make eval` (`evrak` suite) |
| 4 | Eksik bilgileri tespit etme | `check_required_fields` (saf küme farkı, LLM'siz) | **Yanlış alarm oranı** | **0.2775** (58/209) | 12 sentetik + 23 gerçek tarama | `make eval` (`evrak` suite) |
| 5 | İlgili mevzuat önerme | `retrieve_mevzuat` + `suggest_mevzuat` + **yeni: `citation_support` doğrulaması** | Atıf doğrulama doğruluğu | **1.0000** (3/3 sabit örnek) | Sabit uydurma-atıf örneği | `make eval` (`evrak` suite) |
| 5b | (destek) İlgili kanunun getirilmesi | `HybridRetriever` (BM25+dense, Qdrant native RRF) | İsabet@3 | **1.0000** (10/10 belge türü) | Yerel mevzuat korpusu (7 kanun) | `python scripts/evaluate_mevzuat_retrieval.py` |
| 6 | Kısa ve öz özet oluşturma | `summary` (≤3 cümle) + isteğe bağlı `detailed_summary` | -- | *ölçülmedi bu geçişte* | 4 gerçek uzun tarama | `python scripts/evaluate_summarization.py` |

**Tümü şu commit'te ölçüldü**: bkz. `git log -1`. `intents`/`drafts` suite'leri bu
çalışmadan etkilenmedi (regresyon kontrolü: `make eval` tam raporunda görünür).

---

## Madde 1 -- OCR veya doğrudan metin okuma

**Uygulama**: `has_pdf_text_layer` / `is_scanned_text_layer`
([base.py](../../backend/app/infrastructure/extractors/base.py)) belgenin
gömülü metin katmanını mı yoksa tarayıcı kaynaklı "Class A" sahte metin
katmanını mı taşıdığını ayırt eder; `FallbackDocumentExtractor` bu karara
göre OCR zincirine (`TesseractExtractor` → `OllamaVisionExtractor`,
`deepseek-ocr`) düşer ya da düşmez.

**Ölçüm**: `evrak_suite.py`'nin `ocr_routing_rates` fonksiyonu, her belgenin
gerçek PDF baytları üzerinde yönlendirme kararını hesaplayıp altın kümenin
`scanned` bayrağıyla karşılaştırır. **35/35 doğru** -- 12 sentetik
(born-digital, `scanned=false`) ve 23 gerçek tarama (`scanned=true`, hepsi
`datasets/resmi_yazisma/00_gelen_kaynaklar/cevap_yazisi/`'den) hiç
karışmadan ayırt edildi.

OCR motoru seçiminin kendisi (hangi motor en iyi Türkçe okur) ayrı ölçülür:
`scripts/evaluate_ocr_benchmark.py`, `scripts/evaluate_ocr_real.py` --
CHANGELOG'un [1.36.0] girdisinde `deepseek-ocr`'ın seçilme gerekçesi.

---

## Madde 2 -- Evrak türünü belirleme

**Uygulama**: `analyze_node`, `DocumentType`'ın 10 değeri üzerinde tek bir
birleşik yapılandırılmış çağrı; deterministik yapısal sinyaller (`DAĞITIM`
gibi) istem içine gerçek olarak enjekte edilir, kalite katmanı başarısız
olursa 3 kademeli bir düşüş merdiveni vardır.

**Ölçüm**: `scripts/evaluate_classification.py --corpus both --report
gorev1-classification-baseline`, canlı `qwen3.5:9b` ile hem 12 sentetik hem
23 gerçek belge üzerinde (tam sonuç:
`evaluation/reports/gorev1-classification-baseline.json`).
**Gerçek taramalarda 23/23 (1.0000)**; sentetik kümede **11/12 (0.9167)** --
tek hata `evrak_06`: `information_request` (bilgi edinme başvurusu),
`petition` (genel dilekçe) olarak sınıflandırıldı. İkisi istem içinde zaten
ayrık kriterlerle ayrılıyor ("information_request: yalnızca 4982 sayılı
Kanun kapsamında... açıkça istendiğinde") ama bu örnekte sınır netleşmedi --
gerçek istem/prompt iyileştirmesi bu skor kartının kapsamı dışında, ama
regresyon olarak kayıtlı.

**Aynı koşumun eksik-bilgi tarafı da ölçüldü, ve gerçek bir bulgu
üretti**: tam ardışık düzenin (regex + LLM birleşimi) altın etiketle **tam
küme** eşleşmesi gerçek taramalarda **0/23**, sentetiklerde **12/12**. Bu
sayı göründüğü kadar kötü değil -- üç örneği elle inceleyince (CY-001,
CY-009, CY-010) neden ortaya çıkıyor:

- **`imza_sahibi`/`imza_unvani` modelin kendi çıkardığı `entities`
  listesinde göründüğü hâlde alan olarak doldurulmuyor.** CY-009'da model
  `Yaşar GÜLER`'i bir varlık olarak doğru tespit ediyor (`entities` içinde),
  ama aynı adı `imza_sahibi` alanına yazmıyor -- metin tam olarak
  "Yaşar GÜLER\nBakan" ile bitiyor, etiketsiz ama konumsal olarak açık bir
  imza bloğu. CY-001'de aynı örüntü (`Cevdet YILMAZ`). Bu tutarsız: CY-010'da
  aynı şekle sahip bir imza bloğu (`Bekir BOZDAĞ\nTürkiye Büyük Millet
  Meclisi\nBaşkanvekili`) **doğru** çıkarılıyor -- yani model bunu
  yapabiliyor, her zaman yapmıyor. Bu, harness'in yalnız-regex bulgusundan
  (`docs/evaluation/gorev1-scorecard.md`'nin Madde 4 bölümü) **farklı ve
  ondan bağımsız** bir zayıflık: regex zaten etiketsiz imza bloklarını hiç
  bulamıyordu, ama burada LLM de -- kendi tanıdığı bir adı bile -- güvenilir
  şekilde doğru alana yazamıyor.
- **CY-010 gibi TBMM-şablonu belgelerde `muhatap`/`gonderen_kurum` LLM
  tarafından da kurtarılamıyor** (`_meta.gorev1_labelling`'in belirttiği
  ayrıştırıcı-mimarisi boşluğu regex'e özgü değilmiş; model de adı geçen bir
  milletvekiline hitabı ve "T.C." satırı olmayan bir antedi güvenilir
  biçimde muhatap/gönderen olarak okumuyor).

Tam ardışık düzenin alan-bazlı yanlış alarm oranı bu geçişte ayrıca
ölçülmedi (yalnızca üç belgelik elle inceleme yapıldı, tam 23 belgelik bir
tekrar ~20 dakika sürüyor); yalnız-deterministik oran (Madde 4, 0.2775)
üst sınır olarak okunabilir -- LLM bazı alanları (`tarih`, `sayi`, `konu`,
etiketli `muhatap`/`gonderen_kurum`) düzeltir ama yukarıdaki iki örüntüyü
düzeltmez, dolayısıyla gerçek tam-ardışık-düzen oranı 0.2775'ten düşük ama
sıfır değildir.

---

## Madde 3 -- Önemli bilgi unsurlarını çıkarma

**Uygulama**: `parse_labelled_fields` (deterministik regex, yönetmeliğin
öngördüğü yan başlıkları okur) modelden **önce** çalışır ve
`merge_parsed_over_model` ile modelin çıktısını ezer -- bir alan belgede
gerçekten varsa, model onu farklı okusa bile kazanan ayrıştırıcıdır.

**Ölçüm**: `evrak_suite.py`'nin `extraction_totals`'ı, yalnızca `sentetik`
vakalarda (`gercek_tarama`'nın neden dışarıda bırakıldığı için
`scripts/build_evrak_eval_set.py`'nin kendi docstring'ine bakın -- 23 gerçek
belge için bağımsız elle-yazılmış değer kümesi bu geçişin kapsamı dışındaydı,
ve `parse_labelled_fields(clean_text)`'i kendi çıktısına karşı ölçmek
totolojik olurdu). **53 doğru / 8 kaçan / 9 yanlış / 0 sahte, 70 alan
üzerinden (0.7571)**.

**Not**: `imza_sahibi`/`imza_unvani` gerçek korpusta neredeyse hiç
kurtarılamıyor (regex açık bir "İmza:" etiketi arıyor; gerçek belgelerde
imza bloğu yalnızca ad/unvan satırı, etiketsiz) -- bu **madde 4'ün** yanlış
alarm oranına doğrudan yansıyor, aşağıda.

---

## Madde 4 -- Eksik bilgileri tespit etme

**Uygulama**: `check_required_fields`, `REQUIRED_FIELD_RULES` üzerinde saf
küme farkı -- **LLM yok**, her bulgu şiddet + madde atfı + gerekçe taşır.

**Ölçüm**: `evrak_suite.py`'nin `missing_field_rates`'i, `parse_labelled_fields`
ile **gerçekten** çıkarılan alanları `check_required_fields`'a verip
sonucu elle etiketlenmiş `expected_missing_fields`'la karşılaştırır (bkz.
`evrak_suite.py`'nin kendi docstring'i: bu tasarım kasıtlı olarak
totolojik olmayan bir sürüme yeniden yazıldı -- ilk sürüm altın kümeden
inşa edilen alanları yine altın kümeye karşı test ediyordu).

**Baş metrik -- yanlış alarm oranı: 0.2775 (58/209 alan-belge çifti)**.
Kategoriye göre: `sentetik` **0.11**, `gercek_tarama` **0.34**. Kaçırma oranı
**0.0000** (0 kaçan gerçek eksiklik).

**Bu sayı ne anlatıyor, ne anlatmıyor**: bu, **yalnızca deterministik
katmanın** (regex + kural tablosu, model hiç çağrılmadan) yanlış alarm
oranıdır. Üretimde `check_compliance_node` her zaman
`merge_parsed_over_model`'in birleşik çıktısını görür -- modelin kendi genel
dil anlayışı, regex'in etiket-eşleşmesi gerektiren körlüğünü (etiketsiz
tarih gibi) kısmen telafi eder. **Madde 2'nin canlı-model koşumunda elle
incelenen üç örnek bunu doğruluyor**: tam ardışık düzen `tarih`'i (etiketsiz
olsa bile) doğru buluyor, regex'in bulamadığı yer -- ama `imza_sahibi`/
`imza_unvani` ve TBMM-şablonu `muhatap`/`gonderen_kurum`'da **LLM de**
tutarsız kalıyor (bkz. Madde 2). Yani üretimin gerçek yanlış alarm oranı
bu sayıdan daha düşük ama **sıfır değil** -- tam bir alan-bazlı üretim oranı
bu geçişte ayrı ölçülmedi (canlı modelle 35 belge x tekrar gerektirir).
Başarısız vakaların tam listesi `make eval`'in ürettiği `evrak-latest.md`
raporunda.

---

## Madde 5 -- İlgili mevzuat, yönetmelik veya standart yazışma kurallarını önerme

**Uygulama**: `retrieve_mevzuat_node` (hibrit BM25+dense getirim) →
`suggest_mevzuat_node` (model alıntıları açıklar) → **yeni:
`citation_support` her önerinin atfını, getirilen alıntılardan gerçekten
gelip gelmediğine karşı doğrular** ([mevzuat_citation.py](../../backend/app/ai/compliance/mevzuat_citation.py)).
Doğrulanamayan bir atıf düşürülür; açıklaması doğrulanamayan bir öneri
atfını korur ama açıklaması nötr metinle değiştirilir. Her ikisi de
başarısız olursa (ya da model hiç öneri üretmezse), getirilen her alıntı
için ham, yapı gereği doğrulanmış bir atıf listesine düşülür.

**Ölçüm 1 -- sabit örnek (harness)**: `evrak_suite.py`'nin
`citation_fixture_rates`'i, üç (atıf, alıntılar, beklenen) üçlüsü üzerinde
**1.0000 doğruluk (3/3)**.

**Ölçüm 2 -- canlı model, gerçek üretim yolu**: bu değişikliği doğrularken
12 sentetik belgenin tamamı gerçek `qwen3.5:9b` ve gerçek yerel mevzuat
getiriminden geçirildi. **23 önerinin 1'i düşürüldü** -- `evrak_04`'te model
"Dilekçe Hakkının Kullanılmasına Dair Kanun - Madde 3" atfını üretti, oysa
getirilen alıntılar yalnızca Madde 4'ün metnini içeriyordu: gerçek bir
uydurma, doğru şekilde yakalandı. **Diğer 22 öneri hiç dokunulmadan
geçti** -- filtrenin meşru önerileri kaybetmediğinin doğrudan kanıtı. Bu
vaka artık `evrak_suite.py`'nin sabit örneğine kalıcı bir regresyon testi
olarak eklendi.

---

## Madde 5 destek -- ilgili kanunun doğru getirilmesi

**Uygulama**: `_build_mevzuat_query`, belge türüne özgü terimlerle
(`DOCUMENT_TYPE_QUERY_TERMS`) deterministik bir sorgu kurar; CHANGELOG'un
[1.35.0] girdisi bu tasarımı sabit ek (4/6) ve eksiz sorgu (3/6) alternatiflerine
karşı seçti.

**Ölçüm**: `scripts/evaluate_mevzuat_retrieval.py`, 10 `DocumentType`
değerinin her biri için beklenen kanunun top-3 içinde olup olmadığını
kontrol eder. **10/10 isabet** (5 tür RYUEHY'yi, 2 tür Dilekçe Kanunu'nu,
birer tür Bilgi Edinme/Memurlar/Tebligat kanunlarını doğru buldu).

---

## Madde 6 -- Kısa ve öz özet oluşturma

**Uygulama**: `analyze_node`'un birleşik çıktısındaki `summary` (≤3 cümle,
her yüklemede üretilir) + isteğe bağlı, sınırsız uzunluklu
`detailed_summary` (`DocumentService.generate_detailed_summary`, ayrı bir
uç nokta, yalnız istenirse).

**Ölçüm**: `scripts/evaluate_summarization.py`, 4 gerçek uzun taranmış
belge üzerinde (`_trim_for_extraction`'ın orta-kısım kısaltmasını
gerçekten tetikleyecek kadar uzun) -- özetin orta üçte-birden kaç
farklı kelime kullandığını ölçen bir kapsama vekili raporlar (özet
kalitesinin kendisi için referans yok, bkz. o betiğin kendi docstring'i).
**Bu geçişte yeniden koşulmadı** -- betik gerçek OCR (vision model) zinciri
çalıştırdığından madde 1-5'in aksine dakikalar sürer; mevcut CHANGELOG
kaydı hâlâ geçerli referans.

---

## Bu geçişte eklenen doğrulama

Önceden yalnızca madde 4 (eksik bilgi) tamamen deterministikti ve madde 5
(mevzuat önerisi) hiç doğrulanmıyordu -- istem modele "alıntılarda olmayan
madde numarası üretme" diyordu ve buna güveniliyordu. `citation_support`
bunu artık gerçek bir denetime çeviriyor: bkz. yukarıdaki Madde 5 ve
`backend/tests/unit/ai/test_mevzuat_citation.py`'deki 9 birim testi.
