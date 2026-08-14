# Resmî Yazı Taslaklama API

> Görev 2 — Resmî Yazı Taslaklama ve Birim Yönlendirme

---

# POST /api/v1/documents/draft

Görev 1'in analiz çıktısından yola çıkarak resmî bir yazı taslağı üretir,
hibrit kalite kapısından geçirir ve (taslak tamamsa) uygun birime
yönlendirme önerisi sunar.

## İstek

```json
{
  "storage_path": "uploads/9f1c....pdf",
  "classification": {
    "document_type": "official_letter",
    "document_type_label": "Resmî Yazı",
    "summary": "Personel Genel Müdürlüğünün yıllık izin talebine ilişkin yazısı.",
    "fields": { "sayi": null, "tarih": "30.07.2026", "konu": "Yıllık İzin Talebi Hakkında", "...": "..." },
    "missing_fields": [{ "key": "sayi", "label": "Sayı", "severity": "zorunlu", "mevzuat": "...", "reason": "..." }],
    "mevzuat_references": [{ "mevzuat": "...", "aciklama": "..." }]
  },
  "instructions": "İzin talebini olumlu değerlendirdiğimizi bildiren bir cevap yazısı hazırla.",
  "correspondence_type": "response_letter"
}
```

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `storage_path` | string | Evet | `POST /documents/analyze`'ın döndürdüğü depolama anahtarı; `uploads/<uuid><uzantı>` biçimine uymalıdır |
| `classification` | object | Evet | Görev 1 analiz çıktısının dar, tipli bir kesiti (`DraftClassificationSchema`) — prompt'a doğrudan giden serbest bir `dict` değildir |
| `instructions` | string | Hayır | En fazla 4000 karakter; kullanıcının ek talimatı |
| `correspondence_type` | string | Hayır | `cover_letter` \| `response_letter` \| `information_notice` \| `other_official`. Boş bırakılırsa sınıflandırma metadata'sı → kullanıcı yönergesi → gelen belge türü sırasıyla çözülür |

---

## Yanıt

```json
{
  "success": true,
  "data": {
    "draft_id": "",
    "draft": "Sayın İlgili Makam, ...",
    "confidence_score": 92.4,
    "requires_human_approval": false,
    "attempts": 1,
    "verification": { "confidence_score": 100.0, "unsupported_claims": [], "missing_structure": [], "placeholder_count": 0 },
    "judge": { "addresses_request": true, "register_ok": true, "closing_direction": "arz", "score": 88.0, "findings": [] },
    "missing_information": [],
    "destination": "İnsan Kaynakları",
    "justification": "Personel izin talebiyle ilgili."
  },
  "error": null,
  "meta": { "timestamp": "2026-08-01T12:00:00Z" }
}
```

### Alan açıklamaları

| Alan | Açıklama |
|---|---|
| `confidence_score` | Tek, deterministik bir kural tablosundan hesaplanır (`app.ai.verification.confidence_rules`) — `100 - uygulanan ceza toplamı`. Yargıç skora katılmaz, yalnızca insan onayı kapısını açar; bkz. `applied_rules` |
| `applied_rules` | `confidence_score`'u üreten kural satırları (`rule_id`, `label`, `occurrences`, `penalty_applied`, `forces_approval`) — "bu skor neden X?" sorusunun satır satır cevabı |
| `attempts` | Kaç üretim/revizyon denemesi yapıldığı (en fazla 2: bir ilk üretim + bir revizyon) |
| `verification` | Deterministik doğrulayıcının raporu — doğrulanamayan iddialar, eksik yapısal unsurlar, yer tutucu sayısı |
| `judge` | Kalite yargıcının verdiği (varsa) yapılandırılmış değerlendirme; yargıç kullanılamadıysa boş `{}` |
| `missing_information` | **Boş değilse** taslak `[...]` yer tutucuları içeriyor demektir; birim yönlendirmesi **yapılmamıştır**. Aşağıdaki "Eksik Bilgi Akışı"na bakınız |
| `destination` / `justification` | Önerilen birim ve gerekçesi. `missing_information` doluysa `""` / "Taslak eksik bilgi içeriyor; birim yönlendirmesi yapılmadı." olur |

---

## Hibrit Kalite Kapısı ve Reflexion Döngüsü

Taslak, `draft_graph`'ın `validate_input → writer → verify → (revise → writer | end)` döngüsünden geçer (ayrıntı: `docs/architecture/ai.md`). Deterministik doğrulayıcı ve hızlı-katman LLM yargıcının birlikte yakaladığı **düzeltilebilir** kusurlar (eksik yapı, doğrulanamayan iddia, düzeltilebilir yargıç bulgusu) otomatik olarak en fazla bir kez revize edilir — `attempts=2` bunu gösterir. Kalan bir `[...]` yer tutucusu veya çözülememiş bir yazışma türü/eksik mevzuat bağlamı bu döngüye girmez, doğrudan insan aşamasına gider.

---

## Eksik Bilgi Akışı (Görev 2'nin HITL gereksinimi)

Bu uç nokta kendi başına bir devam (resume) mekanizması taşımaz — `missing_information` doluysa, aynı taslağı **yeniden üretmeden** tamamlamak için `POST /api/v1/chat/resume` kullanılır (bkz. `docs/api/chat.md`). Akış:

1. Kullanıcı sohbet üzerinden ("bu evraka cevap yazısı hazırla") veya doğrudan bu uç nokta üzerinden taslak ister.
2. Sohbet yolunda (`POST /chat/stream`), yazar bilmediği bir zorunlu bilgi için `[...]` bıraktıysa akış `human_gate` düğümünde durur ve bir `interrupt` SSE olayı yayınlanır; olay `payload.questions` altında her yer tutucu için `{key, label, why, example, required}` taşır.
3. İstemci `POST /chat/resume` ile `{"action": "answer", "answers": {"muhatap": "İlgili Makama"}}` gönderir.
4. Sunucu yer tutucuları düz metin ikamesiyle doldurur (`apply_answers`) ve yalnızca deterministik doğrulayıcıyı yeniden çalıştırır — taslak **hiçbir zaman yeniden üretilmez**.

`POST /documents/draft` doğrudan çağrıldığında bu uç nokta yalnızca `missing_information` listesini raporlar; devam etmek isteyen bir istemcinin `/chat/*` akışına geçmesi gerekir.

---

## Hata durumları

| Durum | Kod | Sebep |
|---|---|---|
| 422 | `VALIDATION_ERROR` | `storage_path` biçimsiz, evrak bulunamadı, evrak metni çıkarılamadı |
| 502 | `AI_EXECUTION_ERROR` | Taslak veya yönlendirme iş akışı zaman aşımına uğradı ya da hata verdi |
