# Resmî Yazı Taslaklama API (Drafting API)

> Analiz çıktısından yola çıkarak resmî bir yazı taslağı üretir, hibrit kalite kapısından geçirir ve uygun birime yönlendirme önerisi sunar.

---

## `POST /api/v1/documents/draft`

Resmî yazı taslağı oluşturur ve kalite kapısı (Reflexion) döngüsünü işletir. 

**Güvenlik:** Bearer Token

### İstek Gövdesi (Request Body)

`application/json`

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `storage_path` | string | Evet | Evrak analizinden dönen dosya yolu (`uploads/<uuid>.pdf`). |
| `classification` | object | Evet | `POST /documents/analyze` çıktısındaki dar tipli `DraftClassificationSchema` nesnesi. |
| `instructions` | string | Hayır | Kullanıcının ek yönlendirme talimatı (Maks: 4000 karakter). |
| `correspondence_type`| string | Hayır | `cover_letter`, `response_letter`, `information_notice`, `other_official`. |

**Örnek İstek:**

```json
{
  "storage_path": "uploads/9f1c.pdf",
  "classification": {
    "document_type": "official_letter",
    "document_type_label": "Resmî Yazı",
    "summary": "Personel Genel Müdürlüğünün yazısı.",
    "fields": { "tarih": "30.07.2026", "konu": "İzin" },
    "missing_fields": [],
    "mevzuat_references": []
  },
  "instructions": "Olumlu cevap yazısı hazırla.",
  "correspondence_type": "response_letter"
}
```

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "draft_id": "",
    "draft": "Sayın İlgili Makam, ...",
    "confidence_score": 92.4,
    "requires_human_approval": false,
    "attempts": 1,
    "verification": {
      "confidence_score": 100.0,
      "unsupported_claims": [],
      "missing_structure": [],
      "placeholder_count": 0
    },
    "judge": {
      "addresses_request": true,
      "register_ok": true,
      "closing_direction": "arz",
      "score": 88.0,
      "findings": []
    },
    "missing_information": [],
    "destination": "İnsan Kaynakları",
    "justification": "Personel izin talebiyle ilgili."
  }
}
```

> **NOT:** Eğer `missing_information` alanı dolu gelirse, taslak `[...]` yer tutucuları içeriyor demektir ve `destination` boş kalır. Bu durumda `/chat/resume` kullanılarak eksik bilgiler kullanıcıdan istenmelidir (HITL akışı).

## `POST /api/v1/drafts/{draft_id}/review/approve`

Yetkili kullanıcının seçili taslak sürümünü incelediğini kaydeder. İşlem
`requires_human_approval` alanını `false` yapar. Başka bulgu yoksa taslak
durumu `APPROVED` olur; `missing_information` varsa bu bulgular korunur ve
durum `NEEDS_INPUT` kalır. Taslak sahibi ile aynı kurumdaki yönetici rollerinin
`draft:update` yetkisi gerekir.

---

## `GET /api/v1/drafts/{draft_id}/export`

Taslak sürümünü indirilebilir bir belgeye dönüştürür. Diğer uçların aksine
`SuccessResponse` zarfı değil, doğrudan `attachment` olarak işaretlenmiş binary
döndürür.

| Sorgu Parametresi | Değer | Açıklama |
| :--- | :--- | :--- |
| `fmt` | `docx` \| `pdf` | Çıktı biçimi. Varsayılan `docx`. |

Yazı tipi her iki biçimde de 12 punto Times New Roman'dır; PDF'te Türkçe glif
kapsamı için Times New Roman metriğine denk bir serif TTF (Liberation Serif)
çalışma anında kaydedilir. Yetki `GET /drafts/{draft_id}` ile aynıdır (sahip
veya kurum genelinde ADMIN/MANAGER/ROOT).

- **200 OK** — `Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document` veya `application/pdf`; `Content-Disposition: attachment; filename="..."` (Türkçe adı `filename*` ile de taşır).
- **404 Not Found** — `draft_id` yok.
- **422 Unprocessable Entity** — `fmt` `docx`/`pdf` dışında.

#### 422 Unprocessable Entity
`VALIDATION_ERROR`: `storage_path` geçersiz veya evrak okunamadı.

#### 502 Bad Gateway
`AI_EXECUTION_ERROR`: İş akışı (Workflow) zaman aşımına uğradı veya LLM yanıt vermedi.
