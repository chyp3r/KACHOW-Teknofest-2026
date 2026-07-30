# Evrak Analizi API

> Görev 1 — Evrak Sınıflandırma ve İçerik Analizi

---

# POST /api/v1/documents/analyze

Kuruma ulaşan bir evrakın ilk inceleme (ön inceleme) aşamasını yürütür.

Şartnamede istenen altı yeteneği tek çağrıda karşılar:

1. Evrakı OCR veya doğrudan metin olarak okur
2. Evrakın türünü belirler
3. Önemli bilgi unsurlarını çıkarır
4. Bulunması gereken ancak eksik olan bilgileri tespit eder
5. İlgili mevzuat hükümlerini önerir
6. Kısa ve öz bir özet üretir

---

## İstek

`multipart/form-data`

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `file` | dosya | Evet | Analiz edilecek evrak |

Desteklenen türler: `application/pdf`, `text/plain`, `application/msword`,
`image/png`, `image/jpeg`, `image/tiff`. Azami boyut 50 MB
(`MAX_FILE_SIZE_BYTES`).

Dosya türü hem uzantı hem de `content-type` üzerinden denetlenir; ikisinden biri
uygunsa istek kabul edilir.

### Örnek

```bash
curl -X POST http://localhost:8000/api/v1/documents/analyze \
  -F "file=@datasets/sample/evrak_02.pdf"
```

---

## Yanıt

Tüm uç noktalarda olduğu gibi birleşik `APIResponse` zarfı kullanılır.

```json
{
  "success": true,
  "data": {
    "file_name": "evrak_02.pdf",
    "storage_path": "uploads/9f1c....pdf",
    "extraction": {
      "extractor": "opendataloader",
      "page_count": 1,
      "char_count": 281,
      "used_ocr": false
    },
    "document_type": "official_letter",
    "document_type_label": "Resmî Yazı",
    "summary": "Personel Genel Müdürlüğünün yıllık izin talebine ilişkin yazısı.",
    "fields": {
      "sayi": null,
      "tarih": "30.07.2026",
      "konu": "Yıllık İzin Talebi Hakkında",
      "muhatap": "İLGİLİ MAKAMA",
      "gonderen_kurum": "Örnek Bakanlığı",
      "ilgi": [],
      "ekler": [],
      "imza_sahibi": "Mehmet Öztürk",
      "imza_unvani": "Genel Müdür",
      "gizlilik_derecesi": null,
      "ivedilik": null,
      "basvuran_adi": null,
      "adres": null,
      "iletisim": null
    },
    "missing_fields": [
      {
        "key": "sayi",
        "label": "Sayı",
        "severity": "zorunlu",
        "mevzuat": "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik m.11",
        "reason": "Belgelerde sayı bulunması zorunludur; belge takibi ve atıf sayı üzerinden yapılır."
      }
    ],
    "compliance_status": "incomplete",
    "mevzuat_references": [
      {
        "mevzuat": "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik m.11",
        "aciklama": "Belgede sayı bulunmadığı için bu hüküm karşılanmamıştır."
      }
    ]
  },
  "error": null,
  "meta": { "timestamp": "2026-07-30T12:00:00Z", "response_time_ms": 51230.5 }
}
```

### Alan açıklamaları

| Alan | Açıklama |
|---|---|
| `extraction.extractor` | Metni çıkaran bileşen: `plain_text`, `opendataloader`, `pdfium` veya `tesseract` |
| `extraction.used_ocr` | `true` ise metin OCR ile okunmuştur ve alan değerleri kullanıcıya doğrulatılmalıdır |
| `document_type` | `DocumentType` enum değeri (gelen evrak türü) |
| `compliance_status` | `compliant`, `partially_compliant` veya `incomplete` |
| `missing_fields[].severity` | `zorunlu` veya `onerilen` |
| `missing_fields[].mevzuat` | Alanı gerektiren mevzuat ve madde atfı |

`compliance_status` şu şekilde belirlenir: eksik `zorunlu` alan varsa
`incomplete`, yalnızca `onerilen` alan eksikse `partially_compliant`, hiçbiri
eksik değilse `compliant`.

---

## Hata durumları

| Durum | Kod | Sebep |
|---|---|---|
| 422 | `VALIDATION_ERROR` | Dosya yok, boş, çok büyük, desteklenmeyen tür veya metin çıkarılamadı |
| 502 | `AI_EXECUTION_ERROR` | Analiz iş akışı hata verdi veya zaman aşımına uğradı |

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Desteklenmeyen dosya türü.",
    "details": { "file_name": "evrak.exe", "content_type": "application/octet-stream" }
  },
  "meta": { "timestamp": "2026-07-30T12:00:00Z" }
}
```

---

## Davranış notları

**Eksik bilgi tespiti deterministiktir.** Eksik alan denetimi dil modeli ile
değil, evrak türüne göre anahtarlanmış Python kural tablosu ile yapılır
(`app/ai/compliance/field_rule.py`). Aynı girdi için sonuç her çalıştırmada
birebir aynıdır ve madde numaraları sabit metinden gelir; model tarafından
üretilmez.

**Mevzuat önerileri korpusa bağlıdır.** Öneriler `datasets/mevzuat/` altındaki
metinlerden getirilen alıntılara dayanır. Dense (Qdrant) arama için korpusun
önceden indekslenmesi gerekir:

```bash
python scripts/index_mevzuat.py
```

Qdrant çalışmıyorsa hibrit arama sessizce yalnızca BM25'e düşer; bu durumda
öneriler üretilmeye devam eder ancak isabet kalitesi düşer.

**OCR yolu.** Born-digital PDF'ler `opendataloader-pdf` ile okunur (Java 11+
gerektirir). Java yoksa `pypdfium2` yedeği devreye girer. Taranmış PDF veya
fotoğraflanmış evrak, 300 DPI'a rasterize edilip Tesseract Türkçe dil paketi
(`tur`) ile okunur.

**Kimlik doğrulama.** Bu uç nokta şu aşamada kimlik doğrulaması istemez.
Korumaya alınması için `Depends(get_current_user)` bağımlılığının eklenmesi
yeterlidir.

**Kalıcılık.** Bu aşamada veritabanı kaydı tutulmaz; yalnızca ham evrak
`BaseStorage` üzerinde saklanır ve `storage_path` ile döndürülür.
