# Evrak Havuzu (Document Pool) API

> Şartnamedeki "yönetici, evrakı çalışanın evrak havuzuna gönderir" ve
> "her çalışanın kendi evrak havuzu" maddelerinin karşılığı. Her kullanıcının
> kişisel varsayılan havuzu, ilk evrak yüklemesinde (veya ilk `GET /pools/me`
> çağrısında) tembel oluşturulur -- ayrı bir kurulum adımı gerekmez.
>
> Havuzlar **şirket bazlı** kapsanır ve Postgres Row-Level Security ile
> korunur (bkz. `docs/architecture/backend.md`).

---

# GET /api/v1/pools/me

Çağıranın kendi kişisel evrak havuzunu döner (yoksa oluşturur).

## Yanıt

```json
{
  "success": true,
  "data": { "id": "p1...", "owner_type": "user", "owner_id": "u1...", "name": "Kişisel Havuz", "is_default": true },
  "error": null,
  "meta": { "timestamp": "2026-08-14T12:00:00Z" }
}
```

---

# GET /api/v1/pools/{pool_id}/items

Bir havuzdaki evrakları, en yeniden eskiye sıralı listeler. **Havuzun
sahibi, veya Admin/Manager/Root (şirket geneli).**

## Yanıt

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
    "total": 1, "page": 1, "size": 20, "pages": 1
  },
  "error": null,
  "meta": { "timestamp": "2026-08-14T12:00:00Z" }
}
```

`source`: `"upload"` (sahibinin kendi yüklediği evrak, otomatik) |
`"manager_push"` (bir yönetici tarafından itildi) | `"share"` (ayrılmış,
henüz kullanılmıyor).

---

# POST /api/v1/pools/{pool_id}/items

Bir evrakı doğrudan, önceden bilinen bir havuza iter. **Admin/Manager
yetkisi gerektirir.**

## İstek

```json
{ "document_id": "uploads/abc.pdf", "note": "lütfen incele" }
```

Havuzun sahibi bir kullanıcıysa (`owner_type: "user"`), o kullanıcının
gizlilik yetkisi evrakın gizlilik derecesini karşılamıyorsa
`403 PERMISSION_DENIED` döner -- bkz. aşağıdaki "Gizlilik kontrolü".

---

# POST /api/v1/pools/push

Bir evrakı birden fazla alıcının (veya bir birimin tüm üyelerinin) kişisel
havuzuna toplu iter. **Admin/Manager yetkisi gerektirir.**

## İstek

```json
{
  "document_id": "uploads/abc.pdf",
  "recipient_ids": ["u1...", "u2..."],
  "note": "lütfen inceleyin"
}
```

veya

```json
{ "document_id": "uploads/abc.pdf", "unit_id": "b1...", "note": "birime duyuru" }
```

`recipient_ids` ve `unit_id` alanlarından **tam olarak biri** verilmelidir.

## Yanıt

Her alıcı için ayrı bir sonuç -- kısmi başarı desteklenir, tek bir
alıcının reddi diğerlerini engellemez:

```json
{
  "success": true,
  "data": [
    { "user_id": "u1...", "status": "pushed", "reason": null },
    { "user_id": "u2...", "status": "denied_clearance", "reason": "Alıcının gizlilik yetkisi bu evrak için yeterli değil." }
  ],
  "error": null,
  "meta": { "timestamp": "2026-08-14T12:00:00Z" }
}
```

`status`: `"pushed"` | `"denied_clearance"` | `"not_found"` (alıcı ID'si
şirkette bulunamadı).

### Gizlilik kontrolü

Her alıcı **ayrı ayrı** değerlendirilir (`app.core.permissions.role_checker.
assert_clearance`): `gizli` bir evrakı `hizmete_ozel` yetkili bir çalışanın
havuzuna itmek o alıcı için sessizce izin verilmez, `denied_clearance`
olarak raporlanır -- beş kişiye gönderilen bir evrakın dördü görebiliyorsa
gönderim kısmen başarılı olur, tamamı reddedilmez.

---

# DELETE /api/v1/pools/{pool_id}/items/{item_id}

Bir öğeyi havuzdan kaldırır. **Havuzun sahibi, veya Admin/Manager/Root.**

---

# POST /api/v1/pools/items/{item_id}/acknowledge

Bir öğeyi okundu/onaylandı olarak işaretler (`acknowledged_at` set edilir).
**Havuzun sahibi, veya Admin/Manager/Root.**

---

## Hata durumları

| Durum | Kod | Sebep |
|---|---|---|
| 401 | `AUTHENTICATION_ERROR` | Geçersiz/eksik jeton |
| 403 | `AUTHORIZATION_ERROR` | Havuza erişim izni yok, veya rol yetersiz (mutasyon uçları) |
| 404 | `NOT_FOUND` | `pool_id`/`item_id`/`document_id` bulunamadı |
| 422 | `VALIDATION_ERROR` | `recipient_ids`/`unit_id` ikisi de veya hiçbiri verilmemiş |

## İlgili

- `docs/api/units.md` -- `GET /units/{id}/suggested-recipients`, AI'nin
  yönlendirdiği birimin üyeleri.
- `docs/architecture/backend.md` -- Postgres RLS ve kiracı izolasyonu.
