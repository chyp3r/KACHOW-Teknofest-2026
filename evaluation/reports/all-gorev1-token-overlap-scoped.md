# Deterministik Karar Katmanı Değerlendirme Raporu

> Bu rapor `make eval` ile üretilir ve **hiç LLM çağrısı içermez**.
> Ölçülen, üretim kodundaki deterministik karar fonksiyonlarının kendisidir.

Policy sürümü: `3.0.0`

## Suite: `intents`

Altın küme: `evaluation/datasets/intents.jsonl` · Koşu: 2026-08-23T21:10:30 · Süre: 124.0 ms

### Genel

| Metrik | Değer |
|---|---|
| Vaka sayısı | 173 |
| Macro F1 | 0.9520 |
| Doğruluk (tüm vakalar) | 0.9133 |
| Doğruluk (karar verilenler) | 0.9634 |
| Eskalasyon (abstention) oranı | 0.0520 |
| **Clarify oranı** (kullanıcıya soru) | **0.1098** |
| Kalibrasyon hatası (ECE) | 0.1265 |

### Kaynak dağılımı

| Kaynak | Vaka |
|---|---|
| `fused` | 140 |
| `clarify` | 19 |
| `compound` | 8 |
| `clarification_resolved` | 5 |
| `scope_deterministic` | 1 |

### Kategori kırılımı

| Kategori | Vaka | Doğruluk | Eskalasyon |
|---|---|---|---|
| `clarify_resolution` | 6 | 1.00 | 0.00 |
| `compound` | 8 | 1.00 | 0.00 |
| `continuation` | 8 | 1.00 | 0.00 |
| `document_question` | 10 | 1.00 | 0.00 |
| `escalation` | 10 | 1.00 | 0.00 |
| `farewell` | 2 | 1.00 | 0.00 |
| `greeting_mid_session` | 2 | 1.00 | 0.00 |
| `heldout_paraphrase` | 22 | 0.36 | 0.41 |
| `inversion` | 8 | 1.00 | 0.00 |
| `keyword_analyze` | 8 | 1.00 | 0.00 |
| `keyword_assist` | 8 | 1.00 | 0.00 |
| `keyword_draft` | 10 | 0.90 | 0.00 |
| `memory_recall` | 10 | 1.00 | 0.00 |
| `paraphrase_analyze` | 6 | 1.00 | 0.00 |
| `paraphrase_draft` | 8 | 1.00 | 0.00 |
| `paraphrase_memory` | 10 | 1.00 | 0.00 |
| `precedence` | 6 | 1.00 | 0.00 |
| `revise` | 17 | 1.00 | 0.00 |
| `short_imperative` | 8 | 1.00 | 0.00 |
| `short_message` | 6 | 1.00 | 0.00 |

### Etiket bazında

| Etiket | P | R | F1 | Destek |
|---|---|---|---|---|
| `<abstain>` | 1.00 | 1.00 | 1.00 | 10 |
| `analyze` | 1.00 | 0.81 | 0.90 | 27 |
| `assist` | 0.93 | 0.96 | 0.94 | 71 |
| `draft` | 1.00 | 0.85 | 0.92 | 46 |
| `revise` | 1.00 | 1.00 | 1.00 | 19 |

### Başarısız vakalar (15)

| ID | Kategori | Mesaj | Beklenen | Gözlenen | Kaynak |
|---|---|---|---|---|---|
| `draft_04` | `keyword_draft` | Bu konuda bir bilgilendirme metni hazırlamanı istiyorum. | `draft` | `refuse` | `scope_deterministic` |
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

## Suite: `drafts`

Altın küme: `evaluation/datasets/drafts.jsonl` · Koşu: 2026-08-23T21:10:30 · Süre: 9.5 ms

### Genel

| Metrik | Değer |
|---|---|
| Vaka sayısı | 43 |
| Doğruluk | 1.0000 |
| **Yanlış pozitif oranı** (gereksiz HITL) | **0.0000** |
| Yanlış negatif oranı (kaçan hata) | 0.0000 |
| TP / FP / TN / FN | 25 / 0 / 18 / 0 |

### Kategori kırılımı

| Kategori | Vaka | Doğruluk | YP | YN |
|---|---|---|---|---|
| `grounded` | 5 | 1.00 | 0 | 0 |
| `hallucinated` | 12 | 1.00 | 0 | 0 |
| `kimlik` | 3 | 1.00 | 0 | 0 |
| `other_official` | 3 | 1.00 | 0 | 0 |
| `paraphrased_grounded` | 10 | 1.00 | 0 | 0 |
| `placeholder` | 4 | 1.00 | 0 | 0 |
| `structural` | 6 | 1.00 | 0 | 0 |

### Başarısız vakalar (0)

Yok.

### Dayanaksız ifade sayımı sapmaları (0)

Yok.

## Suite: `evrak`

Altın küme: `evaluation/datasets/evrak.jsonl` · Koşu: 2026-08-23T21:10:30 · Süre: 141.8 ms

### Genel -- şartname eşlemesi

| Şartname maddesi | Metrik | Değer |
|---|---|---|
| 1 -- OCR/doğrudan metin yönlendirmesi | Doğruluk | 1.0000 |
| 3 -- bilgi unsuru çıkarma (yalnız `sentetik`) | Doğru alan oranı | 0.7571 |
| 4 -- eksik bilgi tespiti | **Yanlış alarm oranı** | **0.1148** |
| 4 -- eksik bilgi tespiti | Kaçırma oranı | 0.0000 |
| 5 -- mevzuat atfı doğrulaması | Doğruluk | 1.0000 |

Vaka sayısı: 35 · Eksik-alan (alan, belge) çifti: TP=21 FP=24 TN=185 FN=0 · Çıkarım: doğru=53 kaçan=8 yanlış=9 sahte=0 · Atıf: TP=1 FP=0 TN=2 FN=0

### Kategori kırılımı

| Kategori | Vaka | OCR yönlendirme doğruluğu | Eksik-alan yanlış alarm oranı |
|---|---|---|---|
| `gercek_tarama` | 23 | 1.00 | 0.12 |
| `sentetik` | 12 | 1.00 | 0.11 |

### Eksik-alan kümesi uyuşmayan belgeler (17)

| ID | Kategori | Beklenen eksik | Gözlenen eksik |
|---|---|---|---|
| `evrak_04` | `sentetik` | `[]` | `['basvuran_adi']` |
| `evrak_05` | `sentetik` | `['adres', 'imza_sahibi']` | `['adres', 'basvuran_adi', 'imza_sahibi']` |
| `evrak_06` | `sentetik` | `[]` | `['basvuran_adi', 'iletisim']` |
| `evrak_07` | `sentetik` | `['iletisim']` | `['basvuran_adi', 'iletisim']` |
| `evrak_08` | `sentetik` | `['tarih']` | `['basvuran_adi', 'tarih']` |
| `CY-010` | `gercek_tarama` | `['konu']` | `['gonderen_kurum', 'konu', 'muhatap']` |
| `CY-017` | `gercek_tarama` | `[]` | `['tarih']` |
| `CY-030` | `gercek_tarama` | `[]` | `['tarih']` |
| `CY-036` | `gercek_tarama` | `[]` | `['tarih']` |
| `CY-023` | `gercek_tarama` | `[]` | `['tarih']` |
| `CY-028` | `gercek_tarama` | `[]` | `['tarih']` |
| `CY-034` | `gercek_tarama` | `['konu']` | `['gonderen_kurum', 'konu', 'muhatap']` |
| `CY-002` | `gercek_tarama` | `[]` | `['gonderen_kurum', 'muhatap']` |
| `CY-011` | `gercek_tarama` | `[]` | `['gonderen_kurum', 'muhatap']` |
| `CY-033` | `gercek_tarama` | `[]` | `['gonderen_kurum', 'muhatap']` |
| `CY-050` | `gercek_tarama` | `[]` | `['gonderen_kurum', 'muhatap']` |
| `CY-049` | `gercek_tarama` | `[]` | `['tarih']` |

