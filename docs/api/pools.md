# Evrak Havuzu API (Document Pool API)

> Kullanıcıların kişisel evrak havuzlarının (inbox) yönetimini sağlar. Varsayılan havuz ilk yüklemede veya ilk çağrıda oluşturulur. Havuzlar arası transferler ve yetki engelleri (Clearance) yine bu katmanda yönetilir.

---

## `GET /api/v1/pools/me`

Kullanıcının kendi kişisel evrak havuzu detaylarını döner. Eğer henüz bir havuzu yoksa arka planda oluşturulup döndürülür.

**Güvenlik:** Bearer Token

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "id": "p1...",
    "owner_type": "user",
    "owner_id": "u1...",
    "name": "Kişisel Havuz",
    "is_default": true
  }
}
```

---

## `GET /api/v1/pools/{pool_id}/items`

Bir havuza atılmış evrakları, en yeniden eskiye doğru listeler.

**Güvenlik:** Bearer Token (Havuzun sahibi, Admin veya Manager olmalıdır).

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "i1...",
        "pool_id": "p1...",
        "document_id": "uploads/abc.pdf",
        "file_name": "dilekce.pdf",
        "added_by": "u2...",
        "source": "manager_push",
        "note": "lütfen incele",
        "acknowledged_at": null,
        "created_at": "2026-08-14T12:00:00Z"
      }
    ],
    "total": 1,
    "page": 1,
    "size": 20
  }
}
```

---

## `POST /api/v1/pools/{pool_id}/items`

Bir evrakı, önceden ID'si bilinen belirli bir havuza iter.

**Güvenlik:** Bearer Token (Yalnızca Admin veya Manager). Alıcının güvenlik izinleri (`Clearance`) yetersiz ise işlem reddedilir.

### İstek Gövdesi (Request Body)

```json
{
  "document_id": "uploads/abc.pdf",
  "note": "lütfen incele"
}
```

### Yanıtlar (Responses)

#### 200 OK
İşlem başarılı.

#### 403 Forbidden
Alıcının gizlilik yetkisi evrakın derecesini karşılamıyor (`PERMISSION_DENIED`).

---

## `POST /api/v1/pools/push`

Bir evrakı, birden fazla kullanıcının (veya bir birimin) kişisel havuzuna toplu olarak iter (Push). 

**Güvenlik:** Bearer Token (Yalnızca Admin veya Manager).

### İstek Gövdesi (Request Body)

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `document_id` | string | Evet | İtilecek evrakın kimliği. |
| `recipient_ids` | array[str] | Seçmeli | Kullanıcılara özel itme (En az biri olmalı). |
| `unit_id` | string | Seçmeli | Belirli birim üyelerine itme (En az biri olmalı). |
| `note` | string | Hayır | Gönderi notu. |

> **NOT:** `recipient_ids` ve `unit_id` alanlarından sadece biri kullanılmalıdır. 

### Yanıtlar (Responses)

#### 200 OK
Bu uç nokta kısmi başarıyı (Partial Success) destekler. 

```json
{
  "success": true,
  "data": [
    { "user_id": "u1...", "status": "pushed", "reason": null },
    { "user_id": "u2...", "status": "denied_clearance", "reason": "Alıcının gizlilik yetkisi bu evrak için yeterli değil." }
  ]
}
```

---

## `DELETE /api/v1/pools/{pool_id}/items/{item_id}`

Bir öğeyi havuzdan kaldırır.

**Güvenlik:** Bearer Token (Havuzun sahibi veya Admin/Manager).

#### 204 No Content
Başarıyla silindi.

---

## `POST /api/v1/pools/items/{item_id}/acknowledge`

Evrakın okunup onaylandığını (`acknowledged_at`) işaretler.

**Güvenlik:** Bearer Token (Havuzun sahibi veya Admin/Manager).

#### 200 OK
Durum başarıyla güncellendi.
