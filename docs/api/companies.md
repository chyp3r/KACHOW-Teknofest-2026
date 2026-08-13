# Şirket (Kiracı) Yönetimi API

> Çok kiracılı sistemin kök kaynağı. Her şirket (`company`) kendi
> kullanıcılarını, birimlerini, evraklarını ve taslaklarını taşır (bkz.
> `docs/architecture/backend.md` -- "Kiracı sınırı"). Bu uç noktalar yalnızca
> **Root** ve, kendi şirketleriyle sınırlı olarak, **Şirket Admini**
> tarafından kullanılabilir; Yönetici ve Çalışan rolleri buraya erişemez.

---

# POST /api/v1/companies

Yeni bir şirket oluşturur. **Yalnızca Root.**

## İstek

```json
{
  "name": "Acme Holding",
  "slug": "acme-holding",
  "tax_number": "1234567890"
}
```

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `name` | string | Evet | Şirket adı (1-200 karakter) |
| `slug` | string | Evet | Benzersiz, URL/depolama güvenli kısa ad (küçük harf, rakam, tire) |
| `tax_number` | string | Hayır | Vergi numarası |

`slug` zaten mevcutsa `409 RESOURCE_CONFLICT` döner.

---

# GET /api/v1/companies

Tüm şirketleri sayfalı listeler. **Yalnızca Root.**

## Sorgu Parametreleri

| Parametre | Varsayılan | Açıklama |
|---|---|---|
| `page` | 1 | Sayfa numarası |
| `size` | 20 | Sayfa başına kayıt (azami 100) |

## Yanıt

```json
{
  "success": true,
  "data": {
    "items": [
      { "id": "c1...", "name": "Acme Holding", "slug": "acme-holding", "tax_number": null, "is_active": true, "settings": {} }
    ],
    "total": 1,
    "page": 1,
    "size": 20,
    "pages": 1
  },
  "error": null,
  "meta": { "timestamp": "2026-08-13T12:00:00Z" }
}
```

---

# GET /api/v1/companies/{company_id}

Tek bir şirketin detayını döner. **Root, veya o şirketin kendi Admini.**
Başka bir şirketin Admini erişmeye çalışırsa `403 PERMISSION_DENIED` döner
(kaynağın var olup olmadığını bile sızdırmaz).

---

# PATCH /api/v1/companies/{company_id}

Şirket adını, vergi numarasını, aktiflik durumunu veya `settings` alanını
günceller. **Root, veya o şirketin kendi Admini.** Tüm alanlar opsiyoneldir.

```json
{
  "is_active": false
}
```

`is_active: false` yapılan bir şirketin tüm kullanıcıları giriş yapamaz hale
gelir (bkz. `app.core.permissions.role_checker`).

---

# POST /api/v1/companies/{company_id}/admins

Şirketin **zaten üyesi olan** bir kullanıcıyı Admin rolüne yükseltir.
**Yalnızca Root.**

## İstek

```json
{ "user_id": "u1..." }
```

Kullanıcı bu şirkete ait değilse (`user.company_id != company_id`)
`422 VALIDATION_ERROR` döner -- Root, başka bir şirketten bir yabancıyı
doğrudan bu şirkete admin olarak taşıyamaz; kullanıcı önce bu şirkete davet
edilmiş/kaydolmuş olmalıdır (bkz. `docs/api/users.md`'deki davet akışı).

---

# DELETE /api/v1/companies/{company_id}

Şirketi **yumuşak siler** (`is_deleted=true`, `is_active=false`).
**Yalnızca Root.** Şirkete bağlı kullanıcı/evrak/birim satırları
silinmez -- referans bütünlüğü ve denetim geçmişi korunur; kalıcı temizlik
kapsam dışıdır (bkz. `app/domains/companies/repository.py::soft_delete`
docstring'i).

---

## İlgili

- `docs/api/units.md` -- birimler artık `(company_id, name)` bazında
  benzersizdir, bir şirketin birim listesi yalnızca o şirketin kullanıcılarına
  görünür.
- `docs/api/users.md` -- kullanıcı davet/kayıt akışı, `company_id`'nin
  davetten geldiği self-escalation koruması.
- `docs/architecture/backend.md` -- kiracı izolasyonunun repository
  katmanındaki uygulanışı ve Postgres RLS'in (sonraki faz) bu API ile ilişkisi.
