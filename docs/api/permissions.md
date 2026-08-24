# Yetki Yönetimi (ABAC) API

> Role-Based Access Control (RBAC) yetkilerinin üzerine, spesifik kullanıcılara geçici veya kalıcı yetkiler vermek (veya kısıtlamak) için kullanılır. Yalnızca Şirket Yöneticileri (Admin/Manager) bu sistemi kullanarak kendi çalışanlarına yetki atayabilir.

---

## `POST /api/v1/users/{user_id}/permissions`

Kullanıcıya özel bir yetki (`permit`) veya kısıtlama (`deny`) kuralı tanımlar.

**Güvenlik:** Bearer Token (Kendi şirketindeki `Admin` veya `Manager` rolü). Yükseltilmiş yetki devri engellenir (Yönetici sahip olmadığı bir yetkiyi başkasına veremez).

### İstek Gövdesi (Request Body)

`application/json`

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `action` | string | Evet | Etki alanı (Örn: `document:delete`, `draft:send`, `unit:manage`). |
| `resource_type` | string | Evet | Kaynak türü (Örn: `document`, `draft`, `unit`, `*`). |
| `resource_selector` | object | Hayır | `{"any": true}`, `{"owner": "self"}`, `{"id": "..."}`. |
| `effect` | string | Hayır | `permit` veya `deny`. |
| `priority` | integer | Hayır | Rakip izinlerde öncelik sırası (Varsayılan: 0). |
| `valid_from` | datetime | Hayır | Geçerlilik başlangıcı. |
| `valid_until` | datetime | Hayır | Geçerlilik bitişi (Geçici yetkiler için). |
| `reason` | string | Hayır | Atama nedeni (Denetim kaydı için). |

**Örnek İstek:**

```json
{
  "action": "document:delete",
  "resource_type": "document",
  "resource_selector": { "owner": "self" },
  "effect": "permit",
  "priority": 0,
  "valid_until": "2026-08-14T12:00:00Z",
  "reason": "Geçici devir"
}
```

### Yanıtlar (Responses)

#### 201 Created
Yetki başarıyla oluşturuldu.

#### 403 Forbidden
`PERMISSION_DENIED`: Yönetici, kendisinde olmayan bir yetkiyi devretmeye çalışıyor.

#### 422 Unprocessable Entity
Tanımsız (Bilinmeyen) bir `action` gönderildi.

---

## `GET /api/v1/users/{user_id}/permissions`

Kullanıcıya özel atanmış, henüz geri alınmamış açık (ABAC) yetkilerini listeler.

**Güvenlik:** Bearer Token (`Admin` veya `Manager`)

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": [
    {
      "id": "g1...",
      "company_id": "c1...",
      "subject_type": "user",
      "subject_id": "u1...",
      "action": "document:delete",
      "resource_type": "document",
      "effect": "permit",
      "priority": 0,
      "valid_until": "2026-08-14T12:00:00Z",
      "granted_by": "admin-1",
      "reason": "Geçici devir",
      "created_at": "2026-08-13T12:00:00Z"
    }
  ]
}
```

---

## `DELETE /api/v1/users/permissions/{grant_id}`

Tanımlanmış bir özel yetkiyi geri alır (Revoke). Satır fiziksel silinmez, sadece `revoked_at` zaman damgası eklenerek etkisizleştirilir.

**Güvenlik:** Bearer Token (`Admin` veya `Manager`)

### Yanıtlar (Responses)

#### 204 No Content
Yetki başarıyla geri alındı.

#### 404 Not Found
Yetki bulunamadı veya çoktan geri alınmış.
