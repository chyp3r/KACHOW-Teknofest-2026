# Root Konsolu API

> Sistem geneli, tek bir şirkete kapsanmamış okumalar -- `X-Company-Scope`
> anahtar değiştirme başlığı (planın §1.1'i) bu fazda **uygulanmadı**;
> aşağıdaki uçların hiçbiri bir şirkete "geçiş yapmayı" gerektirmiyor,
> hepsi zaten şirketler arası toplam/rollup döndürüyor. Tüm uçlar **yalnızca
> Root**.
>
> `app.domains.companies.root_repository.RootRepository`, `app.domains.
> analytics.repository.AnalyticsRepository`'den kasıtlı olarak ayrı bir
> modül: biri her sorguda `company_id` filtreler, diğeri hiçbirinde
> filtrelemez. Aynı dosyaya "isteğe bağlı `company_id=None`" eklemek yerine
> fiziksel olarak ayrı tutulması, unutulmuş bir filtrenin şirketler arası
> veri sızdırmasını yapısal olarak imkânsız kılıyor.

---

# GET /api/v1/root/overview

Sistem geneli sayaçlar: toplam şirket, kullanıcı, evrak, taslak; run
durumu dağılımı ve hata oranı.

```json
{
  "success": true,
  "data": {
    "total_companies": 3,
    "total_users": 42,
    "total_documents": 128,
    "total_drafts": 340,
    "run_status": { "completed": 300, "running": 5, "failed": 2 },
    "total_runs": 307,
    "error_rate": 0.0065
  }
}
```

---

# GET /api/v1/root/companies/stats

Şirket bazlı rollup: kimlik + kullanıcı/evrak/taslak sayıları.

```json
{
  "success": true,
  "data": [
    { "company_id": "c1...", "name": "Demo Kurum", "slug": "demo", "is_active": true,
      "user_count": 12, "document_count": 40, "draft_count": 95 }
  ]
}
```

---

# GET /api/v1/root/users/stats

Rol dağılımı, 7/30 günlük aktif kullanıcı sayısı, şirket bazlı koltuk
(seat) sayısı.

```json
{
  "success": true,
  "data": {
    "by_role": { "admin": 3, "manager": 5, "employee": 34 },
    "active_7d": 18,
    "active_30d": 25,
    "seats_by_company": [ { "company_id": "c1...", "name": "Demo Kurum", "user_count": 12 } ]
  }
}
```

"Aktif" -- `GET /companies/{id}/analytics/summary`'nin
`active_users_7d`'siyle aynı dürüst vekil sinyal: en az bir `runs`
satırı, izlenen bir giriş zaman damgası değil (bkz. `docs/api/
analytics.md`).

---

# GET /api/v1/root/health

`GET /health?deep=true`'nun tam bağımlılık probu (Postgres/Redis/Qdrant/
Ollama/checkpointer/router-semantic), artı şirket bazlı son aktivite --
düz sağlık ucunun bir kiracı kavramı yok, bu yüzden "hangi kiracı
durgunlaşmış görünüyor" sorusunu cevaplayamıyor.

```json
{
  "success": true,
  "data": {
    "status": "healthy",
    "dependencies": { "postgres": "ok", "redis": "ok", "qdrant": "ok", "ollama": "ok" },
    "checkpointer": "ok",
    "router_semantic": "ok",
    "companies_last_activity": { "c1...": "2026-08-14T09:15:00Z", "c2...": null }
  }
}
```

`companies_last_activity`'de bir şirketin değeri `null` ise o şirkette
henüz hiç `runs` satırı yok (yeni oluşturulmuş, ya da hiç kullanılmamış).

---

## Hata durumları

| Durum | Kod | Sebep |
|---|---|---|
| 401 | `AUTHENTICATION_ERROR` | Geçersiz/eksik jeton |
| 403 | `AUTHORIZATION_ERROR` | Root dışında bir rol |

## İlgili

- `docs/api/analytics.md` -- aynı şeklin şirket-bazlı görünümü.
- `docs/architecture/backend.md` -- "Denetim Kaydı, Analitik ve Kotalar (Faz 6)".
