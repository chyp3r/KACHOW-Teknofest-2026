# Sentetik Evrak Veri Kümesi

> Görev 1 — Evrak Sınıflandırma ve İçerik Analizi

Bu klasör, evrak analizi hattını sınamak için kullanılan **kurgu** evrak
örneklerini içerir.

## Veri kaynağı beyanı

Şartnamenin 6.5 maddesi uyarınca bu veri kümesinde **gerçek kamu verisi
kullanılmamıştır**. Tüm evraklar tarafımızca kurgulanmıştır. İçerideki kurum
adları, kişi adları, adresler, telefon numaraları ve sayı bilgileri açıkça
sentetiktir (`Örnek Bakanlığı`, `Ayşe Demir`, `Örnek Mah. Deneme Sok. No:1`,
`0500 000 00 00`, `E-11111111-...`). Hiçbir örnek gerçek bir belgeden
türetilmemiştir.

Kullanılan mevzuat metinleri (`datasets/mevzuat/`) kamuya açık ve
mevzuat.gov.tr üzerinden erişilebilir resmî metinlerdir.

## Dosya düzeni

Her örnek üç dosyadan oluşur:

| Uzantı | İçerik |
|---|---|
| `.txt` | Evrakın kaynak metni. Birim testleri bu dosyayı kullanır (LLM gerekmez). |
| `.json` | Beklenen sonuç: evrak türü, çıkarılması beklenen alanlar ve eksik olması beklenen alanlar. |
| `.pdf` | `scripts/generate_sample_evrak.py` ile üretilen PDF. |

PDF'ler `.txt` dosyalarından yeniden üretilebilir:

```bash
python scripts/generate_sample_evrak.py
```

## Kapsam

| Dosya | Tür | Kasıtlı eksiklik |
|---|---|---|
| `evrak_01` | Resmî Yazı | — (tam, kontrol örneği) |
| `evrak_02` | Resmî Yazı | Sayı, Muhatap |
| `evrak_03` | Resmî Yazı | Tarih (zorunlu), İmza unvanı (önerilen) |
| `evrak_04` | Dilekçe | — (tam) |
| `evrak_05` | Dilekçe | Adres, İmza (3071 s.K. m.4) |
| `evrak_06` | Bilgi Edinme Başvurusu | — (tam) |
| `evrak_07` | Bilgi Edinme Başvurusu | İletişim (yalnızca önerilen alan) |
| `evrak_08` | İzin Talebi | Tarih |
| `evrak_09` | Genelge | — (tam) |
| `evrak_10` | Tutanak | İmza sahibi |
| `evrak_11` | Resmî Yazı | Alanlar biçimsel olarak var, içerik yok (`Belirtilmemiş`, `-`) |
| `evrak_12` | Resmî Yazı | Taranmış görüntü — metin katmanı yok, OCR yolunu sınar |

Veri kümesi üç uygunluk durumunun tamamını kapsar: `compliant`,
`partially_compliant` (yalnızca `evrak_07`) ve `incomplete`.

`evrak_11`, kümedeki en kritik örnektir: dil modeli bir alan bulunmadığında
`null` yerine sıklıkla `"Belirtilmemiş"` veya `"-"` yazar; bu değerler olduğu
gibi kabul edilirse her evrak eksiksiz görünür.

## Testlerde kullanımı

`backend/tests/unit/ai/test_compliance.py` içindeki parametrik testler her
`.json` dosyası için `check_required_fields()` çıktısını
`expected_missing_fields` ile karşılaştırır. Bu testler dil modeli
çağırmaz; eksik bilgi tespitinin tekrarlanabilirliğini doğrular.
