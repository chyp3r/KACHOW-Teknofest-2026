# Bildirimler (Notifications) API

> Şartnamedeki "gerçek zamanlı bildirim" maddesinin karşılığı. Kişisel:
> her bildirim yalnızca kendi `user_id`'sine ait -- diğer havuz/taslak
> uçlarının aksine Admin/Manager/Root için şirket geneli bir görünüm yok.
>
> Bildirimler **şirket bazlı** kapsanır ve Postgres Row-Level Security ile
> korunur (bkz. `docs/architecture/backend.md`).

---

# GET /api/v1/notifications

Çağıranın kendi bildirimlerini, en yeniden eskiye sıralı listeler.

## Sorgu parametreleri

| Alan | Tür | Açıklama |
|---|---|---|
| `unread_only` | bool | `true` ise yalnızca `read_at IS NULL` olanlar (varsayılan `false`) |

## Yanıt

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
    "total": 1, "page": 1, "size": 20, "pages": 1
  },
  "error": null,
  "meta": { "timestamp": "2026-08-14T12:00:00Z" }
}
```

`type`: bugün `"draft_shared"` (birisi size bir taslak gönderdi) |
`"draft_share_responded"` (gönderdiğiniz bir taslak kabul/red edildi) --
serbest metin, kapalı bir küme olarak zorlanmıyor, yeni bir bildirim türü
migration gerektirmez.

---

# POST /api/v1/notifications/{notification_id}/read

Tek bir bildirimi okundu olarak işaretler. Yalnızca kendi bildirimi --
başka bir kullanıcının bildirim ID'sini vermek `403` döner.

---

# POST /api/v1/notifications/read-all

Çağıranın **tüm** okunmamış bildirimlerini okundu işaretler.

## Yanıt

```json
{ "success": true, "data": { "marked_read": 3 }, "error": null, "meta": {...} }
```

---

# GET /api/v1/notifications/stream

Gerçek zamanlı bildirim akışı, Server-Sent Events (SSE) üzerinden.

Bağlantı açıldığında `{"event": "connected"}` gönderilir, ardından her yeni
bildirim aynı JSON şeklinde (`GET /notifications`'ın tek bir öğesi) anlık
düşer. Bağlantı boşta kaldığında periyodik `: keep-alive` yorum satırları
gelir (proxy zaman aşımını önlemek için) -- istemci tarafında yok sayılır.

```
data: {"event": "connected"}

: keep-alive

data: {"id":"n1...","type":"draft_shared","title":"...", ...}

```

### Neden Redis pub/sub, süreç-içi olay veriyolu değil

Sistemin süreç-içi `EventBus`'ı (`app/events/event_bus.py`) tek bir uvicorn
worker'ına özeldir. Bir worker'da yayınlanan bir olay, başka bir worker'daki
bu akışa asla ulaşamaz -- çok worker'lı bir dağıtımda bildirimler sessizce
kaybolur. Bu yüzden bildirim yazımı (`NotificationService.create`) hem
`notifications` tablosuna satır yazar **hem de** Redis'e publish eder;
bu uç yalnızca o Redis kanalına abone olur. Kanal bağlantı kesilirse/kaçarsa
veri kaybı yok: satır zaten publish'ten önce yazıldı, bir sonraki
`GET /notifications` çağrısı bildirimi görür -- SSE yalnızca gecikmeyi
azaltır, doğruluğu değil.

---

## Hata durumları

| Durum | Kod | Sebep |
|---|---|---|
| 401 | `AUTHENTICATION_ERROR` | Geçersiz/eksik jeton |
| 403 | `AUTHORIZATION_ERROR` | Bildirim başka bir kullanıcıya ait |
| 404 | `NOT_FOUND` | `notification_id` bulunamadı |

## İlgili

- `docs/api/draft-shares.md` -- bildirimleri üreten iki olay
  (`draft.shared`/`draft.share_responded`).
- `docs/architecture/backend.md` -- "Taslak Dağıtımı ve Bildirimler" bölümü,
  Redis pub/sub tasarımının tam gerekçesi.
