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
Sistemin tek orkestrasyon grafiğidir ve **tek checkpointer alan graf**budur (bkz. HITL bölümü). `planner.py`'deki **`resolve_plan()`** ile gelen mesajı/eki analiz eder ve çalıştırılacak alt adımları (`classification`, `draft`, `routing`, `assist`, `revise`) bir plan olarak belirler — sözlüksel/semantik/bağlamsal sinyallerin kalibre bir füzyonuna dayanan bir olasılık bandı (bkz. Planner bölümü); yalnızca füzyonun gerçekten tartışmalı bıraktığı mesajlar hızlı-katman modele düşer. `executor` düğümü planı adım adım yürütür ve her adımın bağımlılığı başarısız olduysa (`_STEP_DEPENDENCIES`) o adımı hiç çalıştırmadan `SKIPPED` işaretler — başarısız bir taslağın üzerine boş girdiyle yönlendirme çalıştırılması buradan engellenir.

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
- **Node'lar**: `validate_input → retrieve_examples → writer → verify → (revise → writer | needs_input=END | end)`.
- **Girdi**: Gelen evrakın brief'i (ham `source_document` writer'a hiç gitmez, yalnızca `_build_brief()`'in ürettiği özetlenmiş yapı gider), doğrulanmış RAG bağlamı, yazım yönergeleri ve isteğe bağlı `correspondence_type`.
- **Yazışma Türleri**: `cover_letter`, `response_letter`, `information_notice`, `other_official`. Çözümleme sırası: açık istek → sınıflandırma metadata'sı → kullanıcı yönergesi → gelen belge türünden çıkarım → `other_official` (fallback, insan incelemesi zorunlu).
- **Few-shot üslup örnekleri** (`retrieve_examples`): `writer`'dan önce çalışır, `ExampleRetriever` üzerinden ayrı bir `resmi_yazisma_ornek` Qdrant koleksiyonundan (`scripts/curate_yazisma_examples.py` + `scripts/index_yazisma_examples.py` ile `datasets/resmi_yazisma`'dan üretilir, chunk'lanmaz — her nokta tam bir yazı) `correspondence_type`'a sert filtrelenmiş, kurum çeşitliliği gözetilmiş 2 gerçek resmî yazı getirir ve writer/reviser promptuna "yalnızca üslup, bilgi kaynağı değil" sınırıyla enjekte eder. `DraftPolicy.style_examples_enabled=False`, retriever yapılandırılmamışsa ya da getirim başarısız/zaman aşımına uğrarsa `style_examples=[]` ile sessizce devam eder — düğüm `node_timeout` dekoratörü yerine kendi iç `asyncio.timeout`'unu kullanır ki bir zaman aşımı bütün taslağı değil yalnızca örnekleri düşürsün. `revise` bu listeye dokunmaz; bir onarım turu ilk taslakla aynı örnekleri görür.
- **Reflexion döngüsü**: `verify` düğümü hibrit kalite kapısını çalıştırır (aşağıya bakınız). Düzeltilebilir kusurlar (eksik yapı, doğrulanamayan iddialar, düzeltilebilir yargıç bulguları) `revise` üzerinden `writer`'a döner — bu kez `ReviserAgent`, yalnızca numaralı kusur listesini hedef alan bir onarım promptuyla çalışır. En fazla `MAX_DRAFT_ATTEMPTS=2` deneme (bir ilk üretim + bir revizyon). `revise` düğümünün kendisi LLM çağrısı yapmaz; döngünün maliyeti her turda tam olarak bir üretimdir.
- **Kaçış yolları**: Kalan bir `[...]` yer tutucusu (yazar zaten bilmediğini işaretlemiştir) veya çözülememiş bir yazışma türü/eksik RAG bağlamı aynı boşluğa tekrar denemek yerine sırasıyla `NEEDS_INPUT` (insan-cevabı bekleyen HITL kesintisi) veya `NEEDS_HUMAN_APPROVAL`'a gider.
- **Güvenlik**: Gelen evrak eksikse veya writer/reviser güvenilir çıktı üretemezse akış sahte bir varsayılan taslak ya da başarı skoru döndürmez; durum `FAILED` olur.

### 4. Routing Graph (`routing_graph.py`)
- **Node'lar**: `route`.
- **Görev**: Taslak metni ve (hibrit) güven skorunu değerlendirerek yazıyı, `app.domains.units` domain'inin yönettiği (yöneticilerin `POST/PATCH/DELETE /units` ile tanımladığı) aktif birim listesinden birine yönlendirir -- liste her çağrıda `units_provider` (`get_active_units_for_routing`) üzerinden veritabanından taze okunur, artık sabit bir Python listesi değildir. Güven skoru `HUMAN_APPROVAL_SCORE_THRESHOLD`'un altındaysa, taslak boşsa, tanımlı hiçbir aktif birim yoksa, ya da model listede olmayan bir birim döndürürse, birim atanmaz (`routed_unit=None`) ve bunun yerine `requires_human_approval=True` işaretlenir -- eskiden sahte bir "İnsan Onayı Gerekli" birimi vardı, artık bu tamamen kaldırıldı; taslak-kalite kapısının kullandığı aynı bayrak yeniden kullanılıyor. `POST /api/v1/routing/suggest` üzerinden, bir taslak üretmeden bağımsız olarak da çağrılabilir — insan bir taslağı elle düzenledikten sonra yeniden üretim ödemeden taze bir yönlendirme kararı almak için.

---

## Hibrit Kalite Kapısı (Görev 2)

Taslak kalite denetimi iki bağımsız mekanizmanın birleşimidir (`ai/verification/`):

1. **Deterministik doğrulayıcı** (`draft_verifier.verify_draft`): regex ve küme-üyeliği ile çalışır, LLM çağırmaz. Taslaktaki her sayı/tarih/kurum/mevzuat atfının kaynak evrakta veya alınan mevzuat bağlamında karşılığı olup olmadığını denetler (kurum adları için ≥%75 önemli-token örtüşmesi paraphrase'e izin verir), beş zorunlu yapısal unsuru (Konu/Sayı/Tarih/Kapanış/İmza) kontrol eder ve doldurulmamış `[...]` yer tutucularını sayar. `style_examples` verildiğinde, kaynakla desteklenmeyen ama bir üslup örneğinde geçen değerleri ayrı bir `example_leaks` alanına ayırır ve `strict` bayrağından bağımsız olarak daima insan onayına düşürür — writer.md'nin "yalnızca üslup, bilgi kaynağı değil" kuralının prompt-ötesi, deterministik doğrulaması. Bilerek `unsupported_claims`/onarım listesinin dışında tutulur: bir revize turu aynı örnekleri gördüğü için sızıntıyı tekrarlama riski taşır.
2. **Hızlı-katman LLM yargıcı** (`llm_judge.judge_draft`): regex'in göremediği şeyleri değerlendirir — talebe gerçekten cevap veriyor mu, arz/rica yönü muhatap hiyerarşisiyle uyumlu mu, resmî üslup korunuyor mu, muhatap/hitap/kapanış tutarlı mı. Yargıç asla taslak metnini tekrar üretmez (her alan uzunluk sınırlı) ve bir yankı-koruması (`_reject_draft_echo`) taslağı büyük ölçüde tekrar eden bir "değerlendirmeyi" geçersiz sayar. Yargıç zaman aşımına uğrarsa, şema hatası verirse veya sağlayıcı istisnası fırlatırsa akış **bloke olmaz** — deterministik skora düşer (`judge_available=False`).

**Güven skoru artık tamamen deterministik bir kural tablosundan hesaplanır** (`ai/verification/confidence_rules.py::RULES`) — yargıç skora hiç girmez, yalnızca kapı ve tamir kaynağıdır (Faz A/§4 düzeltmesi; eskiden `0.6*deterministik + 0.4*yargıç` harmanı vardı, bu aynı taslağın iki farklı çalıştırmada farklı skor almasına ve yargıç zaman aşımına uğradığında skorun aniden sıçramasına yol açıyordu). `merge_verdicts()` `report`'un kendi penaltisini (`100 - report.confidence_score`) PII/yazışma-türü-tahmini/mevzuat-bağlamı-yokluğu/içerik-kaybı/yargıç bulgularından türeyen ek kural bulgularıyla toplar. Her kural `RuleFinding` → `AppliedRule` olarak izlenebilir (`combined.applied_rules`), yani "bu skor neden 62?" sorusu satır satır cevaplanabilir. Yargıcın **kritik** bir bulgusu veya `addresses_request=false` kararı, kural tablosunda sıfır-ceza (`yargic_kritik_bulgu`/`talebi_karsilamiyor`) satırları olarak insan onayını zorunlu kılar ama skoru değiştirmez.

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

`app/ai/workflows/planner.py` — sistemin beş sabit akışı vardır (`draft`/`analyze`/`assist`/`revise`/`clarify`) ve aralarındaki seçim, 2026 başına kadar bir **merdivendi**: sözlüksel skor → semantik prototip → hızlı-katman model, hangisi önce karar verirse o kazanırdı. Merdiven, kendinden önceki sıralı anahtar-kelime şelalesinin "sıra kararı belirler" hatasını çözdü, ama kendi hatasını getirdi: sözlüksel katmanın **marj testi** her şeyi kapıyordu, açık bir emrin bile geçmesi gerektiği yerde. "Cevap yaz." mesajı `draft=3.0` (açık bir istek) karşısında `assist=2.0` (belge yokken kısa mesaj için jenerik yapısal ipucu) skorluyordu — marj 1.0, eski eşiğin (1.2) az altında — ve kullanıcıya gereksiz bir açıklayıcı soru sorduruyordu. Marj testi, aynı toplam skor içine önceden karıştırılmış bir açık emirle zayıf bir yapısal ipucunu ayırt edemiyordu; rungları yeniden sıralamak bunu düzeltmiyordu, tıpkı şelalenin kendi hatasının sıra değiştirmekle düzelmemesi gibi.

Bugün merdiven yok; **sinyal → füzyon → karar politikası** var. Üç kanıt kaynağı (sözlüksel, semantik, bağlamsal) birbirini ezmiyor, tek bir kalibre olasılığa katkıda bulunuyor.

## Sinyal katmanı

* **`intent_rules.py`** — bildirimsel kanıt tablosu. Her kural bir `EvidenceRule` (id, niyet, ağırlık, yüzey ifadeleri, `requires_document`/`requires_active_draft`). Ayrı bir modülde olması, ifade eklemenin **veri değişikliği** olmasını sağlar; hiçbir kontrol akışı bağlı değildir.
* **`intent_scorer.py`** — mesajı tabloya karşı skorlar. Kanıt **kısa devre yapmaz, birikir**. Yüzey eşleşmesi sol kelime sınırı zorunlu kılar (`"uzat"`, `"uzatma"` içinde yanlış ateşlemez); sağ sınır Türkçe eklemeli yapı nedeniyle bilinçli olarak serbesttir. Üç karşı sinyal taşır — *tanım sorusu*, *hafıza-hatırlama*, *veda* — bunlar daha büyük bir sayı değil, **geçersiz kanıtın kaldırılmasıdır**.
* **`router_features.py`** — sözlüksel skorları (her niyet için ayrı), semantik benzerlikleri (her niyet için ayrı), belge/aktif-taslak/önceki-niyet bayraklarını ve mesaj şekli ipuçlarını (soru mu, kaç kelime) **önceden toplamadan** ayrı özellik değerlerine çevirir. Merdivenin hatası tam olarak burada başlıyordu: sinyaller ayrı kalmadığı için hangi birinin ne kadar ağırlıklı olması gerektiğine füzyon değil, elle yazılmış sabitler karar veriyordu.

## Füzyon

* **`router_fusion.py`** — çok sınıflı lojistik regresyon (softmax), saf Python aritmetiği, yeni bağımlılık yok.
* **`app/ai/policy/router_weights.py`** — `scripts/fit_router.py` tarafından `evaluation/datasets/intents.jsonl`'e karşı çevrimdışı fit edilmiş donmuş katsayılar (5 katlı çapraz doğrulama). `compound`/`clarify_resolution`/`escalation`/`heldout_paraphrase` kategorileri eğitimden bilinçli olarak dışlanır (gerekçe scriptin docstring'inde) — özellikle `compound`: softmax sınıfları yarıştırır, "her iki okuma da bağımsız güçlü" bilgisini temsil edemez.
* **`resolve_plan()`** iki geçişlidir: önce yalnız sözlüksel özelliklerle füzyon çalışır (bir mesaj sözlüksel kanıtla zaten kararlıysa gömme çağrısına hiç gerek yok); `tau_high` karşılanmazsa semantik benzerlik eklenip füzyon tekrarlanır (`source="fused_semantic"`).

## Karar politikası

Füzyonun kazanan olasılığı üzerinde basit bir bant:

* `tau_high` üstü → doğrudan karar (`source="fused"`/`"fused_semantic"`).
* `tau_low` ile `tau_high` arası → hızlı-katman model çağrısı tartışmayı çözer (`source="model"`; model de kararsızsa -- `IntentOutput.intent="unclear"` -- ya da çağrının kendisi başarısız olursa (`"model_failed"`) kullanıcıya sorulur).
* `tau_low` altı → model çağrısına bile değmez, doğrudan sorulur (`source="clarify"`).

İki şey füzyona hiç girmez: **bileşik istek** tespiti (`draft`+`analyze` ikisi de bağımsız güçlüyse), ham toplamsal sözlüksel skor üzerinde füzyondan *önce* kontrol edilir; **açık bir açıklayıcı sorunun yanıtı**, mesaj hiç skorlanmadan, bekleyen sorunun kendi seçenekleriyle çözülür.

`PlanDecision` kararla birlikte `confidence` (her kaynakta artık aynı ölçek: füzyonun kalibre olasılığı — eski üç uyumsuz ölçek yerine), `evidence` (tetiklenen sözlüksel kural id'leri) ve `alternatives` (olasılığa göre sıralı) taşır; üretimdeki bir karar geriye dönük açıklanabilir.

## Ölçülen etki

`evaluation/reports/all-fusion-live.md`, füzyon öncesi temel çizgiye (`all-baseline.md`) karşı:

| Metrik | Öncesi | Sonrası |
|---|---|---|
| Macro F1 | 0.8311 | **0.9452** |
| Kalibrasyon hatası (ECE) | 0.2736 | **0.1139** |
| `short_imperative` kategorisi (açık kısa emirler) | 0.00 doğruluk / 1.00 eskalasyon | **1.00 / 0.00** |
| `revise` kategorisi | 0.30 | **1.00** |

`heldout_paraphrase` (kurallar/ağırlıklar ayarlandıktan **sonra** yazılan, hiçbir fit'e girmeyen parafrazlar) bilinçli olarak zayıf kalıyor (~0.32) — ama artık yanlış kararların çoğu `clarify`'a dönüşüyor, sessizce yanlış tahmin etmiyor.

---

# Semantik Katman

`app/ai/semantic/` — füzyonun ikinci geçişini besleyen semantik benzerlik kaynağı. Artık bağımsız bir "basamak" değil: kendi başına karar vermez, `router_features.py` aracılığıyla füzyonun özellik vektörüne katkıda bulunur (bkz. "Planner").

## Neden hâlâ koşullu

Kısa bir mesaj için tek `embed_query`, zaten bellekte duran bir modelde ~20-30 ms. Sözlüksel-only füzyon zaten `tau_high`'ı geçen bir mesaj bu maliyeti hiç ödemez — `resolve_plan()`'ın iki geçişli yapısı tam olarak bunun için var.

## Bayatlık

Vektör dosyaları gömme modeli, boyut ve `POLICY_VERSION` ile damgalıdır. Damga tutmazsa matcher kendini **devre dışı bırakır**: farklı bir modelle üretilmiş vektörlerden karar vermek, bir model çağrısı ödemekten kötüdür — yavaş değil, eminden yanlış olur. Eksik dizin, bozuk dosya ve gömme kesintisi de aynı no-op'a düşer.

Bu artık **sessiz** değil: `ROUTER_SEMANTIC_AVAILABLE` Prometheus gauge'u ve `/system/health?deep=true`'nun `router_semantic` alanı katmanın gerçekten yüklü olup olmadığını gösterir; matcher `None`'a düştüğünde `logger.error` ile loglanır. Bu güvenceyi haftalarca stale bir prototip dosyasının fark edilmeden üretimde durmuş olması sağladı (bkz. `backend/tests/unit/ai/test_prototype_freshness.py`).

```bash
docker compose run --rm --no-deps backend python scripts/build_prototypes.py
docker compose run --rm --no-deps backend python scripts/fit_router.py
```

`app/ai/policy/prototypes.py` değiştiğinde, gömme modeli değiştiğinde veya `POLICY_VERSION` arttığında **her ikisi de** yeniden çalıştırılmalıdır — füzyon ağırlıkları da `POLICY_VERSION` ile damgalanır (uyuşmazlıkta import zamanında `logger.warning`, yapısal bir hata değil bu yüzden süreç düşürülmez — bkz. `router_weights.py`'nin `version` alanı docstring'i).

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

`app/mcp/` katmanı üç yerde kullanılır; üçü de aynı sunucuya bağlanır:
[`mevzuat-mcp`](https://github.com/saidsurucu/mevzuat-mcp) (MIT), mevzuat.gov.tr
ve bedesten.adalet.gov.tr üzerinden sorgu yapar.

**1. Geliştirme zamanı — korpus üretimi.** `scripts/fetch_mevzuat_corpus.py`
tam metinleri çekip `datasets/mevzuat/` altına yazar; bu, `MEVZUAT_SOURCE="local"`
olduğunda ve MCP-first bir çalışma zamanı hatasında geri düşülen korpustur.
Tamamen çevrimdışıdır ve puanlanan gereksinimlerin garantili yolu budur.

**2. Çalışma zamanı — belge analizi (Görev 1, varsayılan açık).**
`app.ai.retrieval.mcp_mevzuat` (`McpMevzuatRetriever` + `FallbackMevzuatRetriever`),
`retrieve_mevzuat_node`'un tek erişim noktası. `MEVZUAT_SOURCE="mcp"` (varsayılan)
iken korpustaki yedi kanunun güncel metnini MCP üzerinden çeker, bellekte BM25 ile
indeksler ve `_build_mevzuat_query`'nin ürettiği sorguyla sıralar; `"local"` iken
doğrudan yerel `HybridRetriever`'ı (Qdrant, dense+sparse) kullanır, bu ayar
eklenmeden önceki davranışın aynısı.

* **Uygunluk kararına hiç dokunmaz.** `check_required_fields` sabit madde
  numaraları üzerinde küme farkıdır; hangi kaynağın kullanıldığından bağımsız
  olarak `missing_fields` bayt bayt aynıdır (bkz.
  `test_missing_fields_is_identical_regardless_of_the_mevzuat_source`).
* **Canlı getirim, istek yolunda değil.** `retrieve()` hiçbir zaman ağa
  çıkmaz — yalnızca `warm_up()`'ın en son kurduğu bellek-içi indeksi okur.
  `warm_up()`, uygulama açılışında diğer ısınma adımlarıyla birlikte en iyi
  çaba ilkesiyle çalışır (`app.lifespan`); yavaş veya erişilemeyen bir sunucu
  açılışı bloklamaz, yalnızca canlı kaynağın devreye girmesini geciktirir.
* **Her hata yerel korpusa düşer.** Kayıtsız sunucu, zaman aşımı, kısmi
  getirim (bazı kanunlar başarısız), boş sonuç — hepsi `FallbackMevzuatRetriever`
  üzerinden yerel `HybridRetriever`'a düşer, asla istisna fırlatmaz.
* **Genel asistan sohbeti (Görev 3) bu anahtardan etkilenmez.** `get_rag_graph`
  hâlâ yalnızca yerel korpusu kullanan `get_mevzuat_retriever`'ı okur;
  `MEVZUAT_SOURCE` yalnızca belge analizinin kendi retriever'ını seçer
  (`get_document_analysis_mevzuat_retriever`).

**3. Çalışma zamanı — asistan aracı (varsayılan kapalı).** `registry.py`,
`MEVZUAT_MCP_ENABLED` açıksa sunucuyu `mcp_manager`'a kaydeder ve asistana
`search_legislation_live` aracı eklenir — `MEVZUAT_SOURCE`'tan bağımsız ikinci
bir anahtar; bir dağıtım ikisini birbirinden bağımsız açıp kapatabilir.

* **İkinci sırada.** Yerel korpus aracı (`search_legislation`) önce kayıtlıdır;
  bu, korpusun kapsamadığı sorular için bir yükseltmedir.
* **Hata da bir cevaptır.** Erişilemeyen bir devlet sitesi, yerel aracın
  döndürdüğü "bulunamadı" ifadesinin aynısını döndürür; asla istisna fırlatmaz.
  Üçüncü taraf bir site yüzünden sohbet turu 500 vermez.

`register_servers()`, iki anahtardan **herhangi biri** açıkken sunucuyu kaydeder
(`MEVZUAT_MCP_ENABLED or MEVZUAT_SOURCE == "mcp"`) — aksi hâlde belgelenen
varsayılan (`MEVZUAT_SOURCE="mcp"`, `MEVZUAT_MCP_ENABLED=False`) sunucuyu hiç
kaydetmez ve yeni varsayılan sessizce devre dışı kalırdı.

Mülga mevzuat ayıklanır: 657 aramasında "DEVLET MEMURLARI KANUNUNUN YÜRÜRLÜKTEN
KALDIRILMIŞ HÜKÜMLERİ" kaydı aynı numarayı taşır ve gerçek kanunun **üstünde**
döner. Yürürlükten kalkmış metni yürürlükteki kanun gibi alıntılamak, bu projenin
önlemek için var olduğu uydurma atıf hatasının ta kendisidir. Bu ayıklama
(`app.mcp.mevzuat_client.pick_document_id`) belge analizi ve asistan aracı
arasında paylaşılan tek bir uygulamadır.

Sunucunun bağımlılık ağacı `playwright` sabitler ve tarayıcı ikilisi çeker, bu
yüzden bu projenin **kendi** Python bağımlılıklarından (`requirements.txt`)
ayrı, izole bir sanal ortama kurulur: çözümlenen sürümleri
(`fastapi`/`pydantic`/`httpx`/`mcp`) bu projenin kendi pinlerine yakın ama aynı
değil (`pydantic-settings` burada 2.15.0'a çözümlenirken bu projenin pini
2.14.2), bu da paylaşılan tek bir ortamda birinin pinini sessizce kırmaya
yetecek kadar bir fark. Docker imajı (`deploy/docker/backend.Dockerfile`) bu
izole ortamı **derleme zamanında zaten kuruyor** — `docker compose up` ekstra
kurulum gerektirmeden çalışır. Docker dışında çalıştıran biri aynı kurulumu
elle yapmalı (bkz. `.env.example`). Her iki durumda da her iki çalışma zamanı
yolu da kurulu bir kopyaya işaret eden `MEVZUAT_MCP_COMMAND` gerektirir. Komut
ve argümanlar yapılandırmada tutulur, kodda değil — böylece bu geçiş kod
değişikliği değil ayar değişikliğidir.

Korpusa yazılan her dosya `mevzuat_id`, kaynak ve çekilme tarihini taşır;
böylece üretilen her atıf resmî metne kadar izlenebilir. Belge analizinin
MCP-first yolu, hangi `mevzuat_id`'nin kullanıldığını `source` metadata'sında
(`"mcp:<id>"`) taşır, aynı gerekçeyle.

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
`app/ai/embeddings/chunking/` altında 4 bölücü sınıfı bulunur, ama **production'da yalnızca biri kullanılıyor**:

1. **RecursiveChunker** (`recursive.py`) — **tek production stratejisi.** Paragraf, cümle ve kelime sınırlarını koruyarak metni rekürsif olarak böler; `add_start_index=True` sayesinde her chunk'ın kaynak metindeki karakter ofsetini taşır, bu da `_index_for_qa`'nın `[s. N]` sayfa atıflarını kurmasını sağlar. Boyut/overlap parametreleri `app.ai.policy.schema.ChunkingPolicy`'de tek kaynaktan yönetilir (bkz. o sınıfın docstring'i).
2. **CharacterChunker** (`character.py`) — basit karakter sınırı ve overlap odaklı bölücü; yalnızca test/karşılaştırma amaçlı, hiçbir production çağrı yerinde kullanılmıyor.
3. **SemanticChunker** (`semantic.py`) — cümleler arası kosinüs benzerliği analiziyle bölen bölücü. **Hiçbir production yoluna bağlı değil ve olduğu gibi bağlanmamalı**: `start_index` üretmiyor (sayfa atıfı kaybolur), Türkçe cümle ayırıcı regex'i yaygın kısaltmaları ve büyük ünlüleri (İ/Ş/Ğ/Ç/Ö/Ü) doğru işlemiyor, ve üst boyut sınırı/overlap'i yok. Ayrıntılar ve production'a bağlanmadan önce çözülmesi gerekenler sınıfın kendi docstring'inde. Şu an yalnızca `evaluation`'ın retrieval eval suite'inde bir keşif kolu olarak kullanılıyor.
4. **AgenticChunker** (`agentic.py`) — LLM/Ajan yardımıyla metni mantıksal bölümlere ayıran, her parçaya özel başlık ve özet üreten bölücü. Production'a bağlı değil; upload anında belge başına LLM çağrısı gerektirdiği için ~28 tok/s yerel model üzerinde production yolu olarak uygun değil.

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




