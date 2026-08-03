# Deterministik Karar Katmanı Değerlendirme Raporu

> Bu rapor `make eval` ile üretilir ve **hiç LLM çağrısı içermez**.
> Ölçülen, üretim kodundaki deterministik karar fonksiyonlarının kendisidir.

## Suite: `intents`

Altın küme: `evaluation/datasets/intents.jsonl` · Koşu: 2026-08-03T09:11:49 · Süre: 0.8 ms

### Genel

| Metrik | Değer |
|---|---|
| Vaka sayısı | 114 |
| Macro F1 | 0.7289 |
| Doğruluk (tüm vakalar) | 0.6316 |
| Doğruluk (karar verilenler) | 0.7742 |
| Eskalasyon (abstention) oranı | 0.1842 |
| Kalibrasyon hatası (ECE) | 0.3011 |

### Kategori kırılımı

| Kategori | Vaka | Doğruluk | Eskalasyon |
|---|---|---|---|
| `compound` | 8 | 0.50 | 0.00 |
| `continuation` | 8 | 1.00 | 0.00 |
| `document_question` | 10 | 1.00 | 0.00 |
| `escalation` | 8 | 0.88 | 0.00 |
| `inversion` | 8 | 0.00 | 0.00 |
| `keyword_analyze` | 8 | 1.00 | 0.00 |
| `keyword_chat` | 8 | 1.00 | 0.00 |
| `keyword_draft` | 10 | 1.00 | 0.00 |
| `memory_recall` | 10 | 0.90 | 0.00 |
| `paraphrase_analyze` | 6 | 0.00 | 0.83 |
| `paraphrase_draft` | 8 | 0.12 | 0.75 |
| `paraphrase_memory` | 10 | 0.10 | 0.70 |
| `precedence` | 6 | 0.00 | 0.50 |
| `short_message` | 6 | 1.00 | 0.00 |

### Etiket bazında

| Etiket | P | R | F1 | Destek |
|---|---|---|---|---|
| `<abstain>` | 1.00 | 0.88 | 0.93 | 8 |
| `analyze` | 0.69 | 0.55 | 0.61 | 20 |
| `chat` | 1.00 | 0.54 | 0.70 | 46 |
| `document_qa` | 0.59 | 1.00 | 0.74 | 10 |
| `draft` | 0.68 | 0.63 | 0.66 | 30 |

### Başarısız vakalar (42)

| ID | Kategori | Mesaj | Beklenen | Gözlenen | Kaynak |
|---|---|---|---|---|---|
| `recall_07` | `memory_recall` | Konuşma geçmişimizi özetler misin? | `chat` | `analyze` | `keyword` |
| `inv_01` | `inversion` | Hazırladığın taslak metnini incele. | `analyze` | `draft` | `keyword` |
| `inv_02` | `inversion` | Bu taslak mevzuata uygun mu, kontrol et. | `analyze` | `draft` | `keyword` |
| `inv_03` | `inversion` | Resmi yazı ne demek, kısaca anlatır mısın? | `chat` | `draft` | `keyword` |
| `inv_04` | `inversion` | Üst yazı ile cevap yazısı arasındaki fark nedir? | `chat` | `draft` | `keyword` |
| `inv_05` | `inversion` | Taslak oluşturma süreci sistemde nasıl işliyor? | `chat` | `draft` | `keyword` |
| `inv_06` | `inversion` | Taslak hakkında ne düşünüyorsun? | `chat` | `draft` | `keyword` |
| `inv_07` | `inversion` | Bir bilgilendirme metni hangi durumlarda kullanılır? | `chat` | `draft` | `keyword` |
| `inv_08` | `inversion` | Taslak içindeki eksik alanları listeler misin? | `analyze` | `draft` | `keyword` |
| `comp_02` | `compound` | Önce evrakı değerlendir, sonra yanıt metnini üret. | `draft` | `analyze` | `keyword` |
| `comp_03` | `compound` | Bu dilekçeyi sınıflandır ve uygun bir mukabele hazırla. | `draft` | `analyze` | `keyword` |
| `comp_04` | `compound` | Evrakı özetle, ardından cevabını yazıya dök. | `draft` | `analyze` | `keyword` |
| `comp_06` | `compound` | Eksik bilgileri tespit ettikten sonra resmi cevabı düzenle. | `draft` | `analyze` | `keyword` |
| `prec_01` | `precedence` | Merhaba | `chat` | `<abstain>` | `None` |
| `prec_02` | `precedence` | Teşekkürler | `chat` | `<abstain>` | `None` |
| `prec_03` | `precedence` | İyi akşamlar, yarın devam ederiz. | `chat` | `draft` | `continuation` |
| `prec_04` | `precedence` | Sağol, çok iyi oldu. | `chat` | `<abstain>` | `None` |
| `prec_05` | `precedence` | Sen neler yapabilirsin? | `chat` | `document_qa` | `document_question` |
| `prec_06` | `precedence` | Bu sistem nasıl çalışır, kısaca anlatır mısın? | `chat` | `document_qa` | `document_question` |
| `pdraft_01` | `paraphrase_draft` | Bu evraka bir mukabele metni oluştur. | `draft` | `<abstain>` | `None` |
| `pdraft_02` | `paraphrase_draft` | Gelen yazıya karşılık bir metin tanzim et. | `draft` | `<abstain>` | `None` |
| `pdraft_03` | `paraphrase_draft` | Buna uygun bir tebligat metni düzenle. | `draft` | `<abstain>` | `None` |
| `pdraft_05` | `paraphrase_draft` | Bu başvuruya resmi bir mukabelede bulun. | `draft` | `<abstain>` | `None` |
| `pdraft_06` | `paraphrase_draft` | İlgili birime iletilecek bir tezkere düzenlemeni istiyorum. | `draft` | `<abstain>` | `None` |
| `pdraft_07` | `paraphrase_draft` | Vatandaşa dönüş yapacak bir metin kurgular mısın? | `draft` | `document_qa` | `document_question` |
| `pdraft_08` | `paraphrase_draft` | Bu konuda kuruma bildirim yapacak bir yazışma kurgula. | `draft` | `<abstain>` | `None` |
| `panalyze_01` | `paraphrase_analyze` | Bu evrakı bir gözden geçir bakalım. | `analyze` | `<abstain>` | `None` |
| `panalyze_02` | `paraphrase_analyze` | Belgedeki eksiklikleri tespit etmeni istiyorum. | `analyze` | `<abstain>` | `None` |
| `panalyze_03` | `paraphrase_analyze` | Evrakın tam olup olmadığına bir bak. | `analyze` | `<abstain>` | `None` |
| `panalyze_04` | `paraphrase_analyze` | Bu belgenin usule uygunluğunu irdele. | `analyze` | `<abstain>` | `None` |
| `panalyze_05` | `paraphrase_analyze` | Evrakı bir süz ve bulgularını raporla. | `analyze` | `<abstain>` | `None` |
| `panalyze_06` | `paraphrase_analyze` | Belgenin hangi kategoriye girdiğini tespit etmeni istiyorum. | `analyze` | `document_qa` | `document_question` |
| `precall_01` | `paraphrase_memory` | Biraz evvel sana ilettiğim konu neydi? | `chat` | `<abstain>` | `None` |
| `precall_02` | `paraphrase_memory` | Önceki turda konuştuğumuz konuyu tekrar eder misin? | `chat` | `<abstain>` | `None` |
| `precall_03` | `paraphrase_memory` | Bu diyalogda hangi konulara değindik? | `chat` | `<abstain>` | `None` |
| `precall_04` | `paraphrase_memory` | Geçen sefer hangi kurumun adını vermiştim? | `chat` | `<abstain>` | `None` |
| `precall_05` | `paraphrase_memory` | Yukarıda bahsettiğim evrak hangisiydi? | `chat` | `document_qa` | `document_question` |
| `precall_07` | `paraphrase_memory` | Demin verdiğin cevabı bir daha söyler misin? | `chat` | `<abstain>` | `None` |
| `precall_08` | `paraphrase_memory` | Buraya kadar neler konuştuğumuzu toparlar mısın? | `chat` | `<abstain>` | `None` |
| `precall_09` | `paraphrase_memory` | Sana ilettiğim ilk talebi anımsıyor musun? | `chat` | `document_qa` | `document_question` |
| `precall_10` | `paraphrase_memory` | Evvelce sorduğum soruyu tekrarlayabilir misin? | `chat` | `<abstain>` | `None` |
| `esc_06` | `escalation` | Bu belgeyle ilgili ne gerekiyorsa onu uygula. | `<abstain>` | `document_qa` | `document_question` |

## Suite: `drafts`

Altın küme: `evaluation/datasets/drafts.jsonl` · Koşu: 2026-08-03T09:11:49 · Süre: 2.2 ms

### Genel

| Metrik | Değer |
|---|---|
| Vaka sayısı | 40 |
| Doğruluk | 0.9000 |
| **Yanlış pozitif oranı** (gereksiz HITL) | **0.2353** |
| Yanlış negatif oranı (kaçan hata) | 0.0000 |
| TP / FP / TN / FN | 23 / 4 / 13 / 0 |

### Kategori kırılımı

| Kategori | Vaka | Doğruluk | YP | YN |
|---|---|---|---|---|
| `grounded` | 5 | 1.00 | 0 | 0 |
| `hallucinated` | 12 | 1.00 | 0 | 0 |
| `other_official` | 3 | 1.00 | 0 | 0 |
| `paraphrased_grounded` | 10 | 0.60 | 4 | 0 |
| `placeholder` | 4 | 1.00 | 0 | 0 |
| `structural` | 6 | 1.00 | 0 | 0 |

### Başarısız vakalar (4)

| ID | Kategori | Tür | Skor | Bulunan dayanaksız ifadeler |
|---|---|---|---|---|
| `para_01` | `paraphrased_grounded` | `false_positive` | 88.0 | tarih: 1 Mart 2026 |
| `para_03` | `paraphrased_grounded` | `false_positive` | 88.0 | mevzuat: m. 11 |
| `para_06` | `paraphrased_grounded` | `false_positive` | 88.0 | tarih: 15 Nisan 2026 |
| `para_09` | `paraphrased_grounded` | `false_positive` | 88.0 | tarih: 5 Şubat 2026 |

### Dayanaksız ifade sayımı sapmaları (9)

| ID | Kategori | Beklenen | Gözlenen |
|---|---|---|---|
| `para_01` | `paraphrased_grounded` | 0 | 1 |
| `para_03` | `paraphrased_grounded` | 0 | 1 |
| `para_06` | `paraphrased_grounded` | 0 | 1 |
| `para_09` | `paraphrased_grounded` | 0 | 1 |
| `hall_01` | `hallucinated` | 1 | 2 |
| `hall_03` | `hallucinated` | 2 | 1 |
| `hall_08` | `hallucinated` | 2 | 3 |
| `hall_10` | `hallucinated` | 2 | 1 |
| `hall_12` | `hallucinated` | 2 | 3 |

