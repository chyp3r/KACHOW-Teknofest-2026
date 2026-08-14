# Şirket Analitikleri API

> Yeni bir veri pipeline'ı değil -- mevcut `documents`/`drafts`/`runs`/
> `guardrail_events` tabloları üzerine düz SQLAlchemy toplu sorgular,
> `(company_id, metric, aralık)` başına 60 saniyelik Redis önbellek.
> Materialized view veya rollup tablosu yok (bkz.
> `docs/architecture/backend.md`).

Tüm uçlar **Root** (herhangi bir şirket), **Admin/Manager** (yalnızca
kendi şirketi) erişimine açık.

---

# GET /api/v1/companies/{company_id}/analytics/summary

Şirketin genel özeti: evrak/taslak hacmi, run durumu dağılımı, son 7
günde aktif kullanıcı sayısı, guardrail engelleme toplamı, kota kullanımı.

## Yanıt

```json
{
  "success": true,
  "data": {
    "company_id": "c1...",
    "document_count": 42,
    "draft_stats": { "total": 30, "avg_confidence_score": 87.5, "requires_human_approval": 4 },
    "run_status": { "completed": 74, "running": 3, "failed": 1 },
    "active_users_7d": 5,
    "guardrail_blocked_total": 2,
    "usage": {
      "documents": { "period": "2026-08", "used": 12, "limit": null },
      "drafts": { "period": "2026-08", "used": 8, "limit": 50 }
    }
  }
}
```

`active_users_7d`: son 7 günde en az bir `runs` satırı (bir sohbet turu)
üreten farklı kullanıcı sayısı -- bu kod tabanında henüz izlenen bir giriş
zaman damgası (`last_login_at`) olmadığından, dürüst ve mevcut olan vekil
sinyal budur.

`usage.<metrik>.limit`: `null` ise o metrik için kota tanımlı değil
(sınırsız). Yalnızca `documents`/`drafts` -- token bazlı kota bilinçli
olarak kapsam dışı (bkz. mimari doküman).

---

# GET /api/v1/companies/{company_id}/analytics/timeseries

Bir metriğin zaman içindeki hacmi, gün/hafta bazlı gruplanmış.

## Sorgu Parametreleri

| Alan | Zorunlu | Açıklama |
|---|---|---|
| `metric` | Evet | `"documents"` \| `"drafts"` \| `"runs"` \| `"guardrail_blocks"` |
| `date_from` | Hayır | Varsayılan: `date_to - 30 gün` |
| `date_to` | Hayır | Varsayılan: şimdi |
| `bucket` | Hayır | `"day"` (varsayılan) \| `"week"` |

## Yanıt

```json
{
  "success": true,
  "data": [
    { "bucket": "2026-08-01T00:00:00+00:00", "count": 4 },
    { "bucket": "2026-08-02T00:00:00+00:00", "count": 7 }
  ]
}
```

---

# GET /api/v1/companies/{company_id}/analytics/units

Taslak hacmi, AI'ın yönlendirdiği birime (`drafts.destination`) göre
gruplanmış -- birim isimlerini gerçek `units` satırlarıyla eşlemek
istemcinin işi (`GET /units` ile aynı yaklaşım,
`docs/api/units.md`'deki `suggested-recipients` ucunun izlediği desen).

```json
{
  "success": true,
  "data": [
    { "destination": "Mali İşler", "count": 12 },
    { "destination": null, "count": 3 }
  ]
}
```

---

# GET /api/v1/companies/{company_id}/analytics/guardrails

Guardrail kararlarının `stage`/`kind`/`decision` kırılımı.

```json
{
  "success": true,
  "data": [
    { "stage": "input", "kind": "sensitivity", "decision": "passed", "count": 40 },
    { "stage": "output", "kind": "pii", "decision": "redacted", "count": 2 }
  ]
}
```

---

# GET /api/v1/companies/{company_id}/analytics/links

Grafana/Langfuse'a şirket önfiltreli derin linkler.

```json
{
  "success": true,
  "data": {
    "grafana_url": "http://localhost:3001/d/kachow-company-metrics?var-company=demo",
    "langfuse_url": "http://localhost:3000?tag=company:demo"
  }
}
```

**Dürüst uyarı**: `langfuse_url`'in gerçekten bir şeyi filtrelemesi,
`compose.yml`'in çalıştırdığı `langfuse/langfuse:2` sunucusunun `langfuse`
Python bağımlılığının v4 SDK'sıyla uyumlu olmasına bağlı -- bu ikisinin
uyuşmadığı önceki fazlardan beri biliniyor (bkz. mimari doküman). Grafana
linki koşulsuz çalışır.

---

## Hata durumları

| Durum | Kod | Sebep |
|---|---|---|
| 401 | `AUTHENTICATION_ERROR` | Geçersiz/eksik jeton |
| 403 | `AUTHORIZATION_ERROR` | Rol yetersiz, ya da başka bir şirket (Admin/Manager için) |
| 404 | `NOT_FOUND` | `company_id` bulunamadı (`/links`) |
| 422 | `VALIDATION_ERROR` | Bilinmeyen `metric`/`bucket` (`/timeseries`) |

## İlgili

- `docs/api/root.md` -- aynı verinin şirketler arası toplamı.
- `docs/architecture/backend.md` -- "Denetim Kaydı, Analitik ve Kotalar (Faz 6)".
