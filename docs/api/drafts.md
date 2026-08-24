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

#### 422 Unprocessable Entity
`VALIDATION_ERROR`: `storage_path` geçersiz veya evrak okunamadı.

#### 502 Bad Gateway
`AI_EXECUTION_ERROR`: İş akışı (Workflow) zaman aşımına uğradı veya LLM yanıt vermedi.
