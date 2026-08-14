# Denetim Kaydı (Audit Log) API

> Hash zincirli, kurcalamaya dayanıklı denetim kaydı. Her satırın
> `hash`'i bir önceki satırın `hash`'ine bağlıdır (`hash = sha256(prev_hash
> || canonical_json(satır))`) -- bir satırı sonradan değiştirmek veya
> silmek, ondan sonraki her satırın zincirini kırar. `GET /audit/verify`
> bunu doğrular.
>
> Kapsam **dürüsttür, her istek değil**: yalnızca durum-değiştiren idari
> eylemler kaydedilir -- yetki ver/geri al, şirket oluştur/güncelle/sil/
> admin-ata, birim oluştur/güncelle/sil, taslak paylaşım gönder/kabul/
> reddet/geri-çek, evrak havuzu push. Kayıt, diğer recorder'lar gibi
> **best-effort** -- bir denetim kaydı yazma hatası, asıl idari eylemi
> asla engellemez veya geri almaz.

---

# GET /api/v1/audit

Denetim kayıtlarını en yeniden eskiye listeler.

**Root**: `company_id` query parametresiyle herhangi bir şirket, ya da
boş bırakılırsa **sistem geneli her satır** (her şirket + root'un kendi
sistem-geneli eylemleri).
**Admin**: her zaman kendi şirketi -- `company_id` parametresi ne
gönderilirse gönderilsin yok sayılır (bir admin'in başka bir şirketin
denetim kaydını sorgulayabileceği tek nokta burası olurdu, bu yüzden hiç
güvenilmiyor).

## Sorgu Parametreleri

| Alan | Zorunlu | Açıklama |
|---|---|---|
| `company_id` | Hayır | Yalnızca Root için etkili |
| `actor_user_id` | Hayır | Eylemi yapan kullanıcıya göre filtre |
| `action` | Hayır | Örn. `"unit:create"`, `"permission:grant"` |
| `resource_type` | Hayır | Örn. `"unit"`, `"company"`, `"permission_grant"` |

## Yanıt

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "a1...",
        "company_id": "c1...",
        "seq": 42,
        "actor_user_id": "u1...",
        "actor_role": "admin",
        "acting_as_company_id": null,
        "action": "unit:create",
        "resource_type": "unit",
        "resource_id": "b1...",
        "decision": "permit",
        "reason": null,
        "before": null,
        "after": { "name": "Mali İşler" },
        "correlation_id": null,
        "created_at": "2026-08-14T12:00:00Z"
      }
    ],
    "total": 1, "page": 1, "size": 20, "pages": 1
  },
  "error": null,
  "meta": { "timestamp": "2026-08-14T12:00:00Z" }
}
```

---

# GET /api/v1/audit/verify

Bir zinciri baştan sona yürür, her satırın hash'ini kendi alanlarından
yeniden hesaplar ve bir öncekinin gerçek hash'iyle karşılaştırır.

**Root**: `company_id` verilirse o şirketin zinciri; boş bırakılırsa
root'un kendi **sistem geneli** (`company_id IS NULL`) zinciri -- `GET
/audit`'in aksine burada "boş = her şey" anlamına gelmez, çünkü `seq`/
`prev_hash` sürekliliği yalnızca **tek bir** zincir içinde tanımlıdır.
**Admin**: her zaman kendi şirketinin zinciri.

## Yanıt

```json
{
  "success": true,
  "data": { "valid": true, "rows_checked": 42, "broken_at_seq": null, "reason": null }
}
```

Zincir bozulmuşsa:

```json
{
  "success": true,
  "data": {
    "valid": false,
    "rows_checked": 15,
    "broken_at_seq": 15,
    "reason": "satırın hash'i kendi alanlarından yeniden hesaplananla eşleşmiyor"
  }
}
```

---

## Hata durumları

| Durum | Kod | Sebep |
|---|---|---|
| 401 | `AUTHENTICATION_ERROR` | Geçersiz/eksik jeton |
| 403 | `AUTHORIZATION_ERROR` | Root/Admin dışında bir rol |

## İlgili

- `docs/architecture/backend.md` -- "Denetim Kaydı, Analitik ve Kotalar
  (Faz 6)" bölümü, hash formülü ve `seq` hesaplamasının `NULL`-güvenli
  olma gerekçesi.
