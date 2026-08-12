# Birim Yönlendirme API

> Görev 2 — Birim Yönlendirme (bağımsız kullanım)

---

# POST /api/v1/routing/suggest

`POST /documents/draft`'tan **bağımsız**, yalnızca bir taslak metni ve güven
skoru okuyan tek başına birim-yönlendirme uç noktası. İnsan bir taslağı elle
düzenledikten sonra, yeni bir üretim ödemeden yönlendirme kararını
tazelemek için vardır — `routing_graph` yalnızca taslak metnini ve güven
skorunu okur, hızlı katmanda çalışır.

## İstek

```json
{
  "draft": "Sayın İlgili Makam, izin talebimi arz ederim.",
  "confidence_score": 92.4,
  "document_type": "official_letter"
}
```

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `draft` | string | Evet | Yönlendirilecek taslak veya evrak metni (1-20000 karakter) |
| `confidence_score` | float | Hayır (varsayılan `100.0`) | 0-100 arası; `HUMAN_APPROVAL_SCORE_THRESHOLD` (50.0) altındaki skorlar doğrudan insan onayına yönlendirir |
| `document_type` | string | Hayır | Bağlam için evrak türü |

## Yanıt

```json
{
  "success": true,
  "data": {
    "routed_unit": "İnsan Kaynakları",
    "priority": "Normal",
    "reasoning": "Personel izin talebiyle ilgili.",
    "justification": "Personel izin talebiyle ilgili.",
    "requires_human_approval": false
  },
  "error": null,
  "meta": { "timestamp": "2026-08-01T12:00:00Z" }
}
```

Birimler artık statik değil: `GET /units` ile listelenen, yöneticilerin
(`POST`/`PATCH`/`DELETE /units`, bkz. [`units.md`](./units.md)) tanımladığı
aktif birimler arasından seçilir -- `routed_unit`, o an aktif olan birimlerden
biridir.

`routed_unit`, boş taslak, düşük güven skoru (`HUMAN_APPROVAL_SCORE_THRESHOLD`
altı, 50.0), tanımlı hiçbir aktif birim yokken, ya da bir model hatası/geçersiz
yanıtı durumunda `null` olur -- bu artık ayrı bir "İnsan Onayı Gerekli" birimi
**değil**; bunun yerine `requires_human_approval` alanı `true` olur (taslak
kalite kapısının kullandığı bayrakla aynı alan). `priority`,
`requires_human_approval` true olduğunda `"Yüksek"`, aksi halde `"Normal"`dir.

## Hata durumları

| Durum | Kod | Sebep |
|---|---|---|
| 422 | `VALIDATION_ERROR` | `draft` boş veya eksik |
| 502 | `AI_EXECUTION_ERROR` | Yönlendirme iş akışı zaman aşımına uğradı ya da hata verdi |
