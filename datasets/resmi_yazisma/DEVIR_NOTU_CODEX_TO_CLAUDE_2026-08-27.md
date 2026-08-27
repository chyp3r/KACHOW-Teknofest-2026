# Claude devir notu — issue #284 / 240 vakalık resmî yazışma veri seti

Bu dosya Codex'ten Claude Code'a güncel ve uygulanabilir devir notudur.
Çalışmaya başlamadan önce bu dosyanın tamamını, ardından aşağıdaki ana kaynakları
oku. Eski `DEVIR_NOTU.md` tarihsel bağlam içerir ancak son durum için bu dosya
esas alınmalıdır.

## 1. Güncel durum

- Repository: `chyp3r/KACHOW-Teknofest-2026`
- Yerel yol: `C:\Users\yigit\OneDrive\Desktop\projects\KACHOW-Teknofest-2026`
- Issue: `#284`
- Branch: `fix/284-resmi-yazisma-anonimlestirme-denetimi`
- Son yerel commit: `c5e03ca feat(dataset): add deterministic parallel case generation`
- Bir önceki önemli commit: `c9ec5a2 feat(dataset): harden official correspondence case generation`
- Push/PR/merge yapılmadı.
- Üretim `ornekler.jsonl` veya üretim RAG kümesine merge edilmedi.
- Güvenilir checkpoint: **21 benzersiz vaka, 0 hata, 0 uyarı**.

Ana kaynaklar:

1. `AGENTS.md`
2. `datasets/resmi_yazisma/VAKA_URETIMI_240_PROMPT.md`
3. `datasets/resmi_yazisma/VAKA_URETIM_PLAYBOOK.md`
4. `datasets/resmi_yazisma/GELEN_EVRAK_KARAR_CEVAP_VERI_PLANI.md`
5. Bu dosya

## 2. Kullanıcının değişmez talimatları

1. Kullanıcı açıkça istemeden push, PR veya merge yapma.
2. Üretilen vakaları üretim RAG kümesine otomatik karıştırma.
3. Her değişiklik issue #284 ve mevcut branch üzerinde kalmalı.
4. Ham kaynak dosyalarını değiştirme.
5. Düşük kaliteli kayıtları silme; `rejected/` ve `audit/` altında gerekçeli
   biçimde koru.
6. Manuel kalite kontrolünden geçmeyen bir kaydı otomatik kapı geçmiş olsa bile
   kabul etme.
7. `datasets/sample_benchmark/` altındaki mevcut silmeler kullanıcıya aittir.
   Bunları stage etme, restore etme, taşıma veya başka bir commit'e katma.
8. `.env`, API anahtarı, Qdrant anahtarı veya parola içeriğini hiçbir çıktıda,
   raporda ya da commit'te gösterme.

## 3. Güvenlik notu

Kullanıcı konuşmada Evren LLM, Qdrant ve arayüz kimlik bilgilerini açık şekilde
paylaştı. Bunlar bu dosyaya alınmadı ve commit edilmedi. Anahtarlar açığa çıkmış
kabul edilmeli; kullanıcıya rotasyon önerildi.

- Anahtarları kaynak koda veya dokümana yazma.
- `.env` içeriğini ekrana basma.
- `docker compose config` tüm ortam değişkenlerini açık yazabildiği için ham
  çıktısını kullanıcıya veya log dosyasına aktarma.
- Mevcut `.env` üzerinden çalış; anahtar değerlerini asla tekrarlama.

## 4. Şu ana kadar tamamlanan teknik işler

### 4.1 Kalite kapısının sertleştirilmesi

`scripts/generate_yazisma_vaka_pilotu.py` ve
`scripts/evaluate_yazisma_vaka_seti.py` aşağıdaki hatalara karşı fail-closed
çalışacak şekilde sertleştirildi:

- kişi ve özel kuruluş adlarının metadata dahil anonimleştirilmesi;
- tarih kronolojisi ve geçersiz yıl kontrolü;
- desteklenmeyen tutar, yüzde ve gün/süre kontrolü;
- desteklenmeyen olgu ve kurum içi inceleme bulgusu kontrolü;
- kaldırılmış büyükşehir il özel idaresi ve uydurma kurum kontrolü;
- kurumun somut işte görev/yetki uygunluğu;
- `required_facts`, `kaynak_satir`, `must_include`, `missing_information` ve
  `expected_questions` izlenebilirliği;
- numara, resmî başlık, madde ve uygulanabilirlik bazında mevzuat doğrulaması;
- tekrar, checkpoint, retry, manuel karantina ve ret arşivi.

Mevzuat çeşitliliği çekirdek üretimden ayrıldı. Çekirdek vaka üretiminde yeni
mevzuat atfı eklenmemeli; doğrulanmış mevzuat daha sonraki ayrı aşamada
eklenmelidir.

### 4.2 Paralel çalışma

Üretim betiğine `--concurrency` eklendi. Paralel modda:

- `asyncio.Semaphore` eşzamanlı çağrı sayısını sınırlar;
- her worker bağımsız üretir ve doğrular;
- JSONL yazımları worker içinde değil ana süreçte seri yapılır;
- böylece satırların birbirine girmesi engellenir;
- sonuç `datasets/resmi_yazisma_vakalar/son-paralel-benchmark.json` dosyasına
  yazılır;
- paralel modda `--max-cases` zorunludur.

Evren altyapısı 6 eşzamanlı isteği hata veya rate-limit olmadan taşıdı. Ancak
H200 kapasitesi kalite sorununu çözmüyor; asıl darboğaz serbest LLM üretimiydi.

### 4.3 Deterministik üretim prototipi

Betikte `--deterministic-prototype` modu ve `DETERMINISTIC_PROTOTYPES` eklendi.
İki farklı hibrit yaklaşım denendi:

1. Karar/olgu/kurum iskeleti kodda, iki belge Evren tarafından yazıldı.
2. İki belge ve metadata tamamen deterministik, Evren yalnız kalite hakemi.

Birinci yaklaşım güvenli değildir. Model sabit prompta rağmen:

- yeni tarih ve evrak numarası;
- desteklenmeyen teknik inceleme/ihale/işlem bulgusu;
- yanlış kurum yetkisi;
- maskelenmemiş kişi adı

üretebildi. Otomatik kapının kaçırdığı örnekler manuel kontrolde karantinaya
alındı.

İkinci yaklaşım başarılı oldu: belge gövdeleri ve metadata kod tarafından
belirlendi, Evren yalnız düşük sıcaklıklı kalite değerlendirmesi yaptı.

## 5. Deney sonuçları

| Yöntem | Hedef | Paralellik | Süre | Otomatik kabul | Manuel kabul |
| --- | ---: | ---: | ---: | ---: | ---: |
| Serbest LLM tüm vakayı üretir | 6 | 6 | 44,3 sn | 1/6 | 0/6 |
| Deterministik prompt iskeleti, belgeleri LLM yazar | 6 | 6 | 19,4 sn | 4/6 | 0/6 |
| Tam deterministik belgeler, Evren kalite hakemi | 3 | 3 | 1,898 sn | 3/3 | 3/3 |

Son başarılı benchmark:

- `requested`: 3
- `accepted`: 3
- `failed`: 0
- `elapsed_seconds`: 1.898
- `throughput_cases_per_minute`: 94.837

Bu throughput yalnız mevcut kanonik metinlerin kalite değerlendirme hızıdır;
240 ayrı, kaliteli senaryonun hazırlanma süresini temsil etmez.

## 6. Güvenilir vaka seti

Dosya: `datasets/resmi_yazisma_vakalar/vakalar.jsonl`

Toplam: **21**

| Karar | Adet |
| --- | ---: |
| `tam_kabul` | 3 |
| `ret` | 3 |
| `kismi_kabul` | 2 |
| `eksik_belge` | 3 |
| `yetkisizlik` | 2 |
| `yalnizca_bilgilendirme` | 3 |
| `belirsiz_basvuru` | 3 |
| `coklu_talep` | 2 |

Son eklenen ve hem manuel hem otomatik kontrolden geçen üç kayıt:

- `GKC-BELIRSIZ_BASVURU-003`
- `GKC-EKSIK_BELGE-003`
- `GKC-YALNIZCA_BILGILENDIRME-003`

Bunların üçü de kota sözleşmesi gereği gerçek birer `incoming_type: itiraz`
vakasıdır. İlk sürümler normal dilekçe/şikâyet olduğu için evaluator
`itiraz_kotasi_uyusmazligi` verdi; sürümler karantinaya alınıp itiraz biçiminde
yeniden yazıldı.

Son evaluator sonucu:

```text
case_count: 21
unique_case_count: 21
error_count: 0
warning_count: 0
gate_status: passed
```

## 7. Çok önemli: tamamlanmamış prototipler

`DETERMINISTIC_PROTOTYPES` içinde altı kimlik bulunuyor; fakat yalnız aşağıdaki
üçünde tam kanonik `incoming_document` ve `gold_draft` hazır ve güvenilir:

- `GKC-BELIRSIZ_BASVURU-003`
- `GKC-EKSIK_BELGE-003`
- `GKC-YALNIZCA_BILGILENDIRME-003`

Aşağıdaki üçü hâlâ yalnız prompt iskeletidir ve önceki deneyde manuel kontrolden
geçmemiştir:

- `GKC-COKLU_TALEP-003`
- `GKC-KISMI_KABUL-003`
- `GKC-YETKISIZLIK-003`

Bu üç vakayı mevcut halleriyle üretip kabul etme. Önce tam kanonik
`incoming_document` ve `gold_draft` alanlarını kodla, kota gereği gerçekten
itiraz olduklarını doğrula, sonra tekrar çalıştır.

## 8. Sıradaki doğru iş

### Adım 1 — çekirdek üçlüyü 24 vakaya tamamla

Önce yukarıdaki tamamlanmamış üç `-003` vakayı tam deterministik hale getir.
Hedef, checkpoint'i 21'den 24 güvenilir vakaya çıkarmaktır.

Her vaka için:

1. Kurum gerçek ve somut işlemde yetkili olmalı.
2. `incoming_type` kota gereği `itiraz` olmalı.
3. Gelen evrak, önceki karar/bildirim ile itiraz ilişkisini açıkça kurmalı.
4. Cevap yalnız gelen evrak ve sabit `decision_reason` içindeki olguları
   kullanmalı.
5. Yeni mevzuat, tarih, tutar, oran, süre, evrak numarası veya iç inceleme
   bulgusu eklenmemeli.
6. Kişi/özel kuruluş adı yerine baştan semantik yer tutucular kullanılmalı.
7. Kısmi kabulde en az bir istem açıkça kabul, başka bir istem açıkça ret
   edilmeli.
8. Çoklu talepte bağımsız istemler ve her istemin ayrı sonucu bulunmalı.
9. Yetkisizlikte gerçek ve açık yetkili merci belirtilmeli.

### Adım 2 — 24 vakalık çeşitlilik partisi

24 vaka kalite kapısından geçince, her karar türünden üç yeni vaka olacak
şekilde 24 vakalık kontrollü parti hazırla. `index <= _itiraz_count_for(adet)`
kuralını kullan; `-004` ve sonrası otomatik olarak normal başvuru varsayılmamalı.

240 tam belgeyi Python içindeki dev bir sözlüğe gömmek sürdürülebilir değildir.
Ölçeklemeden önce kanonik senaryo tanımlarını ayrı, şemalı ve izlenebilir bir
JSONL veri kaynağına taşıman önerilir. Üretim betiği bu JSONL'yi okuyup aynı
kalite kapısından geçirmelidir. Yeni format için unit test ve deterministik
yeniden çalıştırma testi ekle.

Önerilen üretim düzeni:

```text
kanonik senaryo/olgular
        ↓
deterministik gelen evrak + karar + cevap
        ↓
PII/placeholder ve sayısal olgu kapısı
        ↓
Evren kalite hakemi (concurrency=6)
        ↓
deterministik evaluator
        ↓
manuel inceleme
        ↓
checkpoint / rejected / audit
```

Evren'e yeniden serbestçe tam belge yazdırma. İleride üslup çeşitliliği için
yalnız gerçek içermeyen cümlelerde kontrollü paraphrase denenebilir; ancak yeni
özel isim, sayı, tarih, kurum, işlem veya mevzuat eklenmediğini birebir diff
kapısıyla kanıtlamadan kabul etme.

## 9. Çalıştırma komutları

PowerShell'de repository kökünden çalıştır:

### Tamamlanmamış üç `-003` vaka kanonik hale getirildikten sonra

```powershell
docker compose run --rm --no-deps backend python -u /workspace/scripts/generate_yazisma_vaka_pilotu.py --apply --resume --max-cases 3 --max-retries 1 --concurrency 3 --deterministic-prototype --case-id GKC-COKLU_TALEP-003 --case-id GKC-KISMI_KABUL-003 --case-id GKC-YETKISIZLIK-003
```

### Deterministik kalite raporu

```powershell
docker compose run --rm --no-deps backend python /workspace/scripts/evaluate_yazisma_vaka_seti.py --write
```

### Vaka üretim unit testleri

```powershell
docker compose run --rm --no-deps backend pytest -q /workspace/tests/unit/test_generate_yazisma_vaka_pilotu.py
```

Son doğrulama: **66 passed**.

### Geniş zorunlu veri süiti

```powershell
docker compose run --rm --no-deps backend pytest -q -p no:cacheprovider --no-cov /workspace/tests/unit/test_generate_yazisma_vaka_pilotu.py /workspace/tests/unit/test_mevzuat_dogrulama.py /workspace/tests/unit/test_prepare_resmi_yazisma_markdown.py /workspace/tests/unit/test_curate_yazisma_examples.py /workspace/tests/unit/mcp
```

Bu geniş süit `c9ec5a2` checkpoint'inde **212 passed** verdi. Son prototip
değişikliklerinden sonra yalnız 66 testlik hedefli dosya yeniden çalıştırıldı;
bir sonraki veri commit'inden önce geniş süiti yeniden çalıştır.

## 10. Dosya ve provenance sözleşmesi

- Başarılı vaka: `datasets/resmi_yazisma_vakalar/vakalar.jsonl`
- Üretim hataları: `datasets/resmi_yazisma_vakalar/vaka-hatalari.jsonl`
- Manuel/otomatik retler:
  `datasets/resmi_yazisma_vakalar/rejected/vaka-reddedilenler.jsonl`
- Değişiklik öncesi snapshotlar: `datasets/resmi_yazisma_vakalar/audit/`
- Kalite raporu: `datasets/resmi_yazisma_vakalar/VAKA_KALITE_RAPORU.md`
- Makine okunur istatistik:
  `datasets/resmi_yazisma_vakalar/vaka-istatistikleri.json`
- Son paralel ölçüm:
  `datasets/resmi_yazisma_vakalar/son-paralel-benchmark.json`

Kanonik kayıtların `provenance.uretim_yontemi` değeri:

```text
deterministic_canonical+evren_quality_review
```

Prompt iskeletinden Evren'in belge yazdığı deneysel kayıtların değeri:

```text
deterministic_blueprint+evren_llm_large_realization
```

İkinci yöntemden gelen hiçbir kayıt yalnız otomatik kapıya güvenilerek kabul
edilmemeli.

## 11. Git ve çalışma ağacı

Son commitler:

```text
c5e03ca feat(dataset): add deterministic parallel case generation
c9ec5a2 feat(dataset): harden official correspondence case generation
36c42d5 fix(dataset): Aşama 4 üretim kapılarını sertleştir
312f5fc docs(dataset): #284 üretim işi için devir notu ekle
9d95a65 feat(dataset): mevzuat atıflarını tür-farkındalıklı doğrula (Aşama 3.2)
d37b1ad feat(dataset): 240 vakalık üretim için kota, checkpoint/resume ve kurum çeşitliliği
```

Bu dosya oluşturulmadan hemen önce tracked çalışma ağacında yalnız
`datasets/sample_benchmark/` altındaki kullanıcıya ait silmeler unstaged idi.
Her işlemden önce `git status --short` kontrol et. Yalnız kendi değiştirdiğin
dosyaları açık adlarıyla stage et; `git add .` kullanma.

## 12. Tamamlanma ve durma koşulları

Bir parti ancak aşağıdakilerin tamamında başarılı sayılır:

- otomatik üretim kapısı geçti;
- deterministik evaluator `error_count=0`, `warning_count=0` verdi;
- her yeni vaka manuel okundu;
- ham PII veya anlamsız yer tutucu yok;
- karar türü ve itiraz kotası doğru;
- kurum ve yetki gerçekçi;
- desteklenmeyen tarih/sayı/tutar/süre/mevzuat/işlem yok;
- tekrar veya near-duplicate yok;
- testler geçti;
- CHANGELOG güncellendi;
- yalnız ilgili dosyalar yerel commit'e alındı.

Bir kayıt bu koşullardan birini karşılamıyorsa ana JSONL'de bırakma; gerekçeli
olarak karantinaya taşı. Kullanıcı onayı olmadan push/PR/merge/RAG entegrasyonu
yapma.
