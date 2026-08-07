# Deterministik Karar Katmanı Değerlendirme Raporu

> Bu rapor `make eval` ile üretilir ve **hiç LLM çağrısı içermez**.
> Ölçülen, üretim kodundaki deterministik karar fonksiyonlarının kendisidir.

Policy sürümü: `1.4.0`

## Suite: `intents`

Altın küme: `evaluation/datasets/intents.jsonl` · Koşu: 2026-08-07T09:55:47 · Süre: 47.7 ms

### Genel

| Metrik | Değer |
|---|---|
| Vaka sayısı | 160 |
| Macro F1 | 0.8311 |
| Doğruluk (tüm vakalar) | 0.8250 |
| Doğruluk (karar verilenler) | 0.9496 |
| Eskalasyon (abstention) oranı | 0.1313 |
| **Clarify oranı** (kullanıcıya soru) | **0.0875** |
| Kalibrasyon hatası (ECE) | 0.2736 |

### Kaynak dağılımı

| Kaynak | Vaka |
|---|---|
| `scored` | 101 |
| `context_default` | 15 |
| `clarify` | 14 |
| `compound` | 8 |
| `continuation` | 7 |
| `semantic` | 7 |
| `clarification_resolved` | 6 |
| `empty` | 2 |

### Kategori kırılımı

| Kategori | Vaka | Doğruluk | Eskalasyon |
|---|---|---|---|
| `clarify_resolution` | 6 | 1.00 | 0.00 |
| `compound` | 8 | 1.00 | 0.00 |
| `continuation` | 8 | 1.00 | 0.00 |
| `document_question` | 10 | 1.00 | 0.00 |
| `escalation` | 8 | 1.00 | 0.00 |
| `heldout_paraphrase` | 22 | 0.41 | 0.32 |
| `inversion` | 8 | 1.00 | 0.00 |
| `keyword_analyze` | 8 | 1.00 | 0.00 |
| `keyword_assist` | 8 | 1.00 | 0.00 |
| `keyword_draft` | 10 | 1.00 | 0.00 |
| `memory_recall` | 10 | 1.00 | 0.00 |
| `paraphrase_analyze` | 6 | 1.00 | 0.00 |
| `paraphrase_draft` | 8 | 1.00 | 0.00 |
| `paraphrase_memory` | 10 | 1.00 | 0.00 |
| `precedence` | 6 | 1.00 | 0.00 |
| `revise` | 10 | 0.30 | 0.60 |
| `short_imperative` | 8 | 0.00 | 1.00 |
| `short_message` | 6 | 1.00 | 0.00 |

### Etiket bazında

| Etiket | P | R | F1 | Destek |
|---|---|---|---|---|
| `<abstain>` | 1.00 | 1.00 | 1.00 | 8 |
| `analyze` | 0.95 | 0.78 | 0.86 | 27 |
| `assist` | 0.91 | 0.96 | 0.93 | 67 |
| `draft` | 1.00 | 0.76 | 0.86 | 46 |
| `revise` | 1.00 | 0.33 | 0.50 | 12 |

### Başarısız vakalar (28)

| ID | Kategori | Mesaj | Beklenen | Gözlenen | Kaynak |
|---|---|---|---|---|---|
| `held_03` | `heldout_paraphrase` | Bunun cevabını sen yazar mısın? | `draft` | `assist` | `scored` |
| `held_04` | `heldout_paraphrase` | İlgili makama sunulmak üzere bir yazı ihzar et. | `draft` | `<abstain>` | `context_default` |
| `held_05` | `heldout_paraphrase` | Şu belgeye bir göz atıp durumu anlatır mısın? | `analyze` | `assist` | `scored` |
| `held_06` | `heldout_paraphrase` | Bu evrakta bir sorun var mı acaba? | `analyze` | `assist` | `scored` |
| `held_07` | `heldout_paraphrase` | Bu yazının kurallara uyup uymadığını söyler misin? | `analyze` | `assist` | `semantic` |
| `held_08` | `heldout_paraphrase` | Belgenin durumunu bir çıkar bakalım. | `analyze` | `<abstain>` | `context_default` |
| `held_12` | `heldout_paraphrase` | Sen ne tür işler görebiliyorsun? | `assist` | `<abstain>` | `context_default` |
| `held_13` | `heldout_paraphrase` | Buradaki akış nasıl ilerliyor tam olarak? | `assist` | `<abstain>` | `context_default` |
| `held_15` | `heldout_paraphrase` | Şu ana kadar neler geçti aramızda? | `assist` | `<abstain>` | `context_default` |
| `revise_01` | `revise` | Bu taslağı biraz kısalt. | `revise` | `<abstain>` | `clarify` |
| `revise_02` | `revise` | Metni biraz uzat. | `revise` | `<abstain>` | `clarify` |
| `revise_03` | `revise` | Taslağı daha resmi yap. | `revise` | `<abstain>` | `clarify` |
| `revise_07` | `revise` | Yazının tonunu değiştir. | `revise` | `<abstain>` | `clarify` |
| `revise_08` | `revise` | Şu cümleyi düzeltir misin? | `revise` | `<abstain>` | `clarify` |
| `revise_09` | `revise` | Taslağı güncelle lütfen. | `revise` | `analyze` | `semantic` |
| `revise_10` | `revise` | Kapanışı değiştirir misin? | `revise` | `<abstain>` | `clarify` |
| `short_imp_01` | `short_imperative` | Cevap yaz. | `draft` | `<abstain>` | `clarify` |
| `short_imp_02` | `short_imperative` | Yazı hazırla. | `draft` | `<abstain>` | `clarify` |
| `short_imp_03` | `short_imperative` | Kaleme al. | `draft` | `<abstain>` | `clarify` |
| `short_imp_04` | `short_imperative` | Metni yaz. | `draft` | `<abstain>` | `clarify` |
| `short_imp_05` | `short_imperative` | Tanzim et. | `draft` | `<abstain>` | `clarify` |
| `short_imp_06` | `short_imperative` | Cevap hazırla. | `draft` | `<abstain>` | `clarify` |
| `short_imp_07` | `short_imperative` | Cevabı hazırla. | `draft` | `<abstain>` | `clarify` |
| `short_imp_08` | `short_imperative` | Yanıt hazırla. | `draft` | `<abstain>` | `clarify` |
| `held_18` | `heldout_paraphrase` | Bu konuda ilgili makama iletilecek bir metin oluşturalım mı? | `draft` | `<abstain>` | `context_default` |
| `held_19` | `heldout_paraphrase` | Bu belgenin sorunlu yanları var mı bakar mısın? | `analyze` | `assist` | `scored` |
| `held_20` | `heldout_paraphrase` | Bu evrakın ne tür bir yazı olduğunu sen söyle. | `analyze` | `assist` | `scored` |
| `held_21` | `heldout_paraphrase` | Yazdığın metni bir kez daha ele alır mısın? | `revise` | `<abstain>` | `context_default` |

## Suite: `drafts`

Altın küme: `evaluation/datasets/drafts.jsonl` · Koşu: 2026-08-07T09:55:47 · Süre: 4.6 ms

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

