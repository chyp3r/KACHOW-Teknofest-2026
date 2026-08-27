# Sohbet ve Orkestrasyon API (Chat & Orchestration)

> Ana orkestrasyon, canlı ilerleme akışı (SSE) ve HITL (Human-in-the-Loop) işlemlerini yönetir. Planlayıcı (`planner.py`) mesajları dört akıştan birine yönlendirir.

---

## `POST /api/v1/chat/message`

Senkron: Orkestrasyonu çalıştırır ve tamamlanmış (veya kesintiye uğramış) sonucu döndürür.

**Güvenlik:** Bearer Token, `X-Company-Scope`

### İstek Gövdesi (Request Body)

`application/json`

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `message` | string | Evet | 1-8000 karakter. |
| `session_id` | string | Hayır | `^[A-Za-z0-9:_-]+$`. Belirtilmezse sunucu üretir (`anon:<uuid>`). |
| `document_id` | string | Hayır | Soru-cevap/taslak akışları için evrak `storage_path`'i. |
| `draft_id` | string | Hayır | Revize edilecek kayıtlı taslağın kimliği. |
| `reasoning_level` | string | Hayır | `fast`, `balanced`, `deep`. Varsayılan: `balanced`. |

> **NOT:** `document_id` ve `draft_id` birbirini dışlar. Aynı anda gönderilirse 422 döner.

**Örnek İstek:**

```json
{
  "message": "Muhatap satırını Ankara Valiliği olarak değiştir",
  "session_id": "s-123",
  "draft_id": "a41f..."
}
```

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "reply": "Resmî yazı taslağınız hazırlandı.\n\n...",
    "workflow_status": "COMPLETED",
    "session_id": "s-123",
    "details": {
      "status": "COMPLETED",
      "classification": {},
      "draft": {},
      "routing": {},
      "assist": {},
      "context_usage": {
        "total": 8192,
        "used": 3120,
        "free": 5072,
        "segments": [
          { "key": "system", "label": "Sistem yönergesi", "tokens": 900 },
          { "key": "history", "label": "Sohbet geçmişi", "tokens": 1150 },
          { "key": "input", "label": "Güncel mesaj", "tokens": 46 },
          { "key": "reserved", "label": "Yanıt için ayrılan", "tokens": 1024 }
        ]
      }
    }
  }
}
```

> **NOT:** `details.context_usage` yalnızca soru-cevap/sohbet (asistan) turlarında bulunur; o turun bağlam penceresini nasıl kullandığını gerçek token sayılarıyla döker (frontend'in dairesel göstergesi bunu okur). Taslak/revizyon turlarında alan gelmez.

#### 422 Unprocessable Entity
Geçersiz parametre kombinasyonu.

#### 502 Bad Gateway
`AI_EXECUTION_ERROR`: Oturum zaten kesintideyken yeni mesaj gönderildi.

---

## `POST /api/v1/chat/stream`

Aynı orkestrasyonu **Server-Sent Events (SSE)** üzerinden canlı ilerlemeyle yürütür. 
IP başına dakikada 20 istekle sınırlıdır.

**İçerik Türü (Content-Type):** `text/event-stream`

### SSE Olayları (Events)

| Olay Adı | Açıklama | Önemli Alanlar |
| :--- | :--- | :--- |
| `session` | Akışın ilk olayı. | `thread_id` |
| `node_start` | Düğüm başladığında. | `node`, `label`, `message` |
| `node_end` | Düğüm bittiğinde. | `node`, `result` |
| `token` | Doğrulanmış nihai cevap kullanıcıya aktarılırken. | `node`, `text` (cevabın bir parçası) |
| `interrupt` | HITL kapısında durduğunda. | `kind`, `interrupt_id`, `payload` |
| `final_result`| Akış normal bittiğinde. | `reply`, `workflow_status` |

`token` olayları yalnız guardrail ve doğrulama adımlarından geçmiş nihai
cevaptan üretilir; ham taslak veya ajan çıktısı kullanıcıya akıtılmaz. Parçalar
taşıma amaçlıdır ve aralarına yapay sunucu gecikmesi eklenmez. Web istemcisi
mesaj sırasını yalnız `final_result` ile günceller; yazma efekti tamamlanmış
cevabın frontend'de yerel olarak gösterilmesidir.

---

## `POST /api/v1/chat/resume`

Bir HITL (İnsan Onayı/Kesintisi) kapısında duran çalışmayı devam ettirir. Sonucu SSE (Server-Sent Events) olarak akıtır.

**Sınırlandırma (Rate Limit):** Dakikada 30 istek.

---

## `POST /api/v1/chat/resume/sync`

HITL kapısında duran çalışmayı senkron olarak devam ettirir.

### İstek Gövdesi (Request Body)

`application/json`

| Alan | Tür | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- |
| `session_id` | string | Evet | Devam ettirilecek oturumun `thread_id`'si. |
| `action` | string | Evet | `answer`, `approve`, `revise`, `reject` |
| `answers` | object | Hayır | `action=answer` için `key -> değer` eşlemesi. |
| `instructions`| string | Hayır | `action=revise` için onarım talimatı (Maks: 4000). |

**Örnek İstek:**

```json
{
  "session_id": "s-123",
  "action": "answer",
  "answers": {
    "muhatap": "İlgili Makama"
  }
}
```

### Yanıtlar (Responses)

#### 200 OK
Çalışma başarıyla devam ettirildi (Yeni `workflow_status` döner).

---

## `GET /api/v1/chat/sessions/{session_id}/state`

Oturumun (session) güncel durumunu (boşta, çalışıyor, kesintide) raporlar. SSE bağlantısı koptuğunda durumu sorgulamak içindir.

### Parametreler

| Alan | Tür | Konum | Zorunlu | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `session_id` | string | Path | Evet | Oturum kimliği. |

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "status": "interrupted",
    "interrupt": {
      "kind": "missing_information",
      "questions": []
    }
  }
}
```

---

## `POST /api/v1/chat/sessions/{session_id}/compact`

Sohbeti sıkıştırır: birebir tutulan son geçmiş turları yuvarlanan özete katlar
(son `COMPACT_KEEP_TURNS` turu birebir bırakır). Bağlam göstergesindeki "Bağlamı
sıkıştır" düğmesi çağırır ve sırasında sohbet kilitlenir. Aktif bir tur veya
bekleyen bir HITL varsa `status: "busy"` döner.

### Yanıtlar (Responses)

#### 200 OK

```json
{
  "success": true,
  "data": {
    "status": "compacted",
    "folded_turns": 8,
    "context_usage": {
      "total": 8192,
      "used": 1450,
      "free": 6742,
      "segments": [
        { "key": "system", "label": "Sistem yönergesi", "tokens": 900 },
        { "key": "history_summary", "label": "Geçmiş özeti", "tokens": 180 },
        { "key": "history", "label": "Sohbet geçmişi", "tokens": 90 },
        { "key": "reserved", "label": "Yanıt için ayrılan", "tokens": 1024 }
      ]
    }
  }
}
```

`status` değerleri: `compacted` (sıkıştırıldı) · `noop` (birebir pencere zaten
küçük) · `busy` (aktif tur/HITL) · `unavailable` (checkpointer okunamadı).
