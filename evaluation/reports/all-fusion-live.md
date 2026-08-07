# Deterministik Karar Katmanı Değerlendirme Raporu

> Bu rapor `make eval` ile üretilir ve **hiç LLM çağrısı içermez**.
> Ölçülen, üretim kodundaki deterministik karar fonksiyonlarının kendisidir.

Policy sürümü: `1.5.0`

## Suite: `intents`

Altın küme: `evaluation/datasets/intents.jsonl` · Koşu: 2026-08-07T14:37:34 · Süre: 34.1 ms

### Genel

| Metrik | Değer |
|---|---|
| Vaka sayısı | 164 |
| Macro F1 | 0.9539 |
| Doğruluk (tüm vakalar) | 0.9146 |
| Doğruluk (karar verilenler) | 0.9677 |
| Eskalasyon (abstention) oranı | 0.0549 |
| **Clarify oranı** (kullanıcıya soru) | **0.1037** |
| Kalibrasyon hatası (ECE) | 0.1127 |

### Kaynak dağılımı

| Kaynak | Vaka |
|---|---|
| `fused` | 133 |
| `clarify` | 17 |
| `compound` | 8 |
| `clarification_resolved` | 6 |

### Kategori kırılımı

| Kategori | Vaka | Doğruluk | Eskalasyon |
|---|---|---|---|
| `clarify_resolution` | 6 | 1.00 | 0.00 |
| `compound` | 8 | 1.00 | 0.00 |
| `continuation` | 8 | 1.00 | 0.00 |
| `document_question` | 10 | 1.00 | 0.00 |
| `escalation` | 8 | 1.00 | 0.00 |
| `heldout_paraphrase` | 22 | 0.36 | 0.41 |
| `inversion` | 8 | 1.00 | 0.00 |
| `keyword_analyze` | 8 | 1.00 | 0.00 |
| `keyword_assist` | 8 | 1.00 | 0.00 |
| `keyword_draft` | 10 | 1.00 | 0.00 |
| `memory_recall` | 10 | 1.00 | 0.00 |
| `paraphrase_analyze` | 6 | 1.00 | 0.00 |
| `paraphrase_draft` | 8 | 1.00 | 0.00 |
| `paraphrase_memory` | 10 | 1.00 | 0.00 |
| `precedence` | 6 | 1.00 | 0.00 |
| `revise` | 14 | 1.00 | 0.00 |
| `short_imperative` | 8 | 1.00 | 0.00 |
| `short_message` | 6 | 1.00 | 0.00 |

### Etiket bazında

| Etiket | P | R | F1 | Destek |
|---|---|---|---|---|
| `<abstain>` | 1.00 | 1.00 | 1.00 | 8 |
| `analyze` | 1.00 | 0.81 | 0.90 | 27 |
| `assist` | 0.93 | 0.96 | 0.94 | 67 |
| `draft` | 1.00 | 0.87 | 0.93 | 46 |
| `revise` | 1.00 | 1.00 | 1.00 | 16 |

### Başarısız vakalar (14)

| ID | Kategori | Mesaj | Beklenen | Gözlenen | Kaynak |
|---|---|---|---|---|---|
| `held_01` | `heldout_paraphrase` | Bu belgeye karşılık verecek bir şeyler yazsana. | `draft` | `<abstain>` | `clarify` |
| `held_02` | `heldout_paraphrase` | Şu evraka dönüş yapacak bir metin çıkaralım. | `draft` | `<abstain>` | `clarify` |
| `held_03` | `heldout_paraphrase` | Bunun cevabını sen yazar mısın? | `draft` | `assist` | `fused` |
| `held_04` | `heldout_paraphrase` | İlgili makama sunulmak üzere bir yazı ihzar et. | `draft` | `<abstain>` | `clarify` |
| `held_05` | `heldout_paraphrase` | Şu belgeye bir göz atıp durumu anlatır mısın? | `analyze` | `assist` | `fused` |
| `held_06` | `heldout_paraphrase` | Bu evrakta bir sorun var mı acaba? | `analyze` | `assist` | `fused` |
| `held_08` | `heldout_paraphrase` | Belgenin durumunu bir çıkar bakalım. | `analyze` | `<abstain>` | `clarify` |
| `held_12` | `heldout_paraphrase` | Sen ne tür işler görebiliyorsun? | `assist` | `<abstain>` | `clarify` |
| `held_13` | `heldout_paraphrase` | Buradaki akış nasıl ilerliyor tam olarak? | `assist` | `<abstain>` | `clarify` |
| `held_15` | `heldout_paraphrase` | Şu ana kadar neler geçti aramızda? | `assist` | `<abstain>` | `clarify` |
| `held_17` | `heldout_paraphrase` | Buna karşılık verecek resmi bir dönüş kurgulayalım. | `draft` | `<abstain>` | `clarify` |
| `held_18` | `heldout_paraphrase` | Bu konuda ilgili makama iletilecek bir metin oluşturalım mı? | `draft` | `<abstain>` | `clarify` |
| `held_19` | `heldout_paraphrase` | Bu belgenin sorunlu yanları var mı bakar mısın? | `analyze` | `assist` | `fused` |
| `held_20` | `heldout_paraphrase` | Bu evrakın ne tür bir yazı olduğunu sen söyle. | `analyze` | `assist` | `fused` |

### Baseline karşılaştırması

| Metrik | Baseline | Şimdi | Δ |
|---|---|---|---|
| Macro F1 | 0.8311 | 0.9539 | +0.1228 ↑ |
| Doğruluk (tüm vakalar) | 0.8250 | 0.9146 | +0.0896 ↑ |
| Eskalasyon oranı | 0.1313 | 0.0549 | -0.0764 ↓ |
| Clarify oranı | 0.0875 | 0.1037 | +0.0162 ↑ (kötü) |
| Kalibrasyon hatası | 0.2736 | 0.1127 | -0.1609 ↓ |

## Suite: `drafts`

Altın küme: `evaluation/datasets/drafts.jsonl` · Koşu: 2026-08-07T14:37:34 · Süre: 4.8 ms

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

