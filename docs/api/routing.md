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
    "justification": "Personel izin talebiyle ilgili."
  },
  "error": null,
  "meta": { "timestamp": "2026-08-01T12:00:00Z" }
}
```

`routed_unit`, `ROUTING_UNITS` listesindeki bir birim veya `"İnsan Onayı Gerekli"`
olur (boş taslak, düşük güven skoru veya bir model hatası durumunda).
`priority`, `"İnsan Onayı Gerekli"` seçildiğinde `"Yüksek"`, aksi halde
`"Normal"`dir.

## Hata durumları

| Durum | Kod | Sebep |
|---|---|---|
| 422 | `VALIDATION_ERROR` | `draft` boş veya eksik |
| 502 | `AI_EXECUTION_ERROR` | Yönlendirme iş akışı zaman aşımına uğradı ya da hata verdi |
