# Sohbet ve Orkestrasyon API

> Görev 3 — Ana orkestrasyon, canlı ilerleme akışı (SSE) ve HITL (Human-in-the-Loop)

Kullanıcının mesajı ve varsa eklediği belge, deterministik planlayıcı
(`planner.py`) tarafından dört sabit akıştan (`chat`, `document_qa`, `analyze`,
`draft`) birine yönlendirilir. Ayrıntı için `docs/architecture/ai.md`.

---

# POST /api/v1/chat/message

Senkron: orkestrasyonu çalıştırır ve tamamlanmış (veya kesintiye uğramış)
sonucu döndürür.

## İstek

```json
{ "message": "Muhatap satırını Ankara Valiliği olarak değiştir", "session_id": "s-123", "draft_id": "a41f..." }
```

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `message` | string | Evet | 1-8000 karakter |
| `session_id` | string | Hayır | 1-128 karakter, `^[A-Za-z0-9:_-]+$`. Belirtilmezse sunucu bir tane üretir (`anon:<uuid>`) ve ilk `session` olayında/response'da geri döner. LangGraph checkpointer'ında `thread_id` olarak kullanılır — hem konuşma geçmişini hem de bekleyen bir HITL kesintisini bu kimlik üzerinden taşır |
| `document_id` | string | Hayır | Belge soru-cevap/taslak akışları için önceden yüklenmiş bir evrağın `storage_path`'i |
| `draft_id` | string | Hayır | Revize edilecek kayıtlı taslağın kimliği. Yetkili kullanıcının seçtiği sürümü oturumun aktif taslak bağlamına yükler |
| `reasoning_level` | string | Hayır | `fast` \| `balanced` \| `deep`; varsayılan `balanced` |

`document_id` ve `draft_id` birbirini dışlar; aynı istekte ikisi birlikte
gönderilirse `422 VALIDATION_ERROR` döner. `draft_id` için `draft:update`
yetkisi aranır. Çalışan yalnızca kendi taslağını, yönetici roller ise aynı
şirket içindeki yetkili taslakları revizyon bağlamına alabilir.
`session_id` taşımayan doğrudan-API taslakları ilk revizyon mesajında bu
sohbet oturumuna bağlanır; kaydedilen sonuç ayrı bir v1 yerine seçilen
taslağın bir sonraki sürümü olur.

## Yanıt

```json
{
  "success": true,
  "data": {
    "reply": "Resmî yazı taslağınız hazırlandı.\n\n...",
    "workflow_status": "COMPLETED",
    "session_id": "s-123",
    "details": { "status": "COMPLETED", "classification": {...}, "draft": {...}, "routing": {...} }
  }
}
```

`workflow_status` değerlerinden biri: `COMPLETED`, `FAILED`, veya çalışma bir
HITL kapısında durduysa **`INTERRUPTED`** — bu durumda `reply` sabit bir
Türkçe uyarı metnidir ve gerçek soru/onay talebi `details.interrupt` altında
taşınır. Bir oturum zaten kesintideyken bu uç noktaya (ya da `/chat/stream`'e)
yeni bir mesaj göndermek 502 `AI_EXECUTION_ERROR` döner — devam etmek için
`/chat/resume*` kullanılmalıdır.

---

# POST /api/v1/chat/stream

Aynı orkestrasyonu **Server-Sent Events** üzerinden canlı ilerlemeyle
yürütür. IP başına dakikada 20 istekle sınırlıdır. `text/event-stream`,
her satır `data: <json>\n\n`, akış `data: [DONE]\n\n` ile kapanır.

## Olay Sözlüğü

`app/ai/workflows/event_schema.py`'de tek noktadan tanımlanır
(`WORKFLOW_EVENT_NAMES`); frontend'in elle yazılmış TypeScript union'ı
`tests/unit/ai/test_event_contract.py` ile bu kümeye karşı doğrulanır.

| Olay | Ne zaman | Önemli alanlar |
|---|---|---|
| `session` | Akışın ilk olayı | `thread_id` — sonraki `/chat/resume` çağrılarında kullanılır |
| `node_start` | Bir düğüm çalışmaya başladığında | `node`, `label`, `message`, `meta` (örn. taslak revizyonunda `{"attempt": 2}`) |
| `node_end` | Bir düğüm tamamlandığında | `node`, `result` (düğümün ürettiği veri) |
| `node_error` | Bir düğüm başarısız/deraze olduğunda | `fatal` (false ise akış devam eder — örn. yargıç zaman aşımı), `detail` |
| `node_skipped` | Bir adım, başarısız bir bağımlılık yüzünden hiç çalıştırılmadığında | `reason` (Türkçe açıklama) |
| `token` | Taslak/sohbet/belge-soru-cevap metni üretilirken | `node`, `text` (bir parça) |
| `partial_result` | Nihai sonuçtan önce gösterilebilecek ara veri | `key` (örn. `"classification"`), `value` |
| `planning_completed` | Plan çözüldükten hemen sonra | `plan_steps`, `intent`, `reasoning` |
| `interrupt` | Akış bir HITL kapısında durduğunda | `kind` (`missing_information` \| `writing_brief` \| `artifact_transfer_confirm` \| `artifact_transfer_disambiguate`), `interrupt_id`, `payload` |
| `final_result` | Akış normal tamamlandığında | `reply`, `workflow_status`, `details` |
| `error` | Akış beklenmedik biçimde başarısız olduğunda | `message`, `details` |

Her olay bir `seq` (kuyruk başına monotonik sayaç) taşır. Bu, `interrupt`
olayının **tekrar yayınlanma** ihtimaline karşı istemci tarafı tekilleştirme
içindir: `interrupt()` bulunduğu düğümü resume'da baştan çalıştırır, bu
yüzden aynı `interrupt_id` iki kez gelebilir — istemci `seq`'e göre
sıralayıp tekrarı görmezden gelmelidir.

Bir taslak revizyonu (`revise → writer`) aynı `"draft"` düğüm id'si altında
ikinci kez token yayar; istemci her `node_start`'ta o düğümün önceki
`streamingText`'ini temizlemelidir, aksi halde iki deneme görsel olarak
birleşir.

---

# HITL: Kesinti / Devam

## POST /api/v1/chat/resume

Bir HITL kapısında duran çalışmayı devam ettirir, sonucu yine SSE olarak
akıtır (aynı olay sözlüğü). Dakikada 30 istekle sınırlıdır.

## POST /api/v1/chat/resume/sync

Aynı devam işlemini senkron çalıştırır; tamamlanmış (veya tekrar kesintiye
uğramış) `ChatMessageResponse`'u döndürür.

### İstek (`ChatResumeRequest`)

```json
{ "session_id": "s-123", "action": "answer", "answers": { "muhatap": "İlgili Makama" }, "instructions": "" }
```

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `session_id` | string | Evet | Devam ettirilecek oturumun `thread_id`'si |
| `action` | string | Evet | `answer` \| `approve` \| `revise` \| `reject` |
| `answers` | object | `action=answer` için | `InfoQuestion.key → kullanıcı cevabı` eşlemesi |
| `instructions` | string | `action=revise` için | En fazla 4000 karakter; onarım promptuna eklenen ek talimat |

Sistemde ayrı bir "taslak onayı" kapısı **yoktur** — düşük skorlu veya
tahmine dayalı türde bir taslak, kullanıcıya sorulmadan doğrudan
teslim edilir (skor/`requires_human_approval` alanı yalnızca dahili
denetim/loglama içindir). Bir kesinti yalnızca gerçekten eksik bir alan
(`missing_information`), yazım briefi (`writing_brief`) veya bir transfer
onayı (`artifact_transfer_confirm`/`_disambiguate`) için oluşur.

### Eylemler

- **`answer`** — eksik bilgi ya da yazım briefi kesintisini çözer. `missing_information` için yer tutucular `apply_answers()` ile **taslak yeniden üretilmeden** doldurulur; ardından yalnızca deterministik doğrulayıcı tekrar çalışır. Bazı cevaplar boş bırakılırsa kalan sorularla birlikte akış **tekrar** `NEEDS_INPUT`'a döner (aynı kesinti bir daha sorulur).
- **`revise`** — `missing_information` kesintisinde, cevap kutusuna bilgi yerine bir revizyon talimatı yazıldığında kullanılan kaçış kapısı: `instructions` alanındaki not `gate_revise` alt grafiği üzerinden **gerçek bir revizyon** üretir (aynı çalışma içinde, yeniden taslak oluşturma tetiklenmeden).
- **`reject`** — yazım briefi kesintisinde talebi tamamen iptal eder (`status=SKIPPED`); transfer kesintisinde transferi iptal eder.
- **`approve`** / **`select`** — yalnızca transfer onayı/seçimi kesintilerinde kullanılır (bkz. `artifact_transfer_confirm`/`_disambiguate`).

## GET /api/v1/chat/sessions/{session_id}/state

Bir oturumun boşta mı, çalışıyor mu, yoksa bir kesintide mi beklediğini
raporlar. Sayfa yenilemesi veya kopan bir SSE bağlantısından sonra
istemcinin kaldığı yerden devam edebilmesi içindir.

```json
{ "success": true, "data": { "status": "interrupted", "interrupt": { "kind": "missing_information", "questions": [...] } } }
```

`status`: `idle` (checkpointer yapılandırılmamışsa veya oturum bulunamazsa
da bu döner), `running`, veya `interrupted`.

---

## Notlar

- **Checkpointer olmadan** (`CHECKPOINTER_ENABLED=False` veya Postgres
  erişilemez durumda ise) HITL adımları sessizce atlanır — `human_gate`
  düğümüne hiç girilmez, akış her zamanki gibi tamamlanır (eksik bir alan
  varsa taslak `NEEDS_INPUT`/`[...]` yer tutucularıyla teslim edilir).
  Derece düşer, akış kırılmaz.
- Bu domain'in uç noktaları da `require_auth_if_enabled` arkasındadır (bkz.
  `docs/api/documents.md` — Kimlik doğrulama notu).
