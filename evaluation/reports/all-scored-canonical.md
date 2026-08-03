# Deterministik Karar Katmanı Değerlendirme Raporu

> Bu rapor `make eval` ile üretilir ve **hiç LLM çağrısı içermez**.
> Ölçülen, üretim kodundaki deterministik karar fonksiyonlarının kendisidir.

Policy sürümü: `1.0.0`

## Suite: `intents`

Altın küme: `evaluation/datasets/intents.jsonl` · Koşu: 2026-08-03T10:24:09 · Süre: 1.6 ms

### Genel

| Metrik | Değer |
|---|---|
| Vaka sayısı | 114 |
| Macro F1 | 1.0000 |
| Doğruluk (tüm vakalar) | 1.0000 |
| Doğruluk (karar verilenler) | 1.0000 |
| Eskalasyon (abstention) oranı | 0.0000 |
| Kalibrasyon hatası (ECE) | 0.0702 |

### Kategori kırılımı

| Kategori | Vaka | Doğruluk | Eskalasyon |
|---|---|---|---|
| `compound` | 8 | 1.00 | 0.00 |
| `continuation` | 8 | 1.00 | 0.00 |
| `document_question` | 10 | 1.00 | 0.00 |
| `escalation` | 8 | 1.00 | 0.00 |
| `inversion` | 8 | 1.00 | 0.00 |
| `keyword_analyze` | 8 | 1.00 | 0.00 |
| `keyword_chat` | 8 | 1.00 | 0.00 |
| `keyword_draft` | 10 | 1.00 | 0.00 |
| `memory_recall` | 10 | 1.00 | 0.00 |
| `paraphrase_analyze` | 6 | 1.00 | 0.00 |
| `paraphrase_draft` | 8 | 1.00 | 0.00 |
| `paraphrase_memory` | 10 | 1.00 | 0.00 |
| `precedence` | 6 | 1.00 | 0.00 |
| `short_message` | 6 | 1.00 | 0.00 |

### Etiket bazında

| Etiket | P | R | F1 | Destek |
|---|---|---|---|---|
| `<abstain>` | 1.00 | 1.00 | 1.00 | 8 |
| `analyze` | 1.00 | 1.00 | 1.00 | 20 |
| `chat` | 1.00 | 1.00 | 1.00 | 46 |
| `document_qa` | 1.00 | 1.00 | 1.00 | 10 |
| `draft` | 1.00 | 1.00 | 1.00 | 30 |

### Başarısız vakalar (0)

Yok.

### Baseline karşılaştırması

| Metrik | Baseline | Şimdi | Δ |
|---|---|---|---|
| Macro F1 | 0.7289 | 1.0000 | +0.2711 ↑ |
| Doğruluk (tüm vakalar) | 0.6316 | 1.0000 | +0.3684 ↑ |
| Eskalasyon oranı | 0.1842 | 0.0000 | -0.1842 ↓ |
| Kalibrasyon hatası | 0.3011 | 0.0702 | -0.2309 ↓ |

## Suite: `drafts`

Altın küme: `evaluation/datasets/drafts.jsonl` · Koşu: 2026-08-03T10:24:09 · Süre: 4.5 ms

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

