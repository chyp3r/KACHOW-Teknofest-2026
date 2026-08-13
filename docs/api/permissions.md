# Yetki Yönetimi (ABAC) API

> Rol bazlı taban yetkilerin üzerine, tek tek kullanıcılara ek/kısıtlı yetki
> devretmek için (bkz. `docs/architecture/backend.md` -- "ABAC Yetkilendirme
> Motoru"). Bu uç noktalar yalnızca **Şirket Admini** ve **Şirket Yöneticisi**
> tarafından kullanılabilir; her ikisi de yalnızca kendi şirketinin
> kullanıcılarına yetki verebilir/geri alabilir.
>
> Bu, rol atamasının (`PATCH /users/{id}` ile) yerini almaz -- rol taban
> yetkileri belirler (`app.core.authz.rules.BUILTIN_RULES`), bu uçlar o
> tabanın üzerine ince ayarlı, geri alınabilir, isteğe bağlı süreli istisnalar
> ekler.

---

# POST /api/v1/users/{user_id}/permissions

Bir kullanıcıya açık bir yetki (`permit`) veya kısıtlama (`deny`) tanımlar.
**Admin/Manager, yalnızca kendi şirketindeki kullanıcılara.**

## İstek

```json
{
  "action": "document:delete",
  "resource_type": "document",
  "resource_selector": { "owner": "self" },
  "effect": "permit",
  "priority": 0,
  "valid_until": "2026-08-14T12:00:00Z",
  "reason": "Geçici devir -- izinli olduğu süre boyunca ekibinin evraklarını yönetebilsin"
}
```

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `action` | string | Evet | `app.core.authz.attributes.Action` sabitlerinden biri (örn. `document:read`, `draft:send`, `unit:manage`) |
| `resource_type` | string | Evet | `"document"`, `"draft"`, `"unit"`, ... veya `"*"` |
| `resource_selector` | object | Hayır | `{"any": true}` \| `{"owner": "self"}` (varsayılan) \| `{"id": "<resource_id>"}` |
| `effect` | string | Hayır | `"permit"` (varsayılan) veya `"deny"` -- açık `deny` her zaman kazanır |
| `priority` | int | Hayır | Rakip `permit` yetkileri arasında en yüksek olan kazanır (varsayılan 0) |
| `valid_from` / `valid_until` | datetime | Hayır | Süreli yetki / break-glass için. Boş bırakılırsa kalıcıdır |
| `reason` | string | Hayır | Denetim amaçlı gerekçe (azami 500 karakter) |

**Ayrıcalık yükseltmesi (privilege escalation) engellenir**: devreden kişi
`action`'ı kendi kimliğiyle de gerçekleştiremiyorsa istek
`403 PERMISSION_DENIED` ile reddedilir -- bir yönetici, sahip olmadığı bir
yetkiyi başka birine devredemez.

Hedef kullanıcı çağıranın şirketinde değilse `404 NOT_FOUND` döner. Tanımsız
bir `action` değeri `422 VALIDATION_ERROR` döner.

---

# GET /api/v1/users/{user_id}/permissions

Bir kullanıcıya açıkça tanımlanmış (rol bazlı olmayan), henüz geri
alınmamış yetkileri listeler. **Admin/Manager, kendi şirketi.**

## Yanıt

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
      "resource_selector": { "owner": "self" },
      "effect": "permit",
      "priority": 0,
      "valid_from": null,
      "valid_until": "2026-08-14T12:00:00Z",
      "granted_by": "admin-1",
      "revoked_at": null,
      "reason": "Geçici devir",
      "created_at": "2026-08-13T12:00:00Z"
    }
  ],
  "error": null,
  "meta": { "timestamp": "2026-08-13T12:00:00Z" }
}
```

---

# DELETE /api/v1/users/permissions/{grant_id}

Bir yetkiyi geri alır. **Admin/Manager, kendi şirketi.** Satır silinmez,
`revoked_at` ile işaretlenir -- kendi denetim izini taşır. Yetki
bulunamazsa veya zaten geri alınmışsa `404 NOT_FOUND` döner.

---

## İlgili

- `docs/architecture/backend.md` -- "ABAC Yetkilendirme Motoru": karar
  algoritması (kiracı kapısı → açık deny → en yüksek öncelikli permit →
  yerleşik kurallar → örtük red), Redis epoch-tabanlı önbellek.
- `docs/api/units.md` / `docs/api/companies.md` -- rol bazlı taban yetkiler
  bu uçlardan bağımsız olarak zaten geçerlidir; buradaki yetkiler yalnızca
  o tabanın *üzerine* eklenir.
