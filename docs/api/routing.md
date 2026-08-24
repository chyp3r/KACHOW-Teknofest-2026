# Birim Yönlendirme API (Routing API)

> Yalnızca bir taslak metni ve güven skorunu analiz edip doğru birimi öneren bağımsız bir uç noktadır. İnsan düzenlemesi sonrası yönlendirmeyi "yeniden hesaplatmak" için kullanılır.

---

## `POST /api/v1/routing/suggest`

Taslak metnini baz alarak AI (Hızlı katman) aracılığıyla kurum içi birim yönlendirme önerisi çıkarır.

**Güvenlik:** Bearer Token

### İstek Gövdesi (Request Body)

`application/json`

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `draft` | string | Evet | Yönlendirilecek taslak (1-20000 karakter). |
| `confidence_score`| float | Hayır | `100.0` üzerinden skor. (Varsayılan `100.0`). |
| `document_type` | string | Hayır | Bağlam (Context) vermek amaçlı evrak türü. |

> **NOT:** `confidence_score` değeri, eşik (`HUMAN_APPROVAL_SCORE_THRESHOLD`=50.0) değerinin altında gelirse, sistem taslağı otomatik olarak İnsan Onayına (`requires_human_approval: true`) düşürür.

**Örnek İstek:**

```json
{
  "draft": "Sayın İlgili Makam, izin talebimi arz ederim.",
  "confidence_score": 92.4,
  "document_type": "official_letter"
}
```

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "routed_unit": "İnsan Kaynakları",
    "priority": "Normal",
    "reasoning": "Personel izin talebiyle ilgili.",
    "justification": "Personel izin talebiyle ilgili.",
    "requires_human_approval": false
  }
}
```

> **Açıklama:** `routed_unit`, veritabanındaki aktif birimler listesinden seçilir. Eğer boş bir taslak girilir, eşik altı skor gönderilir veya birim bulunamazsa `routed_unit` null döner.

#### 422 Unprocessable Entity
`VALIDATION_ERROR`: `draft` alanı boş veya kısıtlamalara (Maks 20000) uymuyor.

#### 502 Bad Gateway
`AI_EXECUTION_ERROR`: Yönlendirme (Routing) iş akışı LLM katmanında hata aldı veya zaman aşımına uğradı.
