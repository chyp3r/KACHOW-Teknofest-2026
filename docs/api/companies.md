# Şirket (Kiracı) Yönetimi API (Companies API)

> Çok kiracılı (Multi-tenant) sistemin merkezi API'sidir. Şirketler (`company`); kullanıcıları, birimleri, taslakları ve ayarları izole bir biçimde barındırır. Yeni şirket oluşturma işlemleri yalnızca `Root` tarafından yapılır.

---

## `POST /api/v1/companies`

Yeni bir şirket oluşturur.

**Güvenlik:** Bearer Token (Sadece `Root` rolü)

### İstek Gövdesi (Request Body)

`application/json`

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `name` | string | Evet | Şirket adı (1-200 karakter). |
| `slug` | string | Evet | Benzersiz, URL güvenli kısa ad (Örn: `acme-holding`). |
| `tax_number` | string | Hayır | Vergi numarası. |

**Örnek İstek:**

```json
{
  "name": "Acme Holding",
  "slug": "acme-holding",
  "tax_number": "1234567890"
}
```

### Yanıtlar (Responses)

#### 201 Created
Şirket başarıyla oluşturuldu.

#### 409 Conflict
Aynı `slug` isminde bir şirket zaten mevcut.

---

## `GET /api/v1/companies`

Tüm şirketleri sayfalanmış biçimde listeler.

**Güvenlik:** Bearer Token (Sadece `Root` rolü)

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `page` | integer | Query | Hayır | Sayfa numarası (Varsayılan: 1). |
| `size` | integer | Query | Hayır | Sayfa başı kayıt (Varsayılan: 20, Maksimum: 100). |

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "c1...",
        "name": "Acme Holding",
        "slug": "acme-holding",
        "tax_number": null,
        "is_active": true,
        "settings": {}
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

## `GET /api/v1/companies/{company_id}`

Tek bir şirketin detaylarını getirir.

**Güvenlik:** Bearer Token (`Root` veya o şirketin `Admin`'i)

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `company_id` | string | Path | Evet | Şirket kimliği. |

### Yanıtlar (Responses)

#### 200 OK
Şirket detay objesi döner.

#### 403 Forbidden
Başka bir şirketin Admin'i, yetkisi olmayan şirketi sorgularsa bu hata döner (Şirketin var olup olmadığı gizlenir).

---

## `PATCH /api/v1/companies/{company_id}`

Şirket bilgilerini veya aktiflik durumunu (`is_active`) günceller. Pasife (`is_active: false`) alınan bir şirketin kullanıcıları sisteme giriş yapamaz.

**Güvenlik:** Bearer Token (`Root` veya o şirketin `Admin`'i)

### İstek Gövdesi (Request Body)

`application/json` (Tüm alanlar opsiyoneldir)

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `name` | string | Hayır | Yeni şirket adı. |
| `tax_number` | string | Hayır | Vergi numarası. |
| `is_active` | boolean| Hayır | Şirket aktif/pasif durumu. |
| `settings` | object | Hayır | Özel konfigürasyon (Kotalar vb.). |

**Örnek İstek:**

```json
{
  "is_active": false
}
```

#### 200 OK
Şirket başarıyla güncellendi.

---

## `POST /api/v1/companies/{company_id}/admins`

Şirketin **zaten mevcut üyesi olan** bir kullanıcıyı `Admin` rolüne yükseltir.

**Güvenlik:** Bearer Token (Sadece `Root` rolü)

### İstek Gövdesi (Request Body)

`application/json`

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `user_id` | string | Evet | Admin yapılacak kullanıcının kimliği. |

### Yanıtlar (Responses)

#### 200 OK
Rol ataması başarılı.

#### 422 Unprocessable Entity
`VALIDATION_ERROR`: Kullanıcı henüz bu şirkete dahil değil veya yabancı bir şirketin üyesi. (Önce davet mekanizması işletilmelidir).

---

## `DELETE /api/v1/companies/{company_id}`

Şirketi **yumuşak siler** (Soft Delete). Şirkete bağlı diğer referans satırları (Kullanıcı, Evrak, Birim) silinmez, bütünlük korunur. Kalıcı veri temizliği kapsam dışıdır.

**Güvenlik:** Bearer Token (Sadece `Root` rolü)

### Yanıtlar (Responses)

#### 204 No Content
Şirket başarıyla silindi (`is_deleted=true`).
