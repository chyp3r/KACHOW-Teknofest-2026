# Denetim Kaydı API (Audit Log API)

> Sistemi etkileyen idari eylemlerin hash zinciriyle korunan, kurcalamaya dayanıklı kayıtlarını sunar. Kayıt (Audit) zinciri best-effort çalışır. Her satırın hash değeri, bir önceki satıra bağımlıdır.

---

## `GET /api/v1/audit`

Denetim kayıtlarını en yeniden eskiye doğru sayfalanmış olarak listeler.

**Güvenlik:** Bearer Token 
- `Root` herhangi bir şirketin veya sistem geneli kayıtların listesini alabilir.
- `Admin` her zaman sadece **kendi şirketinin** kayıtlarını görüntüleyebilir (company_id filtresi Admin için yok sayılır).

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `company_id` | string | Query | Hayır | (Sadece Root kullanabilir) İlgili şirketin kimliği. Belirtilmezse sistemdeki tüm kayıtlar gelir. |
| `actor_user_id`| string | Query | Hayır | Eylemi gerçekleştiren kullanıcıya göre filtreler. |
| `action` | string | Query | Hayır | İşlem tipine göre filtreler (`unit:create`, `permission:grant` vb.). |
| `resource_type`| string | Query | Hayır | Kaynak tipine göre filtreler (`unit`, `company`, `permission_grant`). |
| `page` | integer| Query | Hayır | Sayfa numarası (Varsayılan: 1). |
| `size` | integer| Query | Hayır | Sayfa başına sonuç (Varsayılan: 20). |

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "a1...",
        "company_id": "c1...",
        "seq": 42,
        "actor_user_id": "u1...",
        "actor_role": "admin",
        "acting_as_company_id": null,
        "action": "unit:create",
        "resource_type": "unit",
        "resource_id": "b1...",
        "decision": "permit",
        "reason": null,
        "before": null,
        "after": { "name": "Mali İşler" },
        "correlation_id": null,
        "created_at": "2026-08-14T12:00:00Z"
      }
    ],
    "total": 1,
    "page": 1,
    "size": 20,
    "pages": 1
  },
  "error": null,
  "meta": { "timestamp": "2026-08-14T12:00:00Z" }
}
```

#### 403 Forbidden
Root veya Admin rolü dışında erişim denemesi.

---

## `GET /api/v1/audit/verify`

Kriptografik denetim zincirini baştan sona (Head to Tail) yürür, her satırın hash değerini yeniden hesaplar ve zincirin doğruluğunu/kopup kopmadığını onaylar.

**Güvenlik:** Bearer Token 
- `Root` belirli bir `company_id` girerek o şirketin veya boş bırakarak Sistem Genel zincirini kontrol eder.
- `Admin` sadece kendi şirketinin zincirini kontrol eder.

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `company_id` | string | Query | Hayır | (Sadece Root kullanabilir) Şirket zincirini kontrol etmek için. |

### Yanıtlar (Responses)

#### 200 OK (Zincir Sağlıklı)

```json
{
  "success": true,
  "data": {
    "valid": true,
    "rows_checked": 42,
    "broken_at_seq": null,
    "reason": null
  }
}
```

#### 200 OK (Zincir Bozulmuş)

Veritabanında (DB) sonradan oynama yapılmışsa zincir geçerliliğini yitirir:

```json
{
  "success": true,
  "data": {
    "valid": false,
    "rows_checked": 15,
    "broken_at_seq": 15,
    "reason": "satırın hash'i kendi alanlarından yeniden hesaplananla eşleşmiyor"
  }
}
```

#### 401 Unauthorized
Geçersiz jeton.

#### 403 Forbidden
Yetkisiz kullanıcı.
