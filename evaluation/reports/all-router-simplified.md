# Deterministik Karar Katmanı Değerlendirme Raporu

> Bu rapor `make eval` ile üretilir ve **hiç LLM çağrısı içermez**.
> Ölçülen, üretim kodundaki deterministik karar fonksiyonlarının kendisidir.

Policy sürümü: `1.3.0`

## Suite: `intents`

Altın küme: `evaluation/datasets/intents.jsonl` · Koşu: 2026-08-03T21:01:36 · Süre: 2.6 ms

### Genel

| Metrik | Değer |
|---|---|
| Vaka sayısı | 146 |
| Macro F1 | 0.9625 |
| Doğruluk (tüm vakalar) | 0.9247 |
| Doğruluk (karar verilenler) | 0.9783 |
| Eskalasyon (abstention) oranı | 0.0548 |
| Kalibrasyon hatası (ECE) | 0.0797 |

### Kategori kırılımı

| Kategori | Vaka | Doğruluk | Eskalasyon |
|---|---|---|---|
| `assist_vs_analyze` | 6 | 1.00 | 0.00 |
| `compound` | 8 | 1.00 | 0.00 |
| `continuation` | 8 | 1.00 | 0.00 |
| `document_question` | 10 | 1.00 | 0.00 |
| `draft_revision` | 10 | 1.00 | 0.00 |
| `escalation` | 8 | 1.00 | 0.00 |
| `heldout_paraphrase` | 16 | 0.31 | 0.50 |
| `inversion` | 8 | 1.00 | 0.00 |
| `keyword_analyze` | 8 | 1.00 | 0.00 |
| `keyword_assist` | 8 | 1.00 | 0.00 |
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
| `analyze` | 1.00 | 0.85 | 0.92 | 27 |
| `assist` | 0.96 | 0.96 | 0.96 | 67 |
| `draft` | 1.00 | 0.88 | 0.94 | 34 |
| `draft_revision` | 1.00 | 1.00 | 1.00 | 10 |

### Başarısız vakalar (11)

| ID | Kategori | Mesaj | Beklenen | Gözlenen | Kaynak |
|---|---|---|---|---|---|
| `held_01` | `heldout_paraphrase` | Bu belgeye karşılık verecek bir şeyler yazsana. | `draft` | `<abstain>` | `None` |
| `held_02` | `heldout_paraphrase` | Şu evraka dönüş yapacak bir metin çıkaralım. | `draft` | `<abstain>` | `None` |
| `held_03` | `heldout_paraphrase` | Bunun cevabını sen yazar mısın? | `draft` | `assist` | `scored` |
| `held_04` | `heldout_paraphrase` | İlgili makama sunulmak üzere bir yazı ihzar et. | `draft` | `<abstain>` | `None` |
| `held_05` | `heldout_paraphrase` | Şu belgeye bir göz atıp durumu anlatır mısın? | `analyze` | `assist` | `scored` |
| `held_06` | `heldout_paraphrase` | Bu evrakta bir sorun var mı acaba? | `analyze` | `assist` | `scored` |
| `held_07` | `heldout_paraphrase` | Bu yazının kurallara uyup uymadığını söyler misin? | `analyze` | `<abstain>` | `None` |
| `held_08` | `heldout_paraphrase` | Belgenin durumunu bir çıkar bakalım. | `analyze` | `<abstain>` | `None` |
| `held_12` | `heldout_paraphrase` | Sen ne tür işler görebiliyorsun? | `assist` | `<abstain>` | `None` |
| `held_13` | `heldout_paraphrase` | Buradaki akış nasıl ilerliyor tam olarak? | `assist` | `<abstain>` | `None` |
| `held_15` | `heldout_paraphrase` | Şu ana kadar neler geçti aramızda? | `assist` | `<abstain>` | `None` |

### Baseline karşılaştırması

| Metrik | Baseline | Şimdi | Δ |
|---|---|---|---|
| Macro F1 | 1.0000 | 0.9625 | -0.0375 ↓ (kötü) |
| Doğruluk (tüm vakalar) | 1.0000 | 0.9247 | -0.0753 ↓ (kötü) |
| Eskalasyon oranı | 0.0000 | 0.0548 | +0.0548 ↑ (kötü) |
| Kalibrasyon hatası | 0.0702 | 0.0797 | +0.0095 ↑ (kötü) |

## Suite: `drafts`

Altın küme: `evaluation/datasets/drafts.jsonl` · Koşu: 2026-08-03T21:01:36 · Süre: 4.6 ms

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
| Doğruluk | 1.0000 | 1.0000 | +0.0000 → |
| Yanlış pozitif oranı | 0.0000 | 0.0000 | +0.0000 → |
| Yanlış negatif oranı | 0.0000 | 0.0000 | +0.0000 → |

