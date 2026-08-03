# Deterministik Karar Katmanı Değerlendirme Raporu

> Bu rapor `make eval` ile üretilir ve **hiç LLM çağrısı içermez**.
> Ölçülen, üretim kodundaki deterministik karar fonksiyonlarının kendisidir.

## Suite: `drafts`

Altın küme: `evaluation/datasets/drafts.jsonl` · Koşu: 2026-08-03T09:35:02 · Süre: 4.8 ms

### Genel

| Metrik | Değer |
|---|---|
| Vaka sayısı | 40 |
| Doğruluk | 1.0000 |
| **Yanlış pozitif oranı** (gereksiz HITL) | **0.0000** |
| Yanlış negatif oranı (kaçan hata) | 0.0000 |
| TP / FP / TN / FN | 23 / 0 / 17 / 0 |

### Kategori kırılımı

| Kategori | Vaka | Doğruluk | YP | YN |
|---|---|---|---|---|
| `grounded` | 5 | 1.00 | 0 | 0 |
| `hallucinated` | 12 | 1.00 | 0 | 0 |
| `other_official` | 3 | 1.00 | 0 | 0 |
| `paraphrased_grounded` | 10 | 1.00 | 0 | 0 |
| `placeholder` | 4 | 1.00 | 0 | 0 |
| `structural` | 6 | 1.00 | 0 | 0 |

### Başarısız vakalar (0)

Yok.

### Dayanaksız ifade sayımı sapmaları (0)

Yok.

### Baseline karşılaştırması

| Metrik | Baseline | Şimdi | Δ |
|---|---|---|---|
| Doğruluk | 0.9000 | 1.0000 | +0.1000 ↑ |
| Yanlış pozitif oranı | 0.2353 | 0.0000 | -0.2353 ↓ |
| Yanlış negatif oranı | 0.0000 | 0.0000 | +0.0000 → |

