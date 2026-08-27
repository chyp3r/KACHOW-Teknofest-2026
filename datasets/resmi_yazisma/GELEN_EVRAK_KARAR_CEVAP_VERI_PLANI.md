# Gelen Evrak – Karar – Cevap Veri Planı

> **Durum: yalnız plan.** Bu doküman ileride üretilecek deneysel veri kümesini
> tarif eder. Burada tarif edilen kayıtların hiçbiri `ornekler.jsonl` ile
> birleştirilmemiştir ve açık onay verilmeden birleştirilmeyecektir.

Mevcut üretim korpusu (`ornekler.jsonl`, 429 kayıt) tek tek **belgeleri**
saklar. Ürünün asıl görevi ise bir zincirdir: *gelen evrakı anla → yazışma
türünü seç → karar ver → eksik bilgiyi tespit et → doğru soruyu sor → taslağı
üret*. Mevcut korpus bu zincirin yalnız son halkasını (biçim ve üslup)
denetleyebiliyor. Bu plan eksik halkaları kapatacak ayrı bir kümeyi tarif eder.

---

## 1. Neden ayrı bir küme gerekiyor

Mevcut korpusun ölçülen sınırları (`rag-veri-analizi.json`):

| Gözlem | Değer | Sonuç |
| --- | --- | --- |
| Retrieval kaydı | 429 | Biçim/üslup için yeterli |
| Gelen evrak–cevap eşleşmesi taşıyan kayıt | 0 | Karar zinciri hiç denetlenemiyor |
| Karar taşıyan gerçek cevap yazısı | ~78 (`olumlu_cevap` 20, `ret` 20, `ret_kismen_kabul` 16, `eksik_belge_yetkisizlik` 22) | Karar dağılımı ince ve dengesiz |
| Tek kurumun payı (Gelir İdaresi Başkanlığı) | 147/569 (%25,8) | Ciddi kaynak yoğunlaşması |
| Açık `yetkisizlik` etiketi | yok (eksik belge ile birleşik) | Yönlendirme kararı ayırt edilemiyor |
| Negatif/çelişkili başvuru örneği | yok | Uydurma bilgi üretimi ölçülemiyor |

Mevcut kayıtlarda bir belgenin **hangi gelen evraka cevap olduğu**, **hangi
kararın verildiği** ve **kararın hangi dayanağa yaslandığı** alan olarak yok.
Bu bilgi belge gövdesinden çıkarılabilir ama etiketlenmemiştir; dolayısıyla
karar doğruluğu ölçülemez.

---

## 2. Kayıt şeması

Her vaka tek bir JSON nesnesidir; küme `vakalar.jsonl` olarak tutulur.

```yaml
case_id:                    # "GKC-0001" — kararlı, artan
incoming_document:          # gelen evrakın tam anonim metni (Markdown)
incoming_type:              # dilekce | bilgi_edinme_basvurusu | ust_yazi |
                            # sikayet | itiraz | kurum_talebi | soru_onergesi
requested_action:           # başvuranın somut talebi, tek cümle
decision:                   # tam_kabul | ret | kismi_kabul | eksik_belge |
                            # yetkisizlik | yalnizca_bilgilendirme |
                            # belirsiz_basvuru | coklu_talep
decision_reason:            # kararın gerekçesi, tek paragraf
outgoing_correspondence_type: # ust_yazi | cevap_yazisi |
                            # bilgilendirme_metni | diger_resmi_yazisma
required_facts:             # gelen evraktan taslağa TAŞINMASI gereken olgular
                            # [{alan, deger, kaynak_satir}]
missing_information:        # eksikse taslağın isteyeceği bilgiler [{alan, neden}]
expected_questions:         # kullanıcıya sorulması beklenen sorular [str]
gold_draft:                 # referans taslak (tam metin)
must_include:               # taslakta MUTLAKA geçmesi gereken ifadeler [str]
must_not_invent:            # taslakta ASLA geçmemesi gereken uydurma değerler [str]
legal_basis:                # [{mevzuat, madde, url_veya_kaynak}]
evidence:                   # dayanağın korpustaki karşılığı [{kaynak_yolu, satir}]
source_origin:              # gercek_belgeden_turetilmis | sentetik_kurgu
provenance:                 # {kaynak_kart_id, kaynak_sha256, turetme_yontemi}
anonymization:              # {yontem, yer_tutucular[], denetim_durumu}
review_status:              # taslak | uzman_onayli | reddedildi
source_group:               # split ataması için köken anahtarı (sha256[:16])
dataset_split:              # train | dev | heldout (source_group'tan türetilir)
```

`must_not_invent` alanı kritiktir: gelen evrakta **bulunmayan** ama modelin
uydurmaya eğilimli olduğu değerler (sahte evrak sayısı, uydurulmuş madde
numarası, olmayan tarih) buraya yazılır ve değerlendirme bunları arar.

---

## 3. Karar türü kotaları

Dengeli bir ilk sürüm için hedef 240 vaka:

| `decision` | Hedef | Neden bu ağırlık |
| --- | --- | --- |
| `tam_kabul` | 40 | En sık gerçek senaryo |
| `ret` | 40 | Gerekçelendirme kalitesi burada ölçülür |
| `kismi_kabul` | 35 | En zor karar; modelin en çok hata yaptığı yer |
| `eksik_belge` | 35 | Soru sorma davranışının ana testi |
| `yetkisizlik` | 30 | Doğru kuruma yönlendirme; şu an hiç ölçülmüyor |
| `yalnizca_bilgilendirme` | 25 | Karar üretmemesi gerektiğini bilmeli |
| `belirsiz_basvuru` | 20 | Negatif vaka: karar vermek yerine soru sormalı |
| `coklu_talep` | 15 | Tek yazıda farklı sonuçlanan talepler |

Yatay dengeler:

- **Kurum tavanı**: hiçbir kurum vakaların %15'ini aşmamalı (mevcut korpustaki
  %25,8'lik GİB yoğunlaşması tekrarlanmamalı).
- **Yazışma türü**: dört ana tür de ≥%20 pay almalı.
- **Köken**: gerçek belgeden türetilmiş ≥%60, saf sentetik ≤%40.
- **Uzunluk**: gelen evrak uzunluğu üç kovaya dengeli dağılmalı
  (<1500, 1500–4000, >4000 karakter).

---

## 4. Üretim yöntemi

```
gerçek kart (anonimleştirilmiş)
   ↓  1. olgu çıkarımı — belgedeki tarih/sayı/talep/karar elle etiketlenir
   ↓  2. gelen evrak yeniden kurgulanır (cevabın ima ettiği başvuru)
   ↓  3. karar + gerekçe + dayanak alanları doldurulur
   ↓  4. gold_draft mevcut resmî cevaptan türetilir
   ↓  5. must_include / must_not_invent listeleri çıkarılır
   ↓  6. ikinci bir anonimleştirme geçişi + denetim manifesti
   ↓  7. uzman incelemesi (review_status)
vaka kaydı
```

Kurallar:

1. **Ham kaynak değişmez.** Türetme yalnız anonimleştirilmiş Markdown karttan
   yapılır; `provenance.kaynak_sha256` izi korunur.
2. **LLM tek başına karar veremez.** LLM yalnız taslak alan doldurabilir;
   `review_status` `uzman_onayli` olmadan hiçbir kayıt değerlendirmeye girmez.
3. **Anonimleştirme yeniden çalıştırılır.** Türetilen `incoming_document` ve
   `gold_draft`, `scripts/prepare_resmi_yazisma_markdown.py` ile aynı semantik
   yer tutucu şemasından geçirilir ve kendi denetim manifestini üretir.
4. **Sentetik vakalar işaretlenir.** `source_origin: sentetik_kurgu` olan
   kayıtlar karışmasın diye ayrı sayılır ve raporlanır.

---

## 5. Klasör ve dosya düzeni

Mevcut üretim kümesiyle **hiçbir dosyayı paylaşmaz**:

```
datasets/resmi_yazisma_vakalar/          # yeni, ayrı kök
├── vakalar.jsonl                        # tüm vakalar
├── vakalar-train.jsonl
├── vakalar-dev.jsonl
├── vakalar-heldout.jsonl
├── vaka-manifesti.jsonl                 # provenance + anonimleştirme denetimi
├── vaka-istatistikleri.json             # karar/kurum/tür/uzunluk dağılımları
└── VAKA_KALITE_RAPORU.md
```

Betikler: `scripts/build_yazisma_vaka_seti.py` (üretim) ve
`scripts/evaluate_yazisma_vaka_seti.py` (değerlendirme). Mevcut
`curate_yazisma_examples.py` **değiştirilmez**; üretim RAG'ı bu kümeden
etkilenmez.

---

## 6. Split stratejisi

Mevcut korpusla aynı `source_group` mantığı kullanılır
(`curate_yazisma_examples.py:202`): split, kaynak grubunun SHA-256 kovasından
deterministik olarak türetilir; bu sayede aynı kaynak belge veya şablon ailesi
asla iki split'e birden düşmez.

Ek olarak bu küme için iki kısıt daha gerekir:

1. **Çapraz-küme sızıntısı**: bir vakanın türetildiği kart `ornekler.jsonl`
   içinde retrieval'de ise, o vaka `dev`/`heldout`'a **giremez**. Aksi hâlde
   model cevabı retrieval'den birebir kopyalayabilir.
2. **Yakın kopya kontrolü**: `gold_draft` metinleri yer tutucular ve rakamlar
   normalize edilerek hash'lenir; aynı hash iki split'e bölünmez.

Hedef oran: train %70, dev %15, heldout %15.

---

## 7. Değerlendirme metrikleri

### Retrieval

| Metrik | Neyi ölçer |
| --- | --- |
| Recall@5 / Recall@10 | Doğru dayanak belgesi getirildi mi |
| MRR | İlk doğru sonucun sırası |
| nDCG@10 | Sıralama kalitesi |
| Yanlış örnekten kopyalama oranı | Getirilen ama ilgisiz kartın taslağa sızması |

### Taslak üretimi

| Metrik | Tanım |
| --- | --- |
| Yazışma türü doğruluğu | `outgoing_correspondence_type` accuracy |
| Karar doğruluğu | `decision` accuracy + karar bazlı confusion matrix |
| Eksik bilgi P/R/F1 | `missing_information` alan kümesi karşılaştırması |
| Soru isabeti | `expected_questions` ile örtüşme (küme F1) |
| Olgu korunumu | `required_facts` içindeki değerlerin taslakta bulunma oranı |
| Uydurma bilgi oranı | `must_not_invent` ihlali / toplam vaka |
| Zorunlu alan doğruluğu | `must_include` karşılanma oranı |
| Resmî üslup puanı | Kural tabanlı biçim denetimi (sayı/konu/ilgi/imza blokları) |
| Uzman puanı | 1–5 arası insan değerlendirmesi, örneklem üzerinde |
| PII sızıntısı | Üretilen taslakta açık PII bulgusu sayısı (hedef 0) |

### Karşılaştırma kurulumu

Aynı benchmark üzerinde dört yapılandırma:

| # | Yapılandırma | Amaç |
| --- | --- | --- |
| 1 | RAG kapalı | Taban çizgisi; modelin kendi bilgisi |
| 2 | Mevcut RAG (`ornekler.jsonl`, 429) | Bugünkü üretim |
| 3 | Temizlenmiş + dengelenmiş RAG | Bu issue'nun kazancını izole eder |
| 4 | 3 + vaka çiftleri | Deneysel kümenin katkısını ölçer |

4 numaralı yapılandırma yalnız **ayrı** bir indekste çalışır; üretim indeksi
değişmez. Birleştirme kararı yalnız 3 ↔ 4 karşılaştırmasının sonucuna ve açık
onaya bağlıdır.

---

## 8. Riskler

| Risk | Etki | Azaltım |
| --- | --- | --- |
| Türetilmiş gelen evrak, cevabın kelimelerini taşır | Model retrieval'den kopyalayarak yüksek skor alır | Gelen evrak farklı üslupla yeniden yazılır; leksik örtüşme ölçülür ve eşiği aşan vaka reddedilir |
| Karar etiketleri öznel | Ölçüm gürültülü olur | İki bağımsız etiketleyici + anlaşmazlık raporu (Cohen κ) |
| Sentetik vakalar gerçekçi olmaz | Model gerçek dünyada başarısız | ≥%60 gerçek belgeden türetme kotası |
| Yeniden anonimleştirme yeni PII kaçırır | KVKK riski | Aynı denetim manifesti hattı zorunlu; fail-closed |
| Küme üretim RAG'ına sızar | Değerlendirme geçersizleşir | Ayrı kök, ayrı manifest, ayrı indeks; birleştirme yalnız açık onayla |

---

## 9. Sonraki adım

Bu plan onaylanırsa sıradaki iş kalemi 20 vakalık bir **pilot** üretmek,
etiketleyici anlaşmasını ölçmek ve şemayı pilot bulgularına göre
sabitlemektir. Pilot da ayrı klasörde durur.
