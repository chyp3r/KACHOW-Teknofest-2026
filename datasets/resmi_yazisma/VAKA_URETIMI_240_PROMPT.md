# AI Coding Task — 240 Vakalık Gelen Evrak–Karar–Cevap Seti, OS-* Kalite Kapısı ve Kapsamlı Dataset Analizi

> **Durum: yalnız görev tanımı.** Kullanıcı "başla" demeden hiçbir kod
> çalıştırılmaz, hiçbir dosya üretilmez/değiştirilmez.

## 1. Amaç

`KACHOW-Teknofest-2026` projesinde aşağıdaki işleri profesyonel, ölçülebilir,
deterministik ve tekrar çalıştırılabilir biçimde tamamla:

1. OS-* veri kartlarındaki kalite kapısı hatasını düzelt.
2. Gelen evrak–karar–cevap şemasını düzelt.
3. Sekiz karar türüne dağılmış toplam 240 kaliteli vaka üret.
4. Anonimleştirme ve mevzuat doğrulamasını üretim hattına kalıcı olarak ekle.
5. Train/dev/heldout ayrımlarında kaynak ve içerik sızıntısını engelle.
6. Tüm dataset ile yalnızca üretim RAG'ına giren alt kümeyi ayrı ayrı analiz et.
7. Kullanıcıya push/PR öncesinde kapsamlı bir sonuç raporu sun.

Bu prompt çalıştırıldığında göreve başlayabilirsin.

**Commit stratejisi (kullanıcı onayıyla değişti — aşağıdaki 2.1a'ya bakınız):**
her tamamlanmış ve test edilmiş aşama sonunda **yerel** bir commit at (bkz.
Bölüm 2.1 "Commit noktaları"). Codex bu depoyu **aynı makinede** açacağı
için yerel commit'ler tek başına yeterli bir devir noktasıdır.

**Push, PR, merge veya yeni vakaları üretim RAG'ına ekleme işlemi yapma.**
Bunlar son rapordan sonra ayrıca kullanıcı onayı gerektirir.

---

## 2. Zorunlu çalışma kuralları

### 2.1 Git ve mevcut çalışma durumu

Repo:
`C:\Users\yigit\OneDrive\Desktop\projects\KACHOW-Teknofest-2026`

Beklenen çalışma dalı:
`fix/284-resmi-yazisma-anonimlestirme-denetimi`

Başlamadan önce:

- `AGENTS.md`, `CONTRIBUTING.md`, README ve ilgili veri dokümantasyonunu oku.
- Aktif branch'i doğrula.
- `git status` ve mevcut diff'i incele.
- Repoda daha önce yapılmış fakat commit edilmemiş değişiklikleri koru.
- Kullanıcı değişikliklerini silme, geri alma veya ezme.
- `git reset --hard`, `git checkout --`, toplu dosya silme gibi yıkıcı
  işlemler kullanma.
- Yanlış branch'teysen veya mevcut değişikliklerle güvenli biçimde devam
  edilemiyorsa işlem yapmadan kullanıcıya bildir.
- Yeni issue veya branch açma.
- Push veya PR yapma.

### 2.1a Commit noktaları (yerel, push değil)

Kullanıcı bu görev için standart "yalnız son raporda commit" kuralını
**değiştirdi**: iş bu kadar uzun sürdüğünden (14 aşama, saatler), her
tamamlanmış ve **test edilmiş** aşama sonunda yerel bir commit atılmalı.
Codex bu depoyu aynı makinede açacağı için yerel commit'ler yeterli bir
devir noktasıdır; push/PR yine yalnız kullanıcının son onayından sonra.

Önerilen commit noktaları (aynı `fix/284-*` dalında, Conventional Commits
formatında, `AGENTS.md`'deki kurala uygun):

1. Aşama 0 tamamlanıp testler + idempotence kanıtlandıktan sonra
2. Aşama 1 (şema düzeltmesi) tamamlanınca
3. Aşama 3 (üretim betiği genişletmesi) tamamlanınca, henüz vaka
   üretilmeden
4. Aşama 4 (doğrulama batch'i) kapıdan geçince
5. Kalan 240'lık üretim tamamlanınca (gerekirse büyük üretimi de kendi
   içinde ~50-60 vakalık alt-commit'lere böl — tek seferde saatler süren
   bir işi tek commit'te tutma, ara kesintide iş kaybı riski azalsın)
6. Aşama 5-9 (split, kalite kontrolü, envanter analizleri) tamamlanınca
7. Aşama 13 sonunda özet/rapor commit'i

Her commit'ten **önce** ilgili testleri çalıştır ve geçtiğini doğrula —
bozuk/yarım bir ara durumu commit'leme. Commit mesajı o aşamada ne
yapıldığını ve hangi testlerin geçtiğini özetlemeli.

> **Not (bu oturumdan gerçek bir olay):** Daha önce bu görev sırasında,
> hedefli bir `git checkout -- <birkaç yol>` komutuna dataset glob'u ile
> birlikte kod dosyası da eklenmiş ve bu, o dosyadaki tüm uncommitted
> düzeltmeleri (bir önceki ajanın çalışması + bu oturumun 6 hatası)
> HEAD'e sıfırlayıp silmişti. Kurtarma erken yedekten yapıldı ama bu
> tekrarlanmamalı: **"şu veriyi geri al" ile "şu kod dosyasını sıfırla"
> niyetlerini asla aynı `git checkout`/`git restore` komutunda birleştirme.**
> Her hedefli geri alma öncesi hangi dosyaların etkileneceğini `git status`/
> `git diff --stat` ile önce göster, sonra çalıştır.

### 2.2 Ham kaynakların korunması

Ham kaynak niteliğindeki aşağıdaki dosyaları değiştirme:

- PDF
- HTML
- DOC
- DOCX
- Kaynak/orijinal JSON dosyaları

Yalnızca aşağıdaki alanlarda değişiklik yapabilirsin:

- Türetilmiş Markdown veri kartları
- Veri hazırlama ve analiz betikleri
- Testler
- Manifestler
- Türetilmiş JSON/JSONL çıktıları
- Dataset indeksleri
- Kalite raporları
- README/CHANGELOG ve ilgili veri dokümantasyonu
- Yeni vaka datasetinin ayrı klasörü

Çalışma sonunda ham kaynakların değişmediğini Git üzerinden kanıtla.

### 2.3 Aşamalı yürütme

Aşamaları sırayla yürüt:

1. Her aşamadan önce mevcut durumu ölç.
2. Değişikliği uygula.
3. İlgili testleri çalıştır.
4. Kabul kriterlerini doğrula.
5. Kabul kriteri sağlanmadan sonraki aşamaya geçme.
6. Ara sonuçları checkpoint'le.
7. Belirsiz bir veriyi tahmin ederek sınıflandırma; `bilinmiyor` veya
   `review_required` olarak işaretle.
8. Bir aşama başarısız olursa hatayı çözmeden sonraki aşamaya geçme.

Uzun süren işlemleri küçük ve devam ettirilebilir partiler halinde yürüt.
Tek bir uzun araç çağrısına güvenme (arka planda/`run_in_background`
çalıştır, 5 dakikalık araç zaman aşımına takılma).

---

## 3. Mevcut bağlam

Projede `datasets/resmi_yazisma/` altında resmî yazışma RAG veri kümesi
bulunmaktadır.

Daha önce yapılan çalışmalar:

### 3.1 Pilot vaka üretimi

İlgili dosyalar:

- `scripts/generate_yazisma_vaka_pilotu.py`
- `datasets/resmi_yazisma_vakalar_pilot/vakalar-taslak.jsonl`
- `datasets/resmi_yazisma/VAKA_URETIM_PLAYBOOK.md`
- `datasets/resmi_yazisma/GELEN_EVRAK_KARAR_CEVAP_VERI_PLANI.md`

Mevcut pilot:

- 20 vaka
- Yetkisizlik, Belirsiz başvuru, Çoklu talep, İtiraz
- Evren `llm-large` kullanılarak üretildi
- Gerçek ve anonimleştirilmiş korpus kartları few-shot referans olarak
  kullanıldı
- 20/20 anonimleştirme denetiminden geçti
- 24/24 mevzuat referansı doğrulandı

### 3.2 OS-* karşılaştırması

Eski `scripts/scrape_open_sources.py` betiğiyle üretilen 800 OS-* kartında
kurum, konu ve metin havuzları bağımsız ve rastgele birleştirilmiştir. Bu
nedenle bazı kayıtlar biçimsel olarak düzgün görünse de başlık, kurum ve
gövde açısından anlamsal olarak tutarsızdır.

Dosyalar silinmeyecek. Kalite kapısı düzeltilerek uygun olmayan kayıtların
`rag_status: rejected` olması sağlanacaktır.

---

# Aşama 0 — OS-* kalite kapısı düzeltmesi

İlgili dosya: `scripts/prepare_resmi_yazisma_markdown.py`
İlgili fonksiyonlar: `os_body_kind`, `os_is_coherent`

## Kök neden

`os_body_kind(body)` yalnızca belirli sabit ifadeleri tanımaktadır. Örneğin
metinde `Söz konusu meclis kararı, ...` gibi bir varyant bulunduğunda
fonksiyon bunu tanımayıp `genel` sonucuna düşebilmektedir. `os_is_coherent`,
`kind == "genel"` durumunu koşulsuz geçirdiği için tanınmayan içerikler
otomatik olarak tutarlı kabul edilmektedir.

## Yapılacaklar

1. `scripts/scrape_open_sources.py` içindeki `CONTENTS` listesinin tamamını
   incele.
2. Her içerik ailesi için anlamlı bir `body_kind` tanımla.
3. Her `body_kind` için `_OS_RULES` içinde uygun başlık ve konu kelimelerini
   tanımla.
4. `CONTENTS` içindeki hiçbir kalıp kontrolsüz biçimde `genel` sonucuna
   düşmemeli.
5. `os_is_coherent` davranışını fail-closed hale getir: tanınmayan kalıp
   otomatik olarak geçmemeli, anlamsal eşleşme kanıtlanamıyorsa `False`
   dönmeli.
6. Şu somut uyumsuz örnekleri regresyon testine ekle: `OS-02-011`,
   `OS-01-010`, `OS-04-032`.
7. OS-* dosyalarını silme.
8. Uyumsuz kayıtları yalnızca `rejected` yap.
9. Bu kayıtların `ornekler.jsonl` ve üretim RAG'ına girmediğini doğrula.

## Ölçüm

Düzeltmeden önce ve sonra şu sayıları kaydet: toplam OS-* kartı,
`candidate`, `reference_only`, `rejected`, `candidate`'ten `rejected`'e
geçen kayıt, üretim RAG'ından çıkarılan OS-* kaydı, kural tarafından hâlâ
`genel/bilinmiyor` kabul edilen kayıt.

## Yeniden üretim zinciri

Komutların gerçek parametrelerini önce betiklerden veya `--help`
çıktısından doğrula. Ardından uygun sırayla çalıştır:

1. `prepare_resmi_yazisma_markdown.py --apply --normalize-only`
2. `update_dataset_indexes.py`
3. `curate_yazisma_examples.py --report`
4. `review_resmi_yazisma_qa.py`

## İdempotence

Dosya bazlı SHA-256 ile idempotence kanıtla:

1. Türetilmiş MD/JSON/JSONL dosyalarının hash'lerini al.
2. Zinciri çalıştır.
3. Hash'leri tekrar al.
4. Zinciri ikinci kez çalıştır.
5. İkinci ve üçüncü durum arasında değişen dosya sayısı sıfır olmalı.

Zaman damgası gibi değişken metadata idempotence'i bozuyorsa deterministik
hale getir. Gerçek veri kartları her çalıştırmada yeniden değişmemeli.

README'de OS-* kalite kararını ve sayısal etkisini güncelle.

---

# Aşama 1 — Gelen evrak–karar–cevap şeması

Pilotta `itiraz`, ayrı bir `decision` değeri gibi kullanılmıştır. Bu doğru
değildir. `itiraz` bir gelen evrak türüdür:

```text
incoming_type: itiraz
```

Karar sonucu ise standart karar enum'larından biri olmalıdır.

## İzin verilen decision değerleri

```text
tam_kabul
ret
kismi_kabul
eksik_belge
yetkisizlik
yalnizca_bilgilendirme
belirsiz_basvuru
coklu_talep
```

Bunların dışında `decision` değeri üretme.

Pilottaki beş itiraz vakasını yeniden değerlendir:

- İtiraz reddedilmişse `decision: ret`
- Kabul edilmişse `decision: tam_kabul`
- Bir kısmı kabul edilmişse `decision: kismi_kabul`
- Belge eksikse `decision: eksik_belge`
- Kurum yetkisizse `decision: yetkisizlik`

`TARGET_DECISIONS` sabitini bu şemaya göre düzelt. Şema değişikliklerini
geriye dönük uyumluluğu gözeterek yap ve test ekle.

---

# Aşama 2 — 240 vaka kotası

Aşağıdaki karar dağılımını kullan:

| Decision | Hedef |
| --- | ---: |
| `tam_kabul` | 35 |
| `ret` | 35 |
| `kismi_kabul` | 30 |
| `eksik_belge` | 30 |
| `yetkisizlik` | 30 |
| `yalnizca_bilgilendirme` | 25 |
| `belirsiz_basvuru` | 30 |
| `coklu_talep` | 25 |
| **Toplam** | **240** |

## İtiraz dağılımı

`itiraz` bağımsız karar havuzu değildir.

- Toplam vakaların yaklaşık %15–20'si `incoming_type: itiraz` olmalı.
- Mümkün olan her karar türünde en az üç itiraz örneği bulunmalı.
- İtirazla doğal olarak bağdaşmayan bir senaryoya yalnızca kotayı doldurmak
  için yapay biçimde itiraz ekleme.
- Nihai itiraz sayısını ve karar türlerine dağılımını raporla.

## Kurum çeşitliliği

- En az 25 farklı kurum veya kurum ailesi temsil edilmeli.
- Tek bir kurum en fazla 19/240 vakada kullanılabilir.
- İlk 25 vaka tamamlanmadan dinamik yüzde engeli uygulama.
- Sonraki üretimlerde kalan kurum kotasını dikkate al.
- Limite ulaşan kurumları prompt içindeki "kullanma" listesine ekle.
- Kurum adını mevcut güvenilir `_INSTITUTION_LINE` yaklaşımıyla veya yapısal
  metadata alanından çıkar.
- Kurum çeşitliliğini yalnız gövde regex'ine bırakmak yerine mümkünse
  şemada açık `institution` alanıyla takip et.

---

# Aşama 3 — Üretim betiğinin geliştirilmesi

Mevcut: `scripts/generate_yazisma_vaka_pilotu.py`

Betiği tamamen yeniden yazma. Mevcut güvenlik katmanlarının üzerine inşa et.

## 3.1 TARGET_DECISIONS

`TARGET_DECISIONS` değerini sekiz karar türü ve belirlenen kotalara göre
düzenle. Her karar türü için gerçek örneklerin yoğun olduğu uygun
`few_shot_glob` kullan. Örneğin:

- `tam_kabul`: `02_cevap_yazisi/06_olumlu_cevap/*.md`
- `ret`: ilgili ret örnekleri
- `kismi_kabul`: ilgili kısmi kabul örnekleri
- `eksik_belge`: eksik belge örnekleri
- `yetkisizlik`: yetkisizlik/iade örnekleri

Few-shot seçiminde:

- `rejected` kayıtları kullanma.
- Karantina kayıtlarını kullanma.
- Aynı kaynağın tekrarlarını mümkün olduğunca azalt.
- Kullanılan few-shot kayıtlarının ID ve `source_group` bilgilerini
  provenance içine yaz.
- Ham kişisel değerleri provenance içine taşıma.

## 3.2 Mevzuat şeması

Mevzuat bilgisini mümkünse yapısal tut:

```text
legal_basis:
  - type
  - number
  - title
  - article
  - verification_source
  - verification_status
```

Desteklenmesi gereken türler: Kanun, Yönetmelik, Tebliğ, Genelge,
Cumhurbaşkanlığı kararnamesi, diğer doğrulanabilir resmî mevzuat.

Her referansı koşulsuz `"KANUN"` türünde arama. Mevzuat türüne göre uygun
doğrulama yap. Mevcut MCP fonksiyonlarını ve proje altyapısını kullan:

- `app.mcp.registry.register_servers()`
- `app.mcp.mevzuat_client.resolve_and_fetch`

LLM tarafından verilen tür/numara/başlık/madde bilgilerini resmî sonuçla
normalize ederek karşılaştır. Doğrulanamayan mevzuatı kabul etme.

Bir vaka için mevzuat referansı zorunlu değilse LLM'in sırf alanı doldurmak
için mevzuat uydurmasına izin verme. Mevzuat alanı mevcutsa doğrulanması
zorunludur.

## 3.3 Retry ve hata yönetimi

Üretim sırası:

1. Şema doğrulaması
2. Öz-bildirilen kişi adlarının temizlenmesi
3. Semantik anonimleştirme
4. PII audit
5. Mevzuat doğrulaması
6. Duplicate/yakın kopya kontrolü
7. Başarılı kaydın checkpoint'e yazılması

Bir vaka doğrulamadan geçmezse aynı karar türü için en fazla üç retry yap.

Şunları ayrı ve güvenli manifestte kaydet: vaka ID, karar türü, deneme
sayısı, başarısızlık kategorisi, zaman bilgisi, ham hassas değer içermeyen
hata özeti.

API anahtarı, tam model yanıtı veya ham kişisel veri loglara yazılmamalı.

## 3.4 Checkpoint ve devam ettirme

Betiğe şu davranışları ekle: `--dry-run`, `--apply`, `--resume`,
`--max-cases`, uygunsa deterministik `--seed`, küçük batch desteği.

Kurallar:

- Her başarılı vaka anında checkpoint'e yazılmalı.
- Aynı vaka ID'si yeniden üretilmemeli.
- Yeniden başlatıldığında tamamlanmış vakalar tekrar çağrılmamalı.
- Yalnız eksik karar kotaları tamamlanmalı.
- Yarım veya bozuk JSONL satırı bırakılmamalı.
- Yazma işlemi mümkünse atomik yapılmalı.
- Başarısız vakalar başarılı vaka sayısına dahil edilmemeli.
- Maksimum toplam çağrı/retry bütçesi tanımlanmalı.

## 3.5 Güvenlik katmanları

Mevcut güvenlik mekanizmalarını koru: `used_person_names`,
`_scrub_reported_names`, `semantic_anonymize`, `_audit_privacy_findings`,
semantik yer tutucular, ham kişisel veri taşımayan audit manifesti.

LLM'e gerçek kişisel veri kullanmaması, kurgusal değer üretmesi, kişi
adlarını `used_person_names` içinde bildirmesi söylenebilir. Ancak
`used_person_names` öz-bildirimi tek güvenlik mekanizması sayılmamalı.
Serbest metin ayrıca otomatik taranmalıdır.

## 3.6 Çıktı klasörü

Pilot klasörünü değiştirme. Kalıcı çıktıları ayrı yerde üret:
`datasets/resmi_yazisma_vakalar/`

Beklenen dosyalar: `vakalar.jsonl`, `vakalar-train.jsonl`,
`vakalar-dev.jsonl`, `vakalar-heldout.jsonl`, `vaka-manifesti.jsonl`,
`vaka-hatalari.jsonl`, `vaka-istatistikleri.json`,
`VAKA_KALITE_RAPORU.md`.

Yeni vakaları otomatik olarak `ornekler.jsonl`, mevcut üretim RAG'ı, var
olan retrieval collection veya veritabanı içine ekleme. Birleştirme için
ayrıca kullanıcı onayı bekle.

---

# Aşama 4 — Küçük ölçekli üretim kapısı

Doğrudan 240 vaka üretme. Önce karar türleri dengeli olacak biçimde
8–16 vakalık bir doğrulama batch'i üret.

Bu batch için şunların tamamı sağlanmalı:

- Şema geçerli
- Decision enum geçerli
- `itiraz`, decision olarak kullanılmamış
- Açık PII bulgusu yok
- Otomatik düzeltilebilir anonimleştirme bulgusu yok
- Mevzuat referansları doğrulanmış
- Kurum ve konu birbiriyle tutarlı
- Cevap, gelen evrak ve karar sonucuyla uyumlu
- Duplicate/yakın kopya sınırı aşılmamış
- Checkpoint/resume çalışıyor
- Aynı komut yeniden çalıştırıldığında başarılı vakalar tekrar üretilmiyor

Bu kapı geçerse kalan kotaları tamamlayarak 240 vakaya ilerle. Başarısızsa
önce kök nedeni düzelt, test ekle ve küçük batch'i tekrar dene.

---

# Aşama 5 — Split ve veri sızıntısı kontrolü

Train/dev/heldout oranı: Train ~%70, Dev ~%15, Heldout ~%15.

Split, yalnız kayıt bazında rastgele yapılmamalı. `curate_yazisma_examples.py`
içindeki `_dataset_split` yaklaşımını incele ve aynı deterministik yöntemi
kullan.

Aşağıdaki unsurlar iki farklı split'e dağılmamalı: aynı `source_group`,
aynı kaynak belge, aynı kaynak URL, aynı normalize edilmiş içerik hash'i,
aynı kurum+konu şablon ailesi, yakın kopyalar.

## Kopya tanımları

- Tam kopya: normalize edilmiş içeriğin SHA-256 eşitliği
- Yakın kopya: token tabanlı benzerlik veya MinHash/uygun deterministik
  yöntem
- Önerilen yakın kopya eşiği: `>= 0.90`
- Karşılaştırma öncesinde whitespace, başlık biçimi ve semantik maskeler
  tutarlı biçimde normalize edilmeli

Kullanılan algoritmayı, eşiği ve normalizasyon kurallarını rapora yaz.

Split sonunda: her split'in kayıt sayısı, karar dağılımı, kurum dağılımı,
itiraz dağılımı, gerçek/sentetik niteliği, `source_group` sayısı, split'ler
arası çakışma sayısı raporlanmalı.

Split sızıntısı hedefi sıfırdır.

---

# Aşama 6 — Otomatik ve insan kalite kontrolü

## 6.1 Tüm 240 vaka için otomatik kontrol

Zorunlu alanlar dolu, decision enum geçerli, incoming type doğru, gelen
evrak/karar/cevap tutarlı, açık PII yok, otomatik düzeltilebilir
anonimleştirme bulgusu yok, mevzuat referansları doğrulanmış, kurum kotası
aşılmamış, kaynak/provenance mevcut, split sızıntısı yok, tam/yakın kopya
yok, bozuk Türkçe karakter/mojibake yok, genel web boilerplate'i yok, model
çıktısı veya log artığı yok.

## 6.2 İsim taraması

Yaygın Türkçe ad+soyad biçimlerini serbest metinde tara. Yanlış pozitifleri
bağlamsal olarak ayır: cadde/sokak adları, tarihî kişi adları, kurum
adları, mevzuat/karar metnindeki kamuya açık isimler, kişi adı olmayan
makam unvanları.

Belirsiz bulguları otomatik silme; `review_required` olarak raporla.

## 6.3 İnsan inceleme örneklemi

Dengeli rastgele ~%15–20 örnekleme ek olarak aşağıdaki yüksek riskli
vakaların **tamamını** inceleme sayfasına dahil et: mevzuat doğrulamasında
retry gerekenler, anonimleştirme dönüşümü yapılanlar, düşük güven
skorlular, duplicate sınırına yakın olanlar, şema migrasyonu yapılan pilot
itiraz kayıtları, kurum kotasına yakın olanlar, model cevabı yeniden
üretilenler.

İnceleme sayfasında: karar türüne göre gruplama, gelen evrak, karar, cevap,
mevzuat dayanağı, provenance, onay/ret, not alanı, localStorage desteği
bulunsun.

Projede uygun bir tasarım skill'i mevcutsa kullan (`artifact-design`, bu
oturumdaki `vaka_review.html`/`compare.html` sayfalarındaki token sistemi
— IBM Plex Sans/Serif/Mono, kağıt + mühür kırmızısı paleti). Yoksa bu durum
işi bloklamasın; mevcut proje tasarım sistemini veya sade erişilebilir
HTML kullan.

---

# Aşama 7 — Testler

En az aşağıdaki testleri çalıştır: `test_prepare_resmi_yazisma_markdown.py`,
`test_curate_yazisma_examples.py`, yeni vaka üretim testleri, yeni mevzuat
doğrulama testleri, split sızıntısı testleri, checkpoint/resume testleri,
duplicate testleri, dataset analiz testi.

Mümkünse tam backend unit test paketini çalıştır.

Ayrıca: `git diff --check`, açık PII taraması, `[SİLİNMİŞTİR]` ve bozuk
semantik maske taraması, mojibake taraması, ham kaynak değişiklik kontrolü,
JSON/JSONL şema kontrolü, arka arkaya iki çalıştırmada idempotence kontrolü
yap.

Çalıştırılamayan test varsa bunu gizleme; komut, hata nedeni ve etkisini
raporla.

---

# Aşama 8 — Tüm dataset envanteri ve kullanım analizi

Rapor sayılarını README'den kopyalama. Şunları doğrudan incele: dosya
sistemi, Markdown front matter, JSON/JSONL çıktıları, manifestler, RAG
curation çıktıları, split dosyaları, kaynak URL ve provenance alanları.

## 8.1 Kavramları ayrı say

Aşağıdaki kavramları birbirine karıştırma: ham kaynak dosyası, fiziksel
dosya, Markdown kartı, aktif korpus kaydı, karantina kaydı, tekil kaynak
belge, tekil `source_group`, `candidate`, `reference_only`, `rejected`,
üretim RAG'ına gerçekten alınan kayıt, JSONL örneği, train/dev/heldout
kaydı, pilot vaka, yeni 240 vakalık dataset.

Aynı belgenin PDF, Markdown ve JSONL karşılığı varsa bunu üç tekil belge
olarak gösterme. Hem fiziksel dosya sayısını hem tekil belge sayısını ayrı
göster.

## 8.2 Tüm dataset için hesaplanacaklar

Aşağıdaki dağılımların tamamında hem adet hem yüzde ver:

### Dosya türü
PDF, HTML, DOC, DOCX, Markdown, JSON, JSONL, Diğer.

### Konum
Her ana ve alt klasör için: fiziksel dosya, Markdown kartı, tekil belge,
aktif/karantina, RAG statüsü, kullanım amacı.

### Belge türü
Üst yazı, cevap yazısı, bilgilendirme metni, dilekçe, diğer resmî
yazışma, yönetmelik/yazışma kuralları, gelen evrak–karar–cevap vakaları,
mevcut diğer kategoriler.

### Veri niteliği
Gerçek/resmî kaynak, sentetik, gerçek kaynaktan türetilmiş sentetik,
referans amaçlı, karantina, bilinmiyor.

Bu sınıfları dosya adından tahmin etme. Yalnız açık front matter/
provenance/manifest alanlarından belirle. Kanıt bulunamazsa `bilinmiyor`
göster.

### RAG statüsü
`candidate`, `reference_only`, `rejected`, manuel inceleme gereken.

### Anonimleştirme
Anonimleştirilmiş kayıt, semantik maske içeren kayıt, açık PII bulgusu,
otomatik düzeltilmiş bulgu, manuel inceleme bekleyen bulgu.

### Kaynak

Her kurum ve kaynak alan adı için: kayıt sayısı, tekil belge sayısı, genel
dataset yüzdesi, RAG'a alınan kayıt, RAG kabul oranı, kaynak URL'si bulunan
kayıt, URL'si eksik kayıt.

URL erişilebilirliği kontrol edilirse: kontrol zamanı, HTTP/erişim sonucu,
erişilemeyen URL, kontrol edilemeyen URL ayrı gösterilmeli. Geçici ağ
hatasını "kaynak geçersiz" olarak yorumlama.

## 8.3 Veriyi nerede ve neden kullandığımız

Şu matrisi üret:

| Veri/klasör | İçerik | Kaynak | Dosya sayısı | Tekil belge | Kullanıldığı yer | Kullanım amacı | Üretim RAG'ına giriyor mu? |
| --- | --- | --- | ---: | ---: | --- | --- | --- |

Kullanım amaçlarını ayır: doğrudan retrieval, writer agent üslup/biçim
örneği, few-shot vaka üretimi, mevzuat/yazışma kuralı referansı,
anonimleştirme testi, kalite testi, dev değerlendirmesi, heldout
değerlendirmesi, karantina/hata analizi, provenance arşivi, henüz
kullanılmayan veri.

`rejected` kayıtları otomatik olarak "işe yaramaz" diye tanımlama. Her ret
grubu için: ret nedeni, üretim RAG'ına neden girmediği, test/arşiv/analiz
bakımından hâlâ kullanılıp kullanılmadığı açıklanmalı.

---

# Aşama 9 — Yalnız üretim RAG'ının ayrı analizi

Genel dataset analizinden sonra hesaplamaları yalnızca üretim RAG'ına
gerçekten alınmış kayıtlar üzerinde tekrar yap. RAG analizi için payda
yalnız RAG kayıtları olmalı.

Şunları göster: toplam RAG kaydı, tekil belge, tekil `source_group`, dosya
türü dağılımı, belge türü ve alt kategori dağılımı, kaynak kurum dağılımı,
kaynak alan adı dağılımı, gerçek/resmî–sentetik–türetilmiş sentetik
dağılımı, her kaynağın genel dataset sayısı, aynı kaynağın RAG'a giren
sayısı, kaynak başına RAG kabul oranı, train/dev/heldout dağılımı, split
başına gerçek/sentetik oranı, split başına kurum ve kategori dağılımı,
duplicate ve split sızıntısı sonucu, en çok temsil edilen 10 kurum, en az
temsil edilen belge ve karar türleri, RAG'a alınmayan kayıtların ret
nedenleri.

Yeni 240 vaka henüz mevcut RAG'a eklenmediyse bunları RAG toplamına dahil
etme.

Üç ayrı görünüm sun:

1. Mevcut üretim RAG
2. Ayrı 240 vakalık dataset
3. Kullanıcı ileride birleştirmeyi onaylarsa oluşabilecek varsayımsal
   görünüm

Varsayımsal görünümü gerçek mevcut durum gibi sunma.

---

# Aşama 10 — Karşılaştırma ve grafikler

Aşağıdaki tabloyu oluştur:

| Metrik | Tüm dataset | Aktif korpus | Üretim RAG | Dev | Heldout | Karantina | Yeni vaka seti |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |

En az şu metrikler bulunsun: fiziksel dosya, Markdown kartı, tekil belge,
tekil `source_group`, gerçek/resmî kayıt, sentetik kayıt, kaynak kurum
sayısı, belge türü sayısı, açık PII bulgusu, tam/yakın kopya, kaynak
URL'si eksik kayıt.

Şu oranları hesapla: tüm verinin yüzde kaçı üretim RAG'ında, gerçek/resmî
verinin yüzde kaçı RAG'a girmiş, sentetik verinin yüzde kaçı RAG'a girmiş,
her belge türünün RAG kabul oranı, önemli kurumların RAG kabul oranları,
verinin yüzde kaçı arşiv/test/referans/karantinada, yeni vaka datasetinin
karar ve split dağılımı.

Yüzdeleri bir ondalık basamakla göster. Her yüzdede kullanılan paydayı
açıkça belirt. Yuvarlama nedeniyle toplam %100 olmuyorsa dipnot ekle.
`bilinmiyor` kayıtlarını sessizce dışlama.

## Grafikler

Hem adet hem yüzde içeren grafikler üret: tüm dataset gerçek/resmî–sentetik
dağılımı, tüm dataset kaynak kurum dağılımı, dosya türü dağılımı, belge
türü dağılımı, RAG statüsü dağılımı, yalnız üretim RAG'ı gerçek/resmî–
sentetik dağılımı, yalnız üretim RAG'ı kaynak kurum dağılımı, RAG train/
dev/heldout dağılımı, karar türü dağılımı, genel dataset–üretim RAG
karşılaştırması, OS-* düzeltmesi öncesi/sonrası.

Kurum sayısı fazlaysa grafikte ilk 10 kurumu göster ve kalanları `Diğer`
altında topla. Ayrıntılı tabloda tüm kurumları eksiksiz listele.

---

# Aşama 11 — Dataset yeterlilik değerlendirmesi

Sayısal sonuçlara dayanarak dürüst değerlendirme yap:

- Writer agent'ın resmî biçim ve üslubu öğrenmesi için yeterli mi?
- Gelen evraktan karar ve cevap üretme senaryoları yeterli mi?
- Hangi karar türleri eksik?
- Hangi kurumlar aşırı temsil ediliyor?
- Hangi belge türleri az temsil ediliyor?
- Hangi kaynaklarda tekrar oranı yüksek?
- Gerçek ve sentetik veri dengesi sağlıklı mı?
- Retrieval çeşitliliği yeterli mi?
- Sentetik veriler ezber veya şablon tekrarı riski taşıyor mu?
- Heldout set gerçekçi değerlendirme sağlıyor mu?
- Bir sonraki veri toplama turundaki ilk 10 öncelik nedir?

Her yargıyı sayı veya oranla destekle. Ölçülemeyen sonucu tahmin etme;
`ölçülemedi` yaz ve nedenini belirt.

---

# Aşama 12 — Üretilecek raporlar

Üret:

- `datasets/resmi_yazisma/TUM_VERI_SETI_ANALIZI.md`
- `datasets/resmi_yazisma/tum-veri-seti-analizi.json`

Rapor sayıları elle yazılmamalı. Deterministik ve tekrar çalıştırılabilir
bir analiz betiği tarafından üretilmeli.

JSON raporunda: kullanılan filtreler, her metriğin paydası, sayım
tanımları, kaynak kapsamı, üretim zamanı, analiz şema versiyonu bulunmalı.

Zaman alanı idempotence testini bozuyorsa çalışma zamanı ile veri içeriği
hash'ini ayır.

README ve CHANGELOG'u gerçek sonuçlara göre güncelle.

---

# Aşama 13 — Son rapor ve kullanıcı onayı

Kullanıcıya şu özeti sun:

## Yapılan işler
Değiştirilen betikler, eklenen testler, düzeltilen veri kartları, üretilen
raporlar, ham kaynakların korunma sonucu.

## OS-* sonucu
Önce/sonra statü dağılımı, RAG'dan çıkarılan kayıt, kalan belirsiz kayıt,
idempotence sonucu.

## 240 vaka sonucu
Toplam başarılı vaka, karar dağılımı, itiraz dağılımı, kurum çeşitliliği,
retry sayıları, başarısız üretim nedenleri, mevzuat doğrulama sonucu,
anonimleştirme sonucu, duplicate sonucu, split sonucu.

## Tüm dataset özeti
Fiziksel dosya, Markdown kartı, tekil belge, gerçek/resmî kayıt, sentetik
kayıt, aktif/karantina, en büyük beş kaynak, her kaynağın adet ve yüzdesi,
dosyaların nerede ve ne amaçla kullanıldığı.

## Üretim RAG özeti
RAG kayıt sayısı, tekil belge, gerçek/resmî–sentetik oranı, en çok
kullanılan beş kaynak, kategori dağılımı, split dağılımı, RAG'a kabul
oranları, RAG'a alınmayan kayıtların nedenleri.

## Değerlendirme
Datasetin en güçlü üç yanı, en önemli beş açığı, sonraki veri toplama
önerileri, yeni 240 vakayı RAG'a ekleme konusunda öneri, kalan riskler.

## Kanıtlar
Test sonuçları, idempotence hash sonucu, split sızıntısı sonucu, PII
taraması sonucu, `git diff --check`, ham kaynakların değişmediğinin
doğrulanması.

Bu aşamanın kendi yerel commit'ini at (Bölüm 2.1a, madde 7), sonra raporun
sonunda dur. Aşağıdaki işlemleri yapma: push, PR, merge, mevcut üretim
RAG'ına yeni vaka ekleme, retrieval veritabanını güncelleme. Bu işlemler
yalnız kullanıcı raporu inceledikten ve açıkça onayladıktan sonra
yapılabilir.

---

# Ön koşullar

Başlamadan önce doğrula:

- `.env` içinde `LOCAL_MODE=false`
- Geçerli `EVREN_API_KEY`
- API anahtarının Git tarafından izlenmediği
- Docker servislerinin çalıştığı
- En az `backend` ve gereken bağımlılık servislerinin sağlıklı olduğu
- Mevzuat MCP sunucusunun erişilebilir olduğu (`/tmp/mcpvenv/bin/mevzuat-mcp`,
  container içinde zaten kurulu)
- Mevcut anonimleştirme testlerinin geçtiği

240 üretim çağrısını tek parçada çalıştırma.

## Önerilen yürütme sırası

1. Repo denetimi
2. OS-* düzeltmesi
3. OS testleri ve idempotence
4. Şema düzeltmesi
5. 8–16 vakalık doğrulama batch'i
6. Küçük batch kalite kapısı
7. Kalan vakaları 10–20 kayıtlık devam ettirilebilir batch'lerle üretme
8. Otomatik kalite kontrolü
9. İnsan inceleme örneklemi
10. Split üretimi
11. Tüm dataset ve RAG analizi
12. Testler
13. Son rapor
14. Kullanıcı onayını bekleme

Görevi yarıda bırakma; ancak güvenlik, yanlış branch, kayıp API yetkisi,
bozuk mevcut değişiklik veya kullanıcı kararı gerektiren gerçek bir
belirsizlik oluşursa güvenli biçimde dur ve neye ihtiyaç olduğunu açıkça
bildir.
