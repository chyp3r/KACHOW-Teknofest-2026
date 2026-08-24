# Birim Yönetimi API (Units API)

> Kurum (Şirket) içindeki departman ve birimlerin dinamik olarak yönetilmesini sağlar. Yapay Zekâ (`routing_graph`) yönlendirme önerilerinde buradaki aktif birim veritabanını kullanır. Birimler kurum içi (şirket bazlı) izole edilmiştir.

---

## `GET /api/v1/units`

Çağıranın şirketine ait tüm birimleri listeler.

**Güvenlik:** Bearer Token

### Parametreler

Yok.

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": [
    {
      "id": "b3f1...",
      "name": "Mali İşler",
      "description": "Ödemeler, bütçe, faturalar, maaşlar ve finansal işlemler.",
      "is_active": true
    }
  ]
}
```

---

## `POST /api/v1/units`

Yeni bir birim oluşturur.

**Güvenlik:** Bearer Token (`Admin` veya `Manager` yetkisi)

### İstek Gövdesi (Request Body)

`application/json`

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `name` | string | Evet | Şirket içinde benzersiz isim (1-200 karakter). |
| `description` | string | Evet | AI'nin kararı için birimin işlev açıklaması (1-2000 karakter). |

**Örnek İstek:**

```json
{
  "name": "Mali İşler",
  "description": "Ödemeler, bütçe, faturalar..."
}
```

### Yanıtlar (Responses)

#### 201 Created
Birim oluşturuldu.

#### 409 Conflict
Aynı isimde (`name`) bir birim bu şirkette zaten var.

---

## `PATCH /api/v1/units/{unit_id}`

Birimi günceller veya devre dışı bırakır (`is_active: false`).

**Güvenlik:** Bearer Token (`Admin` veya `Manager` yetkisi)

### İstek Gövdesi (Request Body)

Tüm alanlar opsiyoneldir.

```json
{
  "description": "Güncellenmiş açıklama",
  "is_active": false
}
```

#### 200 OK
Güncelleme başarılı. Devre dışı bırakılan birim AI yönlendirme önerilerinden çıkarılır.

---

## `DELETE /api/v1/units/{unit_id}`

Birimi kalıcı olarak siler. Genellikle silmek yerine `is_active: false` (PATCH) tercih edilmelidir.

**Güvenlik:** Bearer Token (`Admin` veya `Manager` yetkisi)

#### 204 No Content
Silme başarılı.

---

## `POST /api/v1/units/{unit_id}/members`

Birimi yeni bir kullanıcı ekler.

**Güvenlik:** Bearer Token (`Admin` veya `Manager` yetkisi)

### İstek Gövdesi (Request Body)

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `user_id` | string | Evet | Şirket içi kullanıcının ID'si. |
| `is_primary` | boolean| Hayır | Ana (birincil) birimi mi? (Önceki ana üyeliği siler). |
| `role_in_unit`| string | Hayır | Birim içi rol (Örn: `lead`, `manager`). |

#### 200 OK
Kullanıcı birime eklendi.

#### 409 Conflict
Kullanıcı bu birime zaten üye.

---

## `DELETE /api/v1/units/{unit_id}/members/{user_id}`

Kullanıcıyı birimden çıkarır.

**Güvenlik:** Bearer Token (`Admin` veya `Manager` yetkisi)

#### 204 No Content
Çıkarma başarılı.

---

## `GET /api/v1/units/{unit_id}/members`

Birimin üyelerini (Önce birincil, sonra lead, sonra alfabetik) listeler.

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": [
    { "user_id": "u1...", "username": "aylin", "email": "a@kurum.com", "is_primary": true, "role_in_unit": "lead" }
  ]
}
```

---

## `GET /api/v1/units/{unit_id}/suggested-recipients`

AI'nin taslak yönlendirme kararında önerdiği hedef birimin tüm üyelerini (potansiyel alıcılar) döner. Sonuç şeması `/members` ucu ile aynıdır.
