# RAG Veri Analizi

> Bu dosya `scripts/curate_yazisma_examples.py` tarafından deterministik olarak üretilir.

## Kalite özeti

- Kalite kapısını geçen toplam örnek: **569**
- Tekil şablon ailesi: **569**
- Birden fazla kayıt taşıyan şablon ailesi: **0**
- Yüksek güvenli PII bulgusu: **0**
- Genel `[KİŞİSEL BİLGİ]` maskesi: **0**
- Eski `[SİLİNMİŞTİR]` maskesi: **0**
- Doğrudan kaynak URL'si olan örnek: **295**
- Yerel kaynak SHA-256 izi olan örnek: **433**
- Gerçek/resmî kaynaklı örnek oranı: **%79.6**
- Sentetik örnek oranı: **%20.4**

## Kaynak kökeni

| Köken | Kayıt |
|---|---:|
| `official_verified_local` | 380 |
| `official_web_pending_review` | 73 |
| `synthetic` | 116 |

`pending_review` kökenleri kaynağın resmî alan adında veya yerel arşivde olduğunu,
ancak kullanım/lisans kararının henüz insan tarafından onaylanmadığını belirtir.

## Sızıntısız veri ayrımı

| Ayrım | Kayıt |
|---|---:|
| `dev` | 89 |
| `heldout` | 51 |
| `retrieval` | 429 |

Ayrım tek tek kayıtlara göre değil, kaynak dosya/URL veya normalleştirilmiş
şablon ailesine göre yapılır. Aynı kaynak ya da aynı şablon retrieval ve ölçüm
kümelerine bölünemez.

## Yazı türü başına gerçek veri açığı

| Yazı türü | Gerçek/resmî | 100 hedefi için açık |
|---|---:|---:|
| `cover_letter` | 107 | 0 |
| `information_notice` | 108 | 0 |
| `other_official` | 107 | 0 |
| `response_letter` | 131 | 0 |

Bu hedef yalnız kayıt sayısı değildir. Aynı şablon ailesinin farklı değerlerle
çoğaltılması sayıyı artırmaz.

## Önce / sonra

| Ölçüt | Önce | Sonra |
|---|---:|---:|
| `total_curated` | 384 | 569 |
| `real_or_official` | 236 | 453 |
| `synthetic` | 148 | 116 |
| `generic_person_placeholder_count` | 58 | 0 |
| `missing_metadata_records` | 32 | 0 |
| `simulation_records_in_production` | 32 | 0 |
| `records_in_duplicate_template_families` | 9 | 0 |
| `separate_dev_heldout_records` | 0 | 140 |

Önce değerleri 2026-08-17 tarihli yol haritası öncesi denetim anlık görüntüsüdür.
Toplamın azalması veri kaybı değil; 32 OCR simülasyonunun üretimden çıkarılması ve
5 şablon tekrarının tekilleştirilmesidir.
