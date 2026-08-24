# Taslak Dağıtımı API (Draft Delivery API)

> Çalışanlar arasında taslak gönderimi ve kabul/ret işlemlerini yönetir. Gelen ve giden kutuları, aynı `draft_shares` tablosunun filtrelenmiş görünümleridir. Row-Level Security ile korunur.

---

## `POST /api/v1/drafts/{draft_id}/send`

Taslak versiyonunu bir veya birden fazla kurum içi alıcıya gönderir.

**Güvenlik:** Bearer Token (Kullanıcı sadece **kendi** taslağını gönderebilir. Adminler kurum içi tüm taslakları gönderebilir).

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `draft_id` | string | Path | Evet | Gönderilecek taslağın ID'si. |

### İstek Gövdesi (Request Body)

`application/json`

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `recipient_ids`| array[string] | Evet | Alıcı ID'leri dizisi (En az 1). Aynı şirkette olmalıdır. |
| `message` | string | Hayır | Gönderi notu (Maks: 2000 karakter). |

**Örnek İstek:**

```json
{
  "recipient_ids": ["u1...", "u2..."],
  "message": "lütfen incele"
}
```

### Yanıtlar (Responses)

#### 200 OK
Gönderim başarılı.

```json
{
  "success": true,
  "data": [
    {
      "id": "s1...",
      "draft_id": "d1...",
      "sender_id": "u0...",
      "recipient_id": "u1...",
      "suggested_unit_id": "b1...",
      "message": "lütfen incele",
      "status": "sent"
    }
  ]
}
```

#### 403 Forbidden
Bu taslağı gönderme yetkisi yok.

#### 404 Not Found
Taslak veya `recipient_ids` içindeki bir kullanıcı bulunamadı (Kısmi başarı uygulanmaz, tamamı reddedilir).

#### 422 Unprocessable Entity
`recipient_ids` dizisi boş.

---

## `GET /api/v1/drafts/inbox`

Kullanıcının **aldığı** paylaşımları sayfalanmış biçimde döner (Gelen Kutusu).

**Güvenlik:** Bearer Token

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `status` | string | Query | Hayır | `sent`, `read`, `accepted`, `rejected`, `withdrawn` |

### Yanıtlar (Responses)

#### 200 OK
Listeleme başarılı. Ögeler taslak içeriği (`content`, `destination`) ile birlikte join edilmiş olarak döner.

---

## `GET /api/v1/drafts/outbox`

Kullanıcının **gönderdiği** paylaşımları sayfalanmış biçimde döner (Giden Kutusu). Parametreler `inbox` ile aynıdır.

---

## `POST /api/v1/drafts/shares/{share_id}/read`

Bir paylaşımın durumunu `read` (Okundu) olarak işaretler.

**Güvenlik:** Bearer Token (Yalnızca Alıcı)

### Yanıtlar (Responses)
#### 200 OK
Durum güncellendi. (Zaten okunduysa işlem atlanır).

---

## `POST /api/v1/drafts/shares/{share_id}/accept`

Paylaşılan taslağı kabul eder. Alıcı için yeni bir taslak versiyonu çatallanır (Fork).

**Güvenlik:** Bearer Token (Yalnızca Alıcı). Durum `sent` veya `read` olmalıdır.

### İstek Gövdesi (Request Body)

```json
{
  "response_note": "tamam, alındı"
}
```

### Yanıtlar (Responses)
#### 200 OK
Taslak kabul edildi ve çatallandı. Gönderene bildirim düşer.

---

## `POST /api/v1/drafts/shares/{share_id}/reject`

Paylaşılan taslağı reddeder. Versiyon fork'lanmaz.

**Güvenlik:** Bearer Token (Yalnızca Alıcı).

### İstek Gövdesi (Request Body)
Aynı `response_note` objesi.

### Yanıtlar (Responses)
#### 200 OK
Ret işlemi başarılı.

---

## `DELETE /api/v1/drafts/shares/{share_id}`

Gönderilmiş bir paylaşımı geri çeker (Withdraw). 

**Güvenlik:** Bearer Token (Yalnızca Gönderen veya Admin). Sadece `sent` durumundayken geri çekilebilir.

### Yanıtlar (Responses)
#### 204 No Content
Geri çekme işlemi başarılı.

#### 403 Forbidden
Paylaşım çoktan okunmuş veya kabul edilmiş.
