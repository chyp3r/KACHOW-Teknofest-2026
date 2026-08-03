# Deterministik Karar Katmanı Değerlendirme Raporu

> Bu rapor `make eval` ile üretilir ve **hiç LLM çağrısı içermez**.
> Ölçülen, üretim kodundaki deterministik karar fonksiyonlarının kendisidir.

Policy sürümü: `1.1.0`

## Suite: `intents`

Altın küme: `evaluation/datasets/intents.jsonl` · Koşu: 2026-08-03T10:55:05 · Süre: 1.9 ms

### Genel

| Metrik | Değer |
|---|---|
| Vaka sayısı | 130 |
| Macro F1 | 0.9326 |
| Doğruluk (tüm vakalar) | 0.9077 |
| Doğruluk (karar verilenler) | 0.9593 |
| Eskalasyon (abstention) oranı | 0.0538 |
| Kalibrasyon hatası (ECE) | 0.1057 |

### Kategori kırılımı

| Kategori | Vaka | Doğruluk | Eskalasyon |
|---|---|---|---|
| `compound` | 8 | 1.00 | 0.00 |
| `continuation` | 8 | 1.00 | 0.00 |
| `document_question` | 10 | 1.00 | 0.00 |
| `escalation` | 8 | 1.00 | 0.00 |
| `heldout_paraphrase` | 16 | 0.25 | 0.44 |
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
| `analyze` | 1.00 | 0.83 | 0.91 | 24 |
| `chat` | 0.98 | 0.92 | 0.95 | 51 |
| `document_qa` | 0.76 | 1.00 | 0.87 | 13 |
| `draft` | 1.00 | 0.88 | 0.94 | 34 |

### Başarısız vakalar (12)

| ID | Kategori | Mesaj | Beklenen | Gözlenen | Kaynak |
|---|---|---|---|---|---|
| `held_01` | `heldout_paraphrase` | Bu belgeye karşılık verecek bir şeyler yazsana. | `draft` | `<abstain>` | `None` |
| `held_02` | `heldout_paraphrase` | Şu evraka dönüş yapacak bir metin çıkaralım. | `draft` | `<abstain>` | `None` |
| `held_03` | `heldout_paraphrase` | Bunun cevabını sen yazar mısın? | `draft` | `document_qa` | `scored` |
| `held_04` | `heldout_paraphrase` | İlgili makama sunulmak üzere bir yazı ihzar et. | `draft` | `<abstain>` | `None` |
| `held_05` | `heldout_paraphrase` | Şu belgeye bir göz atıp durumu anlatır mısın? | `analyze` | `chat` | `scored` |
| `held_06` | `heldout_paraphrase` | Bu evrakta bir sorun var mı acaba? | `analyze` | `document_qa` | `scored` |
| `held_07` | `heldout_paraphrase` | Bu yazının kurallara uyup uymadığını söyler misin? | `analyze` | `document_qa` | `scored` |
| `held_08` | `heldout_paraphrase` | Belgenin durumunu bir çıkar bakalım. | `analyze` | `<abstain>` | `None` |
| `held_12` | `heldout_paraphrase` | Sen ne tür işler görebiliyorsun? | `chat` | `<abstain>` | `None` |
| `held_13` | `heldout_paraphrase` | Buradaki akış nasıl ilerliyor tam olarak? | `chat` | `<abstain>` | `None` |
| `held_15` | `heldout_paraphrase` | Şu ana kadar neler geçti aramızda? | `chat` | `<abstain>` | `None` |
| `held_16` | `heldout_paraphrase` | Bir evvelki turda bana ne iletmiştin? | `chat` | `document_qa` | `scored` |

### Baseline karşılaştırması

| Metrik | Baseline | Şimdi | Δ |
|---|---|---|---|
| Macro F1 | 0.7289 | 0.9326 | +0.2037 ↑ |
| Doğruluk (tüm vakalar) | 0.6316 | 0.9077 | +0.2761 ↑ |
| Eskalasyon oranı | 0.1842 | 0.0538 | -0.1304 ↓ |
| Kalibrasyon hatası | 0.3011 | 0.1057 | -0.1954 ↓ |

## Suite: `drafts`

Altın küme: `evaluation/datasets/drafts.jsonl` · Koşu: 2026-08-03T10:55:05 · Süre: 4.8 ms

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

