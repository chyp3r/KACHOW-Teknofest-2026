# Root Konsolu API (Root API)

> Sistem geneli, tek bir şirkete kapsanmamış okuma ve denetim işlemlerini sağlar. Bu uç noktalar **yalnızca Root (Sistem Yöneticisi)** yetkisi gerektirir. `company_id` filtresi uygulamadan global analiz döndürür.

---

## `GET /api/v1/root/overview`

Sistem geneli toplam şirket, kullanıcı, evrak ve taslak sayaçlarını; çalışma (run) durumu dağılımını ve hata oranını döndürür.

**Güvenlik:** Bearer Token (Sadece `Root` rolü)

### Parametreler

Yok.

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "total_companies": 3,
    "total_users": 42,
    "total_documents": 128,
    "total_drafts": 340,
    "run_status": {
      "completed": 300,
      "running": 5,
      "failed": 2
    },
    "total_runs": 307,
    "error_rate": 0.0065
  }
}
```

#### 401 Unauthorized
Geçersiz veya eksik JWT jetonu.

#### 403 Forbidden
Sadece Root erişebilir. `AUTHORIZATION_ERROR`.

---

## `GET /api/v1/root/companies/stats`

Şirket (Kurum) bazlı istatistikleri (kullanıcı, evrak, taslak sayıları) toplu olarak döndürür.

**Güvenlik:** Bearer Token (Sadece `Root` rolü)

### Parametreler

Yok.

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": [
    {
      "company_id": "c1...",
      "name": "Demo Kurum",
      "slug": "demo",
      "is_active": true,
      "user_count": 12,
      "document_count": 40,
      "draft_count": 95
    }
  ]
}
```

---

## `GET /api/v1/root/users/stats`

Rol dağılımı, son 7/30 günlük aktif kullanıcı sayısını ve şirket bazlı koltuk (seat) kullanımını döndürür. Aktif kullanıcı verisi logine göre değil, yapılan işlemlere (`runs` tablosu) göre hesaplanır.

**Güvenlik:** Bearer Token (Sadece `Root` rolü)

### Parametreler

Yok.

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "by_role": {
      "admin": 3,
      "manager": 5,
      "employee": 34
    },
    "active_7d": 18,
    "active_30d": 25,
    "seats_by_company": [
      {
        "company_id": "c1...",
        "name": "Demo Kurum",
        "user_count": 12
      }
    ]
  }
}
```

---

## `GET /api/v1/root/health`

Sistemin (Postgres, Redis, Qdrant, Ollama, Checkpointer, Semantic Router) sağlık durumunu kontrol eder. Ayrıca şirketlerin sistemdeki son işlem tarihlerini döner.

**Güvenlik:** Bearer Token (Sadece `Root` rolü)

### Parametreler

Yok.

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "status": "healthy",
    "dependencies": {
      "postgres": "ok",
      "redis": "ok",
      "qdrant": "ok",
      "ollama": "ok"
    },
    "checkpointer": "ok",
    "router_semantic": "ok",
    "companies_last_activity": {
      "c1...": "2026-08-14T09:15:00Z",
      "c2...": null
    }
  }
}
```

> **NOT:** `companies_last_activity` alanında `null` dönmesi, o kurumun henüz hiç yapay zekâ veya işlem talebi yapmadığını (`runs` tablosunda kaydı olmadığını) gösterir.
