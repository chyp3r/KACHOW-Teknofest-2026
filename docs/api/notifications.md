# Bildirimler API (Notifications API)

> Gerçek zamanlı ve kalıcı bildirim işlemlerini yönetir. Her bildirim yalnızca ait olduğu kullanıcıya özeldir (Row-Level Security ile korunur). Yönetici dahil şirket geneli bildirimleri görme yetkisi yoktur.

---

## `GET /api/v1/notifications`

Kullanıcının kendi bildirimlerini en yeniden eskiye sıralı şekilde listeler.

**Güvenlik:** Bearer Token

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `unread_only` | boolean | Query | Hayır | `true` ise yalnızca okunmamış bildirimler döner (Varsayılan: `false`). |
| `page` | integer | Query | Hayır | Sayfa numarası. |
| `size` | integer | Query | Hayır | Sayfa boyutu. |

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "n1...",
        "type": "draft_shared",
        "title": "Yeni bir taslak paylaşıldı",
        "body": "aylin size bir taslak gönderdi.",
        "resource_type": "draft_share",
        "resource_id": "s1...",
        "read_at": null,
        "created_at": "2026-08-14T12:00:00Z"
      }
    ],
    "total": 1,
    "page": 1,
    "size": 20,
    "pages": 1
  }
}
```

---

## `POST /api/v1/notifications/{notification_id}/read`

Belirtilen bildirimi okundu olarak işaretler (`read_at` atanır).

**Güvenlik:** Bearer Token (Sadece bildirimin sahibi)

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `notification_id`| string | Path | Evet | Bildirim kimliği. |

### Yanıtlar (Responses)

#### 200 OK
Başarıyla işaretlendi.

#### 403 Forbidden
Başka bir kullanıcının bildirimine erişim denemesi.

---

## `POST /api/v1/notifications/read-all`

Kullanıcının tüm okunmamış bildirimlerini tek seferde okundu olarak işaretler.

**Güvenlik:** Bearer Token

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "marked_read": 3
  }
}
```

---

## `GET /api/v1/notifications/stream`

Gerçek zamanlı bildirim akışı. Server-Sent Events (SSE) teknolojisi kullanılarak anlık düşen bildirimler gönderilir. (Redis Pub/Sub entegrelidir).

**İçerik Türü (Content-Type):** `text/event-stream`

### SSE Olayları (Events)

- **`connected`**: Bağlantı kurulduğunda gönderilen ilk doğrulama.
- **`keep-alive`**: Boşta kalma süresinde bağlantıyı açık tutmak için atılan boş yorum satırları.
- **`[json-payload]`**: `GET /notifications` öğesiyle aynı yapıdaki yeni bildirim JSON'ı.

**Örnek Veri Akışı:**
```text
data: {"event": "connected"}

: keep-alive

data: {"id":"n1...", "type":"draft_shared", "title":"...", "body":"..."}
```
