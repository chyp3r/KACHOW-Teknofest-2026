# Birim Yönetimi API

> Yönlendirme yapılabilecek birimlerin (departman) yönetimi. Bu birim listesi
> artık kod içinde sabit değil; şirket yöneticileri (`ADMIN`/`MANAGER`)
> çalışma zamanında birim ekleyip/düzenleyip/silebilir, ve
> [`routing_graph`](./routing.md) her yönlendirme kararında aktif birim
> listesini veritabanından taze olarak okur.
>
> Birimler **şirket bazlı** kapsanır (bkz. `docs/api/companies.md`): her uç
> nokta kimliği doğrulanmış çağıranın kendi şirketiyle sınırlıdır, ve `name`
> benzersizliği global değil `(company_id, name)` bazındadır -- iki farklı
> şirket aynı anda bir "İnsan Kaynakları" birimi tanımlayabilir.

---

# GET /api/v1/units

Kimliği doğrulanmış çağıranın kendi şirketindeki tüm birimleri (aktif ve
pasif) listeler.

## Yanıt

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
  ],
  "error": null,
  "meta": { "timestamp": "2026-08-12T12:00:00Z" }
}
```

---

# POST /api/v1/units

Yeni bir birim oluşturur. **Admin/Manager yetkisi gerektirir.**

## İstek

```json
{
  "name": "Mali İşler",
  "description": "Ödemeler, bütçe, faturalar, maaşlar ve finansal işlemler."
}
```

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `name` | string | Evet | Şirket içinde benzersiz birim adı (1-200 karakter) |
| `description` | string | Evet | AI'nin yönlendirme kararında kullandığı açıklama (1-2000 karakter) |

`name` bu şirkette zaten mevcutsa `409 RESOURCE_CONFLICT` döner.

---

# PATCH /api/v1/units/{unit_id}

Bir birimin adını, açıklamasını veya aktiflik durumunu günceller. **Admin/Manager
yetkisi gerektirir.** Tüm alanlar opsiyoneldir (yalnızca gönderilenler
güncellenir).

```json
{
  "description": "Güncellenmiş açıklama",
  "is_active": false
}
```

`is_active: false` yapılan bir birim, yönlendirme önerilerinden hariç tutulur
(bkz. `routing.md`) ama silinmez -- geçmişte o birime yönlendirilmiş taslaklar
etkilenmez (`drafts.destination` serbest metindir, birime referans vermez).

Birim bulunamazsa `404 NOT_FOUND`, isim çakışırsa `409 RESOURCE_CONFLICT` döner.

---

# DELETE /api/v1/units/{unit_id}

Bir birimi kalıcı olarak siler. **Admin/Manager yetkisi gerektirir.** Birim
bulunamazsa `404 NOT_FOUND` döner. Bir birimi silmek yerine `is_active: false`
ile devre dışı bırakmak genellikle tercih edilir.

---

## Hata durumları

| Durum | Kod | Sebep |
|---|---|---|
| 401 | `AUTHENTICATION_ERROR` | Geçersiz/eksik jeton (mutasyon uçları) |
| 403 | `AUTHORIZATION_ERROR` | Kullanıcı ADMIN/MANAGER değil (mutasyon uçları) |
| 404 | `NOT_FOUND` | Belirtilen `unit_id` bulunamadı |
| 409 | `RESOURCE_CONFLICT` | `name` zaten kullanılıyor |
| 422 | `VALIDATION_ERROR` | `name`/`description` boş veya çok uzun |
