# Şirket Analitikleri API (Analytics API)

> Şirketin mevcut `documents`, `drafts`, `runs`, ve `guardrail_events` tabloları üzerinden analitik verilerini (Örn: evrak hacmi, engellenen işlemler) hesaplar. Her sorgu 60 saniyelik Redis önbelleği kullanır.

---

## `GET /api/v1/companies/{company_id}/analytics/summary`

Şirketin genel özetini; evrak/taslak hacmini, çalışma (run) durumlarını, aktif kullanıcılarını ve kota durumunu döndürür.

**Güvenlik:** Bearer Token (Root veya Şirketin kendi Admin/Manager rolü)

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `company_id` | string | Path | Evet | İlgili şirketin kimliği. |

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "company_id": "c1...",
    "document_count": 42,
    "draft_stats": {
      "total": 30,
      "avg_confidence_score": 87.5,
      "requires_human_approval": 4
    },
    "run_status": {
      "completed": 74,
      "running": 3,
      "failed": 1
    },
    "active_users_7d": 5,
    "guardrail_blocked_total": 2,
    "usage": {
      "documents": { "period": "2026-08", "used": 12, "limit": null },
      "drafts": { "period": "2026-08", "used": 8, "limit": 50 }
    }
  }
}
```

> **NOT:** `usage.limit` `null` ise o metrik sınırsızdır. Token kotaları bu sürümde desteklenmemektedir.

#### 403 Forbidden
Erişim engeli (Başka bir şirketin yetkilisi sorguladığında).

---

## `GET /api/v1/companies/{company_id}/analytics/timeseries`

Bir metriğin zaman içindeki hacmini (zaman serisi) gün veya hafta bazlı gruplanmış olarak döner.

**Güvenlik:** Bearer Token (Root veya Şirketin kendi Admin/Manager rolü)

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `company_id`| string | Path | Evet | Şirket kimliği. |
| `metric` | string | Query | Evet | `documents`, `drafts`, `runs`, `guardrail_blocks` |
| `date_from` | string | Query | Hayır | ISO8601 Tarih (Varsayılan: `date_to - 30 gün`) |
| `date_to` | string | Query | Hayır | ISO8601 Tarih (Varsayılan: `Şimdi`) |
| `bucket` | string | Query | Hayır | `day` (varsayılan) veya `week` |

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": [
    { "bucket": "2026-08-01T00:00:00+00:00", "count": 4 },
    { "bucket": "2026-08-02T00:00:00+00:00", "count": 7 }
  ]
}
```

#### 422 Unprocessable Entity
Geçersiz `metric` veya `bucket` parametresi.

---

## `GET /api/v1/companies/{company_id}/analytics/units`

Taslak hacmini, AI'ın yönlendirdiği hedef birime (`destination`) göre gruplayıp döner.

**Güvenlik:** Bearer Token (Root veya Şirketin kendi Admin/Manager rolü)

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `company_id`| string | Path | Evet | Şirket kimliği. |

### Yanıtlar (Responses)

#### 200 OK

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

## `GET /api/v1/companies/{company_id}/analytics/guardrails`

Sistem (Guardrail) engellemelerinin ve kararlarının (`stage`/`kind`/`decision`) kırılımını döner.

**Güvenlik:** Bearer Token (Root veya Şirketin kendi Admin/Manager rolü)

### Yanıtlar (Responses)

#### 200 OK

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

## `GET /api/v1/companies/{company_id}/analytics/links`

Grafana ve Langfuse gibi dış izleme sistemlerine doğrudan derin bağlantılar (Deep Link) oluşturur.

**Güvenlik:** Bearer Token (Root veya Şirketin kendi Admin/Manager rolü)

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "grafana_url": "http://localhost:3001/d/kachow-company-metrics?var-company=demo",
    "langfuse_url": "http://localhost:3000?tag=company:demo"
  }
}
```

#### 404 Not Found
`company_id` sistemde mevcut değilse.
