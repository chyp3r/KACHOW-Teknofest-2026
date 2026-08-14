# Taslak Dağıtımı (Draft Delivery) API

> Şartnamedeki "çalışanlar arası taslak gönder/al, gelen kutusu" maddesinin
> karşılığı. Bir taslağın belirli bir **versiyonu**, bir veya birden fazla
> alıcıya gönderilir; ayrı bir gelen/giden kutusu tablosu yok -- gelen kutusu
> `recipient_id = ben`, giden kutusu `sender_id = ben`, ikisi de aynı
> `draft_shares` tablosunun farklı filtreli görünümü.
>
> Paylaşımlar **şirket bazlı** kapsanır ve Postgres Row-Level Security ile
> korunur (bkz. `docs/architecture/backend.md`).

---

# POST /api/v1/drafts/{draft_id}/send

Bir taslak versiyonunu bir veya birden fazla alıcıya gönderir.

`Action.DRAFT_SEND` ile yetkilendirilir: bir çalışan yalnızca **kendi**
taslağını gönderebilir, Admin/Manager/Root şirket geneli herhangi bir
taslağı gönderebilir.

## İstek

```json
{
  "recipient_ids": ["u1...", "u2..."],
  "message": "lütfen incele"
}
```

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `recipient_ids` | string[] | Evet (en az 1) | Alıcı kullanıcı ID'leri, çağıranın kendi şirketinde olmalı |
| `message` | string | Hayır | Gönderene eşlik eden not (maks. 2000 karakter) |

Alıcılardan biri şirkette bulunamazsa **tüm istek** `404 NOT_FOUND` ile
reddedilir (havuz itmenin aksine, kısmi başarı yok -- bkz. aşağıdaki not).

## Yanıt

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
      "status": "sent",
      "responded_at": null,
      "response_note": null,
      "created_at": "2026-08-14T12:00:00Z",
      "content": null,
      "correspondence_type": null,
      "destination": null
    }
  ],
  "error": null,
  "meta": { "timestamp": "2026-08-14T12:00:00Z" }
}
```

Bir alıcı için bir satır -- her biri kendi `draft_shares` ID'siyle.
`suggested_unit_id`, taslağın `destination` alanından (AI'ın routing
kararı) anlık kopyalanır; eşleşen birim yoksa (ya da taslağın hiç routing
kararı yoksa) sessizce `NULL` kalır.

### Neden kısmi başarı yok (`docs/api/pools.md`'nin aksine)

`POST /pools/push`'ta bir alıcının gizlilik yetkisi yetersizse bu
**beklenen bir iş sonucu** -- kısmen başarı mantıklı. Burada "alıcı ID'si
bulunamadı" bir istemci hatası, beklenen bir iş kararı değil; o yüzden tüm
istek reddedilir.

---

# GET /api/v1/drafts/inbox

Çağıranın **aldığı** paylaşımları, en yeniden eskiye sıralı listeler.

## Sorgu parametreleri

| Alan | Tür | Açıklama |
|---|---|---|
| `status` | string | `"sent"` \| `"read"` \| `"accepted"` \| `"rejected"` \| `"withdrawn"` ile filtreler |

## Yanıt

`GET /pools/{pool_id}/items` ile aynı sayfalanmış zarf şeklinde, her öğe
yukarıdaki `POST /send` yanıtındaki gibi -- ama bu kez `content`/
`correspondence_type`/`destination` de doludur (taslağın kendisiyle
join'lenmiş), böylece alıcı ayrı bir `GET /drafts/{id}` çağrısına gerek
kalmadan neyin gönderildiğini okuyabilir.

---

# GET /api/v1/drafts/outbox

Çağıranın **gönderdiği** paylaşımları, aynı şekil ve `status` filtresiyle
listeler.

---

# POST /api/v1/drafts/shares/{share_id}/read

Bir paylaşımı `read` durumuna ilerletir. **Yalnızca alıcı.** Zaten
`accepted`/`rejected`/`withdrawn` bir paylaşımda no-op'tur (geri `read`'e
düşmez).

---

# POST /api/v1/drafts/shares/{share_id}/accept

Paylaşılan taslağı kabul eder. **Yalnızca alıcı**, ve paylaşım hâlâ
`sent`/`read` durumunda olmalı.

## İstek

```json
{ "response_note": "tamam, alındı" }
```

Kabul etmek, `DraftRepository.create_version`'ın mevcut versiyon-zincirleme
mekanizmasını kullanarak **alıcının sahip olduğu** yeni bir taslak versiyonu
fork'lar (`parent_draft_id` orijinali gösterir). Yani "kabul" yalnızca bir
durum değişikliği değil -- alıcı taslağı gerçekten devralır ve
`GET /drafts/{yeni_id}` ile kendi kopyasına erişebilir, düzenleyebilir.
Gönderene bir `draft_share_responded` bildirimi gider (bkz.
`docs/api/notifications.md`).

---

# POST /api/v1/drafts/shares/{share_id}/reject

Paylaşılan taslağı reddeder. **Yalnızca alıcı.** Hiçbir versiyon
fork'lanmaz. Aynı `{ "response_note": "..." }` gövdesi.

---

# DELETE /api/v1/drafts/shares/{share_id}

Bir paylaşımı geri çeker. **Yalnızca gönderen** (veya Admin/Manager/Root),
ve paylaşım hâlâ `sent` durumunda olmalı -- alıcı okumuş/yanıtlamışsa
geri çekilemez.

---

## Hata durumları

| Durum | Kod | Sebep |
|---|---|---|
| 401 | `AUTHENTICATION_ERROR` | Geçersiz/eksik jeton |
| 403 | `AUTHORIZATION_ERROR` | Gönderme yetkisi yok (`draft:send`), paylaşımın tarafı değil, veya paylaşım artık uygun durumda değil |
| 404 | `NOT_FOUND` | `draft_id`/`share_id`/bir `recipient_ids` girdisi bulunamadı |
| 422 | `VALIDATION_ERROR` | `recipient_ids` boş |

## İlgili

- `docs/api/notifications.md` -- her gönderim/yanıt bir bildirim üretir,
  isteğe bağlı olarak `GET /notifications/stream` ile anlık düşer.
- `docs/api/units.md` -- `GET /units/{id}/suggested-recipients`, önerilen
  alıcı seçimi için (bu uç, `suggested_unit_id`'nin kaynağı olan aynı
  routing kararını okur).
- `docs/architecture/backend.md` -- "Taslak Dağıtımı ve Bildirimler" bölümü.
