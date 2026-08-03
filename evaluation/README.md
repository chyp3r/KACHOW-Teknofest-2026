# Değerlendirme Koşumu

> Deterministik karar katmanının LLM'siz, tekrarlanabilir ölçümü.

Bu klasördeki her şey **ölçümdür**: üretim kodunu import eder, asla değiştirmez
ve **hiçbir dil modeli çağrısı yapmaz**. Bu kısıt, bir koşunun bir eşiği
kalibre edecek kadar tekrarlanabilir olmasını sağlayan şeydir.

## Neden LLM-as-judge / RAGAS değil

Yerel Ollama ~28 token/s üretiyor. Birkaç yüz vaka için yargı çağrısı yapan bir
koşum saatler sürer ve **ölçüm aracının kendisi ölçümdeki en gürültülü terim
olur**. Eşik kalibrasyonu için elle yazılmış, deterministik bir altın küme daha
küçük ama çok daha keskindir. `evaluation/ragas/` bu nedenle boş bırakılmıştır.

## Çalıştırma

```bash
# Tüm suite'ler; evaluation/reports/all-latest.{json,md} üretir
make eval

# Değişiklik öncesi referans noktası
make eval-baseline

# Karşılaştırmalı koşu
docker compose run --rm --no-deps backend \
  python -m evaluation.generate_report --suite all --label after-scoring \
  --baseline evaluation/reports/all-baseline.json
```

Koşum `backend` container'ı içinde çalışır (proje kuralı: pytest ve ölçüm host'ta
değil container'da koşulur). `evaluation/` hem `compose.yml` ile mount edilir hem
de imaja kopyalanır — mount, altın küme düzenlemelerinin rebuild gerektirmemesi
içindir.

## Yapı

| Yol | İçerik |
|---|---|
| `metrics.py` | Sınıflandırma ve kalibrasyon metrikleri. Yalnızca standart kütüphane. |
| `harness/runner.py` | Altın kümeyi yükleyen, koşturan ve süre ölçen jenerik koşucu. |
| `harness/intent_suite.py` | `resolve_plan_deterministic`'e bağlanır. |
| `harness/draft_suite.py` | `verify_draft`'e bağlanır (yargıç hariç). |
| `datasets/*.jsonl` | Altın kümeler. |
| `reports/` | Üretilen raporlar (JSON + Markdown). |

## Metrikler neden abstention-farkında

Ölçülen karar katmanı **çekimser kalabiliyor** (abstain): tahmin etmek yerine
işi model katmanına devredebiliyor. Bu, kaliteyi birbiriyle takas eden iki eksene
böler:

1. Karar verdiğinde ne sıklıkla haklı (`accuracy`, `macro_f1`),
2. Yanılacağı vakalarda çekimser kalıyor mu (`risk_coverage_curve`,
   `expected_calibration_error`).

Yalnızca birincisini iyileştirmek, her şeye kendinden emin ve yanlış cevap veren
bir katman üretir. Yalnızca ikincisini iyileştirmek, her şeyde çekimser kalıp tüm
yükü modele yıkan bir katman üretir. Bu yüzden `accuracy` varsayılan olarak
yalnızca karar verilen alt kümeyi puanlar, `confusion_matrix` çekimserliği kendi
sütununda tutar ve `macro_f1` mikro değil makro'dur (altın küme bilinçli olarak
dengesizdir; mikro ortalama, `chat`'i doğru bilip `document_qa`'yı tamamen
kaçıran bir katmanı iyi gösterirdi).

## Altın küme kategorileri

Kategoriler trafiğin tarafsız bir örneklemi **değildir**. Her biri, mevcut
deterministik katmanın bilinen bir kusur sınıfını hedefler — böylece rapor
"ne kadar" değil **"nerede"** kırıldığını söyler.

`keyword_*`, `continuation` ve `document_question` kontrol grubudur: katmanın
tasarlandığı alan. Bunlar geçmeye devam etmeli; başarısız kategorileri
iyileştirirken bunları bozan bir değişiklik anında görünür.

## Veri kaynağı beyanı

Şartnamenin 6.5 maddesi uyarınca bu klasördeki altın kümelerde **gerçek kamu
verisi kullanılmamıştır**. Tüm mesajlar, evraklar, taslaklar, kurum adları, kişi
adları, adresler ve belge sayıları tarafımızca kurgulanmıştır
(`Örnek Bakanlığı`, `Deneme Kaymakamlığı`, `Ayşe Demir`, `E-11111111-...`).
Kullanılan mevzuat metinleri kamuya açık ve mevzuat.gov.tr üzerinden
erişilebilir resmî metinlerdir.
