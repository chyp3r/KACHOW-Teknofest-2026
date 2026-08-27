# KACHOW Türkçe Resmî Yazışma Kaynak Veri Kümesi

Bu klasör KACHOW'un resmî yazı taslağı üreten ajanları için kaynak, referans ve
few-shot örneklerini içerir. RAG yalnız UTF-8 Markdown kartlarından beslenir.

## Ham kaynaklar

Ham kaynak dosyalar (PDF, HTML, DOC, DOCX ve GİB API'nin ham JSON anlık
görüntüleri; `00_gelen_kaynaklar/` altında 679 dosya) **artık GitHub'a
gönderilmez** (`.gitignore`). Bu dosyalar diskte olduğu yerde, değişmeden
kalır — yalnız `git`'e eklenmeleri durduruldu; halihazırda commit edilmiş
geçmişteki kopyalar geriye dönük silinmedi. Her kaynağın türetilmiş Markdown
eşi (`kaynak`/`yerel_orijinal` alanlarıyla izlenebilir) izlenmeye devam eder;
asıl veri kümesi budur. Ham kaynağa yalnız
`scripts/prepare_resmi_yazisma_markdown.py --apply` (kaynaktan yeniden
çıkarım yapan tam mod) ihtiyaç duyar — `--apply --normalize-only`, kataloglar
ve RAG çıktısı yalnız mevcut Markdown kartlarından çalışır.

## Güncel durum

- Kaynak dosya: **492** (PDF 366, HTML 50, DOCX 57, DOC 19) + GİB API ham
  JSON: **200**
- Markdown eşi veya açıklamalı ret kaydı bulunan kaynak: **492/492**
- Belge niteliğindeki toplam Markdown kartı: **1763**
  - aktif korpus: 1723
  - karantina türevi: 40
- Tekil kaynak belge: **870**
- Kaynak kurumu bilinmeyen kart: **0**
- Normalleştirilmiş aktif Markdown kartı: **1723**
  - `candidate`: 584
  - `reference_only`: 37
  - `rejected`: 1102
- Kalite kapısını geçen, tekil şablon ailesi: **515**
  - resmî/gerçek kaynaklı: 453 (%88,0)
  - sentetik: 62 (%12,0)
- Üretim retrieval çıktısı (`ornekler.jsonl`): **396**
  - üst yazı: 87
  - cevap yazısı: 129
  - bilgilendirme metni: 84
  - diğer resmî yazışma: 96
- Ayrı değerlendirme kümeleri: dev 80, heldout 39
- Gerçek/resmî örnek kotası: üst yazı 107, cevap yazısı 131,
  bilgilendirme metni 108, diğer resmî yazışma 107 (**her türde hedef ≥100**)
- Gerçek eksik-belge/yetkisizlik şablon ailesi: **22**. Aynı bildirim
  şablonunun farklı başvuru değerleri veri sayısını yapay biçimde artırmaz.
- Yüksek güvenli PII bulgusu: **0**
- Bağlamsal denetim bulgusu (`anonimlestirme-denetim-manifesti.jsonl`):
  **130**, tamamı otomatik düzeltildi; inceleme bekleyen kayıt: **0**
- Agent-destekli kalite ön incelemesi: **100/100** geçti; insan onayı değildir

Ayrıntılı ve makine tarafından okunabilir sonuçlar `KALITE_RAPORU.md` ile
`kalite-raporu.json` dosyalarındadır. Kurum/format/kategori dağılımları
`VERI_ISTATISTIKLERI.md` ve `veri-istatistikleri.json`; her kartın güvenli
işlem sonucu `anonimlestirme-manifesti.jsonl`; elle doğrulanacak dengeli örneklem
`manuel-qa-manifesti.csv` dosyasındadır. Üretim/dev/heldout ve kaynak kökeni
analizi `RAG_VERI_ANALIZI.md`/`rag-veri-analizi.json`; yeni resmî kaynak araştırması
`KAYNAK_ARASTIRMASI.md`/`kaynak-adaylari.csv` dosyalarındadır.

## Markdown kart şeması

Her kart en az aşağıdaki front matter alanlarını taşır:

```yaml
---
id: "CY-001"
kategori: "cevap_yazisi"
alt_kategori: "bilgi_edinme"
baslik: "Belgenin başlığı"
kaynak: "datasets/resmi_yazisma/.../CY-001.pdf"
kaynak_turu: "pdf"
extractor: "tesseract"
used_ocr: true
quality_score: 0.794
rag_status: "candidate"
kaynak_kurum: "Ticaret Bakanlığı"
anonimlestirme_durumu: "uygun"
anonimlestirilen_alan_sayisi: 3
---
```

Türetilmiş `ornekler*.jsonl` kayıtları ayrıca `source_origin`,
`source_verification`, `source_sha256`, `license_status`, `template_family`,
`source_group` ve `dataset_split` alanlarını taşır.

`rag_status` değerleri:

- `candidate`: kalite kapılarını geçen ve `ornekler.jsonl` için değerlendirilen kart.
- `reference_only`: yönetmelik veya çok sayfalı kılavuz gibi yazım örneği değil,
  bilgi/kural referansı olan belge.
- `rejected`: kısa, bozuk, başlık-gövde uyumsuz veya tekrar belge. `ret_nedeni`
  alanı gerekçeyi açıklar.

## Dönüşüm ve kalite hattı

Hattın kuru çalıştırması hiçbir veri dosyasını değiştirmez:

```powershell
docker compose run --rm --no-deps backend `
  python scripts/prepare_resmi_yazisma_markdown.py --dry-run
```

Doğrulanan dönüşümü uygulamak için:

```powershell
docker compose run --rm --no-deps backend `
  python scripts/prepare_resmi_yazisma_markdown.py --apply
```

Yalnız mevcut Markdown kartlarını yeniden anonimleştirmek/normalleştirmek için
`--apply --normalize-only`; belirli kaynak türleri için örneğin
`--apply --suffix doc --suffix docx` kullanılabilir.

Ardından kataloglar ve RAG çıktısı deterministik olarak yenilenir:

```powershell
docker compose run --rm --no-deps backend python scripts/update_dataset_indexes.py
docker compose run --rm --no-deps backend python scripts/curate_yazisma_examples.py --report
docker compose run --rm --no-deps backend `
  python scripts/review_resmi_yazisma_qa.py --review-date YYYY-MM-DD --apply
```

Resmî GİB API kayıtları ile TÜRKPATENT eksik-belge bildirimlerini kaynak iziyle
yeniden üretmek için:

```powershell
docker compose run --rm --no-deps backend python scripts/collect_gib_official_corpus.py
docker compose run --rm --no-deps backend `
  python scripts/collect_turkpatent_missing_document_examples.py
```

GİB yanıt gövdelerinin değişmeden saklanan JSON anlık görüntüleri
`00_gelen_kaynaklar/gib_api/`; TÜRKPATENT'in değişmeden saklanan kaynak PDF'i
`00_gelen_kaynaklar/turkpatent_bultenleri/` altındadır. İki kaynak için de URL,
erişim tarihi ve SHA-256 izi kartlarda ve ayrı manifestlerde korunur.

## Anonimleştirme

Genel ve bağlamsız silme işareti kullanılmaz. Bağlama göre şu semantik alanlar
üretilir: `[KİŞİ ADI]`, `[BAŞVURU SAHİBİ]`, `[VEKİL ADI]`,
`[İMZA SAHİBİ]`, `[T.C. KİMLİK NO]`, `[IBAN]`, `[KAYIT NUMARASI]`,
`[EVRAK SAYISI]`, `[KURUM ADI]`, `[KURUM ADRESİ]`, `[KURUM TELEFONU]`,
`[KURUM İLETİŞİM BİLGİLERİ]`, `[İL ADI]`, `[YARGI MERCİİ]`, `[E-POSTA]`
ve `[ADRES]`.

Tarama aktif, referans ve reddedilmiş kartlar dahil belge niteliğindeki tüm
Markdown kayıtlarına uygulanır. README/kalite raporu gibi dokümantasyon dosyaları
veri kartı olarak sayılmaz. Kişi mi kurum mu olduğu güvenle belirlenemeyen veya
yüksek güvenli PII taşıyan bir aday `review_required` durumuna alınır ve üretim
RAG çıktısına yazılmaz. Kurum adları anonimleştirilmez; kaynak istatistikleri için
kanonikleştirilerek korunur.

## Veri kalitesi kararları

- `dilekceornegi_*.md` ile kazınan 35 açıklayıcı makale ve 5 site sayfası,
  resmî yazı örneği olmadıkları için `99_reddedilenler/dilekce_makaleleri/`
  altında temizlenmiş türev olarak korunur. Orijinal HTML kaynaklar değişmeden
  kalır; bunlardan üretilen Markdown türevlerinin tamamı PII taramasından geçer
  ve üretim RAG'ına girmez.
- OCR kaynaklı bozuk apostroflar yalnız iki harf arasındaysa deterministik
  olarak düzeltilir. Güvenle düzeltilemeyen mojibake veya bozuk başlık taşıyan
  kartlar `ocr_karakter_bozulmasi` gerekçesiyle RAG dışında tutulur.
- PII denetimi fail-closed çalışır: yüksek güvenli bir bulgu taşıyan kayıt
  `ornekler.jsonl` dosyasına hiç yazılmaz ve eleme raporunda gerekçesi görünür.
- `OS-*` kayıtları gerçek resmî belge değildir; `scripts/scrape_open_sources.py`
  ile üretilmiş sentetik örneklemdir. Bu betik başlık, kurum ve gövdeyi
  **birbirinden bağımsız** rastgele havuzlardan çektiği için üç çekim
  birbiriyle çelişebiliyor. Kalite kapısı bunu üç eksende ayrı ayrı
  denetler ve **fail-closed** çalışır: tanımadığı bir gövde kalıbı
  reddedilir, geçmez.
  - `baslik_govde_uyumsuzlugu`: gövde, başlığın konusunu cevaplayamıyor
  - `kategori_govde_uyumsuzlugu`: bir cevap yazısı gövdesi "diğer resmî
    yazışma" gibi yanlış klasörde dosyalanmış
  - `kurum_govde_uyumsuzlugu`: gövde kendi karar organını adlandırıyor ama
    antet uymuyor (ör. "belediye meclis kararı" bir mahkeme antetiyle,
    "Bakanlığımızca yürütülen projeler" bir üniversite antetiyle)
  - `taninmayan_govde_kalibi`: gövde bilinen hiçbir havuz kalıbına uymuyor
  Bu kapının önceki sürümü tanımadığı kalıbı `genel` sayıp **koşulsuz**
  geçiriyordu; düzeltmeyle 800 karttan `candidate` kalan sayısı 63'ten
  **9**'a düştü, 54 kart üretim RAG'ından çıktı.
- Simülasyon PDF'leri OCR ve anonimleştirme regresyonu içindir. Kurum, şehir,
  tarih ve olay değerlerini rastgele birleştirdikleri için **hiçbiri** üretim
  RAG'ına girmez; `sentetik_simulasyon_yalniz_test` gerekçesiyle korunur.
- Aynı normalleştirilmiş şablon ailesinden yalnız deterministik ilk temsilci
  kalır. Kaynak dosya/URL veya şablon ailesi aynı olan kayıtlar retrieval ile
  dev/heldout kümeleri arasında bölünmez.
- Dilekçeler gelen evrak örneğidir; doğrudan giden resmî yazı few-shot havuzuna
  alınmaz.

Kaynakların erişim/provenans alanları kartlarda korunur. Eski belgeler güncel
biçim kuralı olarak değil, yalnız söylem ve içerik örneği olarak kullanılmalıdır.
Resmî alan adında bulunmak açık lisans anlamına gelmez; insan kullanım/lisans
onayı verilmeyen gerçek kaynaklar `usage_review_required` olarak raporlanır.
