# AI Mimarisi

## Amaç

Bu doküman sistemin yapay zekâ mimarisini, bileşenlerini ve çalışma prensiplerini açıklamaktadır.

AI katmanı sistemin karar verme merkezidir.

Görevleri;

* Kullanıcı isteğini analiz etmek
* Uygun iş akışını belirlemek
* Büyük Dil Modelleri (LLM) ile iletişim kurmak
* RAG süreçlerini yönetmek
* MCP araçlarını kullanmak
* Sonucu oluşturup Backend'e iletmek

AI katmanı FastAPI, HTTP veya kullanıcı arayüzünden bağımsız olarak geliştirilmektedir.

---

# Genel Yaklaşım

AI sistemi aşağıdaki prensiplere göre tasarlanmıştır.

* Agentic AI
* Workflow Driven Architecture
* Tool Calling
* Retrieval-Augmented Generation (RAG)
* Model Context Protocol (MCP)
* Stateless Workflow
* Provider Independent LLM Layer

Her AI işlemi bir iş akışı (workflow) üzerinden yürütülmektedir.

---

# AI Katmanı

AI katmanı aşağıdaki ana bileşenlerden oluşmaktadır.

```text
ai/

├── workflows/
├── agents/
├── prompts/
├── llm/
├── embeddings/
├── retrieval/
├── memory/
├── tools/
├── models/
├── parsers/
├── evaluators/
└── utils/
```

Her klasör yalnızca belirli bir sorumluluğa sahiptir.

---

# AI İstek Yaşam Döngüsü

Bir AI isteği aşağıdaki adımlardan oluşur.

```text
Backend

↓

Workflow

↓

Planner

↓

Agent

↓

Tool Selection

↓

LLM / MCP / RAG

↓

Reasoning

↓

Response Builder

↓

Backend
```

Her istek aynı yaşam döngüsünü takip eder.

---

# Workflow (LangGraph Implementations)

Sistemin iş süreçleri ile bu süreçleri yürüten teknoloji katmanları (LangGraph) birbirinden tamamen ayrılmıştır:
- **Workflow**: İş süreci (Classification, RAG, Draft, Routing, System) mantığını tanımlar.
- **Graph**: Bu süreçlerin LangGraph düğümleri (nodes) ve yönlendirmeleri (edges) ile asenkron ve döngüsel (loop) olarak çalıştırılan somut implementasyonlarıdır (`app/ai/workflows/*_graph.py`).

Tüm sistem, yöneticilik yapan 2 katman ve 5 asenkron iş akışından (workflow graph) oluşur:

---

## Yönetici Katman

### Planning Graph (`planning_graph.py`)
Sistemin tek orkestrasyon grafiğidir ve **tek checkpointer alan graf**budur (bkz. HITL bölümü). `planner.py`'deki **deterministik planlayıcı** ile gelen mesajı/eki analiz eder ve çalıştırılacak alt adımları (`classification`, `rag`, `draft`, `routing`, `chat`, `document_qa`) bir plan olarak belirler — bu artık bir LLM çağrısı değil, bildirimsel bir kanıt tablosu üzerinde marj tabanlı bir skorlamadır (`resolve_plan_deterministic`, bkz. Planner bölümü); yalnızca kanıtı gerçekten dengeli ya da yok olan mesajlar hızlı-katman modele düşer. `executor` düğümü planı adım adım yürütür ve her adımın bağımlılığı başarısız olduysa (`_STEP_DEPENDENCIES`) o adımı hiç çalıştırmadan `SKIPPED` işaretler — başarısız bir taslağın üzerine boş girdiyle yönlendirme çalıştırılması buradan engellenir.

---

## Ana Workflow Graph'ları

### 1. Document Analysis Graph (`document_analysis_graph.py`) — Görev 1
- **Node'lar**: `analyze` (sınıflandırma + alan çıkarımı tek birleşik yapılandırılmış çağrıda) → `check_compliance` ve `retrieve_mevzuat` (paralel dallar) → `suggest_mevzuat`.
- **Görev**: Gelen evrağın türünü ve `EvrakField`'in 15 alanını **tek bir** `ClassifierAgent.run_structured()` çağrısıyla çıkarır (önceden ayrı bir sınıflandırma + ayrı bir metadata ajanı vardı; birleştirme analiz bacağının süresini yarıya indirdi). Kalite katmanı hem birleşik hem de yalnız-sınıflandırma şemasında başarısız olursa, `DocumentType.OTHER`'a düşmeden önce isteğe bağlı bir hızlı-katman istemcisiyle bir kez daha denenir.
- **Eksik bilgi tespiti tamamen deterministiktir** (`check_compliance`, LLM'siz). Mevzuat taraması (`retrieve_mevzuat`) kendi `"rag"` id'si altında gerçek `node_start`/`node_end` yayar; taşınan veri (`search_query`, `documents`, `context`) hem taslak brief'inde hem de UI'daki Mevzuat panelinde doğrudan kullanılır.

### 2. RAG Graph (`rag_graph.py`) — genel soru-cevap
- **Node'lar**: `prepare_query` (deterministik `build_search_query`, model çağrısı yok) → `retrieve`.
- **Görev**: `HybridRetriever` ile Qdrant native RRF (dense+sparse) araması yapar. Sorgu yeniden yazımı için ayrı bir LLM adımı yoktur — `document_analysis_graph`'ın `_build_mevzuat_query`'siyle aynı gerekçeyle: sparse yarı literal terimleri eşleştirir, bir model parafrazı daha kötü bir sorgu üretir.

### 3. Draft Graph (`draft_graph.py`) — Görev 2, hibrit kalite kapılı reflexion döngüsü
- **Node'lar**: `validate_input → writer → verify → (revise → writer | needs_input=END | end)`.
- **Girdi**: Gelen evrakın brief'i (ham `source_document` writer'a hiç gitmez, yalnızca `_build_brief()`'in ürettiği özetlenmiş yapı gider), doğrulanmış RAG bağlamı, yazım yönergeleri ve isteğe bağlı `correspondence_type`.
- **Yazışma Türleri**: `cover_letter`, `response_letter`, `information_notice`, `other_official`. Çözümleme sırası: açık istek → sınıflandırma metadata'sı → kullanıcı yönergesi → gelen belge türünden çıkarım → `other_official` (fallback, insan incelemesi zorunlu).
- **Reflexion döngüsü**: `verify` düğümü hibrit kalite kapısını çalıştırır (aşağıya bakınız). Düzeltilebilir kusurlar (eksik yapı, doğrulanamayan iddialar, düzeltilebilir yargıç bulguları) `revise` üzerinden `writer`'a döner — bu kez `ReviserAgent`, yalnızca numaralı kusur listesini hedef alan bir onarım promptuyla çalışır. En fazla `MAX_DRAFT_ATTEMPTS=2` deneme (bir ilk üretim + bir revizyon). `revise` düğümünün kendisi LLM çağrısı yapmaz; döngünün maliyeti her turda tam olarak bir üretimdir.
- **Kaçış yolları**: Kalan bir `[...]` yer tutucusu (yazar zaten bilmediğini işaretlemiştir) veya çözülememiş bir yazışma türü/eksik RAG bağlamı aynı boşluğa tekrar denemek yerine sırasıyla `NEEDS_INPUT` (insan-cevabı bekleyen HITL kesintisi) veya `NEEDS_HUMAN_APPROVAL`'a gider.
- **Güvenlik**: Gelen evrak eksikse veya writer/reviser güvenilir çıktı üretemezse akış sahte bir varsayılan taslak ya da başarı skoru döndürmez; durum `FAILED` olur.

### 4. Routing Graph (`routing_graph.py`)
- **Node'lar**: `route`.
- **Görev**: Taslak metni ve (hibrit) güven skorunu değerlendirerek yazıyı `ROUTING_UNITS` listesindeki birime yönlendirir veya güven skoru `HUMAN_APPROVAL_SCORE_THRESHOLD`'un altındaysa/hata oluştuysa doğrudan `İnsan Onayı Gerekli`'ye iletir. `POST /api/v1/routing/suggest` üzerinden, bir taslak üretmeden bağımsız olarak da çağrılabilir — insan bir taslağı elle düzenledikten sonra yeniden üretim ödemeden taze bir yönlendirme kararı almak için.

---

## Hibrit Kalite Kapısı (Görev 2)

Taslak kalite denetimi iki bağımsız mekanizmanın birleşimidir (`ai/verification/`):

1. **Deterministik doğrulayıcı** (`draft_verifier.verify_draft`): regex ve küme-üyeliği ile çalışır, LLM çağırmaz. Taslaktaki her sayı/tarih/kurum/mevzuat atfının kaynak evrakta veya alınan mevzuat bağlamında karşılığı olup olmadığını denetler (kurum adları için ≥%75 önemli-token örtüşmesi paraphrase'e izin verir), beş zorunlu yapısal unsuru (Konu/Sayı/Tarih/Kapanış/İmza) kontrol eder ve doldurulmamış `[...]` yer tutucularını sayar.
2. **Hızlı-katman LLM yargıcı** (`llm_judge.judge_draft`): regex'in göremediği şeyleri değerlendirir — talebe gerçekten cevap veriyor mu, arz/rica yönü muhatap hiyerarşisiyle uyumlu mu, resmî üslup korunuyor mu, muhatap/hitap/kapanış tutarlı mı. Yargıç asla taslak metnini tekrar üretmez (her alan uzunluk sınırlı) ve bir yankı-koruması (`_reject_draft_echo`) taslağı büyük ölçüde tekrar eden bir "değerlendirmeyi" geçersiz sayar. Yargıç zaman aşımına uğrarsa, şema hatası verirse veya sağlayıcı istisnası fırlatırsa akış **bloke olmaz** — deterministik skora düşer (`judge_available=False`).

`merge_verdicts()` ikisini `0.6*deterministik + 0.4*yargıç` ile birleştirir; herhangi bir **kritik** yargıç bulgusu veya `addresses_request=false` kararı, ortalamayı ezip skoru otomasyon eşiğinin altına sabitler ve insan onayını zorunlu kılar.

---

## HITL (Human-in-the-Loop)

`draft_graph` yalnızca **raporlar** (durum + `missing_information`), akış kontrolü yapmaz — `interrupt()` bir alt grafın içinde çağrılamaz, çünkü `execute_step_node`'un geniş `except Exception`'ına düşer ve checkpointer'ı yoktur. Kesinti, `planning_graph`'a eklenen ayrı bir `human_gate` düğümünde gerçekleşir:

```
executor --(draft NEEDS_INPUT / NEEDS_HUMAN_APPROVAL)--> human_gate --(interrupt)
human_gate --(Command(resume=...))--> executor (devam) | END (revize talebi / red)
```

`human_gate` ayrı bir düğüm olmasının nedeni: `interrupt()` bulunduğu düğümü resume'da baştan çalıştırır. `execute_step_node`'un içinde olsaydı, resume executor'ın state'e zaten yazdığı ~30 sn'lik taslak üretimini tekrarlardı. `missing_information` kesintisinde cevaplar `apply_answers()` ile **taslak yeniden üretilmeden** yerine konur ve yalnızca deterministik doğrulayıcı tekrar çalışır. Yalnızca `planning_graph` bir `AsyncPostgresSaver` checkpointer alır; dört alt graf `.ainvoke()` ile çağrılan, düğüm olarak kayıtlı olmayan bağımsız Pregel örnekleridir — üzerlerine checkpointer koymak ilgisiz, öksüz bir checkpoint soyağacı başlatırdı.

`thread_id = session_id`; devam uç noktaları `POST /api/v1/chat/resume`, `POST /api/v1/chat/resume/sync` ve `GET /api/v1/chat/sessions/{id}/state`'tir (bkz. `docs/api/chat.md`).

---

# Agent

Agent, belirli bir görevi yerine getiren karar birimidir. Tüm uzman ajanlar, sistemin ortak davranışlarını belirleyen **BaseAgent** sınıfından türetilmiştir.

### Ajan Mimari Yapısı (BaseAgent)
`app/ai/agents/base.py` altında yer alan BaseAgent sınıfı şu SOTA özellikleri barındırır:
* **Unified Messaging**: Tek bir prompt veya konuşma geçmişi (mesaj listesi) ile çalışabilme.
* **Dinamik Prompting**: Sistem promptunun çalışma anında `{{placeholder}}` sözdizimiyle bağlama (context) göre dinamik olarak biçimlendirilmesi.
* **Post-Validation / Guardrails**: `validators` listesi hem `run_structured()` hem de akış sonrası biriken metin üzerinde çalışır (bkz. `ai/guardrails/injection.py`); bir ihlal denemeyi kapalı şekilde başarısız sayar.
* **Self-Correction**: Pydantic model doğrulaması başarısız olduğunda, önceki hata notunun üstüne eklenmek yerine onun yerini alan tek bir düzeltme notuyla kendini düzeltme döngüsü.
* **Metrik enstrümantasyonu**: `run`/`run_structured`/`stream` çağrıları `observability/ai_metrics.py`'deki LLM süresi ve yapılandırılmış-çıktı yeniden deneme sayaçlarını besler.

### Uzman Ajanlar
Sistemdeki tüm uzman ajanlar `app/ai/agents/` altında konumlandırılmıştır:
* **ClassifierAgent** (`classifier.py`): Görev 1'de sınıflandırma ve alan çıkarımını **tek bir birleşik çağrıda** yapar (`document_analysis_graph.py`'nin `MergedDocumentAnalysisOutput` şeması); genel metin sınıflandırması için de kullanılır.
* **ComplianceAgent** (`compliance.py`): Gelen evrakı alınan mevzuat alıntılarıyla eşleştirir ve yalnızca sunulan alıntılara dayanan gerekçe üretir.
* **WriterAgent** (`writer.py`): Brief'ten ilk taslağı yazar; kaynakta olmayan hiçbir kişi/kurum/tarih/sayı/olay üretmemesi ve bilmediği zorunlu bilgi için `[...]` yer tutucusu bırakması istenir.
* **ReviserAgent** (`reviser.py`): Taslağı sıfırdan yeniden yazmaz; yalnızca numaralı kusur listesindeki maddeleri hedefleyen bir onarım promptuyla önceki taslağı düzeltir.
* **JudgeAgent** (`judge.py`): Hibrit kalite kapısının hızlı-katman LLM yarısı — talebe uygunluk, üslup, kapanış yönü ve muhatap tutarlılığını değerlendirir (bkz. "Hibrit Kalite Kapısı").
* **RouterAgent** (`router.py`): Taslağı `ROUTING_UNITS` listesindeki en uygun birime yönlendirir.
* **ChatAgent** (`chat.py`): Evrak işlemi gerektirmeyen genel sohbeti yürütür.
* **DocumentQAAgent** (`document_qa.py`): Yüklü bir belge hakkındaki soruları, belgenin özeti/üstverisi/içeriğinden oluşan bağlamla yanıtlar.

Her agent yalnızca kendi görevinden sorumludur ve prompt şablonunu `get_prompt_manager()` üzerinden dinamik olarak diskten yükler (bkz. "Prompt Yönetimi"). Niyet çözümlemesi artık bir ajan değil, deterministik bir arama tablosudur (bkz. "Planner").

---

# Planner

`app/ai/workflows/planner.py` — sistemin dört sabit akışı vardır ve aralarındaki seçim çoğu mesaj için bir akıl yürütme değil, bir arama işidir.

* **`intent_rules.py`** — bildirimsel kanıt tablosu. Her kural bir `EvidenceRule` (id, niyet, ağırlık, yüzey ifadeleri, `requires_document`). Ayrı bir modülde olması, ifade eklemenin **veri değişikliği** olmasını sağlar; hiçbir kontrol akışı bağlı değildir.
* **`intent_scorer.py`** — mesajı tabloya karşı skorlar. Kanıt **kısa devre yapmaz, birikir**: iki niyet içeren bir mesaj iki skor üretir ve aradaki fark görünür kalır. Üç karşı sinyal taşır — *tanım sorusu* ("Üst yazı ne demek?" taslaktan söz eder, talep etmez), *hafıza-hatırlama* (konuşmaya dair bir soruda belge ifadeleri kanıt değil, hatırlanan konudur) ve *veda* ("yarın devam ederiz" içindeki "devam" onay değildir). Bunlar daha büyük bir sayı değil, **geçersiz kanıtın kaldırılmasıdır**.
* **`resolve_plan_deterministic()`** — kararı ilk eşleşen kural değil, **ilk iki niyet arasındaki marj** verir:
  * `PRESENCE_FLOOR` altında hiçbir niyet aday sayılmaz → eskale.
  * draft ve analyze'ın ikisi de `COMPOUND_FLOOR` üstündeyse → **bileşik plan** (adımlar kanonik sırayla birleştirilir). Bu kontrol marjdan *önce* yapılır: bileşik bir talep dengesiz skorlanabilir ve marj testi talebin bir yarısını sessizce düşürürdü.
  * Marj `DECISIVE_MARGIN` üstündeyse → tek niyet.
  * Aksi hâlde → eskale.
* `PlanDecision` kararla birlikte `confidence`, `evidence` (tetiklenen kural id'leri) ve `alternatives` taşır; üretimdeki bir karar geriye dönük açıklanabilir.
* Yalnızca gerçekten dengeli ya da kanıtsız mesajlar tek etiketlik hızlı-katman model çağrısına düşer (`classify_intent_with_model`); model de başarısız olursa güvenli varsayılan (belge varsa `document_qa`, yoksa `chat`) seçilir — hiçbir zaman en yavaş dört-adımlı boru hattına değil.

Önceki tasarımda bu seçim, tam bir yapılandırılmış çıktı şeması bekleyen bir `OrchestratorAgent` çağrısıydı. Onun yerine gelen sıralı anahtar kelime şelalesi LLM çağrısını kaldırdı ama **sırayı** kararın kendisi hâline getirdi ve `evaluation/` ölçümünde iki kategoriyi 0.00 ile raporladı. Skorlama bunu çözer; planner hâlâ LLM'siz ve milisaniye altıdır.

---

# Semantik Katman

`app/ai/semantic/` — karar merdiveninin **2. basamağı**, sözlüksel kurallar ile hızlı katman modeli arasında.

```
Katman 0/1  Sözlüksel kanıt skorlaması   ~0 ms       intent_rules + intent_scorer
Katman 2    Semantik prototip eşleşmesi  ~50-150 ms  semantic/prototype_matcher   <- YENİ
Katman 3    Hızlı katman modeli          ~1-3 sn     classify_intent_with_model
```

Her basamak yalnızca bir altının **reddettiğini** görür. Kuralların çözdüğü bir mesaj hiç gömme maliyeti ödemez.

## Neden bir basamak etmeye değer

Kısa bir mesaj için tek `embed_query`, zaten bellekte duran bir modelde ~50-150 ms. Hızlı katmanın tek etiketlik yapılandırılmış çağrısı ~1-3 sn. Burada çözülen bir parafraz, bir üst basamağın **yüzde birkaçına** mal olur.

## Neden tek başına asla karar vermez

Aynı resmî registerdeki kısa Türkçe cümleler arasındaki kosinüs benzerliği sıkışıktır; alakasız cümleler rutin olarak 0.6 civarında oturur. Bu yüzden bir eşleşme **iki eşiği birden** geçmelidir:

* `semantic.decisive_similarity` — kazanan sınıfa mutlak benzerlik
* `semantic.decisive_margin` — ikinci sınıfa fark

Tek başına mutlak eşik sürekli tetiklenir; tek başına marj, eşit derecede kötü iki eşleşmenin rastlantısal farkında tetiklenir. Herhangi biri sağlanmazsa modele düşülür — belirsiz bir mesaj için doğru sonuç budur.

## Bayatlık

Vektör dosyaları gömme modeli, boyut ve `POLICY_VERSION` ile damgalıdır. Damga tutmazsa matcher kendini **devre dışı bırakır**: farklı bir modelle üretilmiş vektörlerden karar vermek, bir model çağrısı ödemekten kötüdür — yavaş değil, eminden yanlış olur. Eksik dizin, bozuk dosya ve gömme kesintisi de aynı no-op'a düşer.

```bash
docker compose run --rm --no-deps backend python scripts/build_prototypes.py
```

`app/ai/policy/prototypes.py` değiştiğinde, gömme modeli değiştiğinde veya `POLICY_VERSION` arttığında yeniden çalıştırılmalıdır.

## Ölçülen katkı

Canlı `nomic-embed-text` ile, sözlüksel katmanın çekimser kaldığı 15 mesaj üzerinde:

| | |
|---|---|
| Çözülen | **2 / 130 mesaj** |
| Yanlış karar | 0 |
| Hâlâ eskale | 13 |
| Gecikme | p50 **19.7 ms**, p95 **22.0 ms** |

**Beklenenden çok daha az.** Neden sayılarda görünüyor: resmî registerdeki Türkçe cümleler karşılıklı benzer olduğu için tamamen belirsiz bir mesaj bile alakasız prototiplere karşı 0.60–0.74 alıyor. Kullanılabilir bant, bu gürültü tabanının (`0.740`) üstünde kalan dar aralık. Eşik `0.80` — güvenli bandın (`0.758 → 0.859`) ortası.

Bu, katmanın yanlış olduğu anlamına gelmiyor: 0 yanlış kararla, ödediği ~20 ms karşılığında iki model çağrısını kaldırıyor. Ama planın varsaydığı "eskalasyonların çoğunu soğurur" beklentisi **doğrulanmadı**.

## Bilinen sınırı

Semantik katman yalnızca **çekimserlik** üzerinde çalışır. Sözlüksel katmanın *eminden yanlış* karar verdiği bir mesajı hiç görmez.

Held-out ölçümü (CHANGELOG 1.28.0) bu sınıfın gerçek olduğunu göstermişti: 16 parafrazın 5'i eminden yanlış, 4'ü `document_qa`'ya düşüyordu. CHANGELOG 1.32.0 bu 5'i sözlüksel katmanın kendisinde ele aldı — `document_qa.question_with_document` sezgisel kuralı, belge ekliyken *herhangi* bir soru işaretini içerik sorgusu sayıyordu, kibarlık ekiyle ("mısın/misin") söylenmiş bir eylem isteğini ayırt etmeden. Sonuç: 5 yanlış-kesin karardan 4'ü artık dürüst bir çekimserliğe düşüyor (semantik/model katmanına eskale edilebilir hale geliyor); kalan tek vaka ("bir sorun var mı" ile "gizlilik derecesi var mı" arasındaki fark) sözlüksel olarak gerçekten ayırt edilemez ve bilinen sınır olarak kalıyor.

Bu, semantik katmanın kapsamını **genişletmiyor** — hâlâ yalnızca çekimserlik üzerinde çalışıyor. Ama artık ona ulaşan çekimserlik sayısı, sözlüksel katmanın kendi kalibrasyon hatalarıyla şişirilmiş değil.

---

# Policy Katmanı

`app/ai/policy/` — deterministik karar katmanının **tüm parametre yüzeyi**. Eşikler, ağırlıklar ve düğüm bütçeleri burada; onları okuyan modüller değerleri kendi modül seviyesi isimlerine türeterek alır (`MIN_AUTOMATED_CONFIDENCE_SCORE = get_policy().verification.min_automated_confidence`).

## Neden dosya değil de tipli dataclass

Bir yapılandırma dosyası, bir eşiği **kod değiştirmeden** değiştirme yeteneği satın alır — burada istenmeyen tam olarak budur. Bu sayılar `evaluation/datasets` üzerinde kalibre edilir; birini oynatmak bir CHANGELOG kaydı ve bir `make eval` koşusu gerektirmeli. Tipli dataclass ayrıca invaryantlara yaşayacak bir yer verir ve üretimle testin sapabileceği bir ayrıştırma yolu bırakmaz.

## İnvaryantlar

Modülün asıl ürünü bunlardır; daha önce yalnızca **tesadüfen** doğru olan ilişkileri kodlarlar. `check_invariants()` import anında çalışır — kendisiyle çelişen bir policy, üretimde sessizce yanlış karar üretmek yerine süreci düşürür.

| İnvaryant | Neden |
|---|---|
| `routing.human_approval_score_threshold < verification.min_automated_confidence` | İkisi aynı kavramın iki şiddet derecesi: **70** = "incelemesiz gönderilebilir", **50** = "hiç yönlendirilemez". Ters çevirmek, yönlendirilemeyecek kadar zayıf bir taslağı aynı anda gönderilebilecek kadar iyi yapardı. |
| Yargıç harman ağırlıkları 1.0'a toplanır | `0.6 × deterministik + 0.4 × yargıç` bir ortalamadır; toplamı 1 değilse skor ölçek değiştirir. |
| `intent.compound_floor ≥ intent.presence_floor` | Bileşik bir okuma, tekil bir okumadan daha az kanıta ihtiyaç duyamaz. |
| `memory.history_raw_cap > memory.history_window` | Aksi hâlde konsolidasyonun özete katacak taşma turu hiç olmaz. |
| Her düğüm bütçesi ≤ iş akışı tavanı | Dış zaman aşımına çarpıp tüm turu kaybetmeyi engeller. |
| `budget.node_seconds`'ın her anahtarı bir çağrı yerinde uygulanır | `writer` ve `judge` var oldukları süre boyunca hiç okunmadı. **Uygulanmayan bir bütçe, bütçesizlikten kötüdür**: koruma olduğu izlenimi verir. Testle kilitli. |

## Bütçe çözümlemesi

`policy/budget.py` `node_budget(node, level)` — taban bütçe × seviyenin `timeout_multiplier`'ı, iş akışı tavanına kırpılmış.

`@node_timeout` bir **düğüm adı** alır, sayı değil. Eski imza float alıyordu ve bu ifade graf **derlenirken** değerlendiriliyordu; graf süreçte bir kez derlendiği için istek başına hiçbir değer oraya ulaşamazdı — `reasoning_levels.timeout_multiplier`'ın var olduğu hâlde hiçbir düğüm bütçesini etkilememesinin nedeni budur.

Yazarın bütçesi dekoratörle değil **düğümün içinde** uygulanır: dekoratör düğümün `except` bloklarını aşarak yükselir ve grafiği düşürür; oysa bir zaman aşımının grafiğin zaten yönlendirmeyi bildiği bir `FAILED` sonucuna dönüşmesi gerekir.

`DocumentAnalysisState` ve `RoutingState` `reasoning_level` taşımaz (bkz. CHANGELOG 1.22.0), dolayısıyla dengeli seviyeye düşerler.

## Sürümleme

`POLICY_VERSION` her değer değişiminde artırılır ve Prometheus'a `Info` olarak, değerlendirme raporuna da başlık olarak damgalanır. Bir metrik kayması, "trafik değişti" ile "biz bir eşiği oynattık" arasında belirsiz kalmasın diye.

---

# LLM Katmanı

LLM katmanı farklı model sağlayıcılarını tek bir arayüz altında toplar.

Uygulanan mimari yapıda aşağıdaki bileşenler yer almaktadır:
* **BaseLLMClient** (`app/ai/llms/base.py`): Tüm sağlayıcı istemcilerinin uygulaması gereken soyut taban sınıf. `generate`, `stream` ve `generate_structured` metotlarını içerir.
* **OllamaClient** (`app/infrastructure/providers/ollama.py`): Yerel Ollama servisiyle (`ChatOllama` üzerinden) entegrasyonu sağlar. Şu an tek sağlayıcı budur (`vllm.py` kullanılmadığı için kaldırılmıştır).
* **get_llm_client** / **get_fast_llm_client** (`app/ai/llms/__init__.py`): İki katmanlı fabrika. `get_llm_client()` kalite katmanını (taslak yazımı, sınıflandırma), `get_fast_llm_client()` ise `OLLAMA_FAST_MODEL` tanımlıysa küçük modeli, tanımlı değilse aynı modeli döndürür — niyet çözümlemesi, yönlendirme ve kalite yargıcı gibi kısa/etiket-boyutlu kararlar için.
* **Reasoning Level** (`app/ai/reasoning_levels.py`, `ReasoningLevel` enum'u `app/core/enums/`): Kullanıcının her istekte seçebildiği `fast`/`balanced`/`deep` seviyeleri, yukarıdaki iki katmanı ve Ollama'nın `reasoning` (thinking mode) bayrağını, taslak reflexion döngüsünün (`draft_graph.py`) deneme sayısını ve kalite yargıcının çalışıp çalışmayacağını tek bir preset üzerinden birleştirir. Üçüncü bir model eklenmez: `deep` aynı kalite modelini daha fazla çıkarım-zamanı hesaplamayla (thinking mode + ekstra revizyon + zorunlu yargıç) çalıştırır, `fast` ise zaten sıcak duran hızlı-katman modelini writer/reviser için de kullanır. `balanced`, bu özellik eklenmeden önceki sabit davranışla birebir aynıdır.

### Yerel Ollama Varsayılanları

Yerel Ollama modeli repository genelinde geliştirici donanımına göre değiştirilmez. Paylaşılan fallback değeri `qwen3.5:9b` olarak korunur; her geliştirici kullanacağı modeli Git'e eklenmeyen yerel `.env` dosyasında `OLLAMA_MODEL` ile seçer. Docker Compose kökteki `.env` dosyasını, backend'i doğrudan çalıştırma ise `backend/.env` dosyasını kullanır. Örneğin 6 GB VRAM'e sahip bir bilgisayarda `OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M` kullanılabilir. Düşünme modu `OLLAMA_REASONING`, çıktı uzunluğu ise `OLLAMA_MAX_TOKENS` ile aynı yerel dosyada yapılandırılabilir.

`OllamaClient`, normal metin üretimi, akış ve yapılandırılmış çıktı yöntemlerinde aynı model, `num_ctx`, `keep_alive`, reasoning ve token sınırı ayarlarını uygular; `ChatOllama` örnekleri parametre setine göre önbelleğe alınır.

Diğer katmanlar hangi sağlayıcının kullanıldığını bilmez.

Bu sayede model değişikliği uygulamanın geri kalanını etkilemez.

---

# Prompt Yönetimi

Prompt'lar uygulama kodundan tamamen ayrılmıştır ve `app/ai/prompts/` klasörü altında merkezi olarak yönetilmektedir.

### Prompt Yönetim Sistemi (PromptManager)
`app/ai/prompts/manager.py` altında yer alan **PromptManager** sınıfı şu özellikleri sunar:
- **Dosya İzoleli Şablonlar**: Promptlar Python kodunun içine yazılmaz, `prompts/templates/` dizini altında bağımsız `.md` (Markdown) dosyaları olarak saklanır.
- **Bellek Önbelleklemesi (Caching)**: Disk I/O yükünü en aza indirmek için diskten bir kez okunan prompt şablonları bellekte önbelleğe alınır.
- **Güvenli Değişken Renderlama**: Değişken yerleştirme için standart `{}` yerine `{{deger}}` söz dizimi kullanılır. Bu sayede prompt içindeki JSON şemalarında veya kod bloklarında yer alan tekli kıvırcık parantezlerin (`{}`) render işlemi sırasında çakışması ve hata üretmesi engellenir.
- **Süreç-genelinde tekil erişim**: `get_prompt_manager()` fonksiyonu tüm uygulama genelinde aynı örneği döndürür. (Modül seviyesinde ayrıca dışa aktarılan bir `prompt_manager` nesnesi **yoktur** — her ajanın kendi `PromptManager()` kurması yerine bu tek fonksiyon kullanılır.)
- **Şablon Sözleşmesi**: `TEMPLATE_CONTRACTS` her şablonun deklare ettiği `{{placeholder}}` kümesini kod içinde sabitler; `declared_placeholders()` bir şablon metnindeki gerçek placeholder'ları çıkarır. `tests/unit/ai/test_prompt_templates.py`, her şablonun diskte var olduğunu, sözleşmesiyle eşleştiğini ve **tam olarak bir** ajan modülü tarafından referans verildiğini doğrular — sahipsiz bir şablon burada yakalanır.

### Prompt Şablonları (`prompts/templates/`)
Her uzman ajanın ve akışın sistem yönergesi ilgili markdown dosyasında saklanır:
- `classifier.md`: Sınıflandırma + alan çıkarımı ajanı yönergeleri (Türkçe).
- `compliance.md`: Uygunluk/mevzuat eşleştirme ajanı yönergeleri (Türkçe).
- `writer.md`: Yazar ajanı yönergeleri (Türkçe).
- `reviser.md`: Revizör ajanı yönergeleri — yalnızca listelenen kusurları düzeltme, `[...]` yer tutucularına dokunmama kuralını içerir (Türkçe).
- `judge.md`: Kalite yargıcı ajanı yönergeleri — arz/rica yön kuralı ve hiyerarşi muhakemesi (Türkçe).
- `router.md`: Yönlendirme ajanı yönergeleri (Türkçe).
- `chat.md`: Sohbet sistemi yönergeleri (Türkçe).
- `document_qa.md`: Belge soru-cevap ajanı yönergeleri (Türkçe).

Bu sayede promptlar:
* kolayca sürümlenebilir
* kod değişikliği gerektirmeden güncellenebilir
* test edilebilir

---

# Tool Calling

> **Not**: Bu bölüm mimari hedefi tanımlar; şu anki sürümde hiçbir ajan tool-calling kullanmıyor (`BaseAgent`'ın `tools` parametresi kaldırıldı, bkz. CHANGELOG [1.19.0]) ve aşağıdaki "Dosya Okuma/Yazma/Terminal/Git" örneklerinin karşılığı yok. Ayrı bir temizlik konusu olarak bırakılmıştır.

AI doğrudan sistem işlemi gerçekleştirmez.

Tüm yetenekler Tool katmanı üzerinden kullanılır.

Örnekler

* Web Arama
* Hesaplama
* Dosya Okuma
* Dosya Yazma
* Terminal
* Git
* API Çağrısı

Her Tool bağımsızdır.

---

# MCP

Model Context Protocol sistem araçlarını standart bir arayüz üzerinden sunar.

AI yalnızca MCP istemcisini kullanır.

Araçların nasıl çalıştığını bilmez.

Bu yaklaşım;

* güvenliği artırır
* genişletilebilirliği sağlar
* araç bağımlılığını azaltır

## Mevcut durum

`app/mcp/` katmanı (stdio `MCPClient` + `MCPManager`) çalışır durumdadır ancak
**çalışma zamanında kayıtlı bir sunucu yoktur**; `registry.py` boştur.

Bugün MCP'nin tek gerçek kullanımı geliştirme zamanındadır:
`scripts/fetch_mevzuat_corpus.py`, aynı `MCPClient` üzerinden
[`mevzuat-mcp`](https://github.com/saidsurucu/mevzuat-mcp) (MIT) sunucusuna
bağlanıp mevzuat.gov.tr'den tam metin çeker ve `datasets/mevzuat/` altına yazar.

Sunucu **backend imajına dahil değildir**: bağımlılık ağacı `playwright`
sabitler ve tarayıcı ikilisi çeker. Bu nedenle korpus üretimi izole bir sanal
ortamda, elle çalıştırılır; analiz hattı yalnızca commit'lenmiş yerel dosyaları
okur ve ağa hiç ihtiyaç duymaz. Bu, evrak analizinin çevrimdışı ve tekrar
üretilebilir kalmasını sağlar.

Korpusa yazılan her dosya `mevzuat_id`, kaynak ve çekilme tarihini taşır;
böylece üretilen her atıf resmî metne kadar izlenebilir.

---

# Retrieval

Retrieval katmanı bilgi erişiminden sorumludur.

Başlıca görevleri

* embedding oluşturmak
* benzerlik araması yapmak
* sonuçları sıralamak
* bağlam oluşturmak

Retrieval doğrudan cevap üretmez.

---

# Embeddings

Embedding katmanı belgeleri ve metinleri vektörlere dönüştürerek anlamsal aramaya (semantic search) hazır hale getirir. Projede SOTA düzeyinde modüler bir yapı kurulmuştur.

### Embedding Modelleri
`app/ai/embeddings/models.py` altında sağlayıcı bağımsız bir altyapı uygulanmıştır:
* **BaseEmbeddingsClient**: Tüm embedding sağlayıcılarının türemesi gereken taban arayüz.
* **OllamaEmbeddingsClient**: Yerel Ollama üzerindeki embedding modellerini (`nomic-embed-text:latest` veya `qllama/multilingual-e5-base:q4_k_m`) kullanarak asenkron vektörler üretir.
* **get_embeddings_client**: İlgili sağlayıcıyı başlatan fabrika fonksiyonu.

### Metin Bölme (Chunking) Stratejileri
`app/ai/embeddings/chunking/` altında 4 farklı bölme yöntemi sunulmaktadır:
1. **CharacterChunker** (`character.py`): Basit karakter sınırı ve çakışma (overlap) odaklı bölücü.
2. **RecursiveChunker** (`recursive.py`): Paragraf, cümle ve kelime sınırlarını koruyarak metni rekürsif olarak bölen standart bölücü.
3. **SemanticChunker** (`semantic.py`): Cümleler arası anlamsal kosinüs benzerliği (cosine similarity) analizini yapıp, anlamsal sapma veya eşik (static/percentile threshold) değerine göre bölen bölücü.
4. **AgenticChunker** (`agentic.py`): LLM/Ajan yardımıyla metni mantıksal bölümlere ayıran, her parçaya özel başlık ve özet üreterek zengin meta veri (metadata) üreten gelişmiş bölücü.

### Embedding Servisi
`app/ai/embeddings/service.py` altındaki **EmbeddingService** sınıfı metin bölme (chunking) ve vektör üretme (embedding) adımlarını orkestre ederek, text, vector ve metadata barındıran `EmbeddedChunk` listesini döndürür.

Bu süreç cevap üretiminden bağımsızdır.

---

# Memory

Konuşma geçmişi, **checkpoint'lenmiş graf state'i** üzerinde taşınır — `planning_graph`'ın `thread_id`'si zaten `session_id`'ye eşittir ve `AsyncPostgresSaver` bu state'i (geçmiş, özet, bekleyen bir HITL kesintisi, her şey) zaten tutarlı biçimde kalıcılaştırır. Ayrı bir Redis tabanlı depo, checkpoint yazımıyla arasında bir çökmede bölünebilecek ikinci bir kaynak eklerdi.

### CheckpointMemory (`ai/memory/checkpoint_memory.py`)
`BaseMemory` sözleşmesini `planning_graph.aget_state(...)` üzerine ince, salt-okunur bir görünüm olarak uygular.

### Kayan Pencere + Özet (rolling window + summary)
`HISTORY_WINDOW=12` turluk bir pencere `_append_history` reducer'ıyla state'te tutulur ve `_run_chat`/`_run_document_qa`'ya geçmişi verbatim olarak sağlar. Bunun ötesindeki turlar sonsuza dek atılmaz: state ayrıca `HISTORY_RAW_CAP=40` turluk daha geniş bir ham günlük ve `history_summary`/`history_summarized_through` alanlarını tutar. `consolidate_memory_node`, her tur bittikten sonra (pencerenin dışına yeterince yeni tur çıktığında, `CONSOLIDATION_BATCH_SIZE=4`) hızlı katman modeliyle (`get_fast_llm_client`, intent sınıflandırmasıyla aynı model, `MemorySummarizerAgent`) bu turları var olan özetle birleştirip kısa bir özet üretir. `chat`/`document_qa` prompt şablonları bu özeti ayrı, açıkça etiketlenmiş bir blok olarak alır (`{{history_summary}}`) — belge bağlamıyla karıştırılmaz.

> **Not**: Önceki sürümlerdeki Redis pencere hafızası (`ConversationWindowMemory`), LLM özetleme tabanlı uzun dönem hafıza (`SummaryMemory`) ve Qdrant tabanlı episodik/Mem0-benzeri hafıza (`VectorMemory`) kaldırılmıştır; tek doğruluk kaynağı hâlâ checkpointer'dır — rolling summary da ayrı bir depo değil, aynı checkpoint'lenmiş state'in bir alanıdır.

### Oturum Ölçeği (session scope)
Sunucu, istemci bir `session_id` göndermezse `anon:<uuid4>` üretir (`ChatService._thread_id`). Frontend, `crypto.randomUUID()` ile üretilen bir kimliği `localStorage`'da (`kachow_client_session_id`) kalıcılaştırıp her istekte gönderir, böylece sayfa yenilemede/aynı tarayıcıda yeni sekmede AYNI checkpoint thread'i (ve özeti) yeniden kullanılır. Bu, gerçek kullanıcı kimlik doğrulaması değildir: anonim, tarayıcıya özgüdür ve cihazlar arası değildir (`REQUIRE_AUTH` hâlâ kapalı; gerçek kullanıcı kimliğine bağlı kalıcı memory ayrı bir konu olarak bırakılmıştır).

### Planlama ve Memory
`intent_scorer.py`, konuşmanın kendisine dair bir soru (`chat.memory_recall`, ör. "az önce ne sordum") tespit ettiğinde `document_qa` kanıtını **geçersiz kılar** ve mesaj `document_id`'den bağımsız olarak `chat`'e gider — bir belgenin ekli olması, konuşma hafızasına dair bir soruyu asla belge sorusuna çevirmez.

---

# RAG (Retrieval-Augmented Generation)

Projede RAG akışı, bilgi doğruluğunu artırmak ve halüsinasyonları engellemek amacıyla SOTA hibrid arama ve reranking (yeniden sıralama) teknolojileriyle kurgulanmıştır.

```text
               Kullanıcı Sorgusu
                      │
           ┌──────────┴──────────┐
           ▼                     ▼
     Dense Search          Sparse Search
   (Semantic/Qdrant)       (BM25 Keyword)
           │                     │
           └──────────┬──────────┘
                      ▼
          Reciprocal Rank Fusion (RRF)
                      │
                      ▼
                 LLM Reranker
           (Structured scoring 0-10)
                      │
                      ▼
             Sıralanmış Bağlam
```

### 1. Dense (Anlamsal) Arama (`DenseRetriever`)
- Kullanıcı sorgusunu `EmbeddingService` aracılığıyla vektörleştirir.
- Qdrant vektör veritabanında anlamsal benzerlik araması (`similarity_search`) gerçekleştirir.
- Anlam ve bağlamı yüksek, ancak kelime birebir eşleşmelerinde zayıf kalabilen aday dokümanları getirir.

### 2. Sparse (Anahtar Kelime) Arama (`BM25Retriever`)
- `rank-bm25` kütüphanesi üzerine kuruludur.
- Doküman havuzu (corpus) üzerinde asenkron olarak BM25 indekslemesi yapar.
- Sorguyu Türkçe büyük-küçük harf duyarlı ve stop-word filtreli SOTA bir tokenize işleminden (`tokenize_turkish`) geçirir.
- Özel terimler, hata kodları, model isimleri veya tam eşleşmesi gereken anahtar kelimeleri yakalar.

### 3. Rank Fusion (`reciprocal_rank_fusion`)
- Dense ve Sparse listelerinden dönen adayları **Reciprocal Rank Fusion (RRF)** algoritmasıyla birleştirir.
- Her iki sıralamadaki pozisyonuna göre dokümanlara $1 / (k + rank)$ formülü ile bir RRF skoru atar. Böylece hem anlamsal hem de kelime eşleşmesi yüksek olan dokümanlar en üstte birleşir.

### 4. Yeniden Sıralama
> **Kaldırıldı.** `LLMReranker`, bu boyuttaki bir korpusta 3 sonucu yeniden sıralamak için ~90 sn'lik taslak gecikme bütçesinin kritik yoluna bir LLM çağrısı daha ekliyordu ve kalitenin belirleyicisi hiç olmadı. RRF'nin ürettiği sıralama doğrudan kullanılır.

---

# Reasoning

Reasoning katmanı modelin ara kararlarını yönetir.

Örnek görevler

* bilgi değerlendirme
* araç seçimi
* bağlam analizi
* cevap doğrulama

Reasoning süreci kullanıcıya doğrudan gösterilmez.

---

# Response Builder

Tüm sonuçlar tek bir cevapta birleştirilir.

Görevleri

* çıktı biçimlendirme
* kaynak ekleme
* hata yönetimi
* son doğrulama

Backend yalnızca Response Builder çıktısını alır.

---

# Observability

AI sistemi tamamen izlenebilir şekilde tasarlanmıştır.

İzlenen bilgiler

* LLM çağrıları
* Prompt sürümleri
* Tool kullanımı
* Workflow adımları
* Gecikme süreleri
* Token kullanımı
* Hatalar

Bu bilgiler sistem davranışını analiz etmek için kullanılır.

---

# Güvenlik

AI aşağıdaki güvenlik prensiplerini uygular.

* **Prompt Injection koruması** — `ai/guardrails/injection.py`. `scrub_extracted_text()` çıkarılan evrak metnindeki sıfır-genişlikli/bidi kontrol karakterlerini ve Türkçe/İngilizce talimat-geçersizleştirme satırlarını (yüklenen bir dosya saldırgan kontrolündeki girdidir) temizler; `assert_no_prompt_leak()` bir `BaseAgent` validator'ı olarak hem yapılandırılmış çıktılarda hem de akış sonrası biriken metinde çalışır.
* Tool Permission kontrolü
* Input Validation
* Output Filtering
* Gizli bilgi koruması
* Tool Isolation

AI hiçbir zaman sınırsız sistem yetkisine sahip değildir.

---

# Performans

AI sistemi aşağıdaki optimizasyonları kullanır.

* Embedding Cache
* Semantic Cache
* Prompt Cache
* Streaming Response
* Asenkron Tool Calling
* Paralel Retrieval
* Token Optimizasyonu

Amaç düşük gecikme ve yüksek doğruluktur.

---

# Hata Yönetimi

Her AI işlemi hata durumunda kontrollü şekilde sonlandırılır.

Beklenen hata türleri

* LLM hatası
* Tool hatası
* Retrieval hatası
* MCP bağlantı hatası
* Timeout

Her hata uygun bir üst katmana raporlanır.

---

# Ölçeklenebilirlik

Yeni AI yetenekleri mevcut mimariyi değiştirmeden eklenebilir.

Yeni;

* Agent
* Workflow
* Tool
* Prompt
* Provider
* Retriever

sisteme bağımsız olarak eklenebilir.

Bu yaklaşım AI katmanının sürdürülebilir şekilde büyümesini sağlar.

---

# AI ve Backend İlişkisi

Backend yalnızca AI servisini çağırır.

Backend;

* Prompt bilmez.
* Tool bilmez.
* LLM bilmez.
* Workflow bilmez.

AI katmanı tamamen bağımsızdır.

---

# AI ve Frontend İlişkisi

Frontend AI ile doğrudan iletişim kurmaz.

Tüm iletişim Backend API üzerinden gerçekleştirilir.

Bu yaklaşım güvenlik ve mimari bütünlüğü korur.




