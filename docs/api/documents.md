# Evrak Analizi API (Documents API)

> Kuruma ulaşan bir evrakın ilk inceleme (ön inceleme) aşamasını yürütür. OCR/Metin Okuma, Sınıflandırma, Veri Çıkarımı, Eksik Bilgi Tespiti, Mevzuat Eşleştirme ve Özetleme işlemlerini gerçekleştirir. Ayrıca evrak tabanlı Bilgi Grafiği (Knowledge Graph) yetenekleri sunar.

---

## `POST /api/v1/documents/analyze`

Bir evrakın analizini gerçekleştirir.

**Güvenlik:** Bearer Token (Kimlik doğrulama ayarı açıksa). Dakikada 10 istek kotası (Rate Limit) uygulanır.

### İstek Gövdesi (Request Body)

`multipart/form-data`

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `file` | file | Evet | Desteklenen dosya türleri: `application/pdf`, `text/plain`, `application/msword`, `image/png`, `image/jpeg`, `image/tiff`. Azami boyut 50 MB. |

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "file_name": "evrak_02.pdf",
    "storage_path": "uploads/9f1c.pdf",
    "analysis_id": "uploads/9f1c.pdf",
    "extraction": {
      "extractor": "opendataloader",
      "page_count": 1,
      "char_count": 281,
      "used_ocr": false,
      "scrubbed_markers": []
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
        "reason": "Belgelerde sayı bulunması zorunludur."
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

> **Açıklama:** 
> - `compliance_status`: `compliant` (tam uyumlu), `partially_compliant` (önerilen alanlar eksik), `incomplete` (zorunlu alanlar eksik).
> - Analiz işlemi henüz veritabanına kaydedilmez. Sonuçlar `storage_path` id'si ile önbellekte (JSON) tutulur.

#### 422 Unprocessable Entity
Desteklenmeyen dosya türü, boş dosya veya 50 MB sınır aşımı.

#### 502 Bad Gateway
Yapay Zekâ iş akışı hata verdi.

---

## `GET /api/v1/documents`

Yüklenen evrakları sayfalanmış özet metadata ile listeler. 

**Güvenlik:** Bearer Token

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `page` | integer | Query | Hayır | Sayfa numarası. |
| `size` | integer | Query | Hayır | Sayfa boyutu. |

### Yanıtlar (Responses)
#### 200 OK
Sayfalanmış liste (`items`, `total`, `page`, `size`, `pages`) döner.

---

## `GET /api/v1/documents/{storage_path}`

Belirtilen evrakın önbelleğe alınmış **tam** analiz sonucunu döndürür (`missing_fields` ve `mevzuat_references` dahil).

**Güvenlik:** Bearer Token

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `storage_path`| string | Path | Evet | Analiz kimliği (`uploads/<uuid>.pdf`). |

### Yanıtlar (Responses)
#### 200 OK
`/documents/analyze` ucuyla aynı json şemasını döner.

#### 404 Not Found
Evrak analizi önbellekte yok.

---

## `GET /api/v1/documents/correspondence-types`

Desteklenen çıktı yazışma türlerini (`cover_letter`, `response_letter`, `information_notice`, `other_official`) ve Türkçe etiketlerini listeler.

### Yanıtlar (Responses)
#### 200 OK
Tip-Etiket sözlüğü döner.

---

## `POST /api/v1/documents/draft`

Resmî Yazı Taslaklama (Drafting). Lütfen detaylar için `docs/api/drafts.md` dosyasına bakınız.

---

## `GET /api/v1/documents/graph`

Mevzuat Haritası (Knowledge Graph). Çağıranın görebildiği evraklar üzerinden (Maks 200 evrak) hesaplanan evrak, kurum, mevzuat ve kanun ilişkilerini döner.
Hesaplama `GET` isteği atıldıkça yapılır. Redis önbelleği 60 saniye boyunca (Kullanıcı yetkisine -Clearance- bağlı olarak) saklanır.

**Güvenlik:** Bearer Token. Dakikada 30 istek kotası uygulanır.

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "nodes": [
      {
        "id": "doc:uploads/9f1c.pdf",
        "node_type": "document",
        "label": "evrak_02.pdf",
        "compliance_status": "incomplete"
      },
      {
        "id": "madde:2646:17",
        "node_type": "madde",
        "label": "m.17",
        "kanun": "2646",
        "madde": "17"
      },
      {
        "id": "entity:turkiye buyuk millet meclisi baskanligi",
        "node_type": "entity",
        "label": "TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA",
        "entity_kind": "kurum"
      }
    ],
    "edges": [
      {
        "source": "doc:uploads/9f1c.pdf",
        "target": "madde:2646:17",
        "edge_type": "ihlal",
        "source_kind": "rule"
      }
    ],
    "insights": {
      "document_count": 9,
      "madde_count": 6,
      "kanun_count": 1,
      "entity_count": 38,
      "rule_edge_count": 122,
      "llm_edge_count": 163
    },
    "truncated": false,
    "total_document_count": 9,
    "hidden_document_count": 0
  }
}
```

> **NOT:** Kurum (Entity) düğümleri, `muhatap`, `gonderen_kurum` ve `entities[]` alanlarından alınan verilerin OCR gürültüleri ayıklanıp, Türkçe eklerinden arındırılarak bulanık eşleştirmeyle birleştirilmesi sonucu üretilir. 

---

## `GET /api/v1/documents/{storage_path}/graph`

Tek bir evrakın (ve komşularının) bilgi grafiğini döner. Önbellek kullanılmaz, o an analizden türetilir. Veri şeması `/graph` ile tamamen aynıdır, ancak `insights` bölümündeki `truncated` veya `hidden_document_count` alanlarını barındırmaz.

**Güvenlik:** Bearer Token

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `storage_path`| string | Path | Evet | Analiz kimliği (`uploads/<uuid>.pdf`). |

### Yanıtlar (Responses)
#### 200 OK
Tekil evrak grafiği döner.

#### 404 Not Found
Evrak analizi önbellekte yok veya erişim izni (Clearance) yok.
