# CHANGELOG

Tüm önemli değişiklikler bu dosyada kayıt altına alınacaktır.

## [3.19.0] - 2026-08-18
### Düzeltildi
- **Taslak brief'inde belge varlıkları eksikti** -- doküman analizi bir CV/
  evrakta geçen önemli varlık isimlerini (kişi, kurum, tarih, tutar vb.)
  zaten deterministik olarak çıkarıyordu (`EvrakField.entities`), ama
  `draft_graph._build_brief` bunu hiç okumuyordu. "Bu CV'de çalıştığı
  kurumları belirt" gibi bir istek, yazar bu bilgiyi hiç görmediği için
  `[BİLGİ EKSİK: ...]` yer tutucusuna düşüyor ve insan onay kapısı
  kullanıcıya belgenin zaten cevapladığı bir soruyu soruyordu. Brief'e yeni
  bir "Belgede Geçen Diğer Önemli Varlıklar" satırı eklendi.
- **Revizyonda yanlış paragraf hedefleniyordu ("sayıyı siliyor" hatası)** --
  üretilen bir taslakta `Konu:`/`Sayı:`/`Tarih:` satırları aralarında boş
  satır olmadan art arda geldiği için (bkz. `writer.md`'nin sabit yapısı),
  `instruction.py::_split_paragraphs` bunları TEK bir blok olarak
  `paragraphs[0]`'a yerleştiriyordu. "1. paragrafı sil"/"girişi değiştir"
  gibi talimatlar bu yüzden mektubun gerçek gövdesi yerine bu metadata
  bloğunu hedefliyor, reviser'a alakasız bir gövde talimatını `Sayı:`
  satırına uygulaması söyleniyordu -- kullanıcının "rastgele saçma sapan
  şeyler yapıyor" olarak tarif ettiği davranışın kök nedeni buydu. Ordinal/
  "giriş" hedeflemesi artık saf metadata bloklarını (`Sayı`/`Tarih`/`Konu`/
  `Muhatap`/`İlgi`/`Ekler` etiketli satırlar veya "T.C." anteti) atlıyor;
  `konu`/`kapanış`/`imza` bölüm ipuçları değişmeden tam listede aramaya
  devam ediyor.
- **Revizyonda silme talimatı hâlâ güvenilir değildi** -- önceki dalda
  (#209 PR'ı, artık main'de) eklenen düzeltmeye ek olarak, yukarıdaki yanlış
  hedefleme bug'ı da silme talimatlarının "rastgele" görünmesine katkıda
  bulunuyordu; doğru paragrafı hedeflemek bu ikinci kaynağı da kapatıyor.
- **Kapanış talimatı bazen sessizce taslak turuna dönüşüyordu (uzun süredir
  bilinen, ortam kaynaklı sanılan bir test hatası)** -- kök neden aslında
  iki gerçek router hatasıydı, ortam kısıtı değil: (1) `REVISE_RULES` yalnızca
  "kapanışı **değiştir**" yüzeyini tanıyordu, "kapanışı 'X' **yap**" gibi
  aynı isteğin farklı bir fiille söylenmiş hali hiçbir kurala hiç değmiyordu;
  (2) değse bile, mesaj kısa olduğu ve "yap" ile bittiği için (bir
  `CONTINUATION_SURFACES` yüzeyi) `draft.continuation` sezgiseli aynı anda
  ateşleniyor, "kapanış" alanını açıkça adlandıran çok daha spesifik
  `revise.explicit_request` kanıtına rakip bir `draft` puanı ekliyordu ve
  çoğu zaman onu geçiyordu. `intent_rules.py`'ye çıplak "kapanisi" yüzeyi
  eklendi; `intent_scorer.py`'deki devam sezgiseli artık mesajda zaten
  farklı bir amaç için açık bir kural ateşlenmişse devreye girmiyor.
  `tests/integration/test_brief_survives_into_revise.py`'nin önceden
  "bilinen, ortam kaynaklı" sayılan başarısızlığı bu düzeltmeyle gerçekten
  çözüldü.

### Test
- `docker compose run --rm backend pytest -q` → **2262 test geçti, 0
  başarısız** -- daha önce "bilinen ön-var olan hata" sayılan test artık
  gerçekten geçiyor.

## [3.18.0] - 2026-08-18
### Düzeltildi
Canlı kullanımda tespit edilen 10 ayrı taslak-akışı hatası (#209). Kök
nedenlerin çoğu üç ortak desende toplandı: turn-scoped olması gereken
state'in session-scoped tutulması, guardrail'lerin fail-secure tarafa aşırı
agresif ayarlanmış olması, ve taslak prompt'unun özet dışında hiçbir kaynak
metne erişememesi.

- **State izolasyonu** -- ikinci bir taslak turn'ü artık önceki taslağın
  muhatap/yazan taraf/kapanış cevaplarını miras almıyor
  (`planning_graph._step_brief` yalnızca aktif bir `revise` turn'ünde
  `prior_brief`'i taşıyor; `focus.py::compute_focus_update` `writing_brief`'i
  her draft turn'ünde değiştiriyor); frontend'de `PromptQuestionCard`/
  `InterruptPanel` artık `interrupt_id`/`message.id` ile keylenip soru
  kimliği değiştiğinde local state'i sıfırlıyor.
- **Otomatik tarih** -- kullanıcıya asla tarih sorulmuyor; `app.ai.workflows.
  dates.today_tr()` sunucu tarafında çözülüp brief'in "0. BUGÜNÜN TARİHİ"
  bölümüne enjekte ediliyor, `fill_date_placeholders` deterministik
  backstop olarak kalan tüm `[Tarih]` yer tutucularını dolduruyor.
- **"İnsan onayı" kaldırıldı** -- `draft_approval` gate'i tamamen silindi;
  yalnızca `missing_information` (eksik bilgi) kapısı kaldı, UI'daki
  "İnsan onayı gerekiyor" ibaresi hiçbir bileşende görünmüyor.
  `requires_human_approval` veri modeli olarak (skorlama/audit için) korundu.
- **Birim önerisi hiçbir zaman boş dönmüyor** -- `routing_graph` artık
  model hatası/liste dışı yanıt/düşük skor durumlarının hepsinde
  deterministik bir `_best_effort_unit` fallback'iyle en az bir birim +
  bir alternatif döndürüyor; frontend'e `UnitPicker` bileşeni eklendi
  (seçici + "Diğer birim…" serbest metin).
- **Relevance guardrail'i** -- "bu CV'yi ekibe katılım metni yap" gibi
  belgeye açıkça işaret eden istekler artık yanlışlıkla `unrelated`
  sayılmıyor (yeni deiktik referans kuralı + genişletilmiş karşılaştırma
  yüzeyi); model yalnızca `confidence >= 0.7` iken reddedebiliyor.
- **PII guardrail'i** -- hard block artık yalnızca belgenin kendi
  `gizlilik_derecesi` etiketi GİZLİ/ÇOK GİZLİ olduğunda ve deterministik bir
  PII bulgusu varken tetikleniyor; LLM judge tek başına asla bloklamıyor.
  Adres detector'ü `no:`/`kat:` gibi yalnız unit-keyword satırlarını artık
  adres saymıyor; her blok/maskeleme kararı tetikleyici `rule_id`'yi
  açıklayan bir mesaj üretiyor.
- **Rol farkındalıklı placeholder'lar** -- çıplak `[Ad Soyad]`/`[Unvan]`/
  `[İmza]`/`[Kurum Adı]` artık `normalize_role_placeholders` ile
  "[İmzalayacak yetkilinin adı ve soyadı]" gibi kime ait olduğu açık
  metinlere dönüştürülüyor (dilekçelerde dilekçe sahibine atfediliyor).
- **Alıcı (muhatap) çıkarımı** -- "Ahmet Yılmaz'a bir izin yazısı hazırla"
  artık muhatabı tekrar sormuyor: kesmesiz datif, "Sayın X", "X için",
  "X Bey'e/Hanım'a" desenleri eklendi; tek aday + bir yazma fiili birlikte
  geçtiğinde slot doğrudan çözülüyor, birden fazla aday veya fiilsiz bir
  isim geçişi hâlâ bir onay sorusu üretiyor.
- **Taslak RAG grounding'i** -- yazar artık yalnızca belgenin özetini değil,
  `document_qa` koleksiyonundan (asistanın `search_document` aracının da
  kullandığı) getirilen birebir alıntıları da görüyor. Yeni
  `draft_graph.retrieve_source_chunks_node`, `retrieve_examples`'la aynı
  degrade-on-failure desenini izliyor (bütçe aşımı/hata → sıfır alıntı,
  asla başarısız taslak) ve brief'e "9. BELGEDEN İLGİLİ ALINTILAR" bölümünü
  ekliyor; `DraftPolicy.source_chunks_enabled`/`source_chunk_count`/
  `source_chunk_char_budget` ile yönetiliyor.

Ayrıca, #209 listesinde olmayıp bu dalda test edilirken canlıda tespit
edilen ek bir revizyon hatası:

- **Revizyonda silme talimatı dinlenmiyordu** -- hedeflenecek paragraf/bölüm
  isim/numara ile belirtilmediğinde ("...paragraftan bir kısmı sil" gibi),
  tüm taslağı yeniden yazan prompt'un kendi "zaten doldurulmuş bilgileri
  asla silme" kuralı kullanıcının silme talimatıyla doğrudan çelişiyordu;
  reviser talimatı yine de uygularsa bu kez `detect_content_loss`'un
  kısaltma anahtar kelime listesi yalnızca "kısalt"/"özetle" gibi fiilleri
  tanıdığından, gerçek silme kaynaklı küçülme kazara içerik kaybı sayılıp
  onarım döngüsüyle geri getiriliyordu -- talimat sessizce iptal edilmiş
  oluyordu. Prompt'un kuralı silme talimatları için açık bir istisna
  içerecek şekilde yeniden yazıldı; `_SHORTENING_KEYWORDS`'e "sil"/"çıkar"/
  "kaldır" eklendi.

### Test
- `docker compose run --rm backend pytest -q` → **2196 test geçti**, 1
  bilinen (bu değişikliklerden bağımsız, `main` üzerinde de aynı şekilde
  başarısız) ön-var olan hata hariç.
- `cd frontend && npx vitest run` → tüm testler geçti; `İnsan onayı`/
  `insan onay` dizesi hiçbir bileşende kalmadı.

## [3.17.0] - 2026-08-17
### Eklendi
İnternal communication + AI-assisted artifact transfer planının **Faz 5**'i
(#205) -- sertleştirme: transferi kalıcı bir gözlemlenebilirlik yüzeyine
bağlamak, alıcının paylaşılan bir evrak snapshot'ını gerçekten kendi
evrakına dönüştürebilmesi, ve chat/REST üzerinden tek seferde birden fazla
kişiye gönderim.

- **`POST /pools/items/{item_id}/adopt`** (`DocumentService.
  adopt_pool_item`) -- copy-on-write. Faz 3'ün transfer akışı bir evrakı
  gönderdiğinde alıcının `document_pool_items` satırı bugüne kadar hâlâ
  **göndericinin** `documents` satırına işaret ediyordu
  (`PoolService.file_transferred_document`): alıcı görüntüleyebiliyor ama
  gerçek sahibi değildi, metadata'sını düzenleyemiyordu. `adopt` blob'u
  `BaseStorage` üzerinden kopyalıyor (yerel dosya yolu varsayılmıyor -- S3
  altında `storage_path` bir `s3://...` URI'dir), alıcı adına yeni bir
  `documents` satırı açıyor (transfer anındaki `metadata_snapshot`'tan
  dolduruluyor -- göndericinin o andan sonra değiştirmiş olabileceği canlı
  satırından değil), analiz cache JSON'unu yeni storage_path altına
  kopyalıyor, ve Q&A için yeniden indeksliyor. Pool item'ın kendisi yeni
  belgeye yeniden işaretleniyor (`source="adopted"`, `metadata_snapshot`
  temizleniyor, `transferred_by` provenance olarak kalıyor) -- ikinci bir
  pool item satırı açılmıyor. Yalnızca pool'un kendi sahibi çağırabilir;
  Admin/Manager bypass'ı yok (kişisel bir kopya oluşturuyor).
  **Bilinçli sınır**: plan "arq indexing worker'a job at" diyordu ama bu
  depoda evrak indeksleme için hiç arq worker'ı yok (tek bağlı arq job'u
  LoRA training, `app.workers.queue`) -- yeni bir worker altyapısı kurmak
  orantısız olurdu; reindeksleme, upload akışının zaten yaptığı gibi
  senkron çalışıyor.
- **Prometheus transfer metrikleri** (`observability/transfer_metrics.py`,
  `ai_metrics.py`/`company_metrics.py` ile aynı desen):
  `kachow_artifact_transfers_total{channel,result}` (her
  `ArtifactTransferService.execute()` sonucu -- `success`/`denied`/
  `not_found`; idempotent bir tekrar denemesi sayılmıyor, yeni bir deneme
  değil) ve `kachow_transfer_policy_denials_total{reason}`
  (`TransferPolicy` red sebepleri: `self_transfer`/`recipient_inactive`/
  `clearance`/`favorite_required`). `monitoring/dashboards/
  transfers_dashboard.json` -- yeni bir pano, `company_dashboard.json`'un
  panel şablonunu izliyor.
- **Grup transferi, yalnızca chat/REST** -- araştırma sırasında ortaya
  çıktı: transfer o ana kadar tamamen tek alıcılıydı
  (`TransferCommand.recipient_id: str`), grup transferi hiç yoktu.
  `ArtifactTransferService.execute_group(GroupTransferCommand)` her alıcı
  için var olan `execute()`'u tek tek çağırıyor -- ikinci bir transfer
  implementasyonu yok -- ve `PoolService.push`/`_push_one`'daki
  per-recipient partial-success desenini izliyor: bir alıcının reddi
  (`NotFoundException`/`AuthorizationException`/`ValidationException`)
  diğerlerini bloklamıyor. `POST /transfers/send-group`, en fazla
  `MAX_GROUP_TRANSFER_RECIPIENTS = 50` alıcı. **AI kanalına bilinçli
  olarak bağlanmadı**: `propose_transfer` tool'u ve `TransferGraphProvider`
  değişmedi, tek alıcı olarak kalıyor -- kullanıcıyla konuşulup üzerinde
  anlaşılan kapsam.

### Test
- `docker compose run --rm backend pytest tests/unit tests/integration -q`
  → **2052 test geçti** (+29): `adopt_pool_item`'ın her dalı (yetki, pool
  sahipliği, transfer-olmayan item reddi, storage hatası, snapshot'tan
  doldurma, cache kopyalama + reindeksleme, quota), `execute_group`'un
  boş/aşırı-kalabalık liste reddi, partial-success, her zaman `channel=
  "chat"`, alıcı başına ayrık idempotency key; her yeni Prometheus sayacı
  artışı (başarı/red/bulunamadı/policy-reason); gerçek Postgres üzerinde
  uçtan uca grup transferi (bir alıcı `self_transfer` ile reddedilirken
  diğeri başarıyla gönderiliyor) ve adopt (gerçek `LocalStorage` blob
  kopyası + yeni `documents` satırı + orijinalin dokunulmamış kalması).
- Yeni migration yok -- `metadata_snapshot`/`transferred_by` kolonları
  Faz 4'te zaten vardı, yalnızca `source` sütununun kabul ettiği değer
  kümesi genişledi (uygulama seviyesinde, DB constraint'i yok).

Refs: [#205](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/205).

## [3.16.0] - 2026-08-17
### Eklendi
İnternal communication + AI-assisted artifact transfer planının **Faz 4**'ü
(#201): asistanın "son taslağı Ahmet'e gönder" isteğini deterministik
resolution + policy + zorunlu human confirmation + idempotent execution
zinciriyle karşılaması. Faz 3'te (#199) kurulan `ArtifactTransferService`
tek transfer yolu olarak aynen kullanıldı -- yeni bir execution path yok,
yalnızca AI kanalından bu yola erişim.

Giriş noktası **asistanın kendi tool-calling mekanizması** -- ayrı bir plan
intent'i değil. İlk taslakta transfer, `_try_compound` gibi fusion'dan önce
çalışan bağımsız bir lexical kapıydı (`planner._try_transfer`); iş akışı
grafiğinde bunun görünürlüğü ve `search_document` gibi mevcut tool'larla
tutarlılığı gözden geçirilince, mimari `propose_transfer` adlı bir
**assistant tool**'una taşındı -- artık asistan hangi mesajın transfer
istediğine kendi muhakemesiyle karar veriyor, sabit bir fiil+isim listesine
değil.

- **`propose_transfer`** (`ai/tools/transfer_tools.py`) -- assist adımının
  modelinin çağırabileceği yeni tool, `search_document`'la aynı
  `ToolSpec`/tool-loop mekanizmasından geçiyor. Modelin tek işi
  `recipient_name`/`artifact_kind`'ı tool argümanı olarak çıkarmak --
  hiçbir zaman bir karar değil. Tool **yalnızca önerir**: taslağı/evrakı ve
  alıcıyı deterministik olarak çözer (`ArtifactResolutionService`,
  `RecipientResolutionService`), bir `artifact_transfer_intents` satırı
  açar, sonucu bir yan-kanal callback'le (`on_transfer_proposed`,
  `on_tool_result`/`on_anchor_referenced` ile aynı desen) `_step_assist`'e
  bildirir. Gerçek gönderim asla tool'un kendisinde olmuyor.
- **Neden tool `interrupt()`'u kendisi çağırmıyor**: bir tool handler'ı
  assist adımının kendi node'u içinde çalışıyor, ve `interrupt()` resume'da
  *kendi sahibi node'u* baştan tekrar çalıştırıyor -- assist için bu,
  modelin tüm yanıtının (ve o turdaki her tool çağrısının) ikinci kez
  çalışması demek olurdu; `brief_gate`/`human_gate`'in tam olarak bu
  maliyetten kaçınmak için ayrı node'lara bölünmüş olma nedeni. Bunun
  yerine `_step_assist`, tool'un ürettiği öneriyi görünce turu
  `transfer_gate_node`'a yönlendiriyor -- kendi ayrı node'unda, güvenle
  `interrupt()` edilebilen.
- **`ArtifactResolutionService`** (`domains/transfers/artifact_resolution.py`)
  -- "hangi taslak/evrak" sorusunun DB tabanlı, `SessionFocus.active_draft`'ın
  idle-limitinden tamamen bağımsız cevabı: açık referans → oturumun son
  taslağı (`get_latest_for_session` -- araya kaç tur girerse girsin durur)
  → kullanıcının en son taslakları → birden fazlaysa `ambiguous`, hiç yoksa
  `unresolved`. Bu, kullanıcının orijinal senaryosunu ("taslak yazdır, başka
  işler yap, sonra gönder") çalışır kılan parça.
- **`TransferIntentService`** (`domains/transfers/intent_service.py`) --
  `artifact_transfer_intents` üzerinde CAS tabanlı state machine
  (`INTENT_DETECTED → {AMBIGUOUS, RECIPIENT_RESOLVED, UNRESOLVED} →
  {AWAITING_CONFIRMATION, POLICY_DENIED} → {CONFIRMED, CANCELLED} →
  {TRANSFER_EXECUTED, FAILED}`). Her geçiş tek bir `UPDATE ... WHERE
  state IN (...)`; `confirm()` politikayı TOCTOU korumasıyla sıfırdan
  yeniden değerlendirir (favori kaldırılmış/yetki değişmiş mi diye
  `policy_hash` karşılaştırması), `execute()` `CONFIRMED` olmayan hiçbir
  şeyi çalıştırmaz -- "onaysız transfer" garantisi burada, LLM'in, tool'un
  ya da graph'ın inandığı şeyden tamamen bağımsız olarak.
- **`transfer_gate` / `transfer_execute`** -- `transfer_gate_node` tek bir
  `interrupt()` node'unda hem `artifact_transfer_disambiguate` (alıcı
  belirsizse, seçim **her zaman insan**) hem `artifact_transfer_confirm`'i
  (asıl gönderim onayı) barındırıyor. Checkpointer yoksa öneri iptal edilir,
  asla onaysız çalışmaz.
- **`AI_TRANSFER_ENABLED`** (varsayılan `true`) -- kapalıyken
  `propose_transfer` modele hiç sunulmuyor, sistem Faz 4 öncesiyle bit-bit
  aynı davranıyor.
- **Frontend**: `TransferConfirmCard` -- `InterruptPanel`'e dal, iki
  interrupt türünü de render ediyor. Cross-unit uyarısı her zaman
  `payload.cross_unit`'ten (backend'de `TransferPolicy` tarafından
  hesaplanmış) okunuyor, hiçbir zaman üretilmiş metinden değil.
  `DecisionFlow`'un dinamik iş akışı stepper'ında `transfer_gate`, tetikleyen
  adımı olan "Asistan" aşamasının altına toplanıyor (`brief_gate`'in
  `brief` altına toplanması gibi).

### Bilinçli sınırlar
- Ayrı ve izole bir semantik katman (embedding benzerliği, kendi
  `"transfer_gate"` prototip ailesinde, kalibre edilmiş "intent" ailesinin
  kalibrasyonuna dokunmadan) denendi, **gerçek `nomic-embed-text`
  vektörleriyle ölçüldü ve geri alındı** -- artık ihtiyaç da kalmadı
  (giriş noktası zaten modelin kendi muhakemesi), ama ölçüm bulgusu ileride
  benzer bir katman denenirse diye kayıtlı: 5 örnekli küçük bir prototip
  seti bu embedding modeliyle temiz ayrışmıyor -- "Bu evrakı analiz eder
  misin?" (belirsiz olmayan bir `analyze` isteği) `transfer` prototiplerine
  karşı 0.858 benzerlik / 0.121 marj skorladı, mevcut kalibre-aile
  eşiklerini bile geçerek. Gerçek transfer parafrazlarından bazıları bu
  yanlış pozitiften **daha düşük** skorladı. `SemanticPolicy`'nin "intent"
  ailesi için zaten belgelediği bulgu burada da geçerli: rastgele karar
  veren bir katman, hiç katman olmamasından daha kötü.
- Evrak (document) için ladder'ın "açık referans" katmanı bağlanmadı --
  yalnızca `SessionFocus.active_document_id` ipucu kullanılıyor; serbest
  metinden başlık/sürüm çözümlemesi bu fazın kapsamı dışında.
- Artifact belirsizliği (birden fazla taslak eşleşmesi) tool'un kendi
  metin yanıtıyla çözülüyor, recipient belirsizliği gibi ayrı bir
  interrupt/seçim kartı almıyor -- `artifact_transfer_intents` şeması
  yalnızca `candidate_recipients` taşıyor, aday artifact listesi için bir
  alan yok.
- `MAX_TOOL_TURNS = 2` sınırı transfer için de geçerli: model iki tur
  içinde `propose_transfer`'ı çağırıp yanıt üretmezse (örn. önce başka bir
  tool deneyip sonra transfer'e karar verirse), o turda transfer önerisi
  hiç oluşmaz -- kullanıcı isteğini tekrarlamalı. Kabul edilebilir: aynı
  sınır `search_document`/`search_legislation` için de zaten geçerliydi.

### Test
- `docker compose exec backend pytest tests/unit tests/integration -q` →
  **2023 test geçti**: `TransferIntentService`'in her CAS geçişi + TOCTOU +
  `execute()`'un onaysız reddi, `ArtifactResolutionService`'in her ladder
  katmanı, `propose_transfer`'ın handler'ı (her dal: çözülen/belirsiz
  alıcı, bulunamayan/belirsiz taslak, policy reddi, evrak türü),
  `app.ai.*`'nin `app.domains.*` import etmediğinin AST tabanlı statik
  denetimi, ve gerçek derlenmiş planning graph üzerinde -- modelin tool
  çağırma kararı `FakeLLMClient.generate_with_tools_side_effect` ile
  senaryolanarak -- uçtan uca disambiguate→confirm→execute/reject/
  policy-denial/flag-off/no-checkpointer akışları.
- `docker compose exec frontend npm run typecheck && npm run test && npm run lint`
  → **178/178 test geçti** (6 yeni: `TransferConfirmCard`, cross-unit
  uyarısının `payload.cross_unit` ile birebir eşleştiği dahil).
- Yeni migration yok (`artifact_transfer_intents` Faz 3'te zaten migrate
  edilmişti, kullanılmadan) -- `alembic check`'te bu fazdan kaynaklı yeni
  bir drift yok.

Refs: [#201](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/201).

## [3.15.0] - 2026-08-17
### Eklendi
İnternal communication planının **Faz 3**'ü (#199): taslak/evrak transferini
tek bir deterministik domain katmanına indiren backend + bu katmanı chat
üzerinden manuel kullanan frontend. AI/agent katmanına hiçbir dokunuş yok --
transfer intent tespiti, slot extraction, confirmation state machine Faz 4'te.

- **`ArtifactTransferService.execute`** (yeni, `domains/transfers/`): artık
  *her* kanaldan (chat, eski REST, ileride AI) her transfer bu tek yoldan
  geçiyor -- idempotency kontrolü → PDP (`Action.ARTIFACT_TRANSFER`) →
  `TransferPolicy` (self-send/pasif alıcı/gizlilik/yalnızca-AI-kanalında-
  favori) → snapshot (taslak fork'u veya evrak pool item + metadata
  snapshot) → `artifact_transfers` satırı → alıcıyla DM'e
  `kind="artifact"` mesajı → best-effort audit + bildirim.
- **`DraftShareService.send`** artık bu servise delege ediyor;
  **`respond(status="accepted")` artık fork'lamıyor** -- alıcı kopyasını
  zaten *gönderim anında* alıyor (çift fork bug'ı giderildi). Kabul etmek
  artık yalnızca bir durum geçişi.
- **`POST /transfers/send`**: chat üzerinden taslak/evrak gönderme için
  birincil yeni yol. `GET /transfers/{id}`, `GET /transfers/recommendations`
  (taslağın yönlendirildiği birim → favoriler öncelikli üye listesi, yeni
  bir AI çağrısı yok).
- **`drafts.destination_unit_id`/`destination_justification`** (yeni
  kolonlar, geriye dönük backfill'li): yönlendirmenin serbest metin birim
  adını her göndermede yeniden aramak artık gerekmiyor.
- **`document_pool_items.metadata_snapshot`/`transferred_by`**: evrak
  blob'u paylaşımlı ve hiç mutasyona uğramıyor, ama metadata'sı
  (`document_type`, `özet`, `gizlilik derecesi`...) transfer anında
  donduruluyor -- gönderen sonradan düzenlese bile alıcının gördüğü
  değişmiyor (entegrasyon testiyle doğrulandı).
- **Frontend**: `SendArtifactDialog` (composer'dan taslak/evrak seçip
  gönderme, yalnızca DM'lerde -- transferler 1:1), `ArtifactMessageCard`
  (thread içinde canlı transfer durumu -- başlık/durum asla mesajda
  önbelleklenmiyor, her zaman `GET /transfers/{id}`'den okunuyor).

### Bilinçli sınırlar
- `RecipientResolutionService`/`RecipientRecommendationService` bu fazda
  inşa edildi ve tam test edildi, ama henüz bir çağıranı yok -- manuel
  kanallar (chat composer, eski `/drafts/{id}/send`) zaten Faz 2'nin
  kullanıcı arama UI'ı üzerinden açık bir `recipient_id` taşıyor. İlk
  gerçek çağıran Faz 4'ün AI kanalı olacak.
- Çok alıcılı `POST /drafts/{id}/send` artık kesin all-or-nothing değil --
  her alıcının transferi artık bağımsız commit ediliyor. Frontend
  tüketicisi olmadığı için (doğrulandı) blast radius düşük.
- Evrak transferinde "Aç" eylemi yok -- alıcı evrakı kendi evrak havuzundan
  görüntülüyor, ayrı bir detay sayfası bu fazda yok.

### Test
- `docker compose exec backend pytest tests/unit tests/integration -q` →
  **1983 test geçti** (126 yeni: `TransferPolicy`'nin her deny sebebi,
  `ArtifactTransferService`'in idempotency/authorization/snapshot/delivery
  yolları, recipient resolution/recommendation, PDP `ARTIFACT_TRANSFER`
  kapsamı, gerçek Postgres üzerinde RLS izolasyonu ve uçtan uca
  taslak-fork-bağımsızlığı + evrak-snapshot-değişmezliği + idempotency
  doğrulamaları).
- `docker compose exec frontend npm run typecheck && npm run test && npm run lint`
  → **172/172 test geçti** (6 yeni: `ArtifactMessageCard`).
- `alembic check` yeni tablolar/kolonlar için temiz; `alembic downgrade -3`
  / `upgrade head` round-trip doğrulandı.

Refs: [#199](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/199).

## [3.14.0] - 2026-08-16
### Eklendi
Şirket içi iletişim planının **Faz 2**'si (#196): Faz 1'de (#194/#195) kurulan
mesajlaşma backend'ini tüketen frontend. Backend/AI katmanına hiçbir dokunuş yok.

- **`/messages`, `/messages/:conversationId`** (yeni sayfa): `ConversationList`
  (DM/grup listesi, okunmamış rozeti) + `MessageThread` (keyset "eski
  mesajları yükle") + `MessageComposer` (Enter=gönder, Shift+Enter=yeni satır --
  `ChatComposer` ile aynı konvansiyon). `NewConversationDialog` (DM/Grup
  sekmeleri) ve `UserSearchDrawer` ("Kişiler" paneli) ortak bir `PersonPickerBody`
  üzerinden besleniyor -- arama/filtre/favoriler-boşken görünümü tek yerde.
- **`GroupParticipantsPanel`**: grup üyesi ekleme/çıkarma yalnızca grup sahibi
  veya şirket geneli yetkiye (ADMIN/MANAGER/ROOT) sahip kullanıcılara açık --
  backend'in kendi yetki asimetrisini birebir yansıtıyor, bu UI'ın izin verdiği
  değil.
- **`NotificationBell`**: `GET /notifications/stream` nihayet bağlandı --
  draft-sharing işinden beri var olan ama hiç tüketilmeyen endpoint. Panel bir
  portal ile `position: fixed` render ediliyor: `.app-sidebar`'ın kendi
  `overflow: hidden`'ı yüzünden normal bir mutlak konumlu açılır panel
  kenar boyunca kırpılırdı.
- **`useMessagingStream`/`useNotificationsStream`**: SSE, `AppShell`'in
  kendisinde bağlanıyor (yalnızca `/messages` sayfasında değil) -- kullanıcı
  başka bir sayfadayken de kenar çubuğundaki okunmamış rozeti canlı kalıyor.
- **`services/sse.ts`** (yeni): `chatService.consumeSseStream`'den farklı, ham
  JSON okuyan minimal bir SSE reader -- `/messaging/stream` ve
  `/notifications/stream`'in `WorkflowEvent` zarfı yok, doğrudan kaynağın
  kendisini (`Message`/`Notification`) taşıyorlar.
- **`GET /units`, `GET /notifications`** için frontend tüketicisi yoktu; bu
  fazla ikisi de (birim filtre dropdown'ı, bildirim zili) ilk kez bağlandı.
- **`npm run api:types` düzeltildi**: yanlış bir yola işaret ediyordu
  (`http://localhost:8000/openapi.json`, doğrusu
  `http://localhost:8000/api/v1/openapi.json` -- backend `openapi_url` olarak
  `{API_V1_STR}/openapi.json` kullanıyor). Bu, bu PR'dan önce var olan bir
  kopukluktu -- `src/api/generated.ts` Faz 1 backend uçları eklenmeden önceki
  tarihte (15 Ağustos) donmuştu. Düzeltilmiş yola karşı yeniden üretildi:
  yalnızca yeni `/messaging/*`, `/users/search`, `/users/me/favorites/*`
  yolları eklendi, mevcut hiçbir yol kaldırılmadı.

### Bilinçli sınırlar
- Sanal listeleme/otomatik en alta kaydırma performans optimizasyonu yok --
  uzun bir sohbet geçmişinde `MessageThread` tüm yüklenmiş mesajları render
  ediyor; keyset "eski mesajları yükle" akışı zaten sayfa başına 50 mesajla
  sınırlı olduğu için bu ölçekte gözlemlenebilir bir sorun değil.

### Test
- `docker compose exec frontend npm run typecheck && npm run lint && npm run test`
  → **166/166 test geçti** (24 yeni: `sse.ts` SSE frame ayrıştırma,
  `useConversations`/`useMessageThread`/`useFavorites`/`useUserSearch` hook
  testleri, `ConversationList`/`MessageComposer` bileşen testleri).
  `AppShell.test.tsx` `QueryClientProvider` ile sarmalandı -- `AppShell` artık
  react-query hook'ları mount ediyor.

Refs: [#196](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/196).

## [3.13.0] - 2026-08-16
### Eklendi
Şirket içi iletişim + AI-assisted artifact transfer planının **Faz 1**'i (#194):
DM + grup mesajlaşma domain'i, favoriler ve kullanıcı arama. AI/agent katmanına
hiçbir dokunuş yok -- bu tamamen deterministik zemin, sonraki fazların (frontend,
transfer domain'i, AI-assisted transfer) üzerine oturacağı.

- **`app.domains.messaging`** (yeni): `conversations`/`conversation_participants`/
  `conversation_messages` (migration `0022`). Bir konuşmaya erişim ABAC kararı
  değil -- `conversation_participants` satırının kendisi erişim grant'i, tıpkı
  `draft_shares`'ın zaten kurduğu desen gibi. DM idempotent: `dm_key` üzerinde
  `WHERE kind='dm'` partial unique index, iki kullanıcı arasında ikinci bir DM
  açılmasını uygulama kodu değil veritabanının kendisi engelliyor. Grup yönetimi
  (yeniden adlandırma, başkasını çıkarma) `PoolService`/`DraftShareService`'in
  zaten kullandığı `bypasses_ownership` asimetrisiyle -- yeni bir ABAC action'ı
  eklenmedi, gerek yoktu. Soft-leave: ayrılan bir katılımcı geçmişi okuyabilir,
  yeni mesaj gönderemez. Okunmamış sayısı `last_read_message_id`'nin işaret
  ettiği mesajın `created_at`'ıyla karşılaştırılarak hesaplanıyor (mesaj id'leri
  sıralı değil, opak uuid-hex). `GET /messaging/stream`: `notifications/router.py`
  ile birebir aynı Redis pub/sub SSE deseni, ayrı kanal prefix'i.
- **`user_favorites`** (yeni, migration `0023`): tek yönlü, kullanıcı başına
  favori listesi. Faz 4'teki AI-assisted transfer akışının zorunlu tutacağı
  kapı burada temelleniyor.
- **`GET /users/search`**: isim (kullanıcı adı/e-posta -- `UserModel`'de ayrı bir
  görünen-ad kolonu yok), birim, rol filtreleri. Enumeration'a karşı rate limit +
  minimum 2 karakter.
- **`ConversationMessageCreatedEvent`**: `DraftSharedEvent`'in aktif alıcı başına
  bir kez yayınlama deseninin birebir aynısı. Bildirim gövdesi her zaman kısa bir
  `body_preview` -- tam mesaj içeriği yalnızca katılımcılık-korumalı thread'de.

### Test
- `docker compose exec backend pytest tests/unit tests/integration -q` →
  **1918 test geçti** (120 yeni: mesajlaşma/favori servis unit testleri,
  bildirim subscriber testleri, `conversation_participants`/`conversations`/
  `conversation_messages`/`user_favorites` için RLS izolasyon testleri, gerçek
  Postgres üzerinde uçtan uca DM/okunmamış/soft-leave senaryoları, kullanıcı
  arama SQL'inin repository seviyesinde doğrulanması).
- `alembic check` yeni tablolar için temiz; `alembic downgrade -2` /
  `upgrade head` round-trip doğrulandı.

Refs: [#194](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/194).

## [3.12.0] - 2026-08-16
### Eklendi
Faz C3'ün (#187) kendi gövdesinde ertelenen son parçası: gerçek LoRA/PEFT fine-tuning kodu ve
bunu kuyruğa alıp çalıştıran `arq` worker'ı (#191).

- **`backend/requirements-training.txt`**: `torch`/`transformers`/`peft`/`trl`/`datasets`/
  `accelerate` -- yalnızca yeni `deploy/docker/worker.Dockerfile` imajına giriyor, ana backend
  imajına değil. `bitsandbytes` bilinçli olarak dışarıda bırakıldı: arm64 host'ta wheel
  bulunamayıp build'i tamamen kırdı ve `app.ai.training.lora` zaten kuantizasyon kullanmıyor.
- **`arq` bağımlılık çakışması çözüldü**: `arq` kendi `redis<6` bağımlılığını zorunlu kılıyor
  (`redis==8.1.0` ile hiçbir sürümü uyumlu değil, doğrulandı). Proje genelinde `redis` `5.3.1`'e
  indirildi -- `RedisCache`'in gerçek kullanımı (`from_url`/`get`/`set`/`delete`/`aclose`) bu
  sürümler arasında değişmiyor, tam test paketiyle doğrulandı.
- **`app.ai.training.lora`** (yeni): `PreferencePair`'lardan SFT (`chosen`) ve DPO
  (`chosen`/`rejected`) örnek/JSONL export'u; gerçek `peft`/`trl` çağrıları
  (`get_peft_model`/`SFTTrainer`/`DPOTrainer`, DPO aşaması bir SFT adaptörünün üstüne devam
  edebiliyor); Ollama `Modelfile` üretimi. Ağır kütüphaneler tembel/opsiyonel import edilir --
  bu modülü import etmek (örn. ana backend süreci üzerinden), `peft`/`trl` kurulu olmasa bile
  asla patlamaz; yalnızca gerçek eğitim fonksiyonlarını çağırmak `RuntimeError` fırlatır.
- **`app.workers.queue`/`app.workers.training`** (yeni): `arq` job runner, mevcut Redis
  broker'ı üzerinden. `run_lora_training_job`: örnekleri derler, SFT/DPO JSONL'e döker, LoRA
  eğitir, Ollama `/api/create` HTTP API'siyle (CLI değil -- worker container'ında `ollama`
  binary'si yok) `kachow-{slug}:{run_id}` modelini yayınlar, ardından **shadow değerlendirme**
  yapar: mevcut model ile aday modeli aynı küçük tutulmuş örnek setinde çalıştırıp
  `verify_draft`'ın deterministik güven skorunu karşılaştırır -- aday modelin ortalama skoru
  belirgin şekilde düşükse (`SHADOW_EVAL_REGRESSION_MARGIN`), çalıştırma `failed` olur ve
  `CompanyModel.settings.llm_model_override` **hiç yazılmaz**.
- **`compose.yml`**: yeni `worker` servisi -- **varsayılan `docker compose up`'ta hiç
  başlamıyor** (`profiles: ["training"]`). `scripts/start_training_worker.sh` ile elle ayağa
  kaldırılıyor, `scripts/stop_training_worker.sh` ile durduruluyor. Bir LoRA çalıştırması
  (`POST .../training-runs?kind=lora_sft`) worker çalışmasa bile kuyruğa girer; hiçbir şey
  tüketmeden Redis'te bekler.
- **`POST /companies/{id}/training-runs`**'a `kind` parametresi: `style_adapter` (varsayılan,
  senkron) veya `lora_sft`/`lora_dpo` (kuyruğa alınır, `training_runs.status="queued"` ile
  döner).

### Bilinçli sınırlar
- Şirket bazlı model seçimi (`app.domains.companies.provider.get_llm_model_override`) yalnızca
  worker'ın kendi shadow-eval adımında kullanılıyor; canlı draft/revise grafiklerinin model
  seçimini istek başına şirkete göre değiştirmek (her istekte farklı grafik/istemci inşa etmek)
  ayrı, çok daha büyük bir mimari değişiklik -- kapsam dışı.
- `TRAINING_ARTIFACTS_DIR`'ın Ollama sunucu sürecinin de okuyabildiği bir yol olması gerekiyor
  (bu geliştirme ortamında Ollama host'ta çalışıyor, worker container'ında değil) -- bu,
  gerçek dağıtım topolojisine göre çözülmesi gereken bir bind-mount kararı, kod bunu kendi
  başına çözemez.
- Gerçek bir GPU eğitim koşusu bu ortamda **çalıştırılmadı** (kullanıcının açık isteği) --
  worker image'ı gerçek `torch`/`peft`/`trl`/`transformers` ile inşa edilip içe aktarma
  doğrulandı, ama fine-tuning gerçek bir GPU'lu host'ta ayrıca çalıştırılacak.

### Test
- `docker compose exec backend pytest -q` → **1876 test geçti** (29 yeni: `lora.py` saf
  fonksiyon + mock'lanmış eğitim orkestrasyonu testleri, `run_lora_training_job`'ın
  bulunamadı/eşik-altı/başarılı/regresyon/istisna yollarının tamamı, `enqueue_lora_training_run`,
  router'ın `kind` dallanması, `llm_model_override` okuma/yazma).
- `docker compose --profile training build worker` → **gerçekten inşa edildi** (2.57GB),
  `docker compose --profile training run --rm worker python -c "..."` ile worker image'ında
  `torch`/`peft`/`trl` gerçekten kurulu ve `app.workers.queue`/`app.ai.training.lora` sorunsuz
  import edildiği doğrulandı.
- `docker compose config --services` / `--profile training config --services` → `worker`
  servisinin varsayılan profilde **görünmediği**, yalnızca `--profile training` ile
  göründüğü doğrulandı.

Refs: [#191](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/191), #187.

## [3.11.1] - 2026-08-15
### Düzeltildi
- **Geçersiz/olmayan JWT ile giren kullanıcı artık `/login`'e yönlendiriliyor.**
  `compose.yml`'deki frontend servisinin `VITE_DEV_AUTH_BYPASS` varsayılanı `true`'ydu --
  gerçek bir oturum olmadan siteye girildiğinde sahte bir "Yerel geliştirici" hesabıyla
  doğrudan `/chats`'e düşülüyor, ardından backend'in kendi varsayılanı olan
  `REQUIRE_AUTH=true`'ya çarpan her istek 401 ile başarısız oluyordu. `VITE_DEV_AUTH_BYPASS`
  varsayılanı `false` yapıldı; `App.tsx`'in zaten var olan route guard'ı (`user ?
  <AuthenticatedApp/> : <Navigate to="/login"/>`) artık normal akışta çalışıyor. Bypass,
  backend'i bilerek `REQUIRE_AUTH=false` ile çalıştıran bir geliştirici için hâlâ elle
  (`VITE_DEV_AUTH_BYPASS=true`) açılabilir.

Refs: [#189](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/189)

## [3.11.0] - 2026-08-15
### Eklendi
Faz C2'yi (#185) takip eden, Faz C'nin son parçası: kullanıcıların 👍/👎 oyladığı taslaklardan
(Faz C1, #183) otomatik olarak `CompanyAdapter` (Faz C2) üslup kuralı çıkaran bir eğitim boru
hattı (Faz C3, #187).

- **`app.domains.training.*`** (yeni domain): `TrainingSampleModel`/`TrainingRunModel` +
  migration `0021_training.py` (RLS dahil). Bir tercih çifti örneği (`training_samples`) daima
  tek kanatlı: bir 👍 `chosen`-only, bir 👎 `rejected`-only bir satır üretir -- gerçek metin
  `feedback.draft_id` üzerinden `drafts.content`'e çözülüyor (feedback tablosunun kendisi ham
  metni hiç tutmuyor, bkz. `FeedbackModel`'in kendi docstring'i).
- **`app.ai.training.dataset`**/**`style_miner`** (yeni, `app.ai` katmanı -- `app.domains` import
  etmiyor, C2'nin kurduğu tek yönlü bağımlılık kuralıyla aynı): `compile_pairs_from_feedback`
  saf fonksiyonu + `mine_style` -- deterministik diff sinyalleri (ortalama uzunluk vb.) çıkarıp
  eğitim işi başına **tek** `fast_llm_client` çağrısıyla (mesaj başına değil, bkz. plan'ın A6
  notu) en fazla 10 üslup kuralı + 10 kaçınılacak kalıp üretir. `MIN_FEEDBACK_SAMPLES = 50`
  eşiğinin altında iş `skipped` olarak biter, boş bir adaptör yayınlanmaz.
- **`app.domains.training.service.TrainingService.run_style_adapter_training`**: derle → eşiği
  kontrol et → üslup madenciliği yap → `app.domains.companies.provider.set_company_adapter`
  (Faz C2) ile adaptörü versiyonlayarak yayınla. Otomatik çalıştırmalar `preferred_examples`'a
  asla dokunmuyor -- mevcut değeri `get_company_adapter`'dan okuyup aynen geçiriyor, aksi halde
  her otomatik koşu bir adminin elle girdiği örnekleri sessizce silerdi (`set_company_adapter`
  her alanı tamamen değiştirir, eklemez). Bir istisna asla isteğe sızmaz -- `training_runs.
  status="failed"` + `error` ile görünür kalır.
- **Endpoint'ler** (`/companies/{id}/training-samples[/compile|/stats|/export]`,
  `/training-samples/{id}`, `/companies/{id}/training-runs`): derleme eğitimden ayrı
  tetiklenebilir (veri, eğitilmeden önce denetlenebilir); `.../export` ve `.../training-runs`
  tetikleyicisi **aynı** `list_all_active_samples` sorgusunu paylaşır, yani gösterilen veri ile
  eğitilen veri birebir aynı satırlar. `POST .../training-runs` Root/Admin'e kapalı değil ama
  yeni `company_quotas.max_training_runs_per_month` kotasına tabi (mevcut `usage_counters`
  mekanizması yeniden kullanıldı, yeni tablo yok).
- **Frontend**: `trainingService.ts` + `useTrainingData.ts` + `AdminPage`'e yeni
  `TrainingPanel` -- özet istatistik kartları, örnek tablosu (tıklayınca chosen/rejected diff
  açılır), eğitim geçmişi, derle/eğit butonları.
- **`frontend/src/api/generated.ts` yeniden üretildi** (`npx openapi-typescript`) -- bu dosya
  aylardır güncellenmemişti (analytics/feedback dahil pek çok endpoint eksikti);
  `UserResponse.company_id` artık istemci tarafında da mevcut, `TrainingPanel`'in kendi
  şirketini bilmesini bu sağlıyor. Regenerasyon `UserRole`'e `"root"`'un eklendiğini ortaya
  çıkardı -- `ROLE_LABELS` bunu karşılayacak şekilde güncellendi, atanabilir rol
  dropdown'larına (davet/rol değiştirme) sızmasın diye ayrı bir `ASSIGNABLE_ROLE_LABELS`
  eklendi.

### Kapsam dışı (bilinçli, ayrı bir işe ertelendi)
- **Aşama 3 -- LoRA/PEFT eğitimi** (`peft`/`trl`, `compose.yml --profile training`, shadow
  değerlendirme harness'i): gerçek GPU eğitim altyapısı, bu PR'ın kapsamına girmeyen ayrı
  donanım/dağıtım kararları gerektiriyor.
- **`arq` job runner + worker servisi + haftalık cron tetikleme**: bu fazın eğitim işi
  (deterministik diff + tek LLM çağrısı) saniyeler sürüyor ve isteğin kendi içinde senkron
  çalışıyor -- `chat_recorder`/`draft_recorder` ile aynı "kısa ömürlü, kendi oturumunu açan"
  desenin ötesine geçen bir kuyruk/worker container'ı bu ölçek için erken optimizasyon olurdu.

### Test
- `docker compose exec backend pytest -q` → **1847 test geçti** (33 yeni).
- `npx vitest run` (frontend) → **142 test geçti** (8 yeni, `TrainingPanel`).
- Canlı doğrulama: gerçek Postgres + Redis + Ollama'ya karşı uçtan uca -- 60 feedback oyu →
  60 derlenmiş örnek → üslup madenciliği (tek LLM çağrısı) → `CompanyModel.settings`'e
  yayınlanan versiyonlanmış adaptör, elle çalıştırılıp doğrulandı.

Refs: [#187](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/187)

## [3.10.0] - 2026-08-15
### Eklendi
Şirket bazlı RLHF adapter katmanının ikinci fazı -- runtime prompt-adapter (Faz C2, #185),
Faz C1'i (#183) takip ediyor. Anında etkili, GPU'suz: bir admin bir üslup kuralı yazdığı anda
bir sonraki taslak/revizyon turu bunu uyguluyor.

- **`app.ai.adapters.company_adapter.CompanyAdapter`**: `style_rules`/`preferred_examples`/
  `avoided_patterns`/`version`/`trained_at`/`sample_count` taşıyan değişmez (frozen) veri
  sınıfı. Yalnızca üslup ve biçim taşır, asla olgu taşımaz -- bu yapısal olarak zorlanıyor,
  sınıfta dünya hakkında bir iddia (isim, tarih, kurum) tutabilecek hiçbir alan yok.
- **`app.domains.companies.provider.get_company_adapter`/`set_company_adapter`**:
  `CompanyModel.settings` JSON'ından okur/yazar, Redis'te 5 dk TTL ile cache'lenir.
  `app.domains.units.provider.get_active_units_for_routing`'in kurduğu kalıp birebir izlendi:
  `app.ai.*` hiçbir zaman `app.domains.*` import etmiyor (`docs/architecture/backend.md`), bu
  yüzden gerçek DB/Redis erişimi domains tarafında kalıp AI grafiğine düz bir async callable
  olarak (`adapter_provider`) enjekte ediliyor -- `units_provider` ile aynı desen.
- **`draft_graph.py`/`revise_graph.py`**: `writer_node`/`reviser_node` her denemede şirketin
  adaptörünü çözüp (`_resolve_adapter` -- çözümleme başarısız olursa veya adapter yoksa sessizce
  boş adaptöre düşer, taslak turunu asla düşürmez) `format_adapter_block()` ile prompt'a ekliyor.
  **Kritik sınır korunuyor**: `preferred_examples` mevcut `style_examples` akışına katılıyor, bu
  yüzden `verify_draft`'ın deterministik `ornek_sizintisi` kontrolüne aynen tabi -- adaptörden
  sızan bir kurum adı, tıpkı alınan bir üslup örneğinden sızan gibi yakalanıp insan onayına
  düşürülüyor. Uçtan uca testle doğrulandı.
- **`GET`/`PUT /companies/{id}/adapter`** (admin/root): C3'ün otomatik eğitim boru hattı
  gelmeden önce bir admin elle üslup kuralı/kaçınılacak kalıp/tercih edilen örnek girebiliyor.
  `PUT` her alanı tamamen değiştirir (eklemez), versiyonu artırır, `trained_at` damgalar ve
  audit log'a düşer.

### Test
- `docker compose exec backend pytest -q` → 1814 test geçti (28 yeni: `CompanyAdapter`/
  `format_adapter_block` birim testleri, `provider.py` için sahte Redis/DB testleri, gerçek
  derlenmiş draft/revise grafikleriyle uçtan uca prompt-enjeksiyon ve `ornek_sizintisi`
  sızıntı testi, yeni endpoint'ler için router testleri).
- Migration/RLS gerekmedi -- `CompanyModel.settings` zaten var olan bir JSON alanı.
- Canlı doğrulama: gerçek Postgres + Redis'e karşı `get_company_adapter`/`set_company_adapter`
  elle çalıştırıldı (versiyon artışı, cache isabeti, `CompanyModel.settings`'teki diğer
  anahtarların korunduğu doğrulandı).

Refs: [#185](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/185)

## [3.9.0] - 2026-08-15
### Eklendi
Şirket bazlı RLHF adapter katmanının ilk fazı -- feedback toplama (Faz C1, #183). Kullanıcının
kendi isteğine göre: "otomatik eğitim altyapısı hazır olsun ama şimdilik sadece otomatik veri
toplama çalışsın" -- bu sürüm yalnızca toplama tarafını içeriyor, hiçbir şey bu veriyi henüz
eğitim için okumuyor.

- **Yeni `backend/app/domains/feedback/` domaini** -- `drafts`/`audit`/`notifications`
  domainlerinin kalıbı birebir izlenerek (model/repository/service/schema/router).
- **Yeni `feedback` tablosu** (migration `0020_feedback.py`, RLS'li -- `tenant_isolation`
  politikası, gerçek bir Postgres'e karşı upgrade/downgrade/upgrade ile doğrulandı).
  `(company_id, user_id, target_kind, content_hash)` üzerinde uniq: aynı metne tekrar oy
  verilirse (veya 👍→👎 arası geçilirse) satır çoğalmaz, mevcut oy güncellenir. Oyun kimliği
  bir mesaj id'si değil, metnin kendisinin hash'i -- canlı bir sohbet cevabının henüz kalıcı
  bir id'si yok (`chat_recorder` turdan sonra asenkron yazıyor), `content_hash` ise her zaman
  anında mevcut olan tek kimlik. Ham oylanan metin hiçbir zaman saklanmıyor, yalnızca hash'i --
  metin zaten başka yerde kalıcı (`chat_messages.content`/`drafts.content`), burada ikinci bir
  şifresiz kopyası tutulmuyor.
- **Endpoint'ler**: `POST /feedback` (herhangi bir kullanıcı, kendi şirketiyle sınırlı),
  `DELETE /feedback/{id}` (oy sahibi veya admin/manager/root), `GET /feedback` (admin/manager/
  root, kendi şirketi), `GET /companies/{id}/feedback/stats` (admin/manager/root --
  `analytics/router.py`'nin `_require_company_access` kalıbı). Her `submit`/`delete`
  `AuditService.record` ile denetim izine düşüyor.
- **Frontend**: sohbet balonlarına 👍/👎 butonları (`FeedbackButtons.tsx`) -- 👎'de metni
  hemen göndermek yerine opsiyonel bir yorum kutusu açılıyor ("ne iyileştirilebilir?"), zaten
  verilmiş bir oya tekrar tıklamak onu geri çekiyor. Hedef tür (`draft`/`revision`/
  `assist_reply`) mesajın `details.draft`/`details.intent` alanlarından türetiliyor, ayrı bir
  backend alanı gerekmeden. Yeni `useFeedback.ts` hook'u ve `feedbackService.ts`.
- Canlı tarayıcı testinde yakalanan bir hata: oy başarısız olduğunda (`vote`/`withdraw`)
  yakalanmayan bir promise reddi konsola sessizce düşüyordu, kullanıcıya hiçbir görsel geri
  bildirim vermeden -- artık her iki yol da yakalanıyor ve "Oy gönderilemedi. Lütfen tekrar
  deneyin." satır içi hatası gösteriyor.

### Kapsam dışı (ayrı issue'larda)
- **C2**: Runtime prompt-adapter katmanı (`CompanyModel.settings`'ten okunan, anlık etkili
  üslup adapter'ı).
- **C3**: Eğitim boru hattı (`training_samples`/`training_runs`, `arq` worker, style-mining,
  opsiyonel LoRA, admin arayüzü).

### Test
- `docker compose exec backend pytest -q` → 1786 test geçti.
- `frontend`: `npx vitest run` → 134 test geçti, `tsc --noEmit` temiz.
- Canlı doğrulama: tarayıcıda gerçek bir sohbet turu üzerinden 👍 tıklanıp uç noktanın
  gerçekten kayıtlı olduğu (`POST /api/v1/feedback`), ardından hata yolunun kullanıcıya görünür
  şekilde başarısız olduğu doğrulandı.

Refs: [#183](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/183)

## [3.8.0] - 2026-08-15
### Eklendi
Bekleme sırasındaki UX iyileştirmesi (Faz B) -- bir taslak turu 30-90 saniye sürebiliyordu ve
bu sürede ekranda statik bir "İstek işleniyor" satırından başka hiçbir ilerleme hissi yoktu:

- **`ThinkingBubble.tsx`** eski statik `processing-line`'ın yerine geçti: `useChatWorkflow`'un
  zaten tuttuğu `nodeStatus`/`nodeOrder`/`nodeMeta`/`nodeResults` verisinden türetilen canlı bir
  adım listesi (tamamlanan ✓ ile sabit, çalışan adım nabız animasyonlu), toplam geçen süre
  sayacı ve çalışan adımın kendi süresi, adım-özel alt metin (`draft` node'unun `attempt`/
  `reasoning_level` meta'sından, örn. "2. deneme · deep mod") gösteriyor. `DecisionFlow.tsx`'in
  adım türetme mantığı (`deriveWorkflowStages`) dışa aktarıldı ki iş akışı çekmecesi ile sohbet
  akışındaki balon aynı "şu an ne oluyor" listesini göstersin, ikisi ayrı ayrı bakım gerektiren
  kopyalar olmasın.
- **Kısmi taslak önizlemesi**: `draft_graph.py::writer_node` artık her ~200 karakter
  büyümede bir birikmiş taslak metnini `partial_result` olarak yayınlıyor -- taslak
  tamamlanmadan önce balonda soluk bir önizleme olarak akıyor. Güvenlik değişmezi korundu:
  her önizleme, nihai metnin geçtiği aynı `assert_no_prompt_leak` kontrolünden geçiyor;
  kontrolü geçemeyen bir ara arabellek o turda sessizce atlanıyor (hataya düşmüyor), yani
  doğrulanmamış hiçbir metin -- ne önizleme ne nihai cevap -- kullanıcıya ulaşmıyor.
  Taslak adımı çalışırken gerçek metin henüz yoksa, iskelet (shimmer) bir taslak kartı
  gösteriliyor.
- **Uzun bekleme ipucu**: bir adım 20 saniyeyi aştığında "Bu adım normalden uzun sürüyor"
  uyarısı ve son kullanıcı mesajını `fast` düşünme seviyesinde yeniden gönderen bir kısayol
  beliriyor. "İşlemi durdur" butonu artık `ChatsPage`'te ayrı bir satır değil, balonun içinde.
- **Duraklama şeridi**: `human_gate`/`missing_information`/`draft_approval` kapısı açıkken
  sohbet balonunun üstünde "Yanıtınız bekleniyor — akış duraklatıldı" şeridi gösteriliyor --
  bekleme spinner'ıyla karışmaması için.
- `prefers-reduced-motion` desteği ayrıca eklenmedi: `integration.css`'teki mevcut global kural
  (`animation-duration: .01ms !important`) yeni animasyonları da otomatik kapsıyor.
- **Önizleme artık PII'yi maskeliyor**: `writer_node` her önizlemeyi yayınlamadan önce
  `app.ai.guardrails.pii.redact_pii` (TCKN/IBAN/telefon/adres, çıktı guardrail'inin de
  kullandığı aynı deterministik tarayıcı) ile maskeliyor. Nihai taslak buna dahil değil --
  meşru bir resmî yazı kendi konusunun TCKN'sini taşıyabilir, bu yüzden nihai metin PII'yi
  koruyor ve bunun yerine `pii_bulgusu` güven kuralıyla insan onayına düşüyor; önizleme ise
  kaybolan geçici bir ilerleme göstergesi olduğu için maskelemeden hiçbir şey kaybetmiyor.
  Ayrı bir kayan pencere (sliding window) tamponu gerekmedi: önizleme her seferinde akışın
  *tamamını* baştan yeniden tarıyor, artımlı bir fark değil -- bir kalıp iki ham üretim
  parçası arasına bölünse bile, tamamlanmadan asla eşleşmiyor.

### Test
- `docker compose exec backend pytest -q` → 1766 test geçti.
- `frontend`: `npx vitest run` → 126 test geçti, `tsc --noEmit` temiz.

Refs: [#181](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/181)

## [3.7.0] - 2026-08-15
### Düzeltildi
Sahada tespit edilen beş taslak/revizyon boru hattı hatası (Faz A):

- **Reddedilen revizyon artık düzgün değişiklikleri kaybetmiyor**: `compute_focus_update`'in reddetme dalı turun başındaki eski sürümü arşivleyip `gate_revise_node`'un o turda ürettiği gerçek revizyon metnini hiçbir yere yazmadan atıyordu, sonra `active_draft`'ı `None` yapıyordu -- bir revizyon reddedilince hem revizyonun kendisi kayboluyor hem de sonraki "üslubunu düzelt" mesajı `revise` yerine sıfırdan `draft`'a düşüyordu. Reddetme artık her zaman `draft_result`'taki en yeni metni arşivliyor ve `active_draft`'ı yalnızca `REJECTED` olarak işaretliyor -- taslak revize edilebilir kalıyor, gerçek terk yalnızca `RESET_SURFACES` ile oluyor. `DraftVersion.supersedes` eklendi. `revise_graph._build_brief` artık önceki sürümün reddedilme gerekçesini reviser'a ayrı bir bölüm olarak veriyor.
- **Gelen evrakın sayısı artık taslağa kopyalanmıyor**: `_build_brief` gelen evrakın kimlik bilgilerini artık "yalnızca İlgi satırında kullanılabilir" etiketli ayrı bir bölümde veriyor; `writer.md` giden yazının Sayı/Tarih alanının her zaman yer tutucu olduğunu söylüyor. Deterministik bir `gelen_sayi_sizintisi` kontrolü eklendi -- taslağın kendi Sayı: satırı gelen evrakın sayısıyla eşleşiyorsa insan onayı zorlanıyor ve otomatik tamir listesine düşüyor.
- **Eksik alanlar artık `[...]` yer tutucusuyla soruluyor, "Bulunamadı" olarak yazılmıyor**: `_build_brief` eksik alanları artık `(evrakta yok -- taslakta [Alan] yer tutucusunu bırak)` biçiminde ifade ediyor. Yeni `app.ai.verification.placeholders.normalize_unfilled_markers`, `verify_draft` çağrılmadan önce çalışıp modelin yine de yazdığı "bulunamadı/belirtilmemiş/yok/N/A/---" gibi işaretçileri ilgili `[Alan Adı]` yer tutucusuna çeviriyor -- mevcut missing-information boru hattı böylece devreye giriyor.
- **Güven skoru artık tek bir deterministik kural tablosundan hesaplanıyor**: Skor, deterministik ceza + LLM yargıcının 0-100 skorunun `0.6/0.4` ağırlıklı ortalamasıydı -- aynı taslak iki çalıştırmada farklı skor alabiliyor, yargıç zaman aşımına uğradığında skor aniden sıçrıyordu. Yeni `app.ai.verification.confidence_rules` -- tek, versiyonlu, denetlenebilir kural tablosu (`RULES`); `score_findings()` saf bir fonksiyon, aynı bulgu listesi her zaman aynı skoru üretiyor. Yargıcın kendi sayısal skoru artık aritmetiğe girmiyor -- yalnızca bulguları kapı olarak kullanılıyor. Her taslağın `applied_rules` listesi artık API yanıtında ve `DraftModel` kaydında; `DraftMetaStrip.tsx` bunu "Skor dökümü" olarak gösteriyor. `VerificationPolicy`'nin harman ağırlığı/ceza alanları kaldırıldı; `POLICY_VERSION` 2.0.0 → 3.0.0 (prototip vektörleri ve router füzyon ağırlıkları yeniden üretildi).
- **Revizyon ve bilgi aynı mesajda karışmıyor artık**: `decompose_instruction`, bileşik bir talimatın ne bir yapısal unsur ne de bir işlem adlandıran bir bölümünü sessizce atıyordu ("Konuyu değiştir ve muhatap Ankara Valiliği olsun" içindeki muhatap kısmı kayboluyordu); artık böyle durumlarda tüm talimat tek bir whole-draft revizyonu olarak, hiçbir parça kaybolmadan işleniyor. `intent_scorer`'a yeni bir yapısal kural eklendi (`revise.muhatap_statement`): açık bir revizyon fiili taşımayan salt bilgilendirme cümleleri artık aktif taslak varken `revise`'a puan veriyor. `human_gate_node`'un `missing_information` dalına bir kaçış kapısı eklendi: kullanıcı eksik-bilgi cevap kutusuna bir revizyon talimatı yazarsa, frontend `action="revise"` gönderip `draft_approval` kapısıyla aynı `gate_revise` mekanizmasını çalıştırabiliyor; `InterruptPanel`'e "Bilgi vermek yerine taslağı revize etmek mi istiyorsunuz?" kaçış kapısı eklendi.

### Test
- `docker compose exec backend pytest -q` → 1763 test geçti.
- `frontend`: `npx vitest run` → 119 test geçti, `tsc --noEmit` temiz.

Refs: [#179](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/179)

## [3.6.0] - 2026-08-07
### Değiştirildi
- **`mevzuat-mcp` artık backend imajına gömülü, hiçbir elle kurulum gerektirmiyor**: 1.45.0'ın belgelediği "izole sanal ortamı elle kur" adımı artık `deploy/docker/backend.Dockerfile`'da derleme zamanında otomatik yapılıyor -- `git`, `/tmp/mcpvenv`, `pip install git+...mevzuat-mcp` ve `playwright install --with-deps chromium` hepsi imaja gömülü. `compose.yml`'in backend servisi artık `MEVZUAT_MCP_COMMAND=/tmp/mcpvenv/bin/mevzuat-mcp`'ı zaten ayarlıyor -- önceki varsayılan (`mevzuat-mcp`, PATH'te bulunamayan çıplak bir komut adı) her canlı sorguyu aynı şekilde başarısız kılıyordu.
  - **Kendi sanal ortamına kuruldu, `requirements.txt`'ye eklenmedi**: `mevzuat-mcp`'nin bağımlılık ağacı `fastapi`/`pydantic`/`httpx`/`mcp`'yi bu projenin kendi pinlerine yakın ama aynı olmayan sürümlere çözümlüyor (`pydantic-settings` burada 2.15.0'a çözümlenirken bu projenin pini 2.14.2) -- paylaşılan tek bir ortamda birinin pinini sessizce kırmaya yetecek bir fark.
  - **Gerçek bir taze derlemeyle uçtan uca doğrulandı**: `docker compose build backend` sıfırdan, ardından `docker compose up -d backend` -- açılış günlükleri hiçbir elle müdahale olmadan `MCP-first legislation index warm: 852 chunk(s) from 7/7 law(s).` gösterdi. `/api/v1/health` yanıt verdi, tam birim testi takımı taze imaj içinde **1157/1157** geçti.
  - Görsel dil-modeli araması için Playwright'ın Chromium indirmesi (~280 MB indirme, sıkıştırılmamış daha büyük) imajı belirgin şekilde büyütüyor -- bu bilinçli bir ödünleşim: canlı mevzuat sorgusunun kurulumsuz çalışması, daha küçük bir imajdan daha değerli.
  - `mevzuat-mcp`'nin kendi giriş noktası `sys.argv`'yi hiç ayrıştırmıyor (canlı olarak doğrulandı) -- `.env.example`'daki `MEVZUAT_MCP_ARGS` için yanıltıcı "--transport stdio" örneği kaldırıldı. Paket ayrıca stdio dışında bir taşıma sunmuyor, dolayısıyla ağ üzerinden ayrı bir yan-konteyner (sidecar) mimarisi üçüncü taraf paketin iç yapısına çatallanmadan mümkün değil.
- **`AssistantAgent.run_stream` artık tool turu'nun kendi ürettiği son cevabı tekrar akışa sokmuyor**: `generate_with_tools`'ın son turu (daha fazla araç çağrısı yok) zaten tam cevabı üretiyordu, ama döngü bunu atıp koşulsuz olarak `stream()` ile aynı cevabı ikinci kez -- ve tamamen boşa -- üretiyordu. Gerçek bir MCP mevzuat sorgusunda bu, "assist" node'unun 70s bütçesinin (`node_seconds`, `app/ai/policy/schema.py`) tutup tutmaması arasındaki farktı: 3 Ollama çağrısı / ~85s ve yanıtsız zaman aşımı, aynı modelle 2 çağrı / ~48s ve gerçek bir cevaba düştü. `tests/unit/ai/test_assistant_tools.py`'ye önce başarısız olduğu doğrulanan bir regresyon testi eklendi.
  - Not: bu sürüm numarası, `main`'in kendi bağımsız geçmişiyle art arda iki kez çakışan bir etiketin yeniden numaralandırılmasıdır (`test/mevzuat-vs-latest-main` birleştirmesi sırasında, en son `main`'in 3.3.0 → 3.5.0 aralığına karşı) -- aşağıdaki `main` geçmişi değişmeden korunmuştur.

## [3.5.0] - 2026-08-14
### Eklendi
- **Hash zincirli denetim kaydı -- Faz 6**: Yeni `app.domains.audit` domain'i, `audit_log` tablosu (`company_id` bu kod tabanındaki tek nullable kiracı kolonu -- ROOT'un sistem geneli eylemleri için, mevcut `tenant_isolation` policy'si değişmeden bunu doğru şekilde yalnızca `is_root`'a görünür kılıyor). `hash = sha256(prev_hash || canonical_json(satır))`, `seq` `company_id IS NOT DISTINCT FROM` ile hesaplanır (Faz 5'te bulunan NULL-gruplama hatasına karşı baştan korumalı). `AuditService.record()` diğer recorder'lar gibi best-effort; `permission:grant/revoke`, şirket/birim oluştur-güncelle-sil, taslak paylaşım gönder/kabul/reddet/geri-çek, havuz push'a bağlandı -- her istek değil, dürüst kapsam. `GET /audit` (Root: her şirket/sistem geneli, Admin: yalnız kendi şirketi -- query param'la override edilemez), `GET /audit/verify` (zinciri yürür, ilk kırılan noktayı döner).
- **Analitik -- Faz 6**: Yeni `app.domains.analytics` domain'i. Yeni pipeline yok, mevcut tablolar üzerine düz SQLAlchemy toplu sorgular, `(company_id, metric, aralık)` başına 60s Redis önbellek. `GET /companies/{id}/analytics/summary|timeseries|units|guardrails|links`.
- **Root konsolu -- Faz 6**: `app.domains.companies.root_router` + kasıtlı olarak ayrı `root_repository.py` (analitik repository'sinin aksine hiçbir sorgusu `company_id` filtrelemiyor -- fiziksel ayrım, unutulmuş bir filtrenin şirketler arası sızıntı yapmasını yapısal olarak imkânsız kılıyor). `GET /root/overview|companies/stats|users/stats|health`.
- **Kullanım kotaları -- Faz 6**: Yeni `usage_counters`/`company_quotas` tabloları (`app.domains.quotas`). Yalnızca `documents`/`drafts` sayımı üzerinden dürüst zorlama -- token bazlı kota kasıtlı olarak kapsam dışı (`BaseLLMClient.generate()` bugün token sayısı döndürmüyor). `DocumentService.analyze_document`, `DraftService.generate_draft_and_route`, `DraftShareService.respond`'un `accept` fork'una bağlandı; aşılınca mevcut `RateLimitException` ile 429. Sohbet akışından üretilen taslaklar **kotalanmıyor** -- `app.ai.*`'nin `app.domains.*` import edememesi bunu mimari olarak engelliyor, dürüstçe belgelendi.
- **Şirket bazlı Prometheus/Grafana -- Faz 6**: `app.observability.company_metrics` -- `kachow_company_requests_total`/`_documents_total`/`_drafts_total`/`_guardrail_blocks_total`/`_active_users` (gauge, yalnızca bir analitik özet çağrısında fırsatçı tazelenir), etiket her zaman `slug`. `company_id -> slug` süreç-içi kalıcı önbellek (`get_current_user`'da, şirket başına yalnızca ilk görülüşte bir sorgu). Yeni `monitoring/dashboards/company_dashboard.json` (`company` template değişkeni).
- **Langfuse etiketleme -- Faz 6**: `build_trace_config`'e `langfuse_user_id`/`langfuse_session_id`/`langfuse_tags=[company:slug, role:...]`. Dürüst uyarı: `compose.yml`'in `langfuse/langfuse:2`'si `langfuse` Python bağımlılığının v4 SDK'sıyla muhtemelen uyuşmuyor (önceki fazlardan beri bilinen bir gerçek) -- etiketleme bugün no-op olabilir, tracing çalışır hale geldiğinde otomatik işleyecek.
- Migration `0018_audit_log`, `0019_usage_counters_and_quotas`.
- `docs/api/audit.md`, `docs/api/analytics.md`, `docs/api/root.md` (yeni), `docs/architecture/backend.md`'ye "Denetim Kaydı, Analitik ve Kotalar (Faz 6)" bölümü.

### Düzeltildi
- `DraftRepository.count_drafts` artık `list_drafts(..., limit=10_000)` + `len()` değil, gerçek `SELECT count()`; aynı denetim sırasında `ChatSessionRepository.count_for_user`/`ChatMessageRepository.count_for_session`'da da aynı anti-desen bulunup düzeltildi (`DocumentRepository.count_for_owner` önceki bir fazda zaten düzeltilmiş bulundu).
- **`GET /root/health` `AttributeError` ile 500 veriyordu**: `SuccessResponse` bir Pydantic modeli değil, zaten render edilmiş bir `JSONResponse` döndüren bir fabrika fonksiyonu -- `.data` okumaya çalışmak patlıyordu. `app.domains.system.router.health_check`'in gövdesi `build_health_payload`'a çıkarıldı, hem route hem `root_health` artık ham dict üzerinde çalışıyor.
- **`AuditLogRepository.append` her çağrıda `NameError` ile patlıyordu**: `hashable_fields` yeniden adlandırması tanım satırında yapılmış ama `append`'in kendi içindeki tek çağrı yeri `_hashable_fields` olarak kalmıştı -- `test_audit_service.py`'nin mock'lu testleri gerçek `append()`'i hiç çağırmadığından görünmezdi. `tests/integration/test_audit_repository.py` (yeni, gerçek Postgres) düzeltme öncesi koda karşı doğrulandı.
- **`GET /companies/{id}/analytics/links`'in Langfuse linki container-içi hostname döndürüyordu**: `settings.LANGFUSE_HOST` (`compose.yml`'de backend'in Langfuse'a kendi bağlantısı için `http://langfuse:3000` olarak ayarlı, tarayıcıdan erişilemez) doğrudan kullanılıyordu. Yeni, ayrı `settings.LANGFUSE_PUBLIC_URL` eklendi.

### Test
- `docker compose exec backend pytest -q` → 1692 test geçti (1667 mevcut + 25 yeni). `tests/integration/test_rls_role_is_not_owner.py` artık 19 tabloyu kapsıyor; `tests/integration/test_rls_isolation.py`'ye `audit_log`/`usage_counters`/`company_quotas` için çapraz-şirket izolasyon testleri eklendi; `tests/integration/test_audit_repository.py` (yeni) gerçek Postgres'e karşı hash zincirini uçtan uca doğruluyor.
- Gerçek Docker yığınına karşı uçtan uca doğrulama: root/admin ile `/root/*` ve `/companies/{id}/analytics/*` uçları; birim oluşturma + yetki verme → `GET /audit`'te görünür → `GET /audit/verify` zinciri doğrular; evrak kotası 1 olarak ayarlanıp ikinci yüklemenin 429 ile reddedildiği doğrulandı; `curl localhost:8000/metrics | grep kachow_company_` şirket etiketli serileri gösterdi.

**Not — planın son fazı.** Bu, `docs/plans/1-kullanıcı-sistemini-tam-stateful-lemur.md`'nin 6 fazının tamamını kapatıyor.

Refs: [#177](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/177)

## [3.4.0] - 2026-08-14
### Eklendi
- **Taslak dağıtımı -- Faz 5**: Yeni `draft_shares` tablosu (bir taslak versiyonunun bir/birden fazla alıcıya gönderimi -- ayrı bir gelen/giden kutusu tablosu yok, `recipient_id = ben`/`sender_id = ben` aynı tablonun filtreli görünümü). `POST /drafts/{id}/send` (`Action.DRAFT_SEND` ile gerçek ABAC motorundan geçer -- Faz 2'de tanımlanmış ama o zamana kadar kullanılmamış bir sabit; `suggested_unit_id` taslağın `destination` alanından `UnitRepository.get_by_name` ile anlık kopyalanır, yeni bir AI çağrısı yok), `GET /drafts/inbox`, `GET /drafts/outbox`, `POST /drafts/shares/{id}/read`, `POST /drafts/shares/{id}/accept` (**mevcut `DraftRepository.create_version` zincirleme mekanizmasını kullanarak alıcının sahip olduğu yeni bir versiyon fork'lar** -- "kabul" yalnızca durum değişikliği değil, taslağı gerçekten devralmak), `POST /drafts/shares/{id}/reject`, `DELETE /drafts/shares/{id}` (yalnızca gönderen, yalnızca `sent`).
- **Bildirimler -- Faz 5**: Yeni `app.domains.notifications` domain'i, `notifications` tablosu (kişisel, `bypasses_ownership`'siz). `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all`, **`GET /notifications/stream`** (SSE, Redis pub/sub ile fan-out -- süreç-içi `EventBus` tek başına çok worker'lı bir uvicorn'da yetersiz kalırdı; `notifications` satırı publish'ten önce yazıldığı için canlı push kaybolsa bile veri kaybı yok). `RedisCache.publish()` eklendi.
- **Yeni event'ler**: `app/events/event.py`'ye `DraftSharedEvent`/`DraftShareRespondedEvent`; `app/events/subscribers.py`'de bunları dinleyip `notifications` satırı yazan + Redis'e publish eden dinleyiciler (`tenant_session(company_id)` kullanır -- istek-dışı kod).
- Migration `0017_draft_shares_notifications` -- iki yeni tablo, `document_pools` (Faz 4) gibi baştan `company_id NOT NULL` ile doğuyor, doğrudan RLS'e alınıyor (backfill gerekmiyor).
- `docs/api/draft-shares.md`, `docs/api/notifications.md` (yeni), `docs/architecture/backend.md`'ye "Taslak Dağıtımı ve Bildirimler" bölümü.

### Düzeltildi
- **`GET /drafts` her session-less taslağı gizliyordu**: `DraftRepository.list_drafts`'ın "en son versiyon" alt sorgusu `session_id` üzerinden `GROUP BY`/`JOIN` yapıyordu -- `session_id IS NULL` olan (doğrudan `POST /documents/draft` çağrısı, ya da yeni `accept` fork'u) taslaklar için SQL'in üçlü mantığında `NULL = NULL` `NULL` (TRUE değil) döndüğünden, bu taslakların **tamamı** listeden düşüyordu; üstelik `GROUP BY` NULL'ları tek bir grupta topladığından, birden fazla ilgisiz session-less taslak varsa (artık `accept` fork'uyla mümkün) global `MAX(version)`'ı elinde tutan tek bir satır dışında hepsi gizlenebiliyordu -- şirket/kullanıcı sınırından bağımsız, sistem genelinde. Faz 5'in `accept` özelliğini canlı doğrularken bulundu (fork'lanan taslak doğrudan `GET /drafts/{id}` ile erişilebiliyordu ama `GET /drafts` listesinde hiç görünmüyordu). **Düzeltme**: gruplama anahtarı artık `COALESCE(session_id, id)` -- session-less her taslak kendi tekil grubunu oluşturuyor, sohbet oturumlu taslakların mevcut davranışı değişmiyor. `tests/integration/test_draft_listing.py` (yeni) düzeltme öncesi koda karşı doğrulandı (iki test de gerçekten başarısız oluyordu).

### Test
- `docker compose exec backend pytest -q` → 1659 test geçti (1609 mevcut + 50 yeni). `tests/integration/test_rls_role_is_not_owner.py` artık 16 tabloyu kapsıyor; `tests/integration/test_rls_isolation.py`'ye `draft_shares`/`notifications` için çapraz-şirket izolasyon testleri eklendi.
- Gerçek Docker yığınına karşı uçtan uca doğrulama: iki çalışan arasında gönder → gelen kutusunda gör → bildirim al → kabul et (fork'lanan versiyonu hem doğrudan `GET /drafts/{id}` hem de düzeltme sonrası `GET /drafts` listesinde doğrulandı) → gönderen bildirim aldı; ayrıca reddet ve geri çek akışları, ve canlı `curl -N` ile `GET /notifications/stream`'in Redis pub/sub üzerinden gerçekten anlık push ettiğinin doğrudan gözlemi.

**Not — kapsam yalnızca backend'i içerir.** Sonraki faz (analitik/denetim/kota) ayrı bir issue'da takip edilecektir.

Refs: [#175](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/175)

## [3.3.0] - 2026-08-14
### Eklendi
- **Birim üyeliği + evrak havuzu -- Faz 4**: Yeni `unit_memberships` tablosu (kullanıcı↔birim bağı, en fazla bir `is_primary` üyelik, partial unique index ile zorlanır) ve `POST/DELETE /units/{id}/members`, `GET /units/{id}/members`, `GET /units/{id}/suggested-recipients` uçları -- sonuncusu mevcut `routing_graph`'ı yeniden kullanır, yeni bir AI çağrısı yapmaz. Yeni `app.domains.pools` domain'i: `document_pools`/`document_pool_items` tabloları, `GET /pools/me` (her kullanıcının kişisel havuzu ilk kullanımda tembel oluşturulur -- artık her evrak yüklemesi de otomatik olarak sahibinin havuzuna dosyalanıyor), `GET/POST /pools/{id}/items`, `POST /pools/push` (birden fazla alıcıya veya bir birimin tüm üyelerine toplu gönderim, **alıcı bazlı gizlilik kontrolü** ile -- `gizli` bir evrak `hizmete_ozel` bir alıcı için sessizce değil `denied_clearance` olarak reddedilir), `DELETE /pools/{id}/items/{id}`, `POST /pools/items/{id}/acknowledge`. Migration `0014_units_and_pools` -- yeni tablolar `company_id NOT NULL` ile doğuyor, doğrudan RLS'e alınıyor (backfill gerekmiyor).
- **`company_id` LangGraph state'ine ve dört recorder'a thread edildi**: `PlanningState.company_id`, `ChatService._invoke`'dan `user_id` ile aynı şekilde ekleniyor; `draft_recorder`, `run_recorder`, `guardrail_recorder`, `chat_recorder`'ın hepsi artık `tenant_session(company_id)` kullanıyor. Faz 1'den beri nullable kalan `drafts`/`chat_sessions`/`chat_messages`/`runs`/`run_steps`/`guardrail_events`'in `company_id`'si migration `0015_backfill_recorder_company_id` (veri, `0010`'un "legacy-pre-tenancy" şirketini yeniden kullanır) + `0016_recorder_tables_rls` (`NOT NULL` + RLS) ile artık zorunlu ve RLS kapsamında -- bu değişiklik, Faz 3'ün PR incelemesinde ayrı bir faza mı yoksa Faz 4'e mi katılacağı sorulduğunda kullanıcıyla konuşulup Faz 4'e katıldı.
- `DraftRepository`/`ChatSessionRepository`/`ChatMessageRepository`'ye açık `company_id` filtre parametreleri eklendi (repository katmanının birincil savunma sözleşmesiyle tutarlı -- RLS'e yaslanmak yerine).

### Düzeltildi
- **`GET /drafts` her zaman 500 veriyordu**: Faz 2'nin ABAC refactor'ü `drafts/router.py`'den `bypasses_ownership` import'unu kaldırmıştı ama `list_drafts` uç noktası hâlâ onu çağırıyordu -- gerçek Docker yığınına karşı canlı duman testinde bulundu (mevcut hiçbir test bu uç noktayı HTTP seviyesinde çalıştırmıyordu). Import geri eklendi; regresyonu yakalayacak yeni `tests/unit/domains/test_draft_router.py` eklendi.

### Test
- `docker compose exec backend pytest -q` → 1609 test geçti. `tests/integration/test_rls_role_is_not_owner.py` artık 14 tabloyu (5 mevcut + 9 yeni) kapsıyor; `tests/integration/test_rls_isolation.py`'ye `unit_memberships` ve `drafts` için çapraz-şirket izolasyon testleri eklendi.
- Gerçek Docker yığınına karşı uçtan uca doğrulama: birim üyeliği ekleme/listeleme/önerilen-alıcılar, evrak havuzuna itme (tekli + toplu, alıcı-bazlı gizlilik reddi dahil), evrak yüklemenin otomatik havuz dosyalaması, gerçek bir sohbet turunun `runs`/`chat_sessions`/`guardrail_events`'e doğru `company_id` ile yazdığının doğrudan SQL ile kontrolü.

**Not — kapsam yalnızca backend'i içerir.** Sonraki fazlar (taslak dağıtımı/bildirimler, analitik/denetim) ayrı issue'larda takip edilecektir.

Refs: [#173](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/173)

## [3.2.0] - 2026-08-13
### Eklendi
- **Postgres Row-Level Security -- Faz 3**: `kachow_app` rolü (`NOSUPERUSER`, tablo sahipliği yok, yalnızca DML) -- backend artık şema sahibi olarak değil bu rolle bağlanıyor (`settings.DATABASE_URL`). `ENABLE`+`FORCE ROW LEVEL SECURITY` ve bir `tenant_isolation` policy'si `users`/`units`/`documents`/`invited_emails`/`permission_grants` üzerinde: `company_id = current_setting('app.current_company_id', true) OR current_setting('app.is_root', true) = 'on'`. Migration `0013_rls` idempotent (mevcut volume'lerde `scripts/init-db.sh` yeniden çalışmadığı için); taze volume'ler için aynı kurulum `scripts/init-db.sh`'a da eklendi.
- **Yeni `app.core.context`/`app.api.middleware.tenant.TenantContextMiddleware`**: JWT'nin `company_id`/`role` claim'lerini bir istek başlamadan önce bir `ContextVar`'a yazıyor; `get_db` oturumu açar açmaz bunu Postgres GUC'larına (`app.current_company_id`, `app.is_root`) basıyor -- ilk statement olarak, `SET LOCAL`in transaction'sız buharlaşması tuzağına karşı.
- **`ALEMBIC_DATABASE_URL` + `get_owner_db`**: Alembic ve üç "kiracı-öncesi" uç nokta (`POST /auth/login`, `POST /auth/refresh`, `POST /users` kayıt) artık şema-sahibi bağlantısını kullanıyor -- `username`/`email` şirket bazında değil sistem genelinde benzersiz olduğu için, hangi şirket olduğu henüz bilinmeden bir kullanıcıyı bulmak zorundalar.
- **`tenant_session(company_id, is_root)`**: İstek-dışı yazıcılar (`units/provider.py`, users/units seeder'ları) için `get_db`'nin GUC-basma mantığının eşdeğeri.
- `tests/integration/` altına gerçek Postgres'e karşı çalışan yeni bir entegrasyon paketi: `test_rls_role_is_not_owner.py` (rolün gerçekten tablo sahibi olmadığının ve RLS bayraklarının gerçekten açık olduğunun doğrulanması -- "RLS sessizce hiçbir şey yapmıyor" tuzağını yakalayan test), `test_rls_isolation.py` (çapraz şirket izolasyonu, `kachow_app` üzerinden SQL seviyesinde), `test_tenant_repository_scoping.py` (RLS tamamen kapalıyken bile repository katmanının tek başına yeterli olduğunun kanıtı). Yeni `tests/integration/conftest.py`: oturum başına bir kerelik, gerçek `alembic upgrade head` ile migrate edilmiş atılabilir test veritabanı.

### Değiştirildi
- `checkpointer_dsn` artık şema-sahibi bağlantısını kullanıyor -- `AsyncPostgresSaver.setup()` kendi checkpoint tablolarını her açılışta `CREATE TABLE IF NOT EXISTS` ile kuruyor, kısıtlı `kachow_app` rolünün DDL yetkisi yok.

### Düzeltildi
- **Canlı doğrulama sırasında bulunan iki gerçek hata** (RLS öncesinde de vardı, RLS onları ortaya çıkardı): `users/seeder.py::_seed_one`'ın var-olma kontrolü şirket-scope'lu bir oturumda çalışıyordu, ama `username`/`email` global benzersiz -- iki şirkete aynı "admin" kullanıcı adını seed etmeye çalışmak kontrolü değil global unique constraint'i tetikleyip çöküyordu; kontrol artık şema-sahibi bağlantısında. `AuthService.refresh_access_token`'ın ürettiği yeni access token `company_id` claim'ini taşımıyordu -- RLS öncesi zararsızdı, sonrasında o token'la yapılan her istek "User not found" ile başarısız oluyordu.

### Test
- `docker compose exec backend pytest -q` → 1548 test geçti (1522 mevcut + 26 yeni entegrasyon testi). Gerçek, çalışan Docker yığınına karşı uçtan uca doğrulama: rol/GUC/RLS bayrakları doğrudan `psql` ile, sonra tam HTTP akışı (login, refresh, kayıt/davet, root'un şirketler arası erişimi, kimliksiz istek → 401, `units`/`permission_grants` üzerinde gerçek yazma/okuma) `kachow_app` bağlantısı üzerinden.

**Not — kapsam yalnızca backend'i içerir.** `drafts`/`chat_sessions`/`chat_messages`/`runs`/`run_steps`/`guardrail_events` bilinçli olarak RLS dışı bırakıldı (`company_id` hâlâ nullable, Faz 1'in ertelemesi). Sonraki fazlar (evrak havuzu/taslak dağıtımı, analitik/denetim) ayrı issue'larda takip edilecektir.

Refs: [#171](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/171)

## [3.1.0] - 2026-08-13
### Eklendi
- **ABAC yetkilendirme motoru -- Faz 2**: Yeni `app.core.authz` paketi, kendi PDP'imiz (OPA/Casbin değil) -- `app.ai.policy.schema.Policy`'nin frozen/import-time-doğrulanan dataclass deseniyle aynı. `engine.authorize(subject, action, resource, env, grants)`: saf fonksiyon, DB/Redis bağımlılığı yok, karar sırası kiracı kapısı → açık `deny` yetkisi → en yüksek öncelikli `permit` yetkisi → yerleşik rol kuralları (`rules.BUILTIN_RULES`) → örtük red.
- **`permission_grants` tablosu (PAP deposu)**: `subject_type`/`subject_id`, `action`, `resource_type`/`resource_selector`, `effect`, `priority`, `valid_from`/`valid_until` (süreli yetki/delegasyon/break-glass, ayrı şema gerekmeden), `granted_by`, `revoked_at`, `reason`. Migration `0012_permission_grants`.
- **Redis epoch-tabanlı karar önbelleği** (`app.core.authz.cache.AuthzDecisionCache`): geçersizleştirme `INCR authz:epoch:{company_id}` ile, asla `SCAN`/`DEL` değil. Zaman sınırlı bir yetkiye dayanan kararlar hiç önbelleğe alınmaz; kiracı-uyuşmazlığı red kararları da (bedava yeniden hesaplanır, önbelleklemesi ayak kurşunu). `RedisCache.incr()` eklendi.
- **Yetki yönetimi uçları**: `POST/GET /api/v1/users/{id}/permissions`, `DELETE /api/v1/users/permissions/{grant_id}` (Admin/Manager, kendi şirketi). Yetki devrinde **ayrıcalık yükseltmesi engellenir**: devreden kişi aynı eylemi kendi kimliğiyle de gerçekleştiremiyorsa istek `403` ile reddedilir.
- `docs/api/permissions.md` ve `docs/architecture/backend.md`'ye yeni "ABAC Yetkilendirme Motoru" bölümü eklendi.

### Değiştirildi
- **Beş ayrı yerde tekrarlanan sahiplik kontrolü tek bir çağrıya indi**: `documents/router.py` (4 uç nokta) ve `drafts/router.py::_assert_owns_draft`'taki `if resource.owner_id != current_user.id and not bypasses_ownership(...)` deseni artık tek bir `engine.authorize()` çağrısı (`_authorize_document`/`_assert_owns_draft` içinde). Bilinçli tasarım kararı: bu hot path'ler saf, DB'siz motoru (`grants=()`) çağırıyor -- `bypasses_ownership`'in eski davranışını birebir üretiyor, sıfır yeni DB/Redis round-trip'i ile; `permission_grants`'ın gerçekten tüketilmesi (DB destekli `AuthzService`) yalnızca yetki yönetimi uçlarında.
- **`require_roles` artık `engine.role_permitted`'e ince bir shim** (`api/dependency.py`) -- davranış birebir aynı, tek kaynak `app.core.authz` paketinde.

### Test
- `tests/unit/core/authz/` -- motor (deny kazanır, öncelik sıralaması, süre dolumu/cacheable bayrağı, kiracı kapısı, seçici eşleştirme), repository (DB satırı → `GrantView` dönüşümü) ve servis (önbellek isabet/kaçırma, epoch bump, root'un grant çözümlemesini atlaması) için 38 yeni test. `tests/unit/domains/test_permission_grant_router.py` -- yetki verme/listeleme/geri alma uçları, ayrıcalık yükseltmesi reddi, employee 403 kilidi için 8 yeni test. Mevcut 1476 test, davranış değişmediği için **hiç değişiklik gerekmeden** geçti (`test_ownership.py` dahil). Migration `0012` gerçek geliştirme veritabanına karşı upgrade+downgrade+upgrade ile doğrulandı.

**Not — kapsam yalnızca backend'i içerir.** Frontend (yetki yönetimi arayüzü) bu sürüme dahil değildir. Sonraki fazlar (Postgres RLS, evrak havuzu, taslak dağıtımı/bildirimler, analitik/denetim) ayrı issue'larda takip edilecektir.

Refs: [#169](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/169)

## [3.0.0] - 2026-08-13
### Eklendi
- **Çok kiracılı (multi-tenant) şirket sistemi -- Faz 1: Tenancy temeli**: Sistem artık `root` / `company_admin` / `company_manager` / `employee` olmak üzere dört rollü, şirket (`companies`) bazlı çok kiracılı bir mimari. Yeni `app.domains.companies` domain'i: `CompanyModel` (`id`, `name`, `slug` benzersiz, `tax_number`, `is_active`, `is_deleted`, `settings` JSON, `created_by`), `POST/GET /api/v1/companies`, `GET/PATCH /api/v1/companies/{id}`, `POST /api/v1/companies/{id}/admins` (mevcut bir şirket kullanıcısını Admin'e yükseltir, cross-tenant self-escalation'a karşı kullanıcının zaten o şirkete ait olduğunu doğrular), `DELETE /api/v1/companies/{id}` (yumuşak silme). Tümü Root'a, detay/güncelleme ayrıca o şirketin kendi Admin'ine açık.
- **`UserRole.ROOT`**: `role_clearance_map`'e eklendi (`clearance_for`/`bypasses_ownership` ROOT'u ADMIN/MANAGER ile aynı dala alıyor). `users.company_id` yalnızca `role='root'` için NULL'dur, bir CHECK constraint (`ck_users_company_id_required_unless_root`) ile zorlanıyor.
- **`company_id` her kiracı tablosunda**: `users`, `units`, `documents`, `invited_emails` üzerinde NOT NULL + FK; `drafts`/`chat_sessions`/`chat_messages`/`runs`/`run_steps`/`guardrail_events` üzerinde (henüz uygulanmayan) nullable, çünkü bu tablolar LangGraph orkestrasyon katmanının derinlerinden yazılıyor ve `company_id`'nin oraya taşınması ayrı bir faz (Faz 3). `units.name` artık global değil `(company_id, name)` bazında benzersiz -- iki şirket aynı anda "İnsan Kaynakları" birimi tanımlayabilir. `documents.owner_id` artık NOT NULL + `users.id`'ye FK (önceden `REQUIRE_AUTH=False` altında sahipsiz kalabiliyordu).
- **Demo şirket + `root` hesabı seed'i**: `app.domains.companies.seeder.seed_demo_company` (idempotent, slug bazlı) her açılışta önce çalışıyor; `app.domains.users.seeder` artık `root@kachow.example` (şirketsiz) + demo şirkete bağlı admin/manager/employee hesaplarını seed'liyor; `app.domains.units.seeder` demo şirkete bağlı 6 varsayılan birimi seed'liyor. Jüri tek tıkla giriş yapmaya devam edebiliyor.
- Yeni migration'lar `0009_companies` (şema, nullable `company_id`), `0010_backfill_tenancy` (saf veri, mevcut satırları sentezlenmiş bir "legacy" şirkete atar -- gerçek geçmiş verili bir geliştirme veritabanına karşı doğrulandı), `0011_tenancy_constraints` (`NOT NULL` + kısıtlar, backfill eksikse gürültülü başarısız olur).

### Değiştirildi
- **`REQUIRE_AUTH` zorunlu**: Açık/kimliksiz erişim modu (`REQUIRE_AUTH=False`) kaldırıldı -- her satırın artık bir `company_id`'si var, kimliksiz bir isteğin bağlanacağı bir şirket yok. `compose.yml`'de varsayılan `false`'tan `true`'ya çevrildi. `/documents`, `/chat`, `/drafts`, `/units`, `/routing` router'larındaki `Optional[UserModel]`/"kimliksizken atla" dalları kaldırıldı; her istek artık gerçek, şirkete bağlı bir `current_user` taşıyor.
- **Repository katmanında zorunlu kiracı kapsamı**: `DocumentRepository`, `UnitRepository`, `UserRepository` içindeki her metod artık açık bir `company_id` parametresi alıp ona göre filtreliyor (`app.domains.documents.repository.DocumentRepository`'nin docstring'i, aynı deseni tüm repository'ler için tanımlıyor). `bypasses_ownership` (ADMIN/MANAGER/ROOT) artık *şirket çapında*, sistem çapında değil.
- **Birim yönlendirme artık şirket bazlı**: `app.domains.units.provider.get_active_units_for_routing(company_id)` yalnızca çağıran şirketin aktif birimlerini döndürüyor (önceden tüm şirketlerin birimlerini karıştırıyordu -- gerçek bir kiracı sızıntısıydı). `routing_graph.RoutingState`'e `company_id` eklendi; `company_id` boşsa yönlendirme güvenli tarafta "tanımlı birim yok, insan onayı gerekli"ye düşüyor, hiçbir zaman başka bir şirketin birimlerini sızdırmıyor.
- **Kullanıcı yönetimi uçları şirket kapsamlı**: `GET/PUT /users/{id}`, `DELETE /users/{id}/soft|hard`, `GET /users`, `POST /users/invitations` artık çağıranın kendi şirketiyle sınırlı (yeni `UserRepository.get_by_id_in_company`). Kayıt (`POST /users`) ve davet akışı `company_id`'yi davetiyeden alıyor, istek gövdesinden değil -- self-escalation'a karşı `role` alanının zaten uyguladığı aynı korumanın kiracı karşılığı.
- `backend/alembic/env.py`'deki eksik `UnitModel` importu düzeltildi -- bir sonraki `--autogenerate` artık `units` tablosunu DROP etmeyecek.

### Düzeltildi
- **Seed edilen hesaplar `GET /users/me`'de 500 veriyordu**: `SEED_*_EMAIL` varsayılanları `@kachow.local` kullanıyordu; `.local`, `email-validator`'ın (Pydantic `EmailStr`'ın altyapısı) engelli-alan-adı listesinde (mDNS için ayrılmış, RFC 6762) -- bir `UserModel` gerçek bir HTTP yanıtında `UserResponse`'a doğrulanır doğrulanmaz `500 INTERNAL_SERVER_ERROR` veriyordu. Birim testleri bunu hiç yakalamadı çünkü servis katmanı mock'landığı için hiçbiri seed edilmiş bir satırdan gerçek bir `UserResponse` doğrulamıyordu; gerçek Docker yığınına karşı elle yapılan uçtan uca doğrulamada ortaya çıktı. Tüm `SEED_*_EMAIL` varsayılanları ve `0010_backfill_tenancy`'nin sentezlediği "legacy" kullanıcı, dokümantasyon için ayrılmış ve engelli olmayan `.example` (RFC 2606) alan adına taşındı.

### Test
- `app.domains.companies` için tam repository/service/router/seeder birim testleri eklendi (root/kendi-şirketi-admin'i/farklı-şirket-admin'i/employee yetkilendirme matrisi dahil). Auth-zorunlu geçişinden etkilenen ~100 mevcut test (documents/drafts/chat/units/users/routing router+service+repository katmanları) güncellendi; artık geçerli olmayan "REQUIRE_AUTH=False" senaryoları kaldırıldı. `0009`/`0010`/`0011` migration'ları gerçek, önceden dolu bir geliştirme veritabanına karşı upgrade+downgrade+re-upgrade ile doğrulandı.

**Not — kapsam yalnızca backend'i içerir.** Frontend (giriş ekranı, şirket/birim yönetimi arayüzü) bu sürüme dahil değildir; ayrı bir işte yapılacaktır. Sonraki fazlar (ABAC yetki motoru, Postgres RLS, evrak havuzu, taslak dağıtımı/bildirimler, analitik/denetim) ayrı issue'larda takip edilecektir.

Refs: [#167](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/167)

## [2.0.0] - 2026-08-12
### Eklendi
- **Dinamik Birim Yönetimi API'si (`units` domain'i)**: Yönlendirme yapılabilecek birimler artık kod içinde sabit bir liste değil; şirket yöneticileri (`ADMIN`/`MANAGER`) `POST /api/v1/units` ile yeni birim tanımlayabiliyor, `PATCH /api/v1/units/{id}` ile adını/açıklamasını/aktiflik durumunu güncelleyebiliyor, `DELETE /api/v1/units/{id}` ile kalıcı olarak silebiliyor; `GET /api/v1/units` herkese (auth açıksa kimlik doğrulamalı) tüm birimleri listeliyor. Yeni `units` tablosu ve `0008_units` migration'ı eklendi; mevcut 6 birim (`app.domains.units.seeder`) ilk açılışta geriye dönük uyumluluk için otomatik tohumlanıyor.
- **`docs/api/units.md`**: Yeni birim yönetimi API dokümantasyonu.

### Değiştirildi
- **"İnsan Onayı Gerekli" artık bir birim değil**: `routing_graph.py`, yönlendirme kararını artık `app.domains.units.provider.get_active_units_for_routing` üzerinden veritabanından her çağrıda taze okunan aktif birim listesine göre veriyor (`RoutingPolicy.units`/`human_approval_unit` ve `RouteOutput.destination`'daki sabit `Literal` kaldırıldı -- dinamik bir liste sabit bir tipe sığmadığı için `str` oldu, geçerlilik kontrolü çağrı anında yapılıyor). Yönlendirme belirsiz kaldığında (boş taslak, düşük güven skoru, tanımlı aktif birim yokluğu, model hatası veya listede olmayan bir birim adı) artık sahte bir "İnsan Onayı Gerekli" birimi atanmıyor; bunun yerine `routed_unit=null` döner ve taslak-kalite kapısının zaten kullandığı `requires_human_approval` bayrağı `true` olur -- iki mekanizma artık aynı, tek bir sinyali paylaşıyor. `router.md` prompt şablonundaki sabit 6 birim listesi ve "İnsan Onayı Değerlendirmesi" adımı kaldırıldı; birim listesi + açıklamaları artık her çağrıda kullanıcı promptuna dinamik olarak enjekte ediliyor. `POST /api/v1/routing/suggest` yanıtına `requires_human_approval` alanı eklendi. `POLICY_VERSION` `1.6.0 -> 2.0.0` (bir parametrenin kaldırılması, modülün kendi kuralı gereği major bump).

**Not — kapsam yalnızca backend'i içerir.** Birim yönetimi ekranı ve routing sayfasındaki eski "İnsan Onayı Gerekli" özel durumunun kaldırılması gibi frontend değişiklikleri bu sürüme dahil değildir; ayrı bir işte yapılacaktır.

### Test
- `units` domain'i için repository/service/router/seeder birim testleri eklendi (admin/manager yetkilendirmesi dahil, employee için 403 kilidi). `routing_graph`/`test_routing_endpoint`/`test_policy` testleri dinamik birim listesine (fake `units_provider`), birim atanamama + `requires_human_approval` davranışına ve kaldırılan `İnsan Onayı Gerekli`/`ROUTING_UNITS` referanslarına göre güncellendi. `draft_service` testine, yönlendirmenin başarısız olduğu durumda `requires_human_approval`'ın taslak-kalite bayrağıyla OR'landığını doğrulayan bir senaryo eklendi.

Refs: [#164](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/164)

## [1.55.0] - 2026-08-12
### Düzeltildi (#161)
- **Sohbetten Başlatılan Her Taslak "Cevap Yazısı" Çıkıyordu**: `_run_draft` kullanıcının mesajını sabit bir orkestratör kalıbına gömüyordu (`"...resmî ve kurumsal bir Türkçe **yanıt** taslağı oluştur."`), ve `resolve_correspondence_type` bu birleşik metni tarıyordu -- "yanıt" `RESPONSE_LETTER`'ın alias'ı olduğu için kullanıcının gerçek isteği hiç değerlendirilmiyordu. Kullanıcının ham mesajı artık ayrı bir `user_request` alanında taşınıyor ve tür çözümlemesi yalnızca bunun üzerinden yapılıyor; orkestratör boilerplate'i tür eşleştirmesine hiç girmiyor.
  - **Yön farkındalıklı yazışma-türü sözlüğü** (`correspondence.GENRE_SURFACES`) eklendi: "itiraz dilekçesi", "muvafakatname", "tutanak" gibi 4 ana türe (üst yazı/cevap yazısı/bilgilendirme metni/diğer resmî yazışma) girmeyen özel istekler artık `other_official`'a düşüp kullanıcının kendi ifadesini bir **alt-tür** (`correspondence_sub_genre`) olarak taşıyor; writer/reviser/yargıç promptlarına ayrıca enjekte ediliyor, çıktı gerçekten istenen türde oluyor (örn. gerçek bir itiraz dilekçesi, jenerik "diğer resmî yazışma" değil). "Dilekçeye cevap yaz" gibi karşıt-yönlü ifadeler ("reply to a petition") en uzun-eşleşme-önce kuralıyla bare "dilekçe" (author one) üzerinden doğru yöne çözülüyor.
  - **Belge türünden çıkarım artık yalnızca gerçek bir gelen evrak varken çalışıyor**: sohbet-yalnız akışta `_run_classification` kullanıcının kendi mesajını sınıflandırdığı için, "dilekçe" etiketi "bana dilekçe yaz" demekti, "dilekçeye cevap ver" değil -- bu adım artık `has_source_document=False` iken hiç tetiklenmiyor.
  - **Belirsizse artık sorulmuyor, taslak yanlış türde üretilmiyordu**: yazım briefi kapısına (`writing_brief`) öncelik 0 (en yüksek) bir "Yazışma türü" yuvası eklendi; kullanıcının isteği bir türe net biçimde çözülemiyorsa taslak üretilmeden önce sorulur.
  - **Bireysel dilekçe için kurumsal antet/Sayı zorlanmıyor**: `verify_draft`'ın yapısal denetimi daha önce her taslakta "Sayı:" satırı arıyor ve yoksa taslağı her zaman insan onayına düşürüyordu -- bir dilekçe sahibi kendi evrak sayısını yazmaz. Yeni `is_individual_petition` bayrağı bu denetimi bireysel dilekçe alt-türleri için atlıyor; `writer.md`'ye de antet/Sayı yerine muhatap+gövde+imza yapısını kullanan bir "Yapı İstisnaları" bölümü eklendi.
- **Doğrulanmamış Ara Model Çıktısı Ekrana Basılıyordu**: Taslak (`writer_node`) ve asistan (`_run_assist`) ajanları ham model token'larını `assert_no_prompt_leak`/doğrulama/çıktı güvenlik kapısı çalışmadan **önce** sohbete akıtıyordu; `final_result` geldiğinde bu metin silinip (genelde farklı, çünkü nihai yanıta "Resmî yazı taslağınız hazırlandı." öneki ekleniyordu) yenisiyle değiştiriliyordu -- hem kontrolden geçmemiş bilgi bir an için görünüyor hem de ekran "yazıp siliyor" gibi davranıyordu. Artık hiçbir ajan düğümü kendi ham çıktısını akıtmıyor (draft/assist/revise üçü de tamamen arabelleğe alıp doğruladıktan sonra sonucu döndürüyor); yeni `emit_reply_stream`, doğrulanmış nihai yanıtı `ChatService._enqueue_terminal_event`'ten, `final_result` olayından hemen önce, tek seferlik bir kaynaktan parça parça akıtıyor. Ekrana basılan her karakter artık yapısal olarak nihai yanıtla birebir aynı; frontend'deki kelime-diff/yeniden-yazma mantığı (`DiffRevealText`, `utils/textDiff.ts`) gereksiz hale geldiği için kaldırıldı.
- **Taslak Onayı/Revizyon/Yazım Briefi Sohbeti Kesen Ayrı Bir Popup Gibi Görünüyordu**: `InterruptPanel`, `ChatsPage`'de mesaj listesinin **üzerinde**, kendi kartlaşmış çerçevesiyle (`.upload-card`/`.workflow-panel` ile aynı kutulu görünüm ailesi) sabit duran ayrı bir panel olarak render ediliyordu -- kaydırılabilir konuşmanın dışında, akışı bölen bir diyalog gibi hissettiriyordu. Artık `MessageList` içine taşındı: onay/eksik-bilgi/yazım briefi istekleri konuşmanın kendi kaydırılabilir alanında, diğer asistan mesajlarıyla aynı `.chat-message` balonu içinde, sırayla görünüyor. `InterruptPanel`'in kendi mantığı (soru formu, hızlı seçim çipleri, onayla/revize/reddet) değişmedi; yalnızca dış çerçevesi kaldırıldı ve balonun kendi arka planı/kenarlığını devralacak şekilde yeniden biçimlendirildi.

### Test (#161)
- Yön farkındalıklı yazışma-türü/alt-tür çözümlemesi (orkestratör boilerplate'inin hiçbir türe eşleşmediği regresyon kilidi dahil), bireysel dilekçe için yapısal denetim istisnası, yazım briefi "Yazışma türü" yuvası, `emit_reply_stream`/akış-yalnız-nihai-yanıt davranışı ve `InterruptPanel`'in artık mesaj listesinin kaydırılabilir alanında (boş durumu bastırarak) bir sohbet balonu olarak render edildiği için kapsamlı birim ve entegrasyon testleri eklendi.

Refs: [#161](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/161)
### Eklendi (#162)
- **Markdown-öncelikli veri hazırlama hattı**: 364 PDF, 50 resmî HTML, 57 DOCX ve 19 eski DOC kaynağı; üretimde kullanılan OpenDataLoader/PDFium/Tesseract zinciri, Beautiful Soup, `python-docx` ve `antiword` ile deterministik Markdown kartlarına dönüştürülüyor. Kuru çalışma, yalnız belirli uzantıları işleme ve yalnız mevcut Markdown'ı normalleştirme kipleri eklendi.
- **İzlenebilir kalite raporu**: Her karta kaynak türü, kullanılan çıkarıcı, OCR bilgisi, sayfa sayısı, kalite puanı, `rag_status` ve eleme gerekçesi yazılıyor; özet `KALITE_RAPORU.md`, ayrıntılar `kalite-raporu.json` dosyasında tutuluyor.
- **Bağlama duyarlı anonimleştirme**: Genel `[SİLİNMİŞTİR]` değerleri; evrak sayısı, kişi, imza sahibi, kimlik, adres, telefon ve kurum iletişim bilgisi gibi semantik yer tutuculara dönüştürülüyor. Final few-shot çıktısında yüksek güvenli PII bulgusu sıfırlandı; yeni fail-closed kapı, gelecekte PII bulunan bir kaydın `ornekler.jsonl` dosyasına yazılmasını engelliyor.

### Değiştirildi (#162)
- **RAG kalite kapısı**: `rag_status` değeri `candidate`/`approved` olmayan kartlar artık `ornekler.jsonl` dosyasına alınmıyor. Kısa bilgilendirme metinleri için kategoriye özel alt sınır eklendi, aynı şablonun tekrarları elendi ve güvenle düzeltilemeyen 5 OCR/karakter bozukluğu karantinaya alındı. Final havuz 80 üst yazı, 99 cevap, 115 bilgilendirme ve 90 diğer resmî yazışma olmak üzere 384 örnektir.
- **Yanlış kaynak etiketleri düzeltildi**: 800 `OS-*` kaydın gerçek açık kaynak değil, otonom betikle üretilmiş sentetik örneklem olduğu açıkça işaretlendi; 225 başlık-gövde uyumsuzluğu ve 512 tekrar üretim RAG'ından çıkarıldı.
- **Dilekçe sitesi kazıntıları karantinaya alındı**: 35 açıklayıcı makale ve 5 site/ilke sayfasının ham kopyaları özgün konumlarında değiştirilmeden korundu; temizlenmiş türevleri `99_reddedilenler/dilekce_makaleleri/` altına yazılıp yazım örneği havuzundan çıkarıldı.
- Veri kataloğu artık kaynak/çıkarıcı/kalite/RAG durumu alanlarını taşıyor ve yinelenen `id` değerlerinde sessizce devam etmek yerine hata veriyor.

### Test (#162)
- Front matter, HTML ana içerik ve gerçek başlık seçimi, Word metin kutuları, eski silme işaretlerinin semantik dönüşümü, kurum iletişim bilgilerinin maskelenmesi, başlık-gövde uyumu, OCR karakter bozulması, fail-closed PII kapısı, kalite statüsü ve RAG eleme davranışı için birim testleri eklendi.

Refs: [#162](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/162)

## [1.54.0] - 2026-08-12
### Eklendi
- **Dinamik İş Akışı Paneli**: Sohbet ekranındaki iş akışı göstergesi artık her turda aynı sabit 5 aşamayı (analiz → taslak → doğrulama → onay → yönlendirme) çizmek yerine, backend'in SSE üzerinden zaten gönderdiği `plan_steps`/`intent` (`planning_completed`) ve her düğümün kendi Türkçe etiketini taşıyan `node_start`/`node_end`/`node_error`/`node_skipped` olaylarından türetiliyor -- sadece belge analizi yapan bir tur artık tek bir aşama gösteriyor, bir asistan turu araç çağrılarını kendi satırının altında listeliyor. `verify`/`judge`, revizyonun alt adımları ve `brief_gate` gibi düğümler okunabilirliği korumak için sahip oldukları adımın altına toplanıyor; backend'in hiç bilmediğimiz yeni bir düğüm eklemesi durumunda o düğüm sessizce kaybolmuyor, kendi satırı olarak beliriyor. Bir oturum geçmişten açıldığında (canlı SSE akışı olmadan) planı yeniden kurabilmek için `planning_graph._compile_final_output`'a `plan_steps`/`intent` eklendi.
- **Evrak alanlarını elle düzenleme**: Analiz sırasında tespit edilemeyen veya yanlış çıkarılan üst veri alanları (Sayı, Tarih, Muhatap vb.) artık evrak analiz panelinden elle düzeltilebiliyor. Yeni `PATCH /api/v1/documents/{storage_path}/fields` uç noktası düzeltilen alan setini kaydediyor ve aynı deterministik kural tablosuyla (`check_required_fields`, model çağrısı yok) uygunluk kontrolünü anında yeniden çalıştırıyor.
- **Taslak ve evrak silme**: Taslaklar sayfasından bir taslağı (ve tüm sürüm geçmişini) silme, Evraklar sayfasından bir evrakı (DB kaydı, ham dosya, analiz önbelleği ve dizinlenmiş Q&A parçaları dahil) kalıcı olarak silme eklendi. Taslak silme `DraftModel.is_deleted` üzerinden yumuşak silme (zaten var olan ama hiç yazılmayan bir alan); evrak silme geri alınamaz gerçek bir silme.
- **Sohbet ekranına dosya sürükleyerek yükleme**: Sohbet ekranı açıkken bir dosya sürüklendiğinde tam ekran "dosyanızı buraya bırakın" katmanı beliriyor; bırakıldığında dosya doğrulanıp mevcut evrak yükleme/analiz akışına yönlendiriliyor, yeni evrak otomatik seçiliyor ve sohbete bilgilendirme mesajı düşüyor.

### Değiştirildi
- **Taslak adlandırması**: Taslaklar sayfasındaki satır başlığı artık yalnızca yazışma türünü ("Cevap yazısı") değil, "Belge Adı - Yazı Türü" biçimini (örn. "izin-talebi.pdf - Cevap yazısı") gösteriyor; ayrı "Kaynak evrak" sütunu kaldırıldı.
- **Taslaklar sayfasındaki durum rozetleri kaldırıldı**: yeşil "Hazır" / sarı "İnsan onayı" rozetleri hem satırlarda hem genişletilmiş detay panelinde gösterilmiyor artık.
- **Yönlendirme sayfasındaki güven skoru kaydırıcısı kaldırıldı**: serbest metinle öneri istenirken artık rastgele bir güven skoru gönderilmiyor (backend zaten 100 varsayıyor); kalıcı bir taslak seçildiğinde o taslağın gerçek güven skoru arka planda kullanılmaya devam ediyor.

### Düzeltildi
- **Uzun sohbette sayfa yarım kalması**: `.messages-area`/`.chat-workspace`'in sıfır-tabanlı flex ayarı (`flex:1` = `1 1 0%`) mesaj listesinin hiç küçülmemesine, tüm daralmanın küçülemeyen kardeşlerine (guardrail uyarıları, İnsan Onayı paneli) yıkılmasına ve konteynerin taşarak `overflow:hidden` tarafından sertçe kırpılmasına yol açıyordu; buna `scrollIntoView`'ın `overflow:hidden` atalarını da (scrollbar'ı olmadan) kaydırması ekleniyordu. Mesaj listesi artık kendi kabına göre kayıyor (`scrollTop` doğrudan yazılıyor, kullanıcı yukarı kaydırdıysa aşağı zorlanmıyor), guardrail listesi ve onay paneli kendi üst sınırlarıyla bağımsız kayıyor, ve `100vh` yerine `100dvh` kullanılarak mobil tarayıcı araç çubuğunun sayfayı kırpması önlendi.

### Test
- Dinamik iş akışı türetmesi (plan dışı düğümler, alt adım gruplama, araç çağrıları, bilinmeyen düğümler), evrak alan düzenleme formu, taslak/evrak silme akışları (onay diyaloğu dahil, backend'de sahiplik/yetki testleri), sohbet dosya sürükleme akışı ve mesaj listesi kaydırma davranışı için kapsamlı birim ve entegrasyon testleri eklendi.

Refs: [#159](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/159)

## [1.53.0] - 2026-08-11
### Eklendi
- **Taslak Öncesi Yazım Briefi**: "…dilekçe yazmak istiyoruz KACMAK ekibi olarak" gibi bir sorgu, KACMAK'ı *muhatap* sanan yanlış yönlü bir taslak üretiyordu -- `_build_brief`'in şemasında kim yazıyor/kime yazıyor ayrımı hiç yoktu. Yeni `app.ai.workflows.writing_brief` modülü altı yazım-stili yuvasını (yazan taraf, muhatap, anlatım, kapanış, imza, sayı/tarih) deterministik ve LLM'siz biçimde çözüyor: kullanıcının kendi metninden ("X ekibi olarak", "X adına"), ekli belgenin sınıflandırmasından (bir cevap yazısı turunda gönderen/muhatap rolleri tersine çevrilerek) veya oturumun önceki briefinden. Yalnızca gerçekten bilinmeyen yuvalar sorulur (en fazla 4), her birinde "Sen karar ver" seçeneğiyle. Yeni bir `brief` plan adımı + taslak üretiminden **önce** duraklayan ayrı bir `brief_gate` düğümüyle bağlandı -- `human_gate_node`'un kendi ayrımıyla aynı sebeple: `interrupt()` düğümü resume'da baştan oynattığı için pahalı çözümleme işi replay yoluna hiç girmiyor. Cevaplar hem oturum boyunca (`SessionFocus.writing_brief`) hem sürüm bazında (`DraftVersion.writing_brief`, revize turlarının aynı yönü koruması için) taşınıyor.
- **Claude Tarzı Tek Soru Kartı**: Eksik-bilgi kapısı, yazım briefi kapısı ve `clarify` netleştirme sorusu artık tek bir paylaşılan `PromptQuestion` şeması ve tek bir `PromptQuestionCard` bileşeni üzerinden render ediliyor -- serbest metin, tekli/çoklu seçim ve "Diğer…" serbest metin geri dönüşünü destekliyor. Kart, Claude Code'un plan modundaki gibi **adım adım** çalışıyor: tüm sorular tek bir formda birden açılmıyor, tek soru gösteriliyor ve ilerleme çubuğuyla ("Soru 2/4") sıradaki soruya geçiliyor; tekli seçimde bir seçeneğe tıklamak otomatik olarak ilerletiyor. Onay kartına ayrıca üslup/hitap/kapanış/kapsam için hazır çok-seçimli revizyon kısayolları eklendi.
- **Üç Kademeli Yazım Briefi Çözümü**: `writing_brief` çözümleyicisi artık yuvaları ikili (bilinen / bilinmeyen) değil üç kademeli değerlendiriyor -- güçlü bir sinyal varsa (`"X ekibi olarak"`, bir belgenin kendi alanı) hiç sorulmuyor; zayıf bir sinyal varsa ("Ahmet Yılmaz olarak", `"Fen Fakültesi'ne"` gibi datif işaretli bir özel ad, ya da muhatabın makam hiyerarşisinden çıkarılan bir kapanış tahmini) yuva yine sorulur ama tahmin "(Önerilen)" etiketli bir şık olarak seçeneklerin başına eklenir; hiçbir sinyal yoksa yuva düz sorulur. Böylece kullanıcıya sorgudan/belgeden zaten çıkarılabilecek şeyler kör bir soru olarak değil, tek tıkla onaylanabilecek bir öneri olarak gidiyor.
- Onay kartına, sohbet metninden çıkarılan güven skoru/insan onayı/önerilen birim bilgilerini gösteren sessiz bir meta şerit (`DraftMetaStrip`) eklendi.

### Düzeltildi
- **`notice`/`question` SSE Olayları Sessizce Düşüyordu**: `chatService.ts`'teki `isWorkflowEvent` doğrulayıcısında bu iki olay için `case` eksikti; sisteme daha önce eklenen Claude-tarzı netleştirme kartı ve revizyon çelişki uyarıları bu yüzden hiç ekrana gelmiyordu.
- `ChatService._select_reply` artık taslak yanıtına `**Önerilen Birim:**`, onay/red gerekçesi ve değişiklik özeti gibi serbest metinler eklemiyor -- yanıt yalnızca taslak metnidir; aynı bilgi zaten `details` üzerinden taşınan yapılandırılmış veriden onay kartı ve `DraftMetaStrip` tarafından render ediliyor.
- **"Bilinenler" Şeridi Yanlış Bilgi Gösteriyordu**: imza/sayı-tarih gibi opsiyonel yuvalar hiçbir şeyden çözümlenemediğinde sessizce "Sen karar ver"e varsayılıyordu, ama bu varsayılan sanki gerçekten bilinen bir gerçekmiş gibi "Bilinenler" şeridinde gösteriliyordu. `_step_brief` artık bu "default" kaynaklı girdileri kullanıcıya gönderilen payload'dan filtreliyor.
- **Onay/Soru Kartı Sohbeti Kaplıyordu**: büyük ikon rozeti + eyebrow satırı + başlık + açıklama paragrafından ve amber uyarı kenarlığından oluşan ağır header, sıradan bir soru için gereğinden büyük ve alarm gibi görünüyordu. Tek satırlık kompakt ikon+başlığa indirildi, kenarlık nötr renge çevrildi.
- **Güvenlik Taraması Sırasında Taslağın Birden Kaybolması**: `node_start` her düğümde (doğrulama, güvenlik kontrolü, yönlendirme dahil) akan taslak metnini sıfırlıyordu; yalnızca gerçekten token akıtan üç düğüm (`draft`/`revise`/`assist`) artık metni temizliyor, akan önizleme bu ara adımlar boyunca ekranda kalıyor. Güvenlik taraması sonrası nihai metin akıtılan önizlemeden farklıysa (örn. bir bilgi gizlendiyse), yeni bir kelime-seviyesi diff (`utils/textDiff.ts`) sadece değişen kısmı kısa bir parlama animasyonuyla vurguluyor.
- **Revizyon Sırasında Önceden Doldurulmuş Boşlukların Silinmesi**: `revise_graph`'ın üç taslak-yeniden-yazma yolundan ikisi -- hedef bölüm bulunamayan "tüm taslağı yeniden yaz" durumu ve her onarım (repair) turu -- modelin ham çıktısını, orijinal metinle karşılaştırmadan (splice etmeden) doğrudan nihai taslak olarak kabul ediyordu. Prompt, değişmeyen kısımları aynen korumasını söylese de bunu doğrulayan hiçbir mekanizma yoktu; küçük/hızlı bir model "değişmeyen" bir bölümü "..." gibi bir kısaltmayla atlarsa, kullanıcının eksik-bilgi kapısından veya elle doldurduğu gerçek bir bilgi (isim, kurum vb.) sessizce siliniyordu. Yeni `app.ai.revision.elision.detect_content_loss`, her onarım turunda taslağı turun gerçek başlangıç noktasına (`active_draft.text`) karşı denetliyor -- açık bir kısaltma ifadesi ("...", "[değişmedi]") veya kısaltma talep edilmeden beklenmedik bir uzunluk düşüşü tespit ederse mevcut sınırlı onarım döngüsüne bir düzeltme maddesi ekliyor; onarım denemeleri tükenip sorun hâlâ çözülmemişse taslak sessizce tamamlanmış sayılmak yerine insan onayına düşüyor. Reviser'ın prompt'ları da (`reviser.md` ve `revise_graph`'ın kendi promptları) bu tür kısaltmaları açıkça yasaklayacak şekilde güçlendirildi.

### Test
- `writing_brief` çözümleyicisi (üç kademeli öneri davranışı dahil), taslak öncesi kapı (duraklama/resume/reddetme/tam belirlenmiş turun atlaması), briefin revize turuna taşınması, `textDiff` kelime-diff yardımcı fonksiyonu, `detect_content_loss` içerik-kaybı denetimi ve `PromptQuestionCard`/`DraftMetaStrip`/`InterruptPanel` için kapsamlı birim ve entegrasyon testleri eklendi.

## [1.52.0] - 2026-08-10
### Eklendi
- **Görev Alanı Denetimi (Domain Admission Gate)**: `resolve_plan` şimdiye kadar yalnızca *hangi* akışın istendiğine karar veriyordu, isteğin sistemin görev alanına girip girmediğine hiç bakmıyordu -- "Çiğköfte kampanyası için bir metin yaz" `draft.explicit_request`'in kendi `"metni yaz"` yüzeyine tam uyduğu için sözlüksel katman, füzyon ve gerekirse model tie-breaker'ın tamamı bunu *niyet* olarak doğru şekilde `draft`'a çözüyor, ve alt akışların hiçbiri bunu sorgulamıyordu. Yeni `app.ai.workflows.scope` modülü niyet çözümlendikten *sonra*, herhangi bir adım çalışmadan önce ayrı bir kabul denetimi uyguluyor: deterministik katman isteği yüklü bir belgeye, açık bir taslağa veya resmî yazışma/mevzuat terminolojisine (`DOMAIN_SURFACES`) çapalanmış olarak arıyor; yalnızca çapasız üretim istekleri (draft/analyze/revise) hızlı katman modeline (`resolve_plan`'ın kendi tie-breaker'ıyla aynı istemci) yükseltiliyor. Kapsam dışı bir istek artık her zaman deterministik yeni bir `refuse` plan adımına çözülüyor: `CAPABILITY_MANIFEST`'ten **üretilmeden** (generate edilmeden) render edilen sabit bir yetenek listesi döndürüyor -- bir ret asla bir üretim değildir, aksi hâlde az önce reddedilen model aynı off-topic metni üretmek için bir şans daha bulurdu.
  - **Deny-list değil, kanıt gerektiren model.** Yasaklı konuların bir listesi yerine (öngörülemeyen her yeni konuda tekrar açık kalır), kural tersine çevrildi: küçük sohbet, nezaket, sistem hakkında sorular ve bu konuşmanın kendisiyle ilgili sorular her zaman kapsam içi; bir şey *üretme* isteği yalnızca bir belgeye, açık bir taslağa veya resmî yazışma kaydına çapalıysa kapsam içi.
  - **Bare-command muafiyeti.** "Cevap yaz." gibi salt bir üretim komutu -- kendisinden başka konusu olmayan -- her zaman kapsam içi kabul ediliyor (yeni paylaşılan `app.ai.workflows.topic_words.content_words` yardımcı fonksiyonu, router'ın kendi `DRAFT_RULES`/`REVISE_RULES`/`CONTINUATION_SURFACES` tablolarından komut/devam yüzeylerini çıkarıp geride kalan "konu" kelimelerine bakıyor) -- router'ın kendi modül docstring'indeki belirsiz-olmayan-emir örneğini kırmadan.
- **Belge-İlgi Denetimi (Relevance Gate)**: `scope.py` yüklü bir belgeyi tek başına yeterli çapa sayıyor (bu, kapsam sorusu için doğru cevap), ama bu "Bu evraka çiğköfte kampanyası için bir metin yaz"ın da geçmesine izin veriyordu. Yeni `app.ai.workflows.relevance`, sınıflandırma (ve onun `summary`'si) elde edildikten sonra `planning_graph._step_draft`'tan çağrılan daha dar bir ikinci katman: istek resmî yazışma diliyle mi ifade edilmiş yoksa belgenin kendi özetiyle mi örtüşüyor kontrol ediyor, gerçek bir uyumsuzluğu aynı hızlı model katmanına yükseltiyor. İlgisiz bulunan bir istek artık `draft_graph`'ı hiç çağırmıyor; bunun yerine "bu istek bu belgeyle ilgili değil" + belge özeti şeklinde deterministik bir yanıt üretiyor. `draft_result` artık `SKIPPED` durumuna geçebiliyor (hata değil, bilinçli bir vazgeçiş) ve `_dependency_failed` artık `FAILED`'in yanı sıra `SKIPPED`'i de zincirliyor, böylece `routing` boş bir taslak üzerinde hiç çalışmıyor.
- **Bilgilendirme ve Soru SSE Olayları**: SSE olay sözlüğüne iki yeni tip eklendi -- `notice` (bloklamayan, kendi sohbet mesajı olarak görünen bir bilgilendirme; örn. bir revizyon çelişkisi uyarısı) ve `question` (2-4 tıklanabilir seçenekli bir netleştirme sorusu, Claude Code'un `AskUserQuestion`'ı gibi). `clarify` adımı artık sorusunu seçeneklerle birlikte canlı yayınlıyor; frontend bunları ayrı bir sohbet mesajı üzerinde tıklanabilir düğmeler olarak render ediyor, seçilen etiketi normal bir kullanıcı mesajı gibi geri gönderiyor (`planner._try_resolve_pending_clarification` ile aynı yoldan çözülüyor). Önceden yayınlanan ama tipsiz kalan `guardrail` olayı da sözleşmeye (`event_schema.py`, `test_event_contract.py`) geri kazandırıldı.

### Düzeltildi
- **Revizyon Akışındaki Çakışma Uyarısı Artık Bloklayıcı Bir Popup Değil**: `app.ai.revision.conflict`'in kendi `ConflictReport.applied_anyway` sabiti, bir talimat-mevzuat/kaynak çelişkisinin **her koşulda** ("talimat uygulandı, sadece bir uyarı") çözülmesi gerektiğini söylüyordu, ama `revise_graph.audit_node` yine de bir çelişki bulunca `status`'u `NEEDS_HUMAN_APPROVAL`'a yükseltiyor, `route_after_gate_revise` da bunu insan onay kapısını açan bir tetikleyici olarak okuyordu -- kullanıcının vereceği hiçbir karar yokken (talimat zaten uygulanmıştı) genuine bir onay bekleyen düşük kaliteli taslaktan ayırt edilemeyen bir popup. `audit_node` artık asla `status`'u yükseltmiyor; bunun yerine yeni, bloklamayan bir `notice` SSE olayı yayınlıyor (kendi sohbet mesajı, asla popup). `route_after_gate_revise`'ın `"or draft_result.get('conflicts')"` tetikleyicisi kaldırıldı; `_select_reply` artık aynı uyarıyı iki kez göstermemek için birleşik yanıt metnine çelişki bloğunu eklemiyor (yapılandırılmış bulgu `final_output.draft.conflicts` üzerinden hâlâ erişilebilir).
- **Reviser'ın Kendi Prompt İskeletini Sızdırması ("brief 1 brief 2")**: `revise_graph.rewrite_node`'un ham model tamamlaması, herhangi bir doğrulama çalışmadan **önce**, sohbete parça parça (`emit_token`) canlı akıtılıyordu. Daha küçük yerel modeller yoğun numaralı bir prompt'a (`_build_brief`'in "1. Önceki Taslak Sürümü... 2. Doğrulanmış Sınıflandırma...") maruz kaldığında, kendi iskeletini tamamlamasının içine yansıtma eğilimindedir -- ve bu, hiçbir denetimin göremeyeceği kadar erken ekrandaydı. `rewrite_node` şimdi her reviser çağrısını tamamen arabelleğe alıyor, `assert_no_prompt_leak`'in yanı sıra bu uygulamanın kendi prompt bölüm başlıklarını (`### BRIEF BELGESİ`, `Önceki Taslak Sürümü:`, vb.) yakalayan yeni `assert_no_scaffold_echo` denetimini çalıştırıyor, ve yalnızca doğrulamadan geçen metni **tek bir** token olayı olarak yayınlıyor -- doğrulama başarısız olursa hiçbir şey ekrana çıkmıyor.
- **Ardışık Revizyon Turlarının Sohbette Birbirine Karışması**: frontend, `streamingText`'i yalnızca `node === "draft"` düğüm başlangıcında temizliyordu; `revise` düğümü aynı turda birden çok kez (çok-direktifli talimatlar için direktif başına, onarım döngüsü için tur başına) yeniden çalıştığından, ikinci bir turun token'ları öncekinin bıraktığı metnin üzerine ekleniyordu ("brief 1 brief 2" görünümünün ikinci yarısı). Artık her `node_start` olayı `streamingText`'i temizliyor.
- **"Cevap yaz." ve "evet, hazırla" Yanlışlıkla Reddedilmesi**: kapsam denetiminin bare-command muafiyeti ilk sürümde iki durumda başarısız oluyordu -- (1) `hazirla` gibi tek kelimelik `CONTINUATION_SURFACES` yüzeyleri, daha uzun `"yazi hazirla"` gibi çok kelimeli komut yüzeylerinden **önce** çıkarılıyor, ifadeyi parçalayıp "yazi"yı sahte bir konu kelimesi olarak arkada bırakıyordu; `content_words` artık yüzeyleri en uzundan en kısaya doğru çıkarıyor. (2) "evet" gibi kısa bir onay kelimesi konu içeriği olarak sayılıyordu; `CONTINUATION_SURFACES` artık `topic_words`'ün komut/konu ayrıştırıcısına da dahil.

Refs: [#155](https://github.com/chyp3r/KACHOW-Teknofest-2026/issues/155)

## [1.51.0] - 2026-08-09
### Eklendi
- İş akışı, evrak ve taslak alanlarının farklı bilgi yapıları için `WorkflowStepper`, `DocumentListItem` ve `DraftTable` feature composite bileşenleri eklendi. Ortak primitive sistemi korunurken satır semantiği feature katmanında ayrıştırıldı.
- Uygulama/sidebar/içerik/panel/etkileşim/yükseltilmiş/input yüzeyleri ile 248/76 piksel sidebar rolleri semantik design tokenlarına bağlandı.

### Düzeltildi
- Teknik grafik açıldığında iş akışı panelinin genişlemesi kaldırıldı; panel 400 piksel rolünü korurken grafik düğüm daireleri ve dış etiket mesafeleri büyütüldü.
- Chat composer üst kontrol satırı tek hizaya indirildi; evrak eylemi solda, `AI modu` ve seviye seçimi sağda konumlanarak gereksiz dikey yükseklik kaldırıldı.
- İş akışı marker, başlık, açıklama ve tek durum badge'i sabit grid yapısına geçirildi; dar panelde çakışma kaldırıldı. Teknik grafik kontrollü progressive disclosure, genişleyen panel, tam genişlikte statik toolbar–canvas–yardım katmanları ve yeniden boyutlanınca kamera sıfırlama davranışı kazandı.
- `PageHeader` eylem grupları, sidebar marka/footer/tema kontrolleri ve chat composer/boş durum hizaları ortak responsive hiyerarşiye getirildi; geniş sidebar'daki ikinci tema ikonu kaldırıldı.
- Evrak arama/filtre/sıralama araç çubuğu içerik ölçüsüne göre dengelendi; evrak satırları dosya adı, kısa özet, tür, tarih ve durum alanlarıyla okunabilir hâle getirildi.
- Taslak listesi masaüstünde gerçek kolonlu tabloya, tablet ve mobilde ayrı etiketli alanlara dönüştürüldü; büyük-küçük harf farkı taşıyan kalıcı durumlar kullanıcı diline normalize edildi.

### Test
- Page header, workflow stepper/disclosure/graph, composer loading, duplicate tema kontrolü, evrak/taslak semantiği ve klavye aktivasyonu için regresyon testleri eklendi. 1920×1080, 1440×900, 1366×768, 800×1024, 390×844 ve 200% ölçek eşdeğeri görünümler açık/koyu/sistem temalarında tarayıcıda doğrulandı.

## [1.50.0] - 2026-08-09
### Eklendi
- **Frontend design-system temeli oluşturuldu**: 4 piksel spacing ölçeği; ortak control/touch-target, icon/container, radius, semantic border, focus, surface ve elevation tokenları `design-system.css` içinde merkezileştirildi.
- `Button`, `IconButton`, `Input`, `Select`, `Textarea`, `FormField`, `Card`, `StatusBadge`, `Alert`, `Divider`, `Spinner`, `Skeleton`, `PageHeader`, `SectionHeader`, `EmptyState`, `ErrorState`, `ListRow`, `Drawer`, `Dialog`, `FormActions`, `Stack`, `Inline`, `Cluster` ve `Grid` ortak bileşenleri eklendi veya mevcut ortak bileşenler genişletildi.
- Geçiş öncesi ölçüm envanteri, component API sözleşmesi, state/erişilebilirlik kuralları ve belgelenmiş geometri istisnaları `docs/development/frontend-design-system.md` içinde kaydedildi.

### Değiştirildi
- Uygulama kabuğu, sohbet/composer, sohbet geçmişi, evrak kütüphanesi/seçici/yükleyici, taslaklar, yönlendirme, hesap, yönetim, sistem durumu, workflow ve interrupt panelleri ortak component sistemine taşındı; ordinary production JSX içinde sayfa-özel button/input/select/textarea uygulamaları kaldırıldı.
- Taslak oluşturma alanı responsive shared form grid, `FormField` yapısı, gömülü textarea counter ve mobilde tam genişlikte `FormActions` kullanıyor. Taslak ve evrak kayıtları tüm satırı aktive eden erişilebilir `ListRow` yapısını paylaşır.
- Eski spacing/radius/border bildirimleri 4 piksel token ölçeğine geçirildi; 32/40/44 piksel kontrol ve touch-target rolleri merkezileştirildi. Desktop/tablet/mobile gutterları 32/24/16 piksel olarak standardize edildi.
- Drawer ve dialog focus trap, Escape, scroll lock ve tetikleyiciye focus dönüşü ortak overlay bileşenlerinde konsolide edildi.

### Test
- Button variant/loading/disabled, icon-only accessible name, field label/error ilişkileri, list-row activation, dialog Escape, drawer scroll/focus davranışı ve kritik design token sözleşmeleri için testler eklendi.

## [1.49.0] - 2026-08-09
### Değiştirildi
- **Sohbet ekranı konuşma odaklı bilgi mimarisine taşındı**: Varsayılan masaüstü görünümü 248 piksellik birincil navigasyon ve 860 piksele kadar merkezlenen konuşma alanıyla iki kalıcı sütuna indirildi. Evrak yükleyici/kütüphanesi ve boş sohbet geçmişi kalıcı yan sütunlardan kaldırıldı.
- **Navigasyon ve ikincil içerikler progressive disclosure ile düzenlendi**: Masaüstü navigasyonunun 76 piksellik dar tercihi kalıcı hâle getirildi; mobil navigasyon çekmece olarak çalışıyor. Sohbet geçmişi isteğe bağlı çekmeceye, evrak erişimi aranabilir modal/tam ekran seçiciye taşındı; seçilen evrak kompakt kaldırılabilir çip olarak gösteriliyor.
- **Dar sidebar geri dönüşü ve footer taşması düzeltildi**: Dar görünümde marka metninin ve footer kontrollerinin 76 piksel dışına taşması kaldırıldı. Her zaman görünür 44×44 genişletme düğmesi, 44×44 navigasyon hedefleri ve yalnız ikonlu tema/oturum kontrolleri eklendi. Mobil çekmece masaüstü dar tercihinden ayrıştırıldı; hamburger çekmece açıkken gizleniyor, marka ve kapatma düğmesi çakışmıyor.
- **İlk mesajdan sonra sohbetin sıfırlanması düzeltildi**: Backend'in ilk `session` SSE olayı URL'yi gerçek thread kimliğine taşıdığında bu iç route değişimi artık harici sohbet seçimi gibi aktif isteği abort edip mesajları temizlemiyor. Stream sürerken mesaj/state geçmişi sorguları bekletilerek boş veya kısmi backend cevabının iyimser kullanıcı mesajını ve canlı yanıtı ezdiği yarış durumu kapatıldı.
- **İlk taslak onay ekranının çökmesi düzeltildi**: Backend'in henüz revizyon yapılmamış taslaklarda gönderdiği boş `changelog` nesnesi güvenli biçimde karşılanıyor; panel değişiklik girdilerini yalnızca gerçek bir liste mevcutsa oluşturuyor.
- **Taslaklar sayfası tek sütunlu açılır listeye dönüştürüldü**: Yeni taslak formu varsayılan görünümden kaldırılıp sağ üstteki “Yeni taslak” eylemiyle açılan kompakt, tam genişlikte bir panele taşındı. Kalıcı taslaklar kaynak evrak adlarıyla birlikte satır halinde gösteriliyor; route tabanlı satır seçimi sürüm geçmişini aynı satırın altında açıyor. Her sürüm 420 karakterlik önizleme ve erişilebilir “Tümünü gör / Daha az göster” chevron kontrolü kullanıyor.
- **Evrak Kütüphanesi taslaklarla aynı açılır liste düzenine taşındı**: Ana başlığın yanındaki açıklama kaldırıldı; yükleme alanı sağ üstteki “Evrak yükle” düğmesiyle açılan kompakt, tam genişlikte bir panele dönüştürüldü. Arama/filtre/sıralama korundu; evrak satırı seçildiğinde analiz ayrıntıları mevcut derin route davranışıyla satırın altında açılıyor ve aynı satırdan kapatılabiliyor.
- **Teknik karar grafiği etkileşimli ve keskin bir viewport kazandı**: Grafik %60–%300 arasında büyütülüp küçültülebiliyor; fare/tek parmak sürükleme, iki parmak pinch, tekerlek, araç çubuğu ve klavye kontrolleri destekleniyor. CSS katmanı ölçeklemek yerine SVG'nin yerel `viewBox` kamerası değiştirildiği için yüksek yakınlaştırmada çizgi ve metinler bitmap bulanıklığına düşmüyor. Görünüm sıfırlama, yakınlaştırma yüzdesi, kullanım ipucu ve düğüm seçimiyle çakışmayan pan davranışı eklendi.
- **Teknik grafiğin bağlantı çizgileri belirginleştirildi**: Bekleyen edge'lerin tema uyumlu kontrastı ve kalınlığı artırıldı; çalışan, tamamlanan ve hatalı bağlantılara durum rengiyle hafif vurgu eklendi. `non-scaling-stroke` sayesinde zoom sırasında çizgi kalınlığı ekranda tutarlı kalıyor.
- **Sohbet geçmişi çekmecesi erişilebilir modal durum makinesine dönüştürüldü**: Çekmece artık viewport'un sol kenarından açılıp sidebar'ı örter; masaüstünde 380 piksel, dar mobilde tam genişlik kullanır. Escape/backdrop/44×44 kapatma düğmesi, odak tuzağı, scroll kilidi ve tetikleyiciye odak dönüşü eklendi. Yükleme skeleton'ları, yalnız hata+retry görünümü, açıklamalı boş durum, Bugün/Dün/Daha eski gruplu başarı listesi ve listeyi koruyan ince yenileme durumu birbirinden ayrıldı; yalnız büyük listelerde arama gösteriliyor.
- **İş akışı varsayılan olarak kapatıldı ve sadeleştirildi**: İlk görünüm beş adımlı durum zaman çizelgesidir; aktif, tamamlanan, başarısız ve kullanıcı eylemi bekleyen durumlar ikon ve metinle belirtilir. Tam teknik düğüm grafiği, tool/guardrail sinyalleri ve meta veriler ayrı bir genişletme eyleminin arkasında korunur. Panel 1366 pikselde konuşma ölçüsünü değiştirmeyen 400 piksellik örtü, mobilde tam ekran katman olarak açılır.
- **Görsel yoğunluk ve hata kapsamı azaltıldı**: Nötr açık/koyu yüzeyler, daha az kart/gölge ve kompakt 24–27 piksel sayfa başlıkları kullanılıyor. Yerel geçmiş hataları tüm sayfayı kaplayan banner yerine ilgili alanda yeniden denenebilir inline bildirim olarak sunuluyor; mesaj oluşturucu tek yüzeyde belge, yanıt biçimi, giriş ve gönderme hiyerarşisini koruyor.
- **Frontend typography sistemi semantik tokenlarla birleştirildi**: Sayfa/boş-durum/bölüm başlıkları, 16 piksellik okuma içeriği, 14 piksellik arayüz ve kontrol metinleri, 13 piksellik ikincil metinler ile 12 piksellik caption rolleri `typography.css` içinde merkezileştirildi. Eski tek seferlik 7.5–36 piksel değerler ve 750/800 ağırlıklar kaldırıldı; Türkçe sarma, 60–75 karakterlik içerik ölçüsü, açık/koyu tema kontrast renkleri, mobil başlık ölçeği ve tarayıcı font ölçekleme davranışı standardize edildi.

### Test
- Evrak seçicinin varsayılan kapalı durumu, arama/seçim akışı ve kaldırılabilir çipi için bileşen testleri eklendi; teknik grafiğin açık kullanıcı eylemine kadar kapalı kaldığı doğrulandı. Sohbet geçmişi için durum ayrımı, gruplama, koşullu arama, yenileme, Escape/backdrop, odak tuzağı, scroll kilidi ve odak geri dönüş testleri eklendi. Dar sidebar genişletme geri dönüşü, açık mobil drawer'da hamburgerin kaldırılması, ilk `session` route çözümlemesinin aktif stream'i koruması, boş taslak changelog'unun onay panelini çökertmemesi, taslak formu/liste/sürüm metni, evrak yükleme/liste/analiz progressive-disclosure akışları ve teknik grafiğin zoom/pan/reset etkileşimleri için regresyon testleri eklendi. Frontend test paketi 21 dosyada 43 test, TypeScript denetimi, ESLint ve production build ile doğrulandı.
- Typography token ölçeği, kritik semantik rol eşlemeleri, dört izinli ağırlık ve eski layout stylesheet'lerinde keyfi typography bildirimi kalmaması için kaynak sözleşmesi testleri eklendi.

## [1.48.0] - 2026-08-09
### Eklendi
- **Frontend–backend entegrasyonu tamamlandı**: React Router tabanlı korumalı ve lazy rotalar; TanStack Query ile sunucu-otoriteli belge, sohbet, taslak, yönlendirme ve health verileri; kalıcı sohbet/taslak geçmişi; hesap şifre değişimi; stateless yönlendirme önerisi ve rol kontrollü sistem durumu ekranları eklendi.
- **OpenAPI tip üretimi kuruldu**: Çalışan FastAPI uygulamasının gerçek OpenAPI çıktısından `frontend/src/api/generated.ts` üretildi; yeniden üretme ve drift kontrol komutları package script'lerine eklendi.
- **SSE dayanıklılığı genişletildi**: Parçalı frame buffer'ı, event-family doğrulaması, `seq` tekrar önleme, bozuk/bilinmeyen olay toleransı, kullanıcı iptali ve sayfa yenilemesinden backend state ile interrupt kurtarma eklendi.

### Değiştirildi
- **Kimlik doğrulama ve hata yönetimi merkezileştirildi**: Eşzamanlı 401 yanıtları tek refresh isteğinde birleştiriliyor; tekrar döngüsü engelleniyor; refresh başarısızlığında güvenli logout ve kullanıcı bildirimi üretiliyor. API hata kodu, request ID ve Retry-After bilgisi ortak hata modeline taşındı.
- **Backend tek doğruluk kaynağı yapıldı**: Belge, sohbet ve taslak geçmişi için eski localStorage otoritesi kaldırıldı; localStorage yalnızca tema tercihiyle sınırlandı.
- **Taslak deneyimi tamamlandı**: Backend list/detail/version endpoint'leri, doğrudan taslak üretimi, son iki sürüm karşılaştırması ve routing girdisi olarak kalıcı taslak seçimi bağlandı.

## [1.47.0] - 2026-08-07
### Değiştirildi
- **Niyet router'ı kalibre edilmiş sinyal füzyonuna taşındı (Router SOTA, Faz 1-5)**: router "bazen saçmalıyor" şikayetinin üç somut kök nedeni bulundu ve düzeltildi.
  - **Faz 1 -- sessiz bozulma**: `datasets/prototypes/intent.json` `policy_version: "1.2.0"` ve eski niyet uzayıyla (`chat`/`document_qa`) damgalıydı; çalışan politika `1.4.0`'dı. `PrototypeMatcher` sürüm uyuşmazlığında dosyayı sessizce atlıyordu -- semantik katman (Katman 2) üretimde haftalardır devre dışıydı ve sözlüksel katmanın çekimser kaldığı her mesaj doğrudan clarify/guess dalına düşüyordu. Vektörler yeniden üretildi, `revise` için prototipler eklendi (önceden hiç yoktu), ve bu sınıfın sessizce tekrarlanmasını önleyen bir bayatlık testi eklendi (`test_prototype_freshness.py`) -- artık `ROUTER_SEMANTIC_AVAILABLE` Prometheus gauge'u ve `/system/health?deep=true`'nun `router_semantic` alanı katmanın gerçekten yüklü olup olmadığını gösteriyor.
  - **Faz 2 -- ölçüm zinciri**: `evaluation/datasets/intents.jsonl` diskte 130 vaka taşıyordu ve etiketlerinin %49'u artık var olmayan niyetlere (`chat`/`document_qa`) işaret ediyordu; commit edilmiş rapor repoda bulunmayan bir altın kümeden üretilmişti. Altın küme göç ettirildi ve genişletildi (130 → 160 vaka: `revise`, `short_imperative`, `clarify_resolution` kategorileri ve genişletilmiş `heldout_paraphrase` eklendi), ölçüm koşumu artık gerçek `resolve_plan`'a (lexical + semantik, model hariç) bağlı -- önceden yalnızca lexical-only bir fonksiyona bağlıydı ve semantik katmanı, clarify dalını, tüm `revise` kurallarını hiç ölçmüyordu.
  - **Faz 3 -- kalibre edilmiş füzyon**: eski merdiven "ilk kararlı katman kazanır" mantığıyla çalışıyordu -- sözlüksel katmanın marj testi her şeyi kapıyordu, açık bir emrin ("Cevap yaz.") bile geçmesi gerektiği yerde (margin 1.0, eşiğin altında). Üç kanıt kaynağı (sözlüksel, semantik, bağlamsal) artık ayrı özellik değerleri olarak kalibre edilmiş bir çok-sınıflı lojistik modele (softmax, saf Python, yeni bağımlılık yok) besleniyor; katsayılar `scripts/fit_router.py` ile altın kümeye karşı çevrimdışı fit ediliyor (5 katlı CV: 1.0000). Ölçülen etki: macro F1 0.8311 → **0.9452**, kalibrasyon hatası 0.2736 → **0.1139**, `short_imperative` kategorisi (K2'nin somut örnekleri) 0.00 → **1.00** doğruluk.
  - **Faz 4 -- model rungu**: hızlı-katman model tasarım gereği en pahalı ama en akıllı rung olması gerekirken fiilen erişilemezdi ve yalnızca 3 etiket biliyordu (`revise` hiç döndürülemiyordu, "emin değilim" kanalı yoktu). `IntentOutput` 5 etikete çıkarıldı (`unclear` dahil), prompt aktif taslağı ve önceki niyeti görüyor, model çağrısının çökmesi (`model_failed`) ile modelin dürüstçe kararsız kalması (`unclear`) artık aynı sinyale toplanmıyor.
  - **Faz 5 -- gözlemlenebilirlik**: `kachow_router_decisions_total`/`kachow_router_confidence`/`kachow_router_stage_duration_seconds` Prometheus metrikleri, Grafana panosuna kaynak dağılımı ve clarify oranı panelleri, `planning_completed` SSE olayına `source`/`confidence`/`alternatives`, ve üretim trafiğinden düşük güvenli/clarify kararları JSONL olarak dışa aktaran `scripts/export_router_traces.py` (altın kümenin insan onaylı geri beslemeyle büyümesi için -- otomatik yeniden eğitim yok, bilinçli bir seçim).
  - `POLICY_VERSION` 1.4.0 → 1.5.0 (`IntentPolicy`'ye `tau_high`/`tau_low` eklendi). **Not**: bu sürümden itibaren bir policy bump hem `scripts/build_prototypes.py` hem `scripts/fit_router.py`'nin yeniden çalıştırılmasını gerektiriyor (bkz. `AGENTS.md`).

## [1.46.0] - 2026-08-07
### Değiştirildi
- **OCR Zinciri Hızlandırıldı**: dört değişiklik, ilki diğer üçünün ölçümünü güvenilir kılmak için zorunluydu.
  - **Kıyaslama betiklerinin tek-sayfa hatası düzeltildi**: `evaluate_ocr_benchmark.py`'deki `rasterise()` yalnızca `document[0]`'ı işliyordu -- çok sayfalı bir kaynak PDF'de bile her motora tek sayfalık bir görsel veriliyor, aşağıdaki sıralı döngüler hiç çalıştırılmıyordu. Artık her sayfayı rasterize ediyor; `ocr` modu artık PDF baytlarını doğrudan motora veriyor (her motor kendi çok sayfalı döngüsünü çalıştırıyor, üretimdekiyle birebir), `ocr-degraded` modu her sayfayı bozup tek bir çok sayfalı PDF'e yeniden paketliyor. `evaluate_ocr_fields.py` (hangi motorun gönderileceğine karar veren betik) hiç süre ölçmüyordu; artık motor başına toplam süre de raporluyor.
  - **Tesseract sayfaları artık eşzamanlı OCR ediliyor**: `_recognize`'ın tek arka plan iş parçacığı içindeki sıralı döngüsü, rasterize etmeyi (ucuz, sıralı kalıyor) OCR'dan (asıl maliyet) ayıran iki adıma bölündü; sayfa başına bir `pytesseract` çağrısı kendi `tesseract` alt sürecini bekleyen ayrı bir iş parçacığında çalışıyor -- alt süreç çağrıları GIL'i serbest bırakır, dolayısıyla eşzamanlı iş parçacıkları gerçekten ayrı CPU çekirdeklerinde çalışır. Regresyon testi, her sayfanın çağrısının **tüm sayfaların çağrıları başlamadan** dönmesini engelleyen bir `threading.Barrier` kullanıyor: sıralı bir uygulama sonsuza dek bekler (zaman aşımıyla başarısız olur), eşzamanlı bir uygulama anında serbest kalır.
  - **Görsel dil modeli yolu kasıtlı olarak sıralı bırakıldı**: Ollama tek bir modele karşı üretimi sıralar; bu projede daha önce ölçülen eşzamanlı `classify`+`extract` çağrılarıyla aynı maliyet şekli (kazanç yerine kayıp). Bu ortamda canlı bir Ollama örneği olmadan bunu yeniden ölçmek mümkün değildi -- son çare, en zor okunur belgeler için olan bu yolda tahmin ederek yanlış yapmak, doğru ölçüp uygulamaktan daha riskli.
  - **Taranmış PDF'ler artık yalnızca bir kez rasterize ediliyor**: `TesseractExtractor` ve `OllamaVisionExtractor` arasında paylaşılan, DPI'a göre anahtarlanan bir `raster_cache` sözlüğü -- `FallbackDocumentExtractor` her üst düzey `extract()` çağrısında tazesini kuruyor. Tesseract'ın sonucu reddedilip zincir görsel modele yükseldiğinde (bozuk bir taramada asıl senaryo budur), ikinci motor pdfium'u hiç açmadan Tesseract'ın zaten render ettiği sayfaları yeniden kullanıyor.
  - **`opendataloader` artık gerçek taramalarda hiç çalıştırılmıyor**: yeni `has_pdf_text_layer` (pdfium'un kendi metin akışını okuyan, JVM'siz, OCR'sız ucuz bir yoklama; ilk birkaç sayfayla sınırlı) hem `OpenDataLoaderExtractor.supports()` hem `PdfiumExtractor.supports()`'a eklendi. Metin katmanı olmayan bir PDF artık bu iki metin-katmanı çıkarıcısını tamamen atlayıp doğrudan OCR motorlarına düşüyor -- taranmış bir belge artık `opendataloader`'ın JVM başlatma maliyetini hiç ödemiyor.

## [1.45.0] - 2026-08-07
### Eklendi
- **Belge Analizi Artık Varsayılan Olarak Canlı Mevzuat Kullanıyor (MCP-first)**: `retrieve_mevzuat` düğümü artık `MEVZUAT_SOURCE` ayarına göre kaynak seçiyor -- `"mcp"` (yeni varsayılan) korpustaki yedi kanunun güncel metnini `mevzuat-mcp` üzerinden çeker, bellekte BM25 ile indeksler ve mevcut `_build_mevzuat_query`'nin ürettiği sorguyla sıralar; `"local"` önceki davranışın aynısı, doğrudan yerel `HybridRetriever` (Qdrant, dense+sparse).
  - **Uygunluk kararı hâlâ dokunulmuyor.** `check_required_fields` sabit madde numaraları üzerinde küme farkı; yeni `test_missing_fields_is_identical_regardless_of_the_mevzuat_source` iki kaynak altında `missing_fields`'in bayt bayt aynı kaldığını, yalnızca alıntıların (`mevzuat_documents`) farklılaşabildiğini doğruluyor.
  - **`mevzuat-mcp`'nin gerçek yüzeyi bir içerik/konu araması değil, bir katalog aramasıdır** (numara/ad ile ara, tam metni getir) -- `_build_mevzuat_query`'nin ürettiği anahtar-kelime yoğun konu dizesini doğrudan bir katalog başlığı aramasına vermek neredeyse hiç eşleşmezdi. Bunun yerine korpusun zaten küratörlüğünü yaptığı aynı yedi kanun numara ile çekilip yerel indeksle aynı `RecursiveChunker(1000, 200)` parametreleriyle parçalanıyor ve taze bir `BM25Retriever`'da sıralanıyor.
  - **Getirim isteğe hiç ağ I/O'su eklemiyor.** `McpMevzuatRetriever.retrieve()` yalnızca `warm_up()`'ın en son kurduğu bellek-içi indeksi okur; `retrieve_mevzuat`'ın düğüm bütçesi (dengeli seviyede 25 sn) yedi kanunun playwright-destekli bir MCP sunucusundan soğuk çekilmesini garanti bitiremeyeceğinden, çekim tamamen istek yolunun dışında tutuluyor. `warm_up()` açılışta diğer ısınma adımlarıyla (`app.lifespan`) birlikte en iyi çaba ilkesiyle çalışıyor; yavaş/erişilemeyen sunucu açılışı bloklamıyor, yalnızca canlı kaynağın devreye girmesini geciktiriyor.
  - **Her hata yerel korpusa düşüyor:** kayıtsız sunucu, zaman aşımı (kanun başına, yedisi eşzamanlı çekilirken biri asılı kalırsa diğerlerini bekletmemesi için ayrı ayrı sınırlı), kısmi getirim, boş sonuç -- hepsi `FallbackMevzuatRetriever` üzerinden yerel `HybridRetriever`'a düşüyor.
  - **Genel asistan sohbeti (Görev 3) bu anahtardan etkilenmiyor.** `get_rag_graph` hâlâ yalnızca yerel korpusu okuyan `get_mevzuat_retriever`'ı kullanıyor; yeni `get_document_analysis_mevzuat_retriever` bu anahtarı yalnızca belge analizine uyguluyor.
  - **`register_servers()` artık iki anahtardan herhangi biri açıkken sunucuyu kaydediyor** (`MEVZUAT_MCP_ENABLED or MEVZUAT_SOURCE == "mcp"`) -- aksi hâlde belgelenen varsayılan (`MEVZUAT_SOURCE="mcp"`, `MEVZUAT_MCP_ENABLED=False`, asistan aracı hâlâ kapalı) sunucuyu hiç kaydetmez ve yeni varsayılan sessizce hiçbir şey yapmazdı.
  - Mülga mevzuat ayıklama mantığı (`pick_document_id`) ve numara çözümleme (`resolve_and_fetch`, KANUN-filtreli önce, filtresiz yeniden deneme) `app.mcp.mevzuat_client`'a taşındı; asistanın canlı arama aracı (`mevzuat_tools.py`) ve bu yeni getirici artık aynı, tek uygulamayı paylaşıyor.

## [1.44.0] - 2026-08-07
### Düzeltildi
- **11 Hata Giderildi**: bkz. PR #133 için ayrıntılı açıklama. Kısaca: hız sınırlayıcının ZSET üye çakışması yüzünden hiç sınırlamaması (kaba kuvvet savunması etkisizdi), `X-Forwarded-For`'un koşulsuz güvenilmesi, `get_document_details`'in gerçek analizlerin çoğunda çökmesi, `search_document`'ın vektör deposu kesintisiyle "sonuç yok"u ayırt etmeden aynı yedek metne düşmesi, Türkçe katlamanın `ı`'yı NFKD'de sessizce silmesi (kurum adı iki kez uydurma sayılıyordu), `MEVZUAT_MCP_ARGS`'ın pydantic-settings'in JSON-önce-doğrulama sırasıyla açılışta çökmesi, numaralı yönetmelik aramalarının KANUN filtresiyle hep NOT_FOUND dönmesi, logout'un blacklist yazma hatasını yutup 200 dönmesi, ve Türkçe büyük-I'nin stopword filtresinden kaçması.
  - Her hata için, düzeltme öncesi kodda başarısız olduğu `git stash`/`pop` ile doğrulanmış bir regresyon testi var.
  - `suggest_mevzuat`'ın iç bütçesi artık dış `node_timeout`'un okuduğu aynı `state.get("reasoning_level")`'ı okuyor -- bugün her ikisi de aynı varsayılana rastlantıyla düşüyor, ama artık yapı gereği bağlı.

## [1.43.0] - 2026-08-06
### Değiştirildi
- **Mevzuat Önerisi Düğümü Hızlandırıldı**: `suggest_mevzuat` artık üretim belirteç sayısını 512 ile sınırlıyor (varsayılan 1024). Çıktısı birkaç tek cümlelik gerekçeden ibaret olduğu için varsayılan yalnızca modele kullanmadığı alan veriyordu.
  - **İlk denenen 384 değeri gerçek alıntılara karşı yetersiz çıktı ve kazandırdığından fazlasına mal oldu**: `qwen3.5:9b` JSON'u yarıda kesip ayrıştırma hatası veriyor, yeniden deneniyor, tekrar başarısız oluyor ve model kendi üretim süresinin iki katı harcandıktan sonra ham alıntı geri dönüşüne düşülüyordu. Bu başarısızlık yalnızca uçtan uca ortaya çıktı, 384'ü ilk seçen izole çağrıda değil.
  - **512 değeri altı belge/eksik-alan kombinasyonunda, ikişer tekrarla ölçüldü**: 6/6 ilk denemede başarılı, hiç yeniden deneme yok. Doğrulanmış tek bir sunucu süreci üzerinden canlı uçla da doğrulandı: aynı belgenin arka arkaya üç yüklemesi **49-51 sn** (önceden sınırsızken 65-85 sn), `ComplianceAgent` çağrısının kendisi ~35 sn'den ~25 sn'ye indi, deterministik çekirdek (tür, uygunluk durumu, eksik alanlar) üç koşuda da aynı.
  - `MEVZUAT_RESULT_LIMIT` düşürülmesi de ölçüldü ve reddedildi: ~2 sn kazandırıyor ama **cevabı değiştiriyor** — sınırsız metni birebir üreten bir sınırla aynı türden bir kazanım değil.

## [1.42.0] - 2026-08-05
### Düzeltildi
- **Bütçesini Aşan Düğümler Artık Yeniden Denenmiyor**: Uçtan uca demo sırasında bulundu — aynı belge yüklemesi 58 sn'de 200, ardından 166 sn'de **502**, ardından 55 sn'de 200 döndürüyordu. Sebep yavaş model değildi.
  - `node_timeout` yalın bir `TimeoutError` fırlatıyordu ve `TRANSIENT_ERRORS` içinde `TimeoutError` vardı; dolayısıyla yalnızca bütçesini aşan bir düğüm, kopmuş bir bağlantı gibi görünüp **yeniden deneniyordu**. `suggest_mevzuat` 70 sn'lik bütçeye karşı normalde 28-34 sn sürüyor; ara sıra uzadığında LangGraph ikinci bir denemeye 70 sn daha harcayıp tüm isteği düşürüyordu. Marjinal bir yavaşlama, **alıntılar zaten doğru biçimde getirilmişken**, 5. gereksinimin *isteğe bağlı* yarısı uğruna 166 sn süren bir 502'ye dönüşüyordu.
  - Bütçe aşımı artık `NodeBudgetExceeded` fırlatır: bilinçli olarak `TimeoutError` değildir ve bilinçli olarak `TRANSIENT_ERRORS` içinde yer almaz. İkisi birbirine benzer ve zıt şeyler söyler — asılı kalmış bir bağlantı ikinci denemeye değer, bütçesine sığmayan iş ikinci denemede de sığmaz.
  - `suggest_mevzuat` ayrıca kendi model çağrısını düğüm bütçesinin altında sınırlar. `node_timeout` tüm düğümü sardığı için zaman aşımı `try/except` **dışında** tetikleniyor ve düğümün mevcut düşüş yolu (ham alıntılara geri dönme) hiçbir zaman devreye giremiyordu. Artık aşım, üretilen açıklamaya mal olur; analize değil.
  - **Ölçüm** (aynı belge, arka arkaya dört yükleme): 4/4 HTTP 200 (önceden 1/3), en kötü durum 166 sn + 502 yerine 85 sn, sıfır zaman-aşımı-yeniden-deneme olayı ve deterministik çekirdek (tür, uygunluk durumu, eksik alanlar) dört koşuda da bayt bayt aynı.

## [1.41.0] - 2026-08-05
### Eklendi
- **Asistan İçin Canlı Mevzuat Sorgusu (MCP, varsayılan kapalı)**: `app/mcp/registry.py` dolduruldu — boş duran bu dosya, `docs/architecture/ai.md`'nin "AI yalnızca MCP istemcisini kullanır" ifadesiyle çelişen tek yerdi. `MEVZUAT_MCP_ENABLED` açıkken [`mevzuat-mcp`](https://github.com/saidsurucu/mevzuat-mcp) (MIT) sunucusu `mcp_manager`'a kaydedilir ve asistana `search_legislation_live` aracı eklenir.
  - **Yalnızca ekler.** Uygunluk kararına hiç dokunmaz: `check_required_fields` sabit madde numaraları üzerinde küme farkıdır ve analiz hattı bu modülü hiç çağırmaz. Aynı evrakın her çalıştırmada bayt bayt aynı çıktıyı vermesini sağlayan özellik korunur.
  - **İkinci sırada.** Yerel korpus aracı (`search_legislation`) önce kayıtlıdır; model varsayılan olarak çevrimdışı yola uzanır, bu bir yükseltmedir.
  - **Hata da bir cevaptır.** Erişilemeyen sunucu, zaman aşımı, boş içerik — hepsi yerel aracın döndürdüğü "bulunamadı" ifadesini döndürür, asla istisna fırlatmaz. Üçüncü taraf bir devlet sitesi yüzünden sohbet turu 500 vermez. Bayrak kapalıyken araç modele **hiç sunulmaz**, yani çalıştırılamayacak bir araç önerilmez.
  - **Mülga mevzuat ayıklanır.** `657` araması, gerçek Devlet Memurları Kanunu'nun (`mevzuat_id=102924`) **üstünde** "DEVLET MEMURLARI KANUNUNUN YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ" kaydını (`335559`) döndürüyor — ikisi de meşru biçimde 657 numaralı, biri yürürlükten kalkmış. İlk sonucu almak, yürürlükten kalkmış metni yürürlükteki kanun gibi alıntılamak olurdu; bu, projenin önlemek için var olduğu uydurma atıf hatasının ta kendisidir. Sayısal sorgular ayrıca `mevzuat_tur=KANUN` ile süzülür.
  - Uzun kanunlar kısaltılır: 657 yarım milyon karakteri aşar, sınırsız bırakılsa bağlam penceresini taşırırdı.
  - Sunucu backend imajına **dahil değildir** (bağımlılık ağacı `playwright` sabitler); komut ve argümanlar yapılandırmada tutulur, böylece yerel süreçten yardımcı konteynere geçiş kod değişikliği değildir.

## [1.40.0] - 2026-08-06
### Değiştirildi
- **Frontend güncel backend sözleşmesine taşındı**: Eski monolitik `App.tsx` yerine mevcut `services`/`hooks`/`pages`/`providers` yapısı gerçek uygulama girişi yapıldı; auth zorunluluğu, korumalı sayfalar ve merkezi API istemcisi devreye alındı.
- **JWT yenileme ve oturum sonlandırma tamamlandı**: Normal JSON ve POST-SSE çağrıları Bearer token taşıyor; 401 sonrasında eşzamanlı istekleri tek refresh çağrısında birleştiren bir retry akışı ve refresh başarısızlığında güvenli logout eklendi.
- **Chat checkpoint sözleşmesi düzeltildi**: Frontend üretimli `clientSessionId` ile backend'in kullanıcı prefix'li `threadId` değeri ayrıldı; resume/state çağrıları tam thread kimliğini, yeni mesajlar ham client kimliğini kullanıyor. Sayfa yenilemesinden sonra bekleyen HITL interrupt state endpoint'inden geri yükleniyor.
- **Guardrail ve RBAC arayüzü eklendi**: Belge analizinde gizlilik derecesi, maskelenmiş PII bulguları ve insan incelemesi uyarısı; chat akışında `tool_call`/`guardrail` SSE olayları; yönetim ekranında üç güncel rol ve employee `clearance_level` kontrolü gösteriliyor. Manager liste/davet yetkisini korurken admin-only değişiklik kontrolleri kapalı kalıyor.
- **Frontend görünümü modüler sayfalara uyarlandı**: Responsive uygulama kabuğu, belge kütüphanesi, taslak, chat, karar akışı, login ve yönetim sayfaları ortak tema sistemi altında birleştirildi.
- **Yerel demo girişi eklendi**: Docker development profili, backend'in mevcut `REQUIRE_AUTH=False` açık demo moduyla frontend'in development-only oturum bypass'ını birlikte etkinleştiriyor; production build'lerde bypass devreye giremiyor.
- **Uygulama kabuğunun masaüstü grid yerleşimi düzeltildi**: Genel ikon butonu kuralının gizli mobil menü butonunu yeniden gösterip sidebar ve ana içeriği farklı grid satırlarına itmesi engellendi.
- **Sidebar evrak kütüphanesi kompaktlaştırıldı**: Yükleme alanı, hata bildirimi, arama ve boş durum bileşenleri dar panel genişliğine özel ölçülendirildi; yatay taşma ve gereksiz uzun kartlar kaldırıldı.
- **Sidebar ve tipografi hiyerarşisi yeniden dengelendi**: Masaüstü sidebar genişliği 320 piksele sabitlendi, açılan evrak kütüphanesi yalnızca kendi navigasyon alanında kayıyor, footer yerinde kalıyor ve chevron açık/kapalı durumunu dönüşümle gösteriyor. Başlık, gövde ve Markdown metinleri için okunabilir tipografi ölçeği geri getirildi.
- **Evrak listesi iyimser güncelleniyor**: Başarılı analiz sonucu yeniden listeleme isteğine bağlı kalmadan anında kütüphaneye ekleniyor ve kullanıcıya özel yerel cache'e yazılıyor; liste endpoint'i geçici olarak erişilemese de yüklenen evrak kaybolmuyor.
- **Frontend taslak geçmişi eklendi**: Backend ayrı bir taslak listeleme endpoint'i sunmadığı için kullanıcının bu tarayıcıda oluşturduğu son 20 taslak, kaynak evrak ve oluşturulma zamanıyla yerel olarak saklanıp Taslaklar sayfasında seçilebilir kartlar halinde gösteriliyor.
- **Eski topolojik karar akışı geri getirildi**: Dikey aşama listesi yerine yönlendirici, paralel uygunluk/mevzuat dalları, taslak-revizyon döngüsü, doğrulama/yargıç, insan onayı, sevk ve asistan kolunu aynı SVG grafiğinde gösteren düzen yeniden kullanılıyor. Yeni SSE node durumları, araç çağrıları ve guardrail kararları bu eski görsel hiyerarşiye bağlandı.
- **Sidebar evrak tipografisi sıkılaştırıldı**: Kayıtlı evrak satırlarının başlık/alt bilgi ölçeği küçültüldü, uzun adlar ellipsis ile sınırlandırıldı; yükleme başarı mesajına ikon/metin aralığı ve seçili evrak alanına ayrı etiket-başlık blokları eklendi.
- **Karar grafiği renk ve hareket sistemi sabitlendi**: Düğüm türleri (`deterministik`, `model`, `araç/insan`) ve çalışma durumları (`çalışıyor`, `tamamlandı`, `hata`, `atlandı`) merkezi CSS renk değişkenlerine bağlandı. Aktif düğüm animasyonu konum değiştirmeden kendi merkezi etrafında yalnızca `scale` uyguluyor.
- **Karar grafiği tema uyumlu hâle getirildi**: Canvas, düğüm dolgusu ve grafik metinleri sabit koyu renklerden çıkarılıp tema değişkenlerine bağlandı; açık temada açık zemin, koyu temada koyu zemin kullanılıyor.
- **Revizyon düğümü grafik sınırına alındı**: Düğümün stroke ve aktif glow efektinin SVG viewBox dışına kesilmesini engellemek için yatay konumu güvenli iç boşluğa taşındı.
- **Karar grafiği koordinatları birlikte yeniden dengelendi**: Yalnızca revizyon düğümünü kaydırmak yerine yönlendirici, analiz, paralel uygunluk/mevzuat, taslak-revizyon, doğrulama/yargıç, insan onayı, sevk ve asistan düğümlerinin tamamı ortak bir grid üzerinde hizalandı.
- **Karar grafiğinin nefes alanı genişletildi**: Sağ panel 520 piksele, SVG çalışma alanı `560×580` ölçüsüne çıkarıldı; ana akış katmanları ve paralel dallar arasındaki yatay/dikey aralıklar birlikte büyütüldü.

### Test
- API Authorization/refresh, parçalı SSE ve event dedup, client session/thread ayrımı, interrupt recovery ve belge guardrail gösterimi için frontend testleri eklendi.
- Alpine frontend imajında Rollup'un Linux x64 musl native paketi, npm'in platforma özgü optional dependency lockfile hatasına karşı seçilen Rollup sürümüyle açıkça kuruluyor.

## [1.39.0] - 2026-08-05
### Eklendi
- **Guardrail Sistemi -- Faz 5: Gözlemlenebilirlik**: Faz 0-4'te kurulan karar mekanizması artık kendi metriğini ve canlı olay akışını üretiyor -- önceden bir guardrail kararının (engellendi mi, düzenlendi mi, incelemeye mi düştü) tek görünürlüğü `GuardrailEventModel` tablosuna yazılan denetim satırıydı.
  - **`kachow_guardrail_decisions_total`** (Prometheus sayacı, `stage`/`kind`/`decision` etiketleriyle): `guardrail_recorder.record_event()`'in tek çağrı noktasına eklendi, üç mevcut çağıran (`documents/service.py` içindeki `magic_byte` reddi ve her yüklemedeki `sensitivity` değerlendirmesi, `planning_graph.py`'nin çıktı kapısı) otomatik olarak sayılıyor -- yeni bir guardrail kontrolü eklendiğinde ayrıca bir metrik güncellemesi gerekmiyor. Sayaç, `RUN_RECORDING_ENABLED` kapalıyken bile artıyor: bu bir metrik, denetim kaydı değil.
  - **`emit_guardrail_event`** (`app.ai.workflows.events`): sohbet SSE akışına yeni bir `guardrail` olayı ekliyor, yalnızca gerçek bir etkisi olan kararlarda (flagged/blocked/redacted) tetikleniyor -- rutin bir "passed" sonucunun arayüzde gösterecek bir şeyi yok. `planning_graph.py`'nin çıktı kapısına bağlandı; bu, SSE kuyruğuna erişimi olan tek çağrı noktası (evrak yükleme uç noktasının kendi akışı yok, dolayısıyla oradaki kararlar yalnızca sayaçtan ve denetim tablosundan geçiyor).
  - Canlı doğrulama: `/metrics` üzerinde bir evrak yüklemesinden sonra `kachow_guardrail_decisions_total{decision="needs_review",kind="sensitivity",stage="input"}` görünüyor.

## [1.38.0] - 2026-08-05
### Değiştirildi
- **Guardrail Sistemi -- Faz 4: Uçtan Uca Yetkilendirme (RBAC)**: Gizlilik seviyesi kontrolü artık yalnızca giriş/çıkış guardrail'lerinde değil, **erişimin her katmanında** uygulanıyor -- rol modeli sadeleştirildi, her kullanıcının kendi yetki seviyesi var ve bu seviye içerik modele ulaşmadan önce Qdrant sorgusunun kendisinde uygulanıyor.
  - **Rol modeli değişti**: kullanılmayan `AUDITOR` rolü kaldırıldı. `MANAGER` (şirket yöneticisi) artık `ADMIN` ile birebir aynı tam erişime sahip -- ikisi de her gizlilik derecesini görebilir **ve** sahiplik sınırlamasını (`bypasses_ownership`) aşarak şirket genelindeki her evraka erişebilir, yalnızca kendi yüklediklerine değil. `EMPLOYEE` rolünün tavanı artık role göre sabit değil: her kullanıcının kendi `clearance_level` alanı var (`users` tablosuna eklendi, varsayılan **Hizmete Özel**), böylece iki çalışan farklı yetki seviyesinde olabilir. `clearance_level` yalnızca yöneticiler tarafından değiştirilebilir (`PATCH /users/{id}`); kendi kendine yükseltmeyi önlemek için kayıt sırasında ayarlanamaz.
  - **Erişim reddi artık getirim anında (deny-at-retrieval)**: `document_tools.py`'deki evrak araçları (`search_document`, `get_document_details`, `get_document_outline/section`), çağıranın yetkisi evrakın gizlilik derecesini karşılamıyorsa içeriği modele hiç göstermeden reddediyor. `QdrantStore`'un filtre oluşturucusu artık eşitlik dışında **aralık koşulunu** da destekliyor (`sensitivity_rank: {"lte": ...}`), böylece yetkisiz bir parça vektör aramasından **hiç dönmüyor** -- getirim sonrası filtrelemeye güvenmek yerine sorgunun kendisi sınırlı.
  - **İstem düzeyinde ikinci katman**: Asistan'ın sistem istemine oturumun yetki sınırını özetleyen bir `security_boundary` notu ekleniyor (deterministik kontrolün *yerine* değil, onun üstüne -- model kuralı çiğnese bile Qdrant filtresi ve araç reddi zaten devrede).
  - **`REQUIRE_AUTH` artık varsayılan olarak `True`.** Önceden kimliksiz her istek kabul ediliyordu; artık kimlik doğrulama gerçek bir zorunluluk. **Bilinen kırılma**: frontend'de hiçbir JWT/oturum akışı yok (`Authorization`/`Bearer`/`login` frontend kod tabanında hiç geçmiyor), dolayısıyla bu değişiklik frontend'i kimlik doğrulaması yapmadan **kırıyor**. Bilinçli bir karar: frontend düzeltmesi Faz 5 (Gözlemlenebilirlik) tamamlandıktan sonra ayrı bir çalışma olarak ele alınacak.

## [1.37.0] - 2026-08-05
### Düzeltildi
- **Hız Sınırlayıcı Artık Açık Tarafa Düşüyor**: `rate_limit()` Redis'e hiçbir hata yakalama olmadan gidiyordu; bağlantı hatası doğrudan bağımlılıktan çıkıp **500**'e dönüşüyordu. Hız sınırlama bir *koruma* mekanizmasıdır, doğruluk gereksinimi değil: sayaç erişilemezse isteğin sınırı aşıp aşmadığını bilemeyiz, güvenli cevap isteği servis etmektir.
  - Kapalı tarafa düşmek, bir Redis yeniden başlatmasının `/auth/login`, `/auth/refresh`, `/chat/stream`, `/chat/resume` ve `/documents/analyze` uçlarından 500 döndürmesi demekti — **erişilemeyen bir önbellek tüm kullanıcıları sistemden kilitliyordu, giriş dahil.**
  - Ödünleşim gerçek ve en çok `auth:login` için geçerli (5/60 sn sınırı kaba kuvvet savunmasıdır). Yine de düşülecek doğru taraf budur: bir saldırgan bu dala önce Redis'i düşürmeden ulaşamaz — ki bunu yapabiliyorsa açık zaten sınırlayıcı değildir — buna karşılık Redis'i yeniden başlatan bir operatör bunu **her seferinde** tetikler.
  - **Makefile'ın "yedi API testi Redis olmadan başarısız olur" notu bu hatanın kendisiydi**, bir ortam gereksinimi değil. Paket artık Redis erişilebilirken de, `REDIS_URL` ölü bir porta bakarken de **920/920** geçiyor.
- **`greenlet` Bağımlılığı Açıkça Bildirildi**: SQLAlchemy'nin asenkron katmanı çalışma zamanında `greenlet` gerektirir, ancak bunu yalnızca `platform_machine` ∈ {aarch64, x86_64, amd64, win32} için otomatik bildirir. Apple Silicon `arm64` raporlar — bu listede yok — dolayısıyla yerel macOS kurulumunda `greenlet` gelmiyor ve `get_db`'ye uğrayan her istek `ValueError: the greenlet library is required to use this function` ile ölüyor. Linux konteynerleri işaretçiyi karşıladığı için CI hiç görmedi; birim testleri oturumu taklit ettiği için onlar da görmedi. `sqlalchemy[asyncio]` ile bağımlılık her platformda açık hâle getirildi.
- **Genelge/Resmî Yazı Ayrımı**: Sınıflandırma isteminde `circular` yalnızca dört kelimeyle geçiyor (`"circular: genelge."`), `official_letter` ise tam bir ölçüt paragrafı ve "kurumlar arası yazışmaların varsayılan türüdür" ifadesiyle tanımlanıyordu. Bir genelge yapısal olarak resmî yazı olduğu için model, belirtilen varsayılanı geçersiz kılacak hiçbir ölçüt olmadan hep onu seçiyordu. Ayırt edici işaretler dağıtımlı muhatap ve genel düzenleme dilidir; `detect_structural_signal` `DAĞITIM`'ı zaten tespit edip raporluyordu, eksik olan yalnızca ona göre karar verecek ölçüttü. `qwen3.5:9b` ile sentetik küme üzerinde tür doğruluğu **11/12 → 12/12**, üç tekrarda kararlı (36/36).

## [1.36.0] - 2026-08-05
### Değiştirildi
- **Bozulmuş Tarama OCR'ı `deepseek-ocr`'a Geçti** ve **istem artık Türkçe değil.** İkisi birbirine bağlı: `deepseek-ocr` eski Türkçe istemle hiçbir şey döndürmüyor.
  - **İstem dili çeviri dili değildir.** Türkçe bir belgeyi Türkçe istemle okutmak bariz doğru görünüyordu ve denenen **her model için en kötü seçenek** çıktı — o sırada gönderdiğimiz model dahil. `glm-ocr` yalnızca Türkçe ifadeyi bırakmakla NED 0,164 → 0,145'e geliyor; `deepseek-ocr` ise tam başarısızlıktan (NED 1,000, boş çıktı) en iyi sonucuna geçiyor.
  - **Model seçimi metin sadakatine göre değil, alan kurtarmaya göre yapıldı** — ve ikisi çelişiyor. 12 bozulmuş evrak, 62 etiketli alan:

    | motor | bulunan | birebir | OCRTurk tokF1 |
    |---|---|---|---|
    | tesseract | 1/62 | 0/62 | 0,411 |
    | glm-ocr (önceki) | 59/62 | 35/62 | 0,676 |
    | **deepseek-ocr** | 58/62 | **48/62** | **0,846** |
    | frob/unlimited-ocr:q8_0 | **0/62** | 0/62 | 0,708 |

  - `glm-ocr` ile `deepseek-ocr` aynı alanları buluyor (59'a 62 — belge belge kazanıp kaybediyorlar, bu örneklem boyutunda gürültü). Fark **değerin doğruluğunda**: 48'e 35. Aynı eksik alan doğruluğu, üçte bir daha az yanlış değer, daha iyi metin sadakati ve daha hızlı (OCRTurk kümesinde 142 sn'ye 195 sn).

### Eklendi
- **`scripts/evaluate_ocr_fields.py`**: bozulmuş evrak taramalarında **alan kurtarma** ölçer — çıkarılan metni uygunluk denetiminin kullandığı `parse_labelled_fields`'tan geçirip kaç etiketli alanın hayatta kaldığını sayar.
  - Bu ölçüt neden var: `frob/unlimited-ocr:q8_0` metin sadakatinde `glm-ocr`'ı geçiyor ve **sıfır** alan kurtarıyor. Türkçeyi doğru okuyor ama sayfayı yeniden biçimlendiriyor; ayrıştırıcının bulamadığı bir başlık ise **eksik bilgi** olarak raporlanır. Yani her bozulmuş yüklemeyi yanlış bir uygunluk uyarısına çevirirdi — elimizdeki tüm metin ölçütlerinde daha iyi görünürken.
  - Referans, JSON etiketi değil kaynak metnin ayrıştırmasıdır: soru "OCR temiz okumaya göre neyi kaybediyor", dolayısıyla referans da OCR çıktısıyla aynı ayrıştırıcıdan gelmelidir.
- **`scripts/evaluate_ocr_benchmark.py` genişletildi**: `--vision-models` ile istenen model listesi karşılaştırılabiliyor (Tesseract her koşuda ucuz taban olarak kalıyor, böylece aday başka bir gün başka bir Ollama sürümüyle kaydedilmiş bir sayıyla değil, **aynı oturumda** mevcut modelle karşılaştırılıyor); `--vision-prompt` ile tüm modellere aynı istem veriliyor.

### Not
- Değerlendirmeye [`baidu/Unlimited-OCR`](https://github.com/baidu/Unlimited-OCR) önerisiyle başlandı (MIT, OmniDocBench v1.5 %93,23, DeepSeek-OCR'a göre +6,22). Yayımlanmış sonuçları güçlü ve makalesi **yalnızca İngilizce** belgeler üzerinde değerlendirme yapıyor; Türkçe evrak üzerinde bu yoldan kullanılamaz durumda. **Ölçülmüş olumsuz sonuç** olarak kaydediliyor — sınanmamış bir varsayım olarak değil.
- Alan kurtarma OCRTurk üzerinde ölçülemez: o küme tez, dergi ve rapor içerir, evrak değil; `Sayı:`/`Konu:` yan başlıkları hiç bulunmaz, dolayısıyla referans metinde de ayrıştırıcının bulacağı bir şey yoktur. Bu nedenle ölçüm `datasets/sample/` üzerinde yapılır.

## [1.35.0] - 2026-08-05
### Eklendi
- **Mevzuat Korpusu Resmî Kaynaktan Üretiliyor**: `scripts/fetch_mevzuat_corpus.py`, [`mevzuat-mcp`](https://github.com/saidsurucu/mevzuat-mcp) (MIT) sunucusu üzerinden mevzuat.gov.tr'den tam metin çekip `datasets/mevzuat/` altına yazar. Korpus **3 belge / 44 parçadan 7 belge / 880 parçaya** çıktı.
  - Eklenen mevzuat: **657** Devlet Memurları Kanunu (izin talepleri), **6698** KVKK (evraktan TCKN ve adres çıkarıyoruz, buna atıf yapan hiçbir şey yoktu), **7201** Tebligat Kanunu, **5070** Elektronik İmza Kanunu.
  - Mevcut üç belge de yeniden çekildi: elle aktarılmış hâlleri eksikti — Resmî Yazışmalar Yönetmeliği'nin **39 maddesinden 18'i** vardı, 4982'nin 33 maddesinden 6'sı. Artık tam metinler duruyor.
  - Her dosya `mevzuat_id`, kaynak, çekilme tarihi ve korpustaki gerekçesini taşıyan bir künye ile yazılır; bir atıf her zaman resmî metne kadar izlenebilir.
  - **Çalışma zamanı değişmedi.** Sunucunun bağımlılık ağacı `playwright` sabitliyor ve tarayıcı ikilisi çekiyor; bu nedenle backend imajına **girmiyor**. Betik geliştirme zamanında, izole bir sanal ortamdan çalışır. Analiz hattı yerel dosyaları okumaya ve ağsız çalışmaya devam eder.
  - `--check` kipi farkları yazmadan raporlar. Kullanın: elle aktarılmış bir dosyaya güvenmeden önce ne değiştiğini görmek, altı yeni dosyanın aynı ardışık düzene bağlanmasından ucuzdur.

### Değiştirildi
- **Mevzuat Sorgusu Belge Türüne Göre Kuruluyor**: `_build_mevzuat_query` her sorguya sabit bir `"zorunlu unsurlar sayı tarih konu ilgi imza gizlilik derecesi"` eki koyuyordu. Korpusta tek gerçekçi hedef Resmî Yazışmalar Yönetmeliği olduğu sürece bu zararsızdı; yedi mevzuatla birlikte bir yanlılığa dönüştü. Ölçüm (örnek türler üzerinde, beklenen mevzuatın ilk 3 sonuçta bulunması):
  - sabit ek ile **4/6** — izin talebi KVKK'ya, dilekçe 657'ye kayıyordu
  - ek tamamen kaldırılınca **3/6** — bu sefer yönetmelik kendi belge türlerini kaybediyordu
  - türe özgü terimlerle (`DOCUMENT_TYPE_QUERY_TERMS`) **6/6**
- **`DOCUMENT_TYPE_QUERY_TERMS` kural tablosundan ayrı tutuldu.** İkisi farklı sorulara yanıt verir: `REQUIRED_FIELD_RULES` *uygunluğu* yanıtlar (hangi eksiklik belgeyi eksik kılar) ve atıfları eksik alan raporunda görünür; bu eşleme *ilgililiği* yanıtlar (bu belgeyi okuyan biri hangi mevzuatı görmek ister). 657 bir izin talebinin esasını düzenler ama eksik bir 657 hükmü talebi eksik kılmaz — bu yüzden geri getirimi yönlendirir, kural atfı olmaz. Bir test bu ayrımı kilitler.

### Not
- `evrak_08` (izin talebi) artık **Devlet Memurları Kanunu Madde 103**'e atıf veriyor; önceden yalnızca Resmî Yazışmalar Yönetmeliği'ne veriyordu. Eksik alan tespiti ve atıfları değişmedi: deterministik çekirdek bu işten etkilenmez.
- `yargi-mcp` (mahkeme kararları) kapsam dışı bırakıldı: içtihat, Görev 1'in altı yeteneğinden biri değil. Taslak üretimi (Görev 2) veya asistan için değerlendirilebilir.

## [1.34.0] - 2026-08-03
### Değiştirildi
- **`chat` ve `document_qa` Tek `assist` Adımında Birleştirildi, Gerçek Tool-Calling Döngüsü Eklendi**: Router'ın "bu mesaj sohbet mi, belge sorusu mu" kararını önceden vermek zorunda olması yanlış katmanda alınan bir karardı -- bu, cevabın belgeye ihtiyaç duyup duymadığını bilmeden önce verilen bir tahmindi. `intent_rules.py`/`intent_scorer.py` bu ayrımı kurtarmak için `document_qa.request_softener_counter` ve `document_qa.memory_recall_counter` gibi salt iki intent'i birbirinden ayırmaya yarayan telafi kuralları taşıyordu; `evaluation/reports/all-latest.md`'deki heldout hatalarının çoğu (`held_03/06/07/16`) tam olarak bu iki sınıf arasındaki kaymalardı.
  - Yeni `app/ai/agents/assistant.py` (`AssistantAgent`) ve `app/ai/tools/` (`ToolSpec`, `to_langchain_tool`, `build_assistant_tools`): karar artık router'da değil, modelin kendi tool çağrısında. `search_document`, `get_document_details`, `get_document_text` her istek için `document_id`'ye **closure ile kilitli** -- model hiçbir zaman bir belge kimliği argüman olarak geçirmiyor, dolayısıyla çapraz belge erişimi yapısal olarak imkânsız. Belge yoksa bu üç tool hiç bind edilmiyor. `search_legislation` her zaman (belge olsun olmasın) kullanılabilir.
  - `BaseLLMClient`'a `generate_with_tools` eklendi; `OllamaClient` bunu `bind_tools` ile karşılıyor -- `generate_structured`'ın zaten doğruladığı native tool-calling yolunun (`method="function_calling"`) aynısı: qwen3.5 gibi custom-renderer modellerde `format=<schema>` no-op ama `tools` array'i nested/optional alanlar ve enum'lar dahil tam olarak onurlanıyor.
  - Döngü en fazla 2 tool turu (`MAX_TOOL_TURNS`), `node_budget("assist", ...)` ile zaman sınırlı; son tur her zaman tool bind edilmeden akış (`stream`) olarak üretiliyor, yani döngü hangi noktada dursa da bir düz metin cevabı garanti.
  - `planner.py`: `Intent` uzayı `draft`/`analyze`/`document_qa`/`chat` → `draft`/`analyze`/`assist`. `PLAN_BY_INTENT["assist"] = ["assist"]`. Model fallback artık belgeye bakmadan her zaman `"assist"` döndürüyor (eskiden `document_id` varsa `document_qa`, yoksa `chat` seçip aynı kararı iki isimle veriyordu).
  - `intent_rules.py`/`intent_scorer.py`: `CHAT_RULES`+`DOCUMENT_QA_RULES` → tek `ASSIST_RULES`. `document_qa.request_softener_counter` ve `document_qa.memory_recall_counter` **silindi** (ikisi de yalnızca `chat` ile `document_qa` arasındaki gerilimi çözmek içindi; birleşince gerilim kalmadı, kanıt biriktirmesi yeterli). `document_qa.question_with_document` ise gerçek pozitif kanıt taşıdığı için silinmedi, `assist.question_with_document` olarak yeniden adlandırıldı.
  - `app/ai/policy/prototypes.py`: `chat`+`document_qa` prototip örnekleri tek `assist` ailesinde birleştirildi; `POLICY_VERSION` `1.2.0`→`1.3.0` yükseltildi -- `PrototypeMatcher` sürüm damgası tutmayan eski vektör dosyalarını otomatik devre dışı bırakıyor, üretimde `scripts/build_prototypes.py`'nin yeniden çalıştırılması gerekiyor.
  - `app/ai/policy/schema.py`: `BudgetPolicy.node_seconds`'a `"assist": 45.0` eklendi (eskiden `chat`/`document_qa` için hiç bütçe tanımlı değildi, ikisi de 300 sn'lik iş akışı tavanına düşüyordu).
  - Frontend: `frontend/src/App.tsx`'te `chat`/`document_qa` node'ları tek "Asistan" node'unda birleşti; yeni `tool_call` SSE olayı detay panelinde kullanılan araçların listesini gösteriyor.
  - **Doğrulama:** `docker compose run --rm backend pytest -q` → **815 passed** (hedefli `tests/unit/ai` + `tests/unit/domains/test_chat.py` + `tests/integration/test_memory_consolidation.py` + `tests/integration/test_hitl_flow.py` alt kümesi → 566 passed). Yeni `tests/unit/ai/test_assistant_tools.py`: tool'ların `document_id`'ye kilitli olduğu, belge yokken bind edilmediği, döngünün `MAX_TOOL_TURNS`'te durup yine de cevap ürettiği, bilinmeyen bir tool adının döngüyü çökertmediği. Frontend `npx tsc --noEmit` main ile aynı (önceden var olan, ilgisiz tek bir `TS6133` uyarısı dışında temiz).

## [1.33.0] - 2026-08-03
### Değiştirildi
- **Adım Yürütücüsü: Konumdan Hazır-Kümeye** (AP-5 PR-2, davranış-nötr): `execute_step_node`'un `current_step_idx` tabanlı dizi indekslemesi kaldırıldı. Yeni `backend/app/ai/workflows/step_graph.py` -- `StepSpec`, `STEP_SPECS` (6 adımı kapsayan bildirimsel katalog, eskiden `draft`/`routing` için 2 girişli olan `_STEP_DEPENDENCIES`'in genelleştirilmiş hâli), `ready_steps()`, `all_steps_settled()`. Bir adım artık sırasıyla değil, bağımlılıkları (herhangi bir sonuçla) tamamlanmış olduğu için çalışıyor.
  - `current_step_idx` alanı kalmaya devam ediyor ama artık adım seçmiyor -- yalnızca `human_gate_node`'un interrupt-id hash'i ve ilerleme log satırı için bir sayaç. Yeni `_last_ran_step` alanı, `route_after_step`'in "taslak az önce mi çalıştı" kontrolünü `plan_steps[idx-1]` indekslemesi yerine doğrudan isimle yapmasını sağlıyor.
  - `asyncio.gather` tabanlı bir çoklu-hazır yol yazıldı ve sentetik bir `parallel_safe` spec çiftiyle test edildi (`test_step_graph.py`) -- ama bugünkü `PLAN_BY_INTENT`'in ürettiği hiçbir plan iki adımı aynı anda hazır hâle getirmiyor (hepsi doğrusal zincir), yani bu yol **üretimde hiç tetiklenmiyor**. Dürüstçe not: bu bir mimari temel, ölçülebilir bir hız kazancı değil (AP-4'ün "ölçülen katkı" disipliniyle aynı).
  - **Doğrulama:** `make eval` main'in mevcut haliyle birebir aynı (`intents` macro F1 0.9559, `drafts` accuracy 1.0000); `docker compose run --rm backend pytest -q` 813 test geçiyor (804 + 9 yeni); `test_hitl_flow.py`, `test_planner.py`, `test_event_contract.py` özellikle koşuldu.

## [1.32.0] - 2026-08-03
### Değiştirildi
- **Plan Yürütücüsü: Dispatch Tablosu + `StepStatus` Enum'u** (AP-5 PR-1/3, davranış-nötr): `planning_graph.py`'nin `execute_step_node`'undaki altı dallı `if/elif` zinciri, her adımın kendi `async` fonksiyonuna taşındığı bir `STEP_RUNNERS: dict[str, Callable]` dispatch tablosuna çevrildi. Bu, adım yürütmeyi bir bağımlılık grafiğine (AP-5 PR-2) oturtmanın önkoşuluydu -- dallanmış bir `if` zincirinin üzerine bağımlılık çözümlemesi kurulamaz.
  - Yeni `backend/app/core/enums/step_status.py`: `StepStatus(StrEnum)` -- `planning_graph.py`'de dağınık duran sekiz çıplak durum string'i (`FAILED`, `SKIPPED`, `COMPLETED`, `NEEDS_HUMAN_APPROVAL`, `NEEDS_INPUT`, `REVISE_REQUESTED`, `REJECTED`, `APPROVED`) artık tek bir yerde. `StrEnum` seçildi (mevcut `ReasoningLevel` ile aynı desen) çünkü `draft_graph.py` gibi henüz migrate edilmemiş modüllerin ürettiği düz string'lerle karşılaştırma otomatik çalışıyor, ve SSE üzerinden JSON'a giden değerler kendi string biçimiyle serileşmeye devam ediyor.
  - **Doğrulama:** `make eval` (`intents`: macro F1 0.9326, `drafts`: accuracy 1.0000) main'in mevcut haliyle birebir aynı; `docker compose run --rm backend pytest -q` 798 test değişmeden geçiyor; `test_event_contract.py` ve `test_hitl_flow.py` özellikle koşuldu (kaynak-metin greplemesi ve interrupt-replay davranışı bu refaktörün en kırılgan noktalarıydı).

## [1.31.0] - 2026-08-03
### Eklendi
- **Gelişmiş Sentetik PDF Veri Kümesi**: KVKK/PII ve RAG süreçlerinin testi için, 6 farklı kurum (MEB, İSKİ, SGK, YÖK, BOTAŞ, Ankara BŞB) formatına (antet, mizanpaj, Türkçe TrueType fontlar) birebir uygun ve sahte PII verileri içeren 300 adet zengin içerikli simülasyon PDF belgesi üretilerek veri setine döküldü (`scripts/generate_diverse_pdfs.py`).
- **Dilekçe Veri Kümesi Operasyonu**: Açık kaynak sitelerden (dilekceornegi.net vb.) gerçek dilekçe örnekleri kazındı. Buna ek olarak 12 farklı kategoride kurgusal sahte PII barındıran zengin dilekçe şablonları üretildi (`scripts/scrape_dilekce.py`). Veri setine 74 yeni dilekçe örneği dâhil edildi.
- **Ek Sentetik Veriler**: İhtiyaca yönelik olarak çok sayıda sentetik üst yazı dosyası oluşturuldu.

## [1.30.0] - 2026-08-03
### Eklendi
- **Sentetik RAG Veri Kümesi Genişletmesi**: Veri kümesinde eksik (0-1 adet) olan 9 farklı resmî yazışma kategorisi (İtiraz, Görüş Talebi, Ret/Kısmi Kabul, Eksik Belge, Proje Teklifi, Tekit, İade/Yetkisizlik vb.) için Şartnamenin 6.5 maddesine uygun olarak tamamen kurgusal, ancak kurumsal yapıya ve Yönetmeliğe uygun 53 adet yeni sentetik belge eklendi. Katalogdaki doğrulanmış örnek sayısı 253'e ulaştı.
- **Dataset İndeks Otomasyonu**: `scripts/update_dataset_indexes.py` adında yeni bir Python scripti eklendi. Bu script veri kümesi dizinindeki Markdown (`.md`) dosyalarını tarayıp YAML frontmatter bilgilerini otomatik okuyarak `kaynak-katalogu.jsonl`, `kaynak-ozeti.csv` ve ilgili dizinlerin alt `_indeks.csv` dosyalarını tek tuşla güncelleyerek manuel veri girişi hatalarının önüne geçmektedir.

## [1.29.0] - 2026-08-03
### Düzeltildi
- **Semantik Katman Canlı Ollama'ya Karşı Ölçüldü ve Eşikleri Yeniden Kalibre Edildi**: 1.28.0'da bu katman **atıl** ve **ölçülmemiş** olarak gönderilmişti. Ollama açıldıktan sonra prototip vektörleri üretildi ve katman gerçek `nomic-embed-text` gömmeleriyle uçtan uca ölçüldü. Gönderilen `0.72` eşiğinin **gürültü bandının içinde** olduğu ortaya çıktı:

| sim | vaka | beklenen → eşleşen | |
|---|---|---|---|
| 0.880 | `held_01` | draft → draft | doğru |
| 0.859 | `held_02` | draft → draft | doğru |
| 0.758 | `held_12` | chat → **analyze** | **yanlış** |
| 0.750 | `held_13` | chat → chat | doğru |
| 0.749 | `held_08` | analyze → **draft** | **yanlış** |
| 0.747 | `held_15` | chat → **document_qa** | **yanlış** |
| 0.740 | `esc_08` | (belirsiz) | doğru şekilde kararsız |

  `0.72`'de bu **3 doğru karara karşı 3 yanlış** demek. Şansa karar veren bir katman nötr değil, bir **regresyondur**: o üç mesaj daha önce doğru bilme şansı olan bir modele eskale ediliyordu, semantik basamak bu şansı elinden aldı.
  - Eşik `0.80`'e çekildi — güvenli bandın (`0.758 → 0.859`) **ortası**, kenarı değil. Tarama `0.76`'nın da sıfır hata verdiğini gösteriyor ama bu 15 vakalık bir örneklemde son hataya `0.002` pay bırakır; bu bir eşik değil gürültüdür. Marj eşiği, benzerlik doğru ayarlandığında **hiç bağlayıcı olmuyor** (hayatta kalan iki karar 0.154 ve 0.098 ile geçiyor); yalnızca gerçekten eşit iki eşleşme yuvarlamayla ayrılmasın diye korundu.
  - **Asıl sonuç kalibrasyon değil, kalibrasyonun ortaya çıkardığı şey**: güvenli eşikte bu katman **130 mesajın 2'sini** çözüyor. Nedeni sayılarda görünüyor — resmî registerdeki Türkçe cümleler karşılıklı olarak benzer, dolayısıyla tamamen belirsiz bir mesaj bile alakasız prototiplere karşı 0.60–0.74 alıyor; bu gürültü tabanının üstünde yalnızca dar bir bant kalıyor. Plan bu katmanın eskalasyonların çoğunu soğuracağını varsayıyordu; **yedide birini** soğuruyor.
  - **Gecikme** (önceden bilinmiyordu): p50 **19.7 ms**, p95 **22.0 ms** — docstring'lerdeki 50-150 ms tahmininden belirgin şekilde iyi. Tahminler ölçümle değiştirildi.
- **Prototip Dizini Mount Edilmemiş Bir Yola Yazılıyordu**: `PROTOTYPE_DIR`, `__file__` üzerinden `parents[3].parent` ile türetiliyordu. Container'da paket kökü **çalışma dizininin kendisi** (`/workspace`) olduğu için bunun bir üstü `/` oluyordu; `build_prototypes.py` 768 boyutlu vektörleri `/datasets/prototypes/` altına "başarıyla yazdım" diyerek yazıyor, container çıkınca hepsi kayboluyordu. Betiğin başarı çıktısı gerçek bir üretimden ayırt edilemiyordu. Artık `MEVZUAT_CORPUS_DIR` ile aynı deseni izliyor: `settings` içinde göreli yol.
- **`make test` Redis'siz Koşuyordu**: Hedef `--no-deps` kullanıyordu; birim testlerinin altyapıya dokunmadığı varsayımıyla. Bu, `rate_limit()` arkasındaki yedi API testi dışında doğru — onlar Redis'e ulaşıyor ve bağlantı hatası testin beklediği 422 yerine 500 olarak yüzeye çıkıyor.
  - **Hata kipinden kötüsü, hatanın yanlış atfedilmesiydi**: bu yedi test dört ayrı PR'da "`origin/main`'de de mevcut, httpx/starlette sürüm kayması" diye raporlandı. Hikâye makuldü — çıktıda bir `StarletteDeprecationWarning` vardı ve `origin/main`'e geçip aynı yedi hata görülmüştü. Ama o kontrol de **aynı bozuk çağrıyı** kullanıyordu, dolayısıyla hipotezi değil harness hatasını doğruladı.
  - Redis ayaktayken paket **798 passed, 0 failed**. Ortada bir sürüm kayması yok ve hiç olmadı; deprecation uyarısı ilgisiz ve zararsız.
  - `make eval` `--no-deps` ile kalıyor; orada gerçekten doğru — o suite'ler saf karar fonksiyonlarını çağırıyor.

## [1.28.0] - 2026-08-03
### Eklendi
- **Semantik Prototip Katmanı** (`app/ai/semantic/`, `app/ai/policy/prototypes.py`): Karar merdiveninin 2. basamağı. Sözlüksel kurallar yüzeyleri **birebir** eşleştirir, dolayısıyla parafraza yapısal olarak kördür — "cevap hazırla"nın her yeni söyleniş biçimi elle eklenmek zorundadır. Bu katman, mesajı sınıf başına birkaç **örnek ifadeyle** anlam üzerinden karşılaştırır.
  - **Ekonomi tüm gerekçe**: kısa bir mesaj için tek `embed_query`, zaten bellekte ve sıcak duran bir modelde ~50-150 ms (`HybridRetriever` her mevzuat aramasında aynı servisi çağırıyor). Hızlı katman modelinin tek etiketlik yapılandırılmış çağrısı, JSON şeması + Pydantic doğrulama + olası retry ile ~1-3 sn. Yani burada çözülen bir parafraz, bir üst basamağın maliyetinin **yüzde birkaçına** mal olur.
  - **Değer, karar vermeyi reddetmesinde.** Aynı resmî registerdeki kısa Türkçe cümleler arasındaki kosinüs benzerliği sıkışıktır — alakasız cümleler rutin olarak 0.6 civarında oturur — dolayısıyla "en yakın prototip" neredeyse her zaman *bir* prototiptir. Bu yüzden bir eşleşme hem yüksek mutlak benzerlik hem de ikinciye net bir fark gerektirir; tek başına mutlak eşik sürekli tetiklenir, tek başına marj ise eşit derecede kötü iki eşleşme arasında farkın rastlantısal olduğu yerde tetiklenir. Herhangi biri sağlanmazsa modele düşülür.
  - Prototip vektörleri `scripts/build_prototypes.py` ile **önceden hesaplanır**; istek anında ~30 ifade gömmek, bu katmanın kaçınmak için var olduğu model çağrısından pahalı olurdu. Çalışma yolunda tek bir string gömülür: kullanıcının kendi mesajı (test bunu `embed_documents` hiç çağrılmadığını doğrulayarak kilitliyor).
  - Her vektör dosyası gömme modeli, boyutu ve policy sürümüyle **damgalıdır**; damga tutmazsa matcher kendini devre dışı bırakır. Farklı bir modelle üretilmiş vektörlerden karar vermek, bir model çağrısı ödemekten kötüdür: yavaş değil, **eminden yanlış** olur. Eksik dizin, okunamayan dosya ve gömme servisi kesintisi de aynı no-op'a düşer — betiği hiç çalıştırmamış bir kurulum, katman hiç yokmuş gibi davranır.
  - `resolve_plan` artık üç basamaklı: sözlüksel kurallar → prototipler → hızlı katman modeli. Her basamak yalnızca bir altının reddettiğini görür; kuralların çözdüğü bir mesaj **hiç gömme maliyeti ödemez** (testle kilitli).
  - `FakeEmbeddingsClient` conftest'e eklendi (`FakeLLMClient` deseniyle: gerçek alt sınıf, MagicMock değil).

### Değiştirildi
- **Held-out parafraz kümesi** (`intents.jsonl`, `heldout_paraphrase`, 16 vaka): Kurallar ayarlandıktan **sonra** yazıldı ve hiçbir kural bunlara göre değiştirilmedi. Önceki sürümdeki `1.0000` skorunun ne değerde olduğunu öğrenmenin tek dürüst yolu buydu.

| | 1.27.0 | 1.28.0 |
|---|---|---|
| Macro F1 (genel) | 1.0000 | **0.9326** |
| Eskalasyon (genel) | 0.0000 | **0.0538** |
| Held-out doğruluk | — | **0.25** (16'da 4) |

  **`1.0000` uyduruldu.** Kurallar ve eşikler o kümenin başarısızlıklarına göre ayarlanmıştı; ölçtüğü şey katmanın genelleme gücü değil, o kümeye ne kadar iyi uydurulduğuydu. Bunu bir sayıyla söylemek, 1.26.0'daki uyarı notundan daha değerlidir.

  On iki başarısızlık, farklı önem taşıyan iki sınıfa ayrılıyor:
  - **Yedisi çekimser kalıyor** — semantik katmanın tam olarak kurulduğu trafik: sözlüksel yüzeyi olmayan parafrazlar, bugün doğru davranışın eskalasyon olduğu ve bir prototip eşleşmesinin bunları model çağrısının küçük bir kesrine çözebileceği yerler.
  - **Beşi eminden yanlış** ve semantik katman bunlara **hiç yardım edemez**, çünkü yalnızca çekimserlik üzerinde çalışır. Beşin dördü `document_qa`'ya düşüyor ve bu, belirli bir karara kadar izlenebilir: `question_with_document` ipucu, "Evrakın konusu nedir?" varlık tabanını geçsin diye HINT (1.0) yerine DOMAIN (1.6) yapılmıştı. Bu düzeltme, `document_qa`'yı **belge ekliyken sorulan her soru için varsayılan** hâline getirdi — bir belge sorusu için doğru, parafraz edilmiş bir taslak/analiz/hatırlama talebi için yanlış.

  Bu bulgu **düzeltilmedi, kaydedildi**. Şimdi yapılacak herhangi bir değişiklik bu on altı vakadan haberdar olurdu ve onları bir ölçüm olarak yakardı — ki bu kümenin var olma sebebi tam olarak bu hatayı açığa çıkarmak. Düzeltme, kümeleri genişletme işiyle birlikte kalibrasyon adımına ait.

> **Semantik katman bu kurulumda atıl.** `datasets/prototypes/` altında vektör dosyası yok ve üretim betiği çalışan bir Ollama gerektiriyor. Katman testli olarak geliyor (`FakeEmbeddingsClient` ile 12 test + 5 merdiven testi) ama **gerçek gömmelerle uçtan uca ölçülmedi**: doğruluk katkısı ve `embed_query` p50/p95 gecikmesi bilinmiyor. `scripts/build_prototypes.py` canlı bir Ollama'ya karşı çalıştırılana kadar merdiven iki basamaklı kalır.

## [1.27.0] - 2026-08-03
### Düzeltildi
- **Taslak Yazarının Zaman Bütçesi Hiç Uygulanmıyordu**: `resilience.py:53` yazıldığından beri `writer: 120.0` ve `judge: 20.0` girdilerini taşıyordu ve **hiçbiri okunmuyordu** — `draft_graph.py` `node_timeout`'u import bile etmiyordu. Yani ~90 sn'lik taslak bütçesinin **en pahalı adımının** hiçbir düğüm seviyesi koruması yoktu, ama tabloda varmış gibi görünüyordu. Uygulanmayan bir bütçe, bütçesizlikten kötüdür: koruma olduğu izlenimi verir.
  - Yazarın bütçesi dekoratörle değil **düğümün içinde** uygulanıyor. Dekoratör düğümün `except` bloklarını aşarak yükselir ve taslak grafiğini düşürür; oysa bir zaman aşımının, grafiğin zaten yönlendirmeyi bildiği bir `FAILED` sonucuna dönüşmesi gerekir. Kendi `except TimeoutError` dalı var çünkü `str(TimeoutError())` boştur — kullanıcıya "Taslak üretilemedi: " diye iki nokta üst üsteden sonrası boş bir mesaj gösterilirdi. Kısmi akış korunuyor: kesilmiş bir taslak, insana boş bir taslaktan daha faydalıdır ve kullanıcı zaten yazılışını izlemiştir.
  - `judge` girdisi bağlanmak yerine **tablodan kaldırıldı**: `settings.DRAFT_JUDGE_TIMEOUT_SECONDS` o sayının zaten sahibiydi ve tek bir değer için iki sahip, bu değişikliğin ortadan kaldırmak için var olduğu sorunun ta kendisi. Yargıç çağrısı artık o ayarı seviyenin çarpanıyla ölçekliyor.
- **`reasoning_level` Düğüm Bütçelerine Hiç Ulaşmıyordu**: `reasoning_levels.py`, özellik eklendiğinden beri bir `timeout_multiplier` taşıyor (fast 0.6, deep 1.8) ama bu yalnızca **servis katmanının** dış zaman aşımına ulaşıyordu. Düğüm bütçeleri sabit kalıyordu; yani `deep` bir koşuya genel olarak 1.8× duvar saati veriliyor, ama fazladan işin yapıldığı yerde bu bütçe **harcanamıyordu**.
  - Kök neden: `@node_timeout(NODE_TIMEOUT_SECONDS["analyze"])` bir float alıyordu ve bu ifade graf **derlenirken** değerlendiriliyor; graf süreçte bir kez derlendiği için istek başına hiçbir değer oraya ulaşamazdı. Dekoratör artık düğüm **adı** alıyor ve bütçeyi çağrı anında state'teki `reasoning_level`'dan çözüyor.
  - `DocumentAnalysisState` ve `RoutingState` bu alanı taşımıyor (CHANGELOG 1.22.0 bunları kapsam dışı bırakmıştı), dolayısıyla dengeli seviyeye düşüyorlar — davranış değişmiyor, kablo alan eklendiğinde hazır.
  - Sonuç: `deep` yazara 216 sn (dengeli 120 sn'ye karşı), `fast` 72 sn veriyor. **Hiçbir seviye, hiçbir düğüm için dengeli seviyenin bugünkü sınırından dar değil.**

### Eklendi
- **Bildirimsel, Sürümlenmiş Policy Katmanı** (`app/ai/policy/`): Deterministik karar katmanının üzerinde hareket ettiği her eşik, onu okuyan kodun yanında yaşıyordu — `draft_verifier`'da `70.0`, `routing_graph`'ta `50.0`, `llm_judge`'da `0.6/0.4`, `planning_graph`'ta `12`/`40`/`4`, `intent_scorer`'da marj tabanları. Tek tek makul, toplu hâlde **incelenemez** — ve bunlardan ikisi, aralarındaki ilişki hiçbir yerde yazılmamış hâlde **aynı kavramın** iki şiddet derecesiydi.
  - **YAML değil, dondurulmuş dataclass** — bilinçli. Bir yapılandırma dosyası, bir eşiği kod değiştirmeden değiştirme yeteneği satın alır; burada istenmeyen tam olarak budur. Bu sayılar `evaluation/datasets` üzerinde kalibre ediliyor, dolayısıyla birini oynatmak bir CHANGELOG kaydı ve bir eval koşusu gerektirmeli, bir yeniden dağıtım değil. Tipli dataclass'lar ayrıca invaryantlara yaşayacak bir yer veriyor ve üretimle testin sapabileceği bir ayrıştırma yolu bırakmıyor.
  - **Asıl ürün invaryantlar.** Daha önce yalnızca tesadüfen doğru olan ilişkileri kodluyorlar: yönlendirme eşiği otomasyon eşiğinin **altında kalmalı** (70 "incelemesiz gönderilebilir", 50 "hiç yönlendirilemez"; ters çevirmek, yönlendirilemeyecek kadar zayıf bir taslağı aynı anda gönderilebilecek kadar iyi yapardı); yargıç harman ağırlıkları 1.0'a toplanmalı; bileşik taban varlık tabanının altına inemez (bileşik bir okuma, tekil bir okumadan daha az kanıta ihtiyaç duyamaz); ham geçmiş sınırı birebir pencereyi aşmalı; hiçbir düğüm bütçesi iş akışı tavanını geçemez. **Import anında** çalışıyorlar — kendisiyle çelişen bir policy, üretimde sessizce yanlış karar üretmek yerine süreci düşürüyor.
  - Tüketen modüller kendi modül seviyesi isimlerini koruyor ama policy'den **türetiyor**; mevcut 750 testin tamamı dokunulmadan geçiyor ve diff bir davranış değişikliği değil bir yönlendirme. Testler türetmenin kendisini doğruluyor: biri yeniden sabit kodlansa import'lar yine çalışırdı, yalnızca sapma görünürdü.
  - `ROUTING_UNITS` ile `RouteOutput.destination` Literal'ını hizada tutan bir test eklendi. Daha önce bu işi yapan tek şey "birbirinden sapamaz" diyen bir yorum satırıydı.
- **Policy Sürüm Damgası**: `DRAFT_SCORE` veya `CLAIM_MATCH`'teki bir kayma, "trafik değişti" ile "biz bir eşiği oynattık" arasında belirsizdi ve bu ikisi zıt tepkiler gerektirir. Prometheus'a `Info` olarak ekleniyor (mevcut koleksiyonerlere etiket olarak değil — kardinalite maliyeti sıfır), değerlendirme raporuna hem JSON yüküne hem Markdown başlığına yazılıyor.

> Bu sürüm **davranış-nötr**dür: `make eval` policy düzenlemesinden önceki ile birebir aynı `1.0000 / 1.0000` sonucunu üretiyor. Kanıt commit'lenmiş raporda.

## [1.26.0] - 2026-08-03
### Değiştirildi
- **Niyet Çözümleme: Sıralı Anahtar Kelime Şelalesi → Kanıt Skorlaması**: `planner.py` anahtar kelime gruplarını sabit sırayla kontrol edip ilk eşleşmede dönüyordu; bu, **sırayı** kararın kendisi hâline getiriyordu ve yeniden sıralamayla düzeltilemezdi (taslak önce kontrol edilince "Resmi yazı ne demek?" üç adımlı taslak hattını başlatıyor; analiz önce kontrol edilince "analiz sonrası taslak hazırla" analize düşüyor). 1.25.0'daki ölçüm iki kategoriyi **0.00** ile raporladı — zayıf değil, sıfır, sekiz vakanın sekizi. Artık mesaj bildirimsel bir kanıt tablosuna (`intent_rules.py`) karşı skorlanıyor ve karar, ilk eşleşen kural değil **ilk iki niyet arasındaki marj**. Kanıt kısa devre yapmak yerine biriktiği için çekişmeli bir mesaj görünür şekilde çekişmeli kalıyor; bu da onun bileşik plana yönlendirilmesini ya da dürüstçe eskale edilmesini mümkün kılıyor. Model çağrısı yok, hâlâ milisaniye altı.
  - **Ölçüm** (`evaluation/reports/all-scored-canonical.md`): macro F1 **0.7289 → 1.0000**, eskalasyon oranı **0.1842 → 0.0000**, kalibrasyon hatası **0.3011 → 0.0702**. Kabul kriterinin iki yarısı da doğru yönde: doğruluk artarken model çağrısı **azalıyor**.
  - Üç mekanizma ağırlığı taşıyor ve üçü de daha büyük bir sayı değil **karşı sinyal**: (a) *tanım sorusu sayacı* — "Üst yazı ne demek?" taslaktan söz eder, talep etmez; domain isminin ağırlığını düşürmek yerine çıkarma yapmak her gerçek talebi tam güçte bırakır. (b) *hafıza-hatırlama sayacı* — bu bir tercih değil, zorunluluk: deponun hâlihazırda dayandığı iki kural tek bir ağırlıkla **birlikte sağlanamıyor** (hatırlama `document_qa`'yı yenmeli → kural 4.4 üstünde olmalı; açık taslak talebi hatırlamayı yenmeli → 3.4 altında olmalı). Geçersiz kanıtı kaldırmak ikisini aynı anda sağlıyor. (c) *veda koruması* — "İyi akşamlar, yarın devam ederiz" "devam" içerir ve şimdi devam etmenin tersini söyler.
  - Belge durumu artık baştan sona bir **ağırlık**, asla bir kapı. Selamlama kuralının `document_id is None` koşuluna bağlı olması, belge ekliyken "Merhaba"yı çözülemez yapan şeydi.
  - **Bileşik niyet** marjdan *önce* kontrol ediliyor: "Uygunluk denetimi yap, sonra cevabı kaleme al" her iki okuma için de açık kanıt taşır ama dengesiz skorlar; marj testi bunu tek başına analize çözer ve talebin taslak yarısını sessizce düşürürdü. Yalnızca draft+analyze birleşiyor; `chat`'i `draft`'a katmak hem sohbet cevabı verip hem taslak üretmek olurdu ki bu iki okumadan hiçbirinin istediği değil.
  - `PlanDecision` artık `confidence`, `evidence` ve `alternatives` taşıyor. Eski çözümleyici yalnızca hangi dala girdiğini bildiriyordu; üretimdeki yanlış bir karar geriye dönük açıklanamıyordu.
  - **Yakalanan regresyon**: "evet, hazırla" hiçbir şeye çözülmüyordu — süreklilik sinyali ile kısa-mesaj ipucu aynı kanıtı iki kez sayıyor (kısa bir onay, *onay olduğu için* kısadır) ve iki skor karar verilemeyecek kadar yakın kalıyordu. Süreklilik tetiklendiğinde ipucu bastırılıyor. Bu regresyonu mevcut `test_planner.py` yakaladı.
  - `test_planner.py`'deki `source` doğrulamaları güncellendi: `keyword`/`short_message`/`memory_recall` artık var olmayan bir şelalenin dallarını adlandırıyordu ve `source` tek bir logger çağrısı dışında tüketicisi olmayan tanılama etiketidir. Her `intent` ve `steps` doğrulaması **değişmeden geçiyor** — 1.24.0'ın hafıza-hatırlama önceliği ve süreklilik uzunluk sınırı dâhil.

### Düzeltildi
- **Taslak Doğrulamada Biçim Kaynaklı Yanlış Pozitifler**: `verify_draft` bir iddiayı kaynakla karşılaştırırken her iki tarafı küçük harf ASCII'ye katlayıp birinin diğerini içerip içermediğine bakıyordu. Bu düzyazı için çalışır, **tipli değerler** için çalışmaz: aynı olgunun iki yazımı farklı dizgelere katlanır (`01.03.2026` ↔ `1 Mart 2026`, `Madde 11` ↔ `m. 11`, `125.000,00 TL` ↔ `125.000 TL`, `E-44444444-841-77` ↔ `E-44444444/841/77`). Jeton örtüşmesi geri düşüşü de kurtaramıyordu — "12 Mart 2026" ile "12 03 2026" kısa jetonlar atıldıktan sonra yalnızca yılı paylaşır, 0.75 eşiğine karşı 0.50. 1.25.0 ölçümü, kapının ürettiği **her** yanlış pozitifin bu sınıftan olduğunu gösterdi ve `draft_graph.py` bunu bir HITL kesintisine çevirdiği için her biri doğru bir taslakta gereksiz bir kullanıcı kesintisiydi.
  - Yeni `app/ai/verification/normalizers.py`: `canonical_date`, `canonical_document_number`, `canonical_amount`, `canonical_legislation`. Bu **kayıpsız normalleştirmedir, bulanık eşleştirme değil** — kanonik biçim bir değerin nasıl yazıldığını değiştirir, ne anlama geldiğini asla. Ay tablosu tam, imkânsız tarihler kırpılmak yerine reddediliyor, kanun ve madde ayrı ad alanlarında (`kanun:4982` ≠ `madde:4982`), ayrıştırılamayan değer tahmin üretmek yerine `None` dönüyor. Her kanonikleştiricinin eşlenik bir "farklı değerler farklı kalır" testi var; başarısızlığı bir uydurmayı dayanaklı bir iddiaya çevirecek olan özellik budur.
  - Destek merdiveni tür-farkında: `exact → canonical → token_overlap → none`. Kanonik, jeton örtüşmesinden **önce** deneniyor; tipli bir değer için kanonik eşitlik tam ve nihaidir, ve eşleşmiyorsa iki farklı tarih arasındaki kısmi jeton örtüşmesi hiçbir şeyin kanıtı değildir.
  - `UnsupportedClaim` artık `canonical` (kaynakta gerçekten aranan biçim) ve `best_overlap` (en iyi metinsel eşleşmenin ne kadar yaklaştığı) taşıyor. Eskiden bir bulgu yalnızca "bu dayanaksız" diyordu; bu, uydurma bir belge sayısını farklı ayırıcılarla yazılmış gerçek birinden ayırt edemiyordu.
  - **Ölçüm**: doğruluk **0.9000 → 1.0000**, yanlış pozitif oranı **0.2353 → 0.0000**, yanlış negatif oranı **0.0000 → 0.0000** (yeni kaçak yok), ve dayanaksız ifade sayımı 40 vakanın tamamında **birebir doğru**.
- **`LEGISLATION_PATTERN` Belge Sayısının Kuyruğunu Kanun Numarası Sanıyordu**: `E-22222222-903-118 sayılı yazınız` ifadesinde `\d{3,5}\s+sayılı` kalıbı belge sayısının kuyruğuna eşleşip hayalet bir `118 sayılı` atfı üretiyordu; bu atıf sonra taslağın gerçekten andığı mevzuata karşı denetleniyordu. Bugün bu hayalet yalnızca bağlamda **başka** bir "N sayılı" atfı bulunduğunda jeton örtüşmesi tarafından yutuluyor — hiç kanun atfı içermeyen bir bağlamda dayanaklı bir taslağın kendi referans numarası uydurma yasal atıf olarak raporlanırdı. `[-/\d]` için olumsuz geriye bakış hem bunu hem de "12345 sayılı"nın ayrıca "2345 sayılı" olarak eşleşmesini engelliyor. **Denetimle değil, değerlendirme koşumuyla bulundu.**

### Eklendi
- `CLAIM_MATCH{kind, method}` Prometheus sayacı: `DRAFT_SCORE` kapının ürettiği sayıyı kaydediyordu ama **nasıl** ürettiğini hiçbir şey kaydetmiyordu, dolayısıyla bir groundedness regresyonu tek bir iddia türüne indirgenemiyordu. İki etiket de kapalı küme — serbest metin Prometheus kardinalitesini patlatırdı.

> **Aşırı uyum uyarısı**: Her iki suite'in de 1.0000 alması, kuralların ve eşiklerin bu altın kümenin başarısızlıklarına bakılarak ayarlanmış olmasını yansıtır. Altın kümeler uygulamadan **önce** yazıldı ve mevcut 30 `test_planner.py` testi (bu değişiklikle yazılmadı, eski uygulamaya karşı yazılmıştı) değişmeden geçiyor — bunlar bağımsız kontrollerdir. Yine de bu sayılar "gerçek dünyada %100 doğruluk" iddiası değildir; koşumun asıl değeri regresyonları önlemesi ve baseline karşılaştırmasıdır. Kümenin genişletilmesi ve eşiklerin plato ortasına kalibre edilmesi sonraki iştir.

## [1.25.0] - 2026-08-03
### Eklendi
- **Deterministik Karar Katmanı için Değerlendirme Koşumu**: Sistemin LLM olmayan karar fonksiyonları (`resolve_plan_deterministic`, `verify_draft`) doğru çalışıp çalışmadığı ölçülemez durumdaydı — `evaluation/metrics.py` ve `evaluation/generate_report.py` **0 byte**, `evaluation/` altındaki sekiz klasör boş `.gitkeep` idi. Bu yüzden `draft_verifier.py:88`'deki `UNSUPPORTED_CLAIM_PENALTY=12.0`'ın 10 veya 15 olmasının daha iyi olup olmadığını, ya da `planner.py`'ye eklenen bir anahtar kelimenin başka bir vakayı bozup bozmadığını söyleyecek hiçbir mekanizma yoktu; her eşik sezgiyle seçilmişti. Artık `make eval` ile koşan, **hiç LLM çağrısı içermeyen** bir ölçüm katmanı var.
  - `evaluation/metrics.py`: `accuracy`, `macro_f1`, `confusion_matrix`, `abstention_rate`, `risk_coverage_curve`, `expected_calibration_error`, `precision_at_k`/`recall_at_k`, `binary_rates`. Metrikler baştan sona **abstention-farkında**: ölçülen katman çekimser kalıp işi model katmanına devredebildiği için kalite, birbiriyle takas eden iki eksene bölünür — karar verdiğinde ne sıklıkla haklı olduğu, ve yanılacağı vakalarda çekimser kalıp kalmadığı. Yalnızca birincisini iyileştirmek her şeye kendinden emin ve yanlış cevap veren bir katman üretir; yalnızca ikincisini iyileştirmek tüm yükü modele yıkan bir katman üretir. Yalnızca standart kütüphane kullanıldı.
  - `evaluation/harness/runner.py`: hangi kararı ölçtüğünü bilmeyen jenerik koşucu; suite bir JSONL altın küme ve bir çağrılabilir verir. Karar fonksiyonundan gelen istisnayı **bilinçle yakalamaz** — çökme bir kusurdur, yanlış sınıflandırma değil; ikisini birleştirmek bozuk bir üretim fonksiyonunun makul bir doğruluk düşüşü gibi okunmasına yol açardı.
  - `evaluation/harness/intent_suite.py` ve `draft_suite.py`: her ikisi de kapının **LLM'siz yarısına** bağlanır (`resolve_plan` değil `resolve_plan_deterministic`; yargıçsız `verify_draft`) — aksi hâlde koşum yavaş ve tekrarlanamaz olur, üstelik asıl aranan sayıyı gizlerdi: deterministik katman ne sıklıkla eskale etmek zorunda kalıyor.
  - `evaluation/datasets/intents.jsonl` (114 vaka) ve `drafts.jsonl` (40 vaka). Kategoriler trafiğin tarafsız örneklemi değil, mevcut katmanın **bilinen kusur sınıflarıdır** (`inversion`, `compound`, `precedence`, `paraphrase_*`, `escalation`); `keyword_*`/`continuation`/`document_question` ise kontrol grubudur. Şartname 6.5: tüm vakalar kurgudur.
  - `evaluation/generate_report.py`: JSON + Markdown rapor, `--baseline` ile karşılaştırma. Delta yönü metrik başına belirlenir — macro F1'in yükselmesi iyi, eskalasyon veya yanlış pozitif oranının yükselmesi kötüdür; tek bir "yüksek iyidir" kuralı bunların yarısını ters raporlardı.
  - `Makefile`: `make eval`, `make eval-baseline`, `make test`. Koşum `make test`ten **bilinçle ayrı**: başarısız bir altın küme vakası ölçümdür, kırmızı build'e çevrilmesi kodu değil altın kümeyi zayıflatma baskısı yaratır; ayrıca tam koşum pytest'in 60 sn zaman aşımına sığmaz.
- **Baseline raporu** (`evaluation/reports/all-baseline.{json,md}`) commit'lendi — sonraki her değişikliğin kabul kriteri bu sayılarla karşılaştırmadır, ve her koşuda değişen bir referans noktası referans noktası değildir. Ölçüm, deterministik katmanın **tasarlandığı alanda kusursuz, tasarlanmadığı alanda tamamen kör** olduğunu gösteriyor:
  - Niyet kapısı (114 vaka): macro F1 **0.7289**, eskalasyon **0.1842**. Kontrol kategorilerinin tamamı 1.00. Buna karşılık `inversion` **0.00** (8/8) — hepsi `source=keyword` ile `draft`'a düşüyor, çünkü `DRAFT_KEYWORDS` her şeyden önce kontrol ediliyor ve "taslak"/"resmi yazi"/"ust yazi" taslak *hakkındaki* sorularda da tetikleniyor; bugün "Resmi yazı ne demek?" üç adımlı taslak hattını başlatıyor. `precedence` **0.00** (6/6) — belge ekliyken "Merhaba" çekimser kalıyor (selamlama dalı `document_id is None` koşuluna bağlı), ve taslak turundan sonra "İyi akşamlar, yarın devam ederiz" süreklilik kuralı "devam" üzerinden tetiklendiği için `draft`'a düşüyor. `paraphrase_memory` 0.10, `paraphrase_analyze` 0.00, `paraphrase_draft` 0.12, `compound` 0.50.
  - Taslak kapısı (40 vaka): doğruluk **0.9000**, **yanlış pozitif oranı 0.2353**. `grounded`, `hallucinated`, `structural`, `placeholder` ve `other_official` kategorilerinin tamamı 1.00 — doğrulayıcı kümedeki her uydurma sayıyı, tarihi, kurumu ve atfı yakalıyor. Hata kütlesinin tamamı `paraphrased_grounded` (0.60) içinde ve dördü de saf biçim uyuşmazlığı: `1 Mart 2026` ↔ `01.03.2026`, `15 Nisan 2026` ↔ `15.04.2026`, `5 Şubat 2026` ↔ `05.02.2026`, `m. 11` ↔ `Madde 11`. Dördü de 88.0 puan alıyor — 70.0 otomasyon eşiğinin üstünde — ama `strict` herhangi bir dayanaksız ifadede onayı zorladığı için yine de işaretleniyor. **Her biri, doğru bir taslakta gereksiz bir HITL kesintisi.**

### Düzeltildi
- `evaluation/` klasörü `compose.yml`'de mount edilmiyor ve imaja kopyalanmıyordu; `tests/unit/evaluation/` bu hâliyle toplanamazdı bile. Mount, altın küme düzenlemelerinin yeniden build gerektirmemesi için ayrıca korundu.
- **Bilgi notu (bu sürümde çözülmedi)**: `resilience.py:53`'teki `NODE_TIMEOUT_SECONDS`'ın `writer: 120.0` ve `judge: 20.0` girdileri hiçbir yerde okunmuyor — `draft_graph.py` `node_timeout`'u import bile etmiyor, yani ~90 sn'lik taslak bütçesinin en pahalı adımının hiçbir düğüm seviyesi koruması yok. Tespit kaybolmasın diye kayda geçirildi.

## [1.24.0] - 2026-08-02
### Düzeltildi
- **Hafıza Sorusu → Belge Soru-Cevabına Yanlış Yönlendirme**: `planner.py`'deki `resolve_plan_deterministic`, bir belge eklenmişken "az önce ne sordum" gibi konuşmanın kendisine dair soruları salt "soru gibi görünüyor + belge var" sezgisiyle `document_qa`'ya yönlendiriyordu; bu akış sistem promptunda yalnızca belge bağlamına dayanmayı zorunlu kılıyor, konuşma hafızasını "kapsam dışı" sayıyordu. Yeni `MEMORY_RECALL_MARKERS`/`_is_memory_recall_question()` bu tür mesajları belge durumundan bağımsız olarak `chat`'e yönlendiriyor.
- **Asistan Cevapları Checkpoint'lenmiş Hafızaya Hiç Yazılmıyordu**: `execute_step_node`, `_run_chat`/`_run_document_qa`'nın döndürdüğü `history` girdisini (asistanın kendi cevabı) `chat_result`/`document_qa_result` içine gömüp hiçbir zaman üst seviye bir state güncellemesine yükseltmiyordu; bu yüzden `history` reducer'ı bunu hiç görmüyor, konuşma hafızasında yalnızca kullanıcı mesajları birikiyordu. Artık `history` her iki adımda da üst seviyeye taşınıyor.
### Eklendi
- **Kayan Pencere + Özet Hafıza**: `PlanningState`'e `history_summary`/`history_summarized_through` alanları eklendi; `consolidate_memory_node`, pencerenin (`HISTORY_WINDOW=12`) dışına yeteri kadar (`CONSOLIDATION_BATCH_SIZE=4`) tur çıktığında hızlı katman modeliyle (`MemorySummarizerAgent`) bu turları özetler. Ayrı bir depo/servis eklenmedi — aynı checkpoint'lenmiş state'in bir alanı (`HISTORY_RAW_CAP=40` ham tutma sınırı).
- `document_qa.md`/`chat.md` prompt şablonlarına, konuşma özetini belge bağlamından açıkça ayıran yeni bir bölüm eklendi (`{{history_summary}}`); `TEMPLATE_CONTRACTS` ve yeni `memory_summary` şablonu/ajanı (`MemorySummarizerAgent`) eklendi.
- Frontend: `localStorage`'da kalıcılaştırılan anonim istemci kimliği (`crypto.randomUUID()`), sayfa yenileme/yeni sekmede aynı checkpoint thread'inin (ve özetinin) yeniden kullanılmasını sağlıyor — gerçek kullanıcı kimlik doğrulaması değil, tarayıcıya özgü bir süreklilik.
### Değiştirildi
- `attachActiveDoc` varsayılanı `false` oldu; aktif belge artık her sohbet turuna varsayılan olarak eklenmiyor, kullanıcı onay kutusuyla açıyor.

## [1.23.0] - 2026-08-02
### Değiştirildi
- **Tek Docker Compose Dosyası**: Kökteki `compose.yml` ile `deploy/docker/docker-compose.dev.yml` aynı geliştirme ortamını tanımlayan, zamanla birbirinden sapmış iki ayrı dosyaydı (ör. `deploy/docker/docker-compose.dev.yml`'de `frontend` servisi ve `alembic`/`pyproject.toml` mount'ları hiç yoktu, `langfuse` imaj etiketi ise iki dosyada farklıydı). Artık tek ve kanonik dosya kökteki `compose.yml`; `docker compose` bu dosyayı ekstra bir `-f` bayrağına gerek kalmadan otomatik bulur ve `Makefile` zaten bunu varsayıyordu.
  - `langfuse` servis imajı `:2`den `:3`e hizalandı — backend'in kullandığı `langfuse` Python SDK'sı (v4) `:2` sunucusuyla uyumsuz.
  - Postgres kullanıcı adı/şifre/veritabanı adı, Grafana admin şifresi ve Langfuse `NEXTAUTH_SECRET`/`SALT`/`ENCRYPTION_KEY` değerleri artık sabit kodlanmış değil, `.env`'den `${VAR:-varsayılan}` deseniyle okunuyor; backend'in `DATABASE_URL`'i de aynı `POSTGRES_*` değerlerinden türetiliyor ki iki servis birbirinden sapmasın.
  - Kök `.env.example` bu değişkenlerin tamamını (daha önce yalnızca üç Ollama değişkeni ve eski bir `OLLAMA_MAX_TOKENS=1024` içeriyordu) güncel varsayılanlarla ve açıklayıcı yorumlarla kapsayacak şekilde yeniden yazıldı.
### Kaldırıldı
- `deploy/docker/docker-compose.dev.yml` (kökteki `compose.yml` ile tekilleştirildi) ve içeriği hiç doldurulmamış `deploy/docker/docker-compose.prod.yml` silindi.

## [1.22.0] - 2026-08-02
### Eklendi
- **Agent Düşünme Seviyeleri (Hızlı / Dengeli / Derin)**: Kullanıcının her istekte hız/kalite tercihini seçebilmesini sağlayan `reasoning_level` alanı eklendi (Claude'daki hızlı/derin düşünme modlarının eşdeğeri).
  - `app/core/enums/reasoning_level.py` (`ReasoningLevel`: `fast`/`balanced`/`deep`) ve `app/ai/reasoning_levels.py` (`get_reasoning_level_preset()`): her seviyenin model katmanı, Ollama "thinking mode" (`reasoning`), taslak deneme sayısı, kalite yargıcı açık/kapalı ve zaman aşımı çarpanını tek noktadan tanımlayan preset tablosu.
  - `draft_graph.py`'deki reflexion loop (writer → verify → judge → revise) artık `reasoning_level`'a göre davranıyor: `fast` tek denemede durur ve yargıcı atlar (zaten sıcak duran hızlı-katman modelini writer/reviser için de kullanarak), `deep` aynı kalite modelini "thinking mode" açık şekilde 3 denemeye kadar çalıştırır ve yargıcı zorunlu kılar. `balanced`, bugüne kadarki sabit davranışla (2 deneme, judge ayarına bağlı, thinking mode kapalı) birebir aynı — üçüncü bir model eklenmedi, 16GB RAM'li makinelerde zaten eşzamanlı yüklü iki model (kalite+hızlı) yeniden kullanıldı.
  - `planning_graph.py`, `chat_service.py`, `draft_service.py`: `reasoning_level` sohbet ve taslak uç noktalarından graph state'ine ve zaman aşımı hesaplamalarına taşınıyor; HITL "revise" aşamasında seviye yükseltme (ör. hızlıdan derine geçiş) desteği.
  - `ChatMessageRequest`, `ChatResumeRequest`, `DraftRequestSchema`: yeni opsiyonel/varsayılanlı `reasoning_level` alanı.
  - Frontend: sohbet girişi ve taslak formu yanında "Düşünme Seviyesi" seçici (`<select>`), mevcut yazışma-türü seçici deseniyle aynı stilde.
  - Kapsam dışı bırakılanlar (sonraki iş): `document_analysis_graph`/`routing_graph` seviyelendirmesi, best-of-N örnekleme, "otomatik" adaptif seviye, `/chat/resume` seviye-yükseltme arayüzü.

## [1.21.0] - 2026-08-01
### Değiştirildi
- **Docker Geliştirme Ortamı**: `backend.Dockerfile` artık `requirements.txt` yerine `requirements-dev.txt` kuruyor (yeni HITL entegrasyon testinin ihtiyaç duyduğu `pytest-cov`/`pytest-timeout`/`langgraph-checkpoint` imajda hiç yoktu) ve `alembic/`, `alembic.ini`, `pyproject.toml` dosyalarını imaja kopyalıyor. `compose.yml` aynı yolları `app/`/`tests/` ile aynı desende canlı volume olarak da bağlıyor; migration veya pytest yapılandırması değişiklikleri artık yeniden build gerektirmiyor.

### Düzeltildi
- **Docker İçinde Tam Test Koşusu**: Backend imajı build edilip `db`/`redis`/`qdrant`/`backend` servisleri ayağa kaldırılarak paket ilk kez uçtan uca `python -m pytest tests/` ile Docker içinde çalıştırıldı. Süreçte ortaya çıkan gerçek hatalar giderildi:
  - `RedisCache.close()` içinde artık deprecated olan `redis.asyncio.Redis.close()` çağrısı `.aclose()` ile değiştirildi. `warnings=error` politikası altında bu tek uyarı, `/documents/analyze` gibi `rate_limit()` arkasındaki herhangi bir uç nokta tetiklendiği an sonraki **tüm** testlerin teardown'ında art arda patlıyordu (227 hata).
  - `tests/conftest.py`'ye her testten sonra process-genelindeki Redis istemci referansını **kapatmadan** bırakan bir `autouse` fixture eklendi: bağlantının bağlı olduğu event loop (TestClient'in kısa ömürlü anyio-portal loop'u) teardown anında zaten kapanmış oluyor; kapatmayı denemek "Event loop is closed" hatasını "farklı loop'a bağlı" hatasıyla değiştirmekten öteye geçmiyordu.
  - `test_ollama.py`, `test_base_agent.py`, `test_qdrant.py`, `test_retrieval.py`, `test_user_router.py` içindeki, kodun güncel davranışından (num_ctx/keep_alive parametreleri, `{{çift parantez}}` prompt biçimi, koleksiyon boyutu doğrulaması, `datetime.utcnow()` deprecation, silinmiş `LLMReranker` testinden kalan ölü kod parçası) sapmış eski varsayımlar güncellendi.
  - `document_analysis_graph.py`'nin artık tek bir birleşik sınıflandırma+alan-çıkarım çağrısı yapması nedeniyle `test_document_analysis.py` tamamen bu tek çağrı etrafında yeniden yazıldı; iki ayrı ajanı (`ClassifierAgent`+`MetadataAgent`) mock'layan eski testler koleksiyonda hiç eşleşmiyordu.
  - `alembic upgrade head` ve `GET /api/v1/health?deep=true` (postgres/redis/qdrant/ollama/checkpointer hepsi `ok`) Docker içinde doğrulandı.
  - Sonuç: **621/621 test geçti.**

## [1.20.0] - 2026-08-01
### Eklendi
- **Görev 2 Uç Noktaları ve Ölü Kod Temizliği**:
  - `POST /api/v1/routing/suggest`: `POST /documents/draft`'tan bağımsız, sadece taslak metni + güven skoru okuyan tek başına birim-yönlendirme uç noktası. İnsan bir taslağı elle düzenledikten sonra yeni bir üretim ödemeden yönlendirme kararını tazeleyebilir.
  - `frontend/src/App.tsx` içine `judge`, `revise` ve `human_gate` düğümleri SVG aşama grafiğine eklendi; her biri artık kendi gerçek `node_start`/`node_end`/`interrupt` olaylarıyla besleniyor. Taslak oluşturma formu (`POST /documents/draft`'ı önceden hiç çağırmıyordu) ve eksik-bilgi/onay kesintileri için devam formu eklendi.
  - Sidebar artık `EvrakField`'in **15 alanının tamamını**, `missing_fields` listesini (önem derecesi + mevzuat atfıyla) ve `mevzuat_references`'ı gösteriyor — önceden yalnızca `tarih`/`sayı` görünüyordu.

### Kaldırıldı
- Hiçbir yerde kurulmayan `editor`/`evaluator`/`metadata`/`orchestrator`/`reflection` ajanları, `workflows/system_graph.py`, `infrastructure/providers/vllm.py` (LLM fabrikasındaki kayıtsız `"vllm"` dalıyla birlikte), `core/permissions/role_checker.py` (hiçbir middleware'in hiç doldurmadığı `request.state.user_role`'e bağımlıydı), sıfır route'lu `evaluation`/`feedback`/`settings` domain iskeletleri (9 dosya) ve iki 0 byte'lık worker betiği (`workers/cleanup.py`, `workers/embedding.py`) silindi.
- `ai/retrieval/reranker.py` (`LLMReranker`) kaldırıldı: ~90 sn'lik taslak gecikme bütçesinin kritik yolunda, bu küçüklükteki bir korpusta 3 sonucu yeniden sıralamak hiçbir zaman kalitenin belirleyicisi olmadı.
- İlk EventBus abonesi (`document.analyzed` → yapılandırılmış log satırı) kaydedildi; `DocumentService`/`DraftService`'in `publish()` çağrılarının artık gerçek bir dinleyicisi var.

## [1.19.0] - 2026-08-01
### Eklendi
- **Tipli SSE Olay Sözleşmesi ve Gözlemlenebilirlik**:
  - `emit_node_error`/`emit_node_skipped`/`emit_interrupt` ve kuyruk başına monotonik bir `seq` sayacı eklendi; istemci olayları sıralayabiliyor ve `interrupt()` içeren bir düğümü resume ederken oluşan tekrar (replay) olayını tekilleştirebiliyor.
  - `event_schema.py`: on SSE olay tipinin şeklini bir kez, Pydantic modelleriyle yazan sözleşme dosyası; `test_event_contract.py` sıfır kod üretimi (codegen) kurmadan bu sözleşmeyi doğruluyor.
  - `CorrelationIdMiddleware` (en dıştaki middleware, `X-Request-ID`) eklendi ve bir `ContextVar` aracılığıyla `JSONFormatter`'a bağlandı; yapılandırılmış loglar artık gerçekten yapılandırılmış (tek bir önceden biçimlendirilmiş mesaj string'i değil).
  - `observability/ai_metrics.py`: düğüm/LLM süresi, token sayımı, taslak skorları, revizyon sayısı, yargıç hataları, HITL kesinti/devam sayaçları, yapılandırılmış-çıktı yeniden deneme sayaçları — `BaseAgent` ve olay yayıcılarına bağlandı.
  - `GET /api/v1/health?deep=true`: Postgres/Redis/Qdrant/Ollama/checkpointer'ı zaman aşımı altında sınayan, hiçbir şeyi kontrol etmeyen eski kimliksiz `/health`'in yerini alan birleşik derin sağlık kontrolü.
  - `build_trace_config()`: üç yerde birebir kopyalanmış `_trace_config` mantığını tek noktaya topladı.
- **Prompt Enjeksiyonu Guardrail'leri ve Sınır Doğrulaması**:
  - `scrub_extracted_text()`: çıkarılan evrak metninden sıfır-genişlikli/bidi kontrol karakterlerini ve Türkçe/İngilizce talimat-geçersizleştirme satırlarını temizler; çıkarımdan hemen sonra, `char_count` eşiği çalışmadan önce uygulanır — yüklenen bir PDF sistemin bakış açısından saldırgan kontrolündeki bir girdidir.
  - `assert_no_prompt_leak()` artık `BaseAgent.run_structured()`'da da çalışıyor (önceden bu yolda ölüydü); yazar/revizör/sınıflandırıcı ajanları görünür bir sızıntıda denemeyi kapalı şekilde başarısız sayıp otomatik bir revizyon yerine insan incelemesine yönlendiriyor.
  - `validate_storage_path()`: kimlik doğrulaması gerektirmeyen bir uç noktada, istemcinin verdiği `storage_path` ile `storage.get_file(...)` arasında başka hiçbir engel yoktu — biçimsel olmayan bir path-traversal okuma ilkelliğiydi.
  - `DraftClassificationSchema`: `DraftRequestSchema.classification` artık prompt'a doğrudan giden serbest bir `dict` değil, taslak akışının gerçekten tükettiği dar ve tipli bir alan kümesi.
  - `_read_bounded()`: yükleme 1 MiB'lik parçalar hâlinde okunuyor ve çalışan toplam limiti aştığı an reddediliyor; önceden tüm gövde boyut kontrolü hiç çalışmadan belleğe alınıyordu.
  - `BaseAgent.__init__`'ten ölü `tools` parametresi kaldırıldı — saklanıyordu, hiç okunmuyordu, bu kod tabanındaki hiçbir ajan tool-calling kullanmıyor.

## [1.18.0] - 2026-08-01
### Eklendi
- **Postgres Checkpointer Üzerinde HITL (Human-in-the-Loop) Kesinti/Devam**:
  - Eksik Alembic iskeleti tamamlandı: `alembic.ini` hiç yoktu, `env.py`/`script.py.mako` 0 byte'tı, `users`/`invited_emails` tabloları için bile bir baseline migration yoktu. `env.py`, `checkpoint%` tablolarını `include_object` ile dışlıyor; bu tabloları `AsyncPostgresSaver.setup()` kendi `CREATE TABLE IF NOT EXISTS` mantığıyla yönetiyor.
  - `infrastructure/checkpointing/` eklendi: en-iyi-çaba (best-effort) init/close bir `AsyncExitStack` etrafında — `AsyncPostgresSaver.from_conn_string()` kendisi bir async context manager olduğu için doğrudan `await` edilip bir kenara bırakılamaz.
  - `planning_graph`'a, taslak adımını çalıştıran `executor` düğümünden **ayrı** yeni bir `human_gate` düğümü eklendi: `interrupt()` kendi düğümünü resume'da baştan tekrar çalıştırır; `execute_step_node` içinde olsaydı resume, executor'ın state'e zaten yazdığı ~30 sn'lik taslak üretimini tekrarlardı.
  - `thread_id = session_id` `chat_service`/`chat` router'ı boyunca bağlandı; `POST /chat/resume`, `POST /chat/resume/sync`, `GET /chat/sessions/{id}/state` ve `ChatResumeRequest` (`answer`/`approve`/`revise`/`reject`) eklendi.
  - Yalnızca `planning_graph` bir checkpointer alıyor — dört alt graf `execute_step_node` içinden `.ainvoke()` ile çağrılıyor, düğüm olarak kayıtlı değiller; üzerlerine checkpointer koymak ilgisiz, öksüz checkpoint soyağaçları başlatırdı.
- **Checkpoint'lenmiş Graf State'i Üzerinden Konuşma Hafızası**:
  - `CheckpointMemory`: `planning_graph.aget_state()` üzerine ince, salt-okunur bir görünüm. `thread_id` zaten `session_id`'ye eşit ve checkpointer geçmişi, kesinti payload'ını ve her şeyi zaten tutarlı biçimde saklıyor.
  - Planlayıcıya kısa-onay devam kuralı eklendi: bir taslak/analiz teklifinden sonra "evet, hazırla" artık düz sohbete düşmek yerine o niyeti sürdürüyor; 6 kelimelik bir mesaj sınırı ve yalnızca belirsiz olmayan bir devam eylemi olan iki niyetle (`draft`/`analyze`) sınırlı.

### Kaldırıldı
- `ConversationWindowMemory`/`SummaryMemory`/`VectorMemory` kaldırıldı: checkpointer'ın yanında ikinci bir Redis tabanlı depo, çökme anında ikisi arasında bölünen bir yazma riski taşıyordu ve periyodik özet üretimi ~90 sn'lik bütçeyi zorlardı.

## [1.17.0] - 2026-08-01
### Eklendi
- **Hibrit Kalite Kapısı ve Sınırlı Taslak Reflexion Döngüsü**:
  - `judge_draft()`/`merge_verdicts()`: regex'in göremediği şeyler (talebe uygunluk, arz/rica yönü, resmî üslup, muhatap tutarlılığı) için deterministik doğrulayıcının üzerine hızlı-katman bir LLM yargıcı eklendi. Birleşik skor `0.6*deterministik + 0.4*yargıç`; herhangi bir kritik bulgu veya "talebi karşılamıyor" kararı skoru otomasyon eşiğinin altına sabitliyor.
  - `build_missing_info_request()`/`apply_answers()`: bir taslağın `[...]` yer tutucularının deterministik, LLM'siz biçimde insan tarafından cevaplanabilir sorulara dönüştürülmesi ve taslağı yeniden üretmeden cevaplandıktan sonra devam edilmesi.
  - `draft_graph` yeniden kuruldu: `validate_input → writer → verify → revise → writer`, `MAX_DRAFT_ATTEMPTS=2` ile sınırlı. Düzeltilebilir kusurlar (eksik yapı, doğrulanamayan iddialar, düzeltilebilir yargıç bulguları) yeni bir `ReviserAgent` üzerinden döngüye giriyor; kalan bir yer tutucu veya çözülememiş bir yazışma türü aynı boşluğa tekrar denemek yerine doğrudan insan incelemesine gidiyor.
  - `_build_repair_prompt` her zaman brief'in tamamını + önceki taslağı + numaralı kusur listesini gönderiyor — `num_ctx` içinde rahatça kalıyor, yazar zaten ham `source_document`'i hiç görmüyordu.
- **Yeniden Deneme/Zaman Aşımı Politikası ve Üçüncü Katman Analiz Yedeği**:
  - `resilience.py`: `RetryPolicy`'yi import eden tek yer (sürümler arası `langgraph.pregel`↔`langgraph.types` taşınmasına karşı), `LLM_RETRY`/`IO_RETRY` ve `node_timeout()`. Bilerek `writer`/`revise` düğümlerine uygulanmıyor — zaten token yayınlamış bir düğümü yeniden denemek bunları UI'a tekrar oynatırdı.
  - `document_analysis_graph` artık isteğe bağlı bir `fast_llm_client` alıyor: kalite katmanı hem birleşik hem yalnız-sınıflandırma çağrısında başarısız olursa, `DocumentType.OTHER`'a düşmeden önce hızlı katmanda bir kez daha deneniyor.
  - `retrieve_mevzuat_node` artık `"rag"` id'si altında gerçek `node_start`/`node_end` yayıyor (getirilen belgeler ve render edilmiş bağlamla birlikte) — önceden hiçbir şey yaymıyordu ve bu, frontend'in Mevzuat panelinin hep boş kalmasının kök nedeniydi.

## [1.16.0] - 2026-08-01
### Değiştirildi
- **Bağımlılık ve Araç Zinciri Yükseltmesi**: `langgraph`, `interrupt`/`Command`/`RetryPolicy` garanti eden bir sürüm aralığına sabitlendi; `langgraph-checkpoint-postgres`, `psycopg[binary,pool]`, `prometheus-client` eklendi. `pytest-cov`/`pytest-timeout` ve tutarlı async test davranışı için `[tool.pytest.ini_options]` (asyncio_mode=auto, testpaths, timeout) eklendi. Frontend'e eslint + typescript-eslint, vitest + testing-library eklendi (`npm run lint` daha önce çalışacağı bir yapılandırmaya bile sahip değildi).
- **Prompt Yöneticisi ve Şablon Seti Konsolidasyonu**:
  - Modül seviyesi `prompt_manager` tekil örneği kaldırıldı; `get_prompt_manager()` artık tek giriş noktası. `TEMPLATE_CONTRACTS` + `declared_placeholders()` eklendi; her şablonun `{{placeholder}}` kümesi, ilgili ajanın gerçekten sağladığıyla karşılaştırılıyor.
  - `orchestrator.md`/`metadata.md`/`editor.md`/`evaluator.md`/`reflection.md` şablonları silindi (hiçbir ajan tarafından referans verilmiyorlardı ya da artık çalışmayan bir akışı tanımlıyorlardı); `judge.md` ve `reviser.md` eklendi. `chat.md`'nin kaldırılmış bir "editör ve kendini denetleme" aşamasını kullanıcıya duyuran metni düzeltildi.
  - Yeni `test_prompt_templates.py`: her şablonun deklare edilip edilmediğini, diskte var olup olmadığını ve tam olarak bir ajan modülü tarafından referans verilip verilmediğini doğrulayan iki yönlü sözleşme testi — beş öksüz şablonu tam olarak yakalayacak türden bir kontrol.

## [1.15.0] - 2026-07-31
### Eklendi
- **SparseBM25Encoder**: Türkçe karakter duyarlı ve CRC32 hash tabanlı, yerel olarak çalışan matematiksel bir BM25 Sparse Vector Encoder eklendi (`app/ai/retrieval/sparse_encoder.py`).

### Değiştirildi
- **Yazım Akışının Sadeleştirilmesi**: `draft_graph.py` içindeki hantal ve yavaş döngüsel `Writer -> Editor -> Reflection -> Evaluator` yapısı kaldırıldı. Bunun yerine Editor ajanı `final_draft`, `confidence_score` ve `requires_human_approval` değerlerini tek bir Structured Output olarak döndürecek şekilde güçlendirildi ve akış `Writer -> Editor -> END` doğrusal yapısına sadeleştirildi. Ajan sayısının azaltılmasıyla taslak oluşturmadaki LLM gecikmesi yarı yarıya düşürüldü.
- **Strict Yönlendirme (Routing) Sınırlandırması**: `routing_graph.py` içindeki `destination` alanı serbest metinden `Literal` enum tipine dönüştürülerek modelin uydurma birim isimleri üretmesi (halüsinasyon) engellendi.
- **Qdrant Native Hybrid Search**: Python tarafında yavaş çalışan ve API başlangıcında tüm mevzuat korpusunu diskten okuyup tokenleştiren eski BM25 mekanizması tamamen kaldırıldı. Bunun yerine Qdrant'ın native **Prefetch** ve **RRF (Reciprocal Rank Fusion)** arama yetenekleri entegre edildi. Arama hızı artırıldı ve API/worker başlangıç süresi milisaniyeler seviyesine düşürüldü.

### Düzeltildi
- **Birim Testleri ve İçe Aktarma Hataları**: Yeni akışlara ve HybridRetriever/QdrantStore imzalarına uygun şekilde `test_retrieval.py` ve `test_workflows.py` güncellendi; tüm testler (`446 passed`) başarıyla tamamlandı.

## [1.14.0] - 2026-07-31
### Eklendi
- **Geçici Karar Destek Arayüzü ve LangGraph Canlı Akış Görselleştirme**:
  - **Canlı Grafik Akışı (Graph Visualizer)**: Karar verici Master Planning Graph (Supervisor, Sınıflandırma, RAG, Taslak, Yönlendirme vb. düğümleriyle) akışının anlık durumunun (çalışıyor, tamamlandı, atlandı) SVG grafiği üzerinden canlı takibi sağlandı. Çakışmayan simetrik grid yerleşimi, durum duyarlı (glowing green/pulsing orange) dinamik bağlantı çizgileri, metin hizalamaları ve düğümlere tıklandığında (çalışma tamamlanmasa bile) durum ve açıklamalarını gösteren interaktif detay paneli eklendi.
  - **Dosya Yükleme ve Yönetimi**: Drag-and-drop / tıklayarak dosya yükleme (`/documents/analyze`), yüklü evrakların listelenmesi (`GET /documents`) ve yerel json tabanlı metadata persistence sistemi kuruldu.
  - **Sohbet ve SSE Akışı**: `/chat/stream` SSE uç noktası eklenerek arayüzün sohbet ederken karar akışını anlık izleyebilmesi ve log konsolunda durum güncellemelerini yazdırabilmesi sağlandı.
  - **Frontend Dockerization**: React + TS + Vite frontend uygulaması için `frontend.Dockerfile` ve `nginx.conf` oluşturuldu; `compose.yml` dosyasına HMR uyumlu `frontend` servisi eklendi.
  - **Yazım Akış ve Ajan Mimari Optimizasyonu**:
    - **Briefing Agent / Context Builder Pattern**: Taslak yazma grafiğinde (`draft_graph.py`) **Writer'a tüm OCR veya ham doküman içeriğini doğrudan geçme** yapısı değiştirildi. `validate_input_node` içinde deterministik olarak hazırlanan ve sadece gerekli özet, çıkarılan kritik NER verileri, mevzuat ve kullanıcı yönergelerini barındıran **temiz bir 'Brief'** oluşturuldu. Writer, Editor, Reflection ve Evaluator ajanlarının tamamı ham metin yerine sadece bu temiz brief'i girdi alacak şekilde güncellendi.
    - **Yazım Akış Sadeleştirmesi**: Gereksiz LLM döngüleri azaltıldı. Editör onaylarsa `reflection` düğümü atlanarak doğrudan değerlendirmeye gidilir, reddedilirse editör geri bildirimiyle tek bir revizyon yapılıp değerlendirilir. LLM girdi boyutu ve çağrı sayısı azaltılarak işlem süreleri dramatik ölçüde düşürüldü ve doğruluk arttırıldı.

    - Konsol Düzeni İyileştirmesi: Karar akış konsolu sohbet akışı içerisinden çıkarılarak sohbet giriş alanının hemen üstüne sabitlendi. Böylece iç içe kaydırma (nested scrollbar) ve konsolun en altta sıkışıp okunamaz hale gelmesi sorunu giderildi.
    - Chat Asistanı Odaklanması: Chat ajanı (`chat.md` şablonu) KACHOW EKDS yeteneklerini (sınıflandırma, mevzuat, taslak, sevk, soru-cevap) tanıtacak ve sistemle ilgili soruları yanıtlayacak şekilde kurumsallaştırıldı. Sistem dışı soruları reddetmesi sağlandı.

### Değiştirildi
- **Doğrulama Ajanı (Verifier Agent) İş Akışından Çıkarıldı**:
  - `rag_graph.py` içindeki `verify_node` LLM tabanlı doğrulama yapmak yerine doğrudan `SUFFICIENT` durumu döndürecek şekilde güncellendi. Bu sayede gereksiz LLM doğrulama adımları ve sorgu tekrar yazma/arama döngüleri bypass edilerek RAG gecikmesi (latency) azaltıldı.
  - Ajan sınıfları (`verifier.py`) ve şablonları (`verifier.md`) dosya sisteminde korunmaya devam edildi.
  - RAG birim testi (`test_workflows.py`), verifier agent bypass edilerek tek bir `run_structured` (sorgu zenginleştirme) çağrısı bekleyecek şekilde güncellendi ve `BaseAgent.run_structured` doğrudan mock'landı.

### Düzeltildi
- **Serileştirme Hatası**: LangGraph'in `draft` adımında mevzuat `Document` nesnelerinin JSON serileştirilememesinden kaynaklanan `TypeError` hatası, `_format_classification` fonksiyonu içinde nesnelerin önceden temizlenmesi mantığı eklenerek giderildi.
- **Arayüz Kaydırma Hatası**: Karar akışı log konsolu büyürken chat alanının otomatik olarak en alta kaydırılmaması ve logların sıkışık kalması sorunu, `App.tsx` içindeki useEffect bağımlılık dizisine `currentLogs` eklenerek çözüldü.
- **Zaman Aşımı ve Performans İyileştirmeleri**:
  - Uzun evraklarda LLM bağlam şişmesini önlemek için `draft_graph` yazıcısına giden kaynak evrak metni başından 3500 ve sonundan 1500 karakter kalacak şekilde (toplam max 5000 karakter) otomatik kırpılacak şekilde optimize edildi.
  - Backend içindeki `AI_WORKFLOW_TIMEOUT_SECONDS` sabiti 300 saniyeye çıkarıldı.
  - `nginx.conf` proxy zaman aşımı süreleri (`proxy_read_timeout`) 600 saniyeye yükseltildi ve SSE (Server-Sent Events) akışının anlık iletilmesi için Nginx tamponlaması (`proxy_buffering off`) kapatıldı.

## [1.13.0] - 2026-07-30
### Eklendi
- **Deterministik Alan Ayrıştırıcı (`ai/compliance/field_parser.py`)**: Resmî Yazışmalar Yönetmeliği evrak başlığının biçimini zorunlu kıldığı için, etiketli alanlar (`Sayı:` m.11, `Tarih:` m.12, `Konu:` m.13, `İlgi:` m.15, `Ek:` m.18, `Adres:`, `Gizlilik Derecesi:`, `İvedilik:`) ve konumla belirlenen alanlar (başlık m.10, muhatap m.14, imza bloğu m.17) düzenli ifadelerle okunur. Ayrıştırılan değerler model çıktısını ezer.
- **Alan Çıkarımı Değerlendirme Betiği**: `scripts/evaluate_extraction.py`, alan bazında `correct` / `missed` / `wrong` / `spurious` dağılımını raporlar.

### Değişti
- **Alan Çıkarımı Düğümü**: Artık önce deterministik ayrıştırma çalışır, model yalnızca kalan alanlarla ilgilenir ve sonuçlar birleştirilirken ayrıştırılan değer öncelik alır. Model çağrısı hata verse bile ayrıştırılan alanlar korunur.

### Düzeltildi
- **Alan Çıkarımı Doğruluğu**: `qwen3:8b` ölçümünde tek alan istendiğinde `sayi` doğru dönerken üç alan birlikte istendiğinde `null` dönüyor, başka bir alan ise üretim bütçesi bitene kadar tekrar eden belirteç döngüsüne giriyordu; model şema genişledikçe bozuluyordu. Etiketli ve konumsal alanların modelden alınmasıyla:
  - genel çıkarım doğruluğu **%28,4 → %98,5**
  - kayıp alan sayısı **48 → 0** (yanlış "eksik bilgi" uyarısı üretmeyen ilk sürüm)
  - `sayi`, `muhatap`, `imza_sahibi`, `imza_unvani` alanları **%0 → %100**
- **Gerçek Türkçe Belgelerle Doğrulama (OCRTurk)**: `scripts/evaluate_ocr_benchmark.py` eklendi; 180 gerçek Türkçe belgeden oluşan [OCRTurk](https://github.com/metunlp/ocrturk) kıyaslama kümesi (tez, dergi, EBA, TCMB, SBB kaynaklı) üzerinde çıkarım zincirini ölçer. Küme lisans dosyası içermediği için **depoya eklenmemiştir**; betik harici bir kopyayı işaret eder.
  - Born-digital çıkarım (180 belge): `opendataloader` NED 0,162 / TRchar 0,795 (42 sn), `pdfium` NED 0,167 / TRchar 0,738 (1 sn). Zincirdeki mevcut sıralama (opendataloader önce) Türkçe karakter sadakati bakımından doğrulandı.
  - Bozulmuş tarama (8 belge): `tesseract` NED 0,474 / tokF1 0,411, `glm-ocr` NED 0,207 / tokF1 0,789. Okunabilirlik eşiği **8/8 belgede** doğru biçimde yükseltme tetikledi (tesseract kalite 0,41–0,58 < 0,60). Sentetik veriyle ayarlanan eşik gerçek belgelerde de geçerli.
  - **Sıradan bağımsız metrik eklendi**: NED ve TRchar sıra duyarlıdır; çok sütunlu bir sayfada doğru okunmuş metin farklı sırada olduğu için NED 0,63 ve TRchar 0,00 alabiliyor. Aynı çıktının token örtüşmesi (tokF1 0,886) rakip motordan daha iyiydi. Bu nedenle betik tokF1'i birlikte raporlar.
- **Görsel Dil Modeli ile OCR (`infrastructure/extractors/vision.py`)**: Bozulmuş taramalar için Ollama üzerinden `glm-ocr` kullanan `OllamaVisionExtractor` eklendi ve zincire Tesseract'tan sonra yerleştirildi. Ölçüm: temiz 300 DPI çıktıda Tesseract hem daha doğru hem ~67 kat hızlı (alan geri çağırma %100 / %98,3; 4 sn / 269 sn). Fotokopi benzeri bozulmuş taramada ise Tesseract çöküyor (karakter doğruluğu %43,6, alan geri çağırma **0/29**) buna karşılık `glm-ocr` ayakta kalıyor (%97,4, **29/29**). Bu nedenle Tesseract hız için önde tutuldu, görsel model yalnızca okunabilirlik denetimi başarısız olduğunda devreye giriyor.
- **Okunabilirlik Sinyali**: `ExtractedDocument.quality_ratio` (üç ve daha uzun belirteçlerin oranı) eklendi ve `FallbackDocumentExtractor` artık hem uzunluk hem okunabilirlik eşiğini arıyor. Yalnızca karakter sayısına bakmak yetersizdi: bozulmuş bir taramada Tesseract 758 karakterlik anlamsız çıktı üretiyor, 200 karakter eşiğini rahatça geçiyor ve zincir orada durup hiçbir başlık alanı bulamıyordu. Yeni sinyalle aynı belge görsel modele yükseltiliyor ve 8/8 alan kurtarılıyor; temiz taramalar 0,5 sn'de Tesseract'ta kalmaya devam ediyor.
- **Ayrıştırıcı Yetkisi Çift Yönlü Hâle Getirildi**: Mevzuatın biçimini zorunlu kıldığı alanlarda (`sayi`, `tarih`, `konu`, `ilgi`, `ekler`, `muhatap`, `gonderen_kurum`, `imza_sahibi`, `imza_unvani`) ayrıştırıcı bir değer bulamadıysa alan gerçekten yok demektir; modelin bu alan için ürettiği değer artık atılır. Önceden yalnızca ayrıştırıcının *bulduğu* değer modeli eziyordu. Sonuç: uydurulan alan sayısı `qwen3.5:9b` üzerinde **2 → 0**, `qwen3:8b` üzerinde **8 → 0**. Sunumu mevzuatça belirlenmemiş alanlar (`adres`, `iletisim`, `gizlilik_derecesi`, `ivedilik`, `basvuran_adi`) kapsam dışıdır; bunlarda ayrıştırıcının bulamaması 'yok' değil 'bilinmiyor' anlamına gelir.
- **Varsayılan Model Üzerinde Doğrulama**: Ölçümler projenin varsayılan modeli `qwen3.5:9b` ile yinelendi. Tür doğruluğu **%91,7**, uçtan uca eksik alan eşleşmesi **%75,0** (`qwen3:8b` üzerinde sırasıyla %83,3 ve %25,0). Tek sınıflandırma hatası `circular → official_letter` olup aynı kural tablosu kullanıldığı için uygunluk sonucunu etkilemez. Ayrıştırıcı bu modelde de kazanç sağlar: yalnız model %94,0, ayrıştırıcıyla %97,0; `muhatap` %60 → %100 ve çıkarım süresi yaklaşık üçte bir kısalır. Uçtan uca gecikme 37,6 sn/belge.
- **Boş Etiket Yakalaması**: Boş bir `Konu :` satırı, sonraki satırın metnini değer olarak yakalıyordu; iki nokta çevresinde yalnızca boşluk ve sekme kabul edilerek giderildi.
- **Tarih İçeren Liste Ayrıştırması**: `İlgi : 01.01.2026 ...` değerinde `01.` bir madde işareti sanılıp tarihin günü kaybediliyordu.
- **Langfuse Sürüm Uyumsuzluğu**: `observability/tracer.py` v3 içe aktarma yolunu (`langfuse.langchain`) kullanırken `requirements.txt` hâlâ `<3.0.0` sınırını taşıyordu; bu nedenle `main` üzerinde test paketi toplama aşamasında `ModuleNotFoundError` ile kırılıyordu. Bağımlılık `langfuse>=3.0.0` olarak güncellendi ve v3 SDK'nın v2 sunucusuyla desteklenmemesi nedeniyle `compose.yml` ile `docker-compose.dev.yml` içindeki sunucu imajı `langfuse/langfuse:3` olarak hizalandı.
- **İmzasız Dilekçe**: Belgenin sonundaki yalın ad, imza sayılıp gerçek bir 3071 s.K. m.4 eksikliğini gizliyordu. Artık imza için doğrulayıcı kanıt (unvan satırı, açık `İmza` ibaresi veya kurum anteti) aranır. Türkçe büyük İ harfinin `lower()` sonucu `imza` olmadığı için karşılaştırma katlama ile yapılır.

## [1.12.0] - 2026-07-30
### Eklendi
- **Genişletilmiş Birim Test Kapsamı ve Hata Düzeltmeleri** (#51):
  - MCP Modülü, Kullanıcı Alanı (Repository, Service, Router), Altyapı Modülleri (Redis, S3, Qdrant), Gözlemlenebilirlik (Tracer, Logger, Metrics) ve Paylaşılan Olay/Doğrulama (Event Bus, Publisher, Subscriber, Pagination DTO, Validators) katmanları için kapsamlı unit testleri yazıldı.
  - Langfuse `CallbackHandler` başlatma sırasında ortaya çıkan ve `secret_key` parametresini geçersiz kabul eden bir hata giderildi. Artık anahtarlar `os.environ` üzerinden yönetiliyor.
  - Davetiyeler oluşturulduktan sonra `SuccessResponse` dönerken kaynak kodunda yer alan `message` parametresi hatası giderildi.
  - `requirements.txt` dosyasına `fastmcp` ve `langchain` bağımlılıkları eklendi.

## [1.11.0] - 2026-07-30
### Eklendi
- **Görev 2: Resmî Yazı Taslaklama ve Birim Yönlendirme**:
  - `DraftService` oluşturularak RAG'den gelen bağlam üzerinden uygun resmi yazı taslağının oluşturulması sağlandı.
  - Taslak onayı gerektirmeyen durumlarda `RoutingGraph` üzerinden doğru birim ve kişilere yönlendirme önerisi sunulması altyapısı kuruldu.
  - İlgili servis için `POST /api/v1/documents/draft` uç noktası eklendi ve bağımlılıkları `dependency.py` üzerinden yapılandırıldı.
- **Görev 3: Chat Arayüzü ve Planlama Orkestratörü**:
  - Kullanıcı ile doğrudan iletişime geçebilmesi için basit `ChatAgent` ve `chat.md` sistem promptu eklendi.
  - Gelen taleplerin, basit bir soru mu yoksa evrak/mevzuat işi mi olduğuna karar veren Ana Orkestratör (`planning_graph.py`) devreye alındı. Orkestratöre `chat` yeteneği kazandırıldı.
  - `ChatService` ve `POST /api/v1/chat/message` uç noktası eklenerek uçtan uca LangGraph entegrasyonu tamamlandı.

### Kaldırıldı
- Miadını doldurmuş olan eski `classification_graph.py` iş akışı silindi ve bağımlılıkları temizlendi. (`ner.py` istisna olarak korundu).

## [1.10.0] - 2026-07-30
### Eklendi
- **Görev 1: Evrak Sınıflandırma ve İçerik Analizi** (#41):
  - **Metin Çıkarma Katmanı (`infrastructure/extractors/`)**: `BaseDocumentExtractor` soyutlaması ve `ExtractedDocument` sözleşmesi eklendi. Dört uygulama: `OpenDataLoaderExtractor` (birincil, Apache-2.0, düzen/tablo farkındalıklı, Java 11+ gerektirir), `PdfiumExtractor` (Java gerektirmeyen yedek), `TesseractExtractor` (Türkçe OCR, 300 DPI, `--psm 6`) ve `PlainTextExtractor`. `FallbackDocumentExtractor` eşik altı sonuçlarda zinciri ilerletir; `supports()` denetimi düz metin çıkarıcısının PDF baytlarını bozuk karaktere çevirip eşiği geçmesini engeller.
  - **Evrak Alanları ve Uygunluk Denetimi (`ai/compliance/`)**: Resmî evrak üstveri alanları (`EvrakField`: sayı, tarih, konu, muhatap, gönderen kurum, ilgi, ekler, imza sahibi/unvanı, gizlilik derecesi, ivedilik, başvuran, adres, iletişim) ve evrak türüne göre zorunlu/önerilen alan kural tablosu (`REQUIRED_FIELD_RULES`) eklendi. Eksik bilgi tespiti tamamen deterministik Python ile yapılır; LLM yalnızca alan çıkarımından sorumludur. `BLANK_VALUE_MARKER`, modelin `null` yerine yazdığı "Belirtilmemiş", "Yok", "-" gibi değerleri Türkçe karakter katlaması ile yakalar.
  - **Madde Atıfları**: Kural tablosundaki madde numaraları mevzuat.gov.tr üzerindeki resmî Yönetmelik metninden doğrulandı (Başlık m.10, Sayı m.11, Tarih m.12, Konu m.13, Muhatap m.14, İlgi m.15, İmza m.17, Ek m.18).
  - **Yeni Enum'lar**: Gelen evrak taksonomisi için `DocumentType` (10 üye) ve uygunluk durumu için `ComplianceStatus` eklendi. `DocumentType`, üretilen yazışma türünü modelleyen mevcut `CorrespondenceType`'tan kasıtlı olarak ayrı tutulmuştur.
  - **Evrak Analiz İş Akışı (`ai/workflows/document_analysis_graph.py`)**: `classify → extract_field → check_compliance → retrieve_mevzuat → suggest_mevzuat`. Mevcut `classification_graph.py` değiştirilmedi; retriever isteğe bağlıdır ve verilmediğinde mevzuat düğümleri devre dışı kalır.
  - **`ComplianceAgent`**: 11. uzman ajan ve Türkçe `compliance.md` şablonu eklendi; şablon yalnızca sunulan alıntılara dayanmayı zorunlu kılar.
  - **Mevzuat Korpusu (`datasets/mevzuat/`)**: Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik (18 madde), 3071 sayılı Dilekçe Hakkı Kanunu ve 4982 sayılı Bilgi Edinme Hakkı Kanunu metinleri eklendi.
  - **Korpus Yükleyici ve İndeksleme**: `retrieval/corpus_loader.py`, `workers/indexing.py` ve `scripts/index_mevzuat.py` eklendi. Yükleyici, indeksleme worker'ı ile BM25 bağımlılığı arasında paylaşılır; RRF tam `page_content` eşitliğine göre tekilleştirdiği için iki yolun birebir aynı parçaları üretmesi zorunludur.
  - **Uç Nokta**: `POST /api/v1/documents/analyze` (multipart) eklendi. Mevcut `validate_file_extension`, `ALLOWED_FILE_TYPES`, `MAX_FILE_SIZE_BYTES`, `BaseStorage` ve `event_bus` altyapısı yeniden kullanıldı; `DocumentUploadedEvent` ve `DocumentAnalyzedEvent` yayımlanır.
  - **Sentetik Evrak Veri Kümesi (`datasets/sample/`)**: 12 kurgu evrak; her biri `.txt` (kaynak metin), `.json` (beklenen tür, alanlar ve eksik alanlar) ve `.pdf` üçlüsü olarak eklendi. `evrak_11` alanların biçimsel olarak var ama içerik olarak boş olduğu (`Belirtilmemiş`, `-`) durumu, `evrak_12` ise metin katmanı bulunmayan taranmış görüntü ile OCR yolunu sınar. Küme üç uygunluk durumunun tamamını kapsar. Şartname 6.5 uyarınca gerçek kamu verisi kullanılmamıştır; tüm kişi, adres ve sayı bilgileri açıkça sentetiktir.
  - **PDF Üretici**: `scripts/generate_sample_evrak.py`, `.txt` kaynaklarından PDF üretir; Türkçe karakterlerin boş görünmemesi için Unicode TTF kaydı zorunludur ve font bulunamazsa betik hata verir.
  - **Biçimsel İşaret Tespiti (`ai/compliance/signal.py`)**: Belgenin kurum tarafından düzenlendiğini gösteren yapısal işaretler (T.C. anteti, `Sayı:` alanı, `İlgi:` alanı, `DAĞITIM` bölümü, imza bölümünde kurumsal unvan) regex ile deterministik olarak tespit edilir ve sınıflandırma istemine olgu olarak eklenir. Model kararını ezmez, yalnızca bilgilendirir. `qwen3:8b` üzerinde ölçülen etki: tür doğruluğu %66,7 → %83,3; resmî yazıyı dilekçe sanma hatası (yanlış kural tablosunun uygulanmasına yol açan zararlı hata biçimi) ortadan kalktı.
  - **Sınıflandırma Değerlendirme Betiği**: `scripts/evaluate_classification.py`, sentetik küme üzerinde tür doğruluğunu ve uçtan uca eksik alan eşleşmesini ölçer.
  - **Birim Testleri**: 180 yeni test eklendi (`test_extractor.py`, `test_compliance.py`, `test_document_analysis.py`, `test_document_service.py`, `test_document_endpoint.py`). Toplam 285 testin tamamı geçiyor. Veri kümesi güdümlü parametrik testler, taahhüt edilen beklenen sonuçları kural tablosuyla her çalıştırmada karşılaştırır.

### Değişti
- **`core/constants/system.py`**: OCR ve metin çıkarma sabitleri (`MIN_EXTRACTED_CHAR_COUNT`, `OCR_LANGUAGE`, `OCR_RENDER_DPI`, `OCR_PAGE_SEGMENTATION_MODE`, `ALLOWED_DOCUMENT_EXTENSIONS`) eklendi. Taranmış/fotoğraflanmış evrakın OCR yoluna ulaşabilmesi için `ALLOWED_FILE_TYPES` listesine `image/png`, `image/jpeg` ve `image/tiff` eklendi.
- **`core/config.py`**: `MEVZUAT_CORPUS_DIR` ve `MEVZUAT_COLLECTION_NAME` ayarları eklendi.
- **`core/__init__.py`**: Eksik olan `CorrespondenceType` dışa aktarımı ile birlikte yeni enum'lar tek noktadan erişilebilir hâle getirildi.
- **`api/dependency.py`**: Evrak analizi için tembel tekil bağımlılıklar (`get_mevzuat_retriever`, `get_document_analysis_graph`, `get_document_analysis_service`) eklendi.
- **`requirements.txt`**: `python-multipart`, `opendataloader-pdf`, `langchain-opendataloader-pdf`, `pypdfium2`, `pytesseract` ve `pillow` eklendi. `langfuse` bağımlılığı `<3.0.0` olarak sınırlandırıldı: `observability/tracer.py` yalnızca v2'de bulunan `langfuse.callback` içe aktarma yolunu kullanıyor ve `compose.yml` sunucu imajını `langfuse/langfuse:2` olarak sabitliyor. Ayrıca `requirements-dev.txt` (reportlab) oluşturuldu.

### Düzeltildi
- **Satır Yapısının Korunması**: `OpenDataLoader` varsayılan olarak satır sonlarını birleştiriyordu. Resmî yazıda satır yapısı anlam taşıdığı için (Sayı/Tarih aynı satırda, Konu bir alt satırda) alan çıkarımı tarih ve konuyu göremiyordu; `keep_line_breaks=True` ile giderildi.

## [1.9.0] - 2026-07-30
### Eklendi
- **SOTA Güvenlik ve Olay Tabanlı Haberleşme Entegrasyonu**:
  - **Kullanıcı Olayları**: `UserDeletedEvent` ve `UserPasswordChangedEvent` olayları `events/event.py` ve `events/__init__.py` içerisine eklendi.
  - **Asenkron Olay Yayımı**: Kullanıcı kayıt (`user.created`), silme (`user.deleted`) ve şifre değiştirme (`user.password_changed`) işlemlerinde `EventBus` üzerinden asenkron event yayımı aktifleştirildi.
  - **Redis Kara Liste (Token Blacklist)**: Çıkış yapan kullanıcının JWT access token'ının kalan süresi kadar Redis üzerinde bloke edilmesini sağlayan `/auth/logout` (POST) uç noktası geliştirildi.
  - **Güvenlik Bağımlılığı**: `get_current_user` bağımlılığı güncellenerek gelen isteklerin token kara liste kontrolü Redis üzerinden doğrulanmaya başlandı.
  - **Birim Testleri**: `/auth/logout` rotası ve Redis kara liste kontrolünü doğrulayan 2 yeni birim testi `tests/unit/domains/test_auth.py` dosyasına eklendi. Toplam 84 testin tamamı başarıyla geçti.

## [1.8.1] - 2026-07-30
### Değişti
- Paylaşılan Ollama fallback modeli `qwen3.5:9b` olarak korundu; geliştiricilerin kendi modellerini Git'e eklenmeyen `.env` dosyalarında `OLLAMA_MODEL` ile seçebilmesi hem yerel hem de Docker Compose çalıştırmalarında standartlaştırıldı.
- Ollama düşünme modu varsayılan olarak kapatıldı ve `OLLAMA_REASONING` ile yapılandırılabilir hale getirildi.
- Metin, akış ve yapılandırılmış çıktı çağrıları aynı reasoning ve token sınırı ayarlarını kullanacak şekilde birleştirildi.
- Varsayılan çıktı sınırı `OLLAMA_MAX_TOKENS=1024` olarak eklendi; çağrı bazında geçersiz kılma desteği korundu.

### Test
- Ollama varsayılanları, üç üretim yöntemi ve çağrı bazlı geçersiz kılmalar için provider/factory testleri genişletildi.

## [1.8.0] - 2026-07-30
### Eklendi
- **E-posta Davetiye / Whitelist Tabanlı Kayıt Sistemi**:
  - **Davetiye Modeli**: Yöneticilerin e-postaları önceden ekleyebilmesi için `InvitedEmailModel` ve ilgili doğrulamalar (`InvitedEmailCreate`, `InvitedEmailResponse`) eklendi.
  - **Davet Etme Uç Noktası**: `/users/invitations` (POST) ucu geliştirildi. Yalnızca Admin ve Manager'ların e-posta adresi ve önceden atanmış rol bilgisi ile davetiye oluşturabilmesi sağlandı.
  - **Güvenli Kayıt Eşleme**: `/users` (POST) kayıt ucu güncellenerek yalnızca sistemde kullanılmamış aktif davetiyeye sahip olan e-postaların kayıt olmasına izin verildi. Kayıt sonrasında kullanıcının rolü, davetiyedeki rol ile otomatik eşlendi.
  - **Birim Testleri**: Davetiye oluşturma, davetsiz kayıt engelleme, davetli başarılı kayıt ve rol atama senaryolarını test eden 5 adet yeni birim testi `tests/unit/domains/test_invite.py` altına eklendi. `test_user.py` testleri güncellendi ve tüm testler başarıyla çalıştırıldı.

## [1.7.0] - 2026-07-30
### Eklendi
- **Kullanıcı Yönetimi CRUD Uç Noktaları**:
  - **Kullanıcı Listeleme**: `/users` (GET) ucu sayfalama, arama ve rol bazlı filtreleme parametreleriyle eklendi. (Admin ve Manager yetkili).
  - **Tekil Kullanıcı Detayı**: `/users/{user_id}` (GET) ucu ile detaylı profil getirme eklendi (Kullanıcının kendisi veya Admin/Manager yetkili).
  - **Profil Güncelleme**: `/users/{user_id}` (PUT) ucu eklendi. Rol veya hesap aktiflik durumunu değiştirmek yalnızca Admin'lerle sınırlandırıldı.
  - **Şifre Değiştirme**: Giriş yapan kullanıcının kendi şifresini güvenli bir şekilde güncelleyebilmesi için `/users/me/password` (POST) ucu geliştirildi.
  - **Soft Delete**: Kullanıcıyı kalıcı olarak silmeden `is_deleted=True` ve `is_active=False` yapmak için `/users/{user_id}/soft` (DELETE) ucu eklendi (Yalnızca Admin yetkili).
  - **Hard Delete**: Kullanıcı kaydını veritabanından kalıcı olarak silmek için `/users/{user_id}/hard` (DELETE) ucu eklendi (Yalnızca Admin yetkili).
  - **Birim Testleri**: Silme (soft/hard), listeleme, şifre değiştirme ve güncelleme senaryolarını doğrulayan 5 yeni birim testi `tests/unit/domains/test_user.py` dosyasına eklendi. Tüm testler başarıyla geçti.
## [1.6.0] - 2026-07-30
### Eklendi
- **Rol Tabanlı Kullanıcı ve Yetkilendirme Sistemi (RBAC)**:
  - **Kullanıcı Rolleri**: `admin`, `manager`, `employee` ve `auditor` rolleri `UserRole` enum modülüne eklendi.
  - **Şifreleme**: `bcrypt` paketi entegre edilerek şifre hash'leme ve doğrulama işlevleri `core/security.py` altında aktifleştirildi.
  - **JWT Token Yönetimi**: `pyjwt` ile access token ve refresh token üretimi ve doğrulaması tamamlandı.
  - **Kullanıcı Kaydı ve Giriş**: `/users` (kullanıcı kaydı) ve `/auth/login` (kullanıcı girişi) API uç noktaları geliştirildi.
  - **Erişim ve Yetki Kontrolü**: Uç noktalar için token doğrulaması yapan `get_current_user` ve rol yetkilerini kontrol eden `@require_roles` bağımlılık sarmalayıcısı `api/dependency.py` dosyasına eklendi.
  - **Birim Testleri**: Yeni sistemin doğruluğunu test eden 9 adet pytest birim testi `tests/unit/core/test_security.py` ve `tests/unit/domains/` klasörleri altına eklendi. Tüm testler başarıyla çalıştırıldı.
- **API Temizliği ve Health Rotası Refaktörü**:
  - `app/api/v1/` klasörü altındaki tüm atıl ve kullanılmayan placeholder dosyalar silindi.
  - Aktif çalışan `/health` uç noktası `system` domain'i altına (`app/domains/system/router.py`) taşındı.
  - `/health` rotasının prefix'siz olarak `/api/v1/health` şeklinde sunulması sağlandı.

## [1.5.0] - 2026-07-30
### Eklendi
- **Gözlemlenebilirlik Altyapısı (Observability)**:
  - **Prometheus Entegrasyonu**: `prometheus-fastapi-instrumentator` ile `/metrics` uç noktası FastAPI uygulamasına entegre edildi.
  - **Langfuse Entegrasyonu**: LLM aramalarını, ajanları ve iş akışlarını izlemek için Langfuse `CallbackHandler` sağlayıcısı (`tracer.py`) eklendi.
  - **Docker Compose Servisleri**: `prometheus`, `grafana` ve `langfuse` servisleri `compose.yml` ve `deploy/docker/docker-compose.dev.yml` dosyalarına eklenerek otomatik başlatılacak şekilde yapılandırıldı.
  - **Grafana Paneli (ID: 22676)**: `prometheus-fastapi-instrumentator` için hazır FastAPI Observability dashboard şablonu (`fastapi_dashboard.json`) otomatik yüklenecek şekilde projelendirildi.
  - **Veritabanı Başlatma Betiği**: Langfuse için PostgreSQL üzerinde `langfuse` veritabanını otomatik oluşturan `scripts/init-db.sh` betiği eklendi.
  - **Makefile Komutları**: Konteyner çalışırken veritabanını oluşturmak için `make setup-db` hedefi ve temel docker-compose komutları eklendi.
  - **Yapılandırılmış Loglama**: `observability/logger.py` oluşturularak JSON formatında loglama ve clean development formatı entegre edildi.
- **Shared Modülü Refaktörü**:
  - Son harfi "s" olan dosya yasağı kapsamında `types.py`, `dto.py` ve `validators.py` silindi.
  - `shared/type/`, `shared/dto/` ve `shared/validator/` alt klasörleri oluşturularak tipler, DTO'lar (Pagination, Search) ve doğrulayıcılar bağımsız dosyalar olarak modüler hale getirildi.
- **Sadeleştirilmiş MCP Yapısı**:
  - `tools/` altındaki tüm placeholder dosyalar temizlendi.
  - `client.py` ve `manager.py` eklenerek dış MCP sunucularına stdio üzerinden asenkron bağlantı kurabilen ve bunları yöneten merkezi altyapı oluşturuldu.
  - `server.py` sadeleştirilerek FastMCP sunucusu için minimum bir taban haline getirildi.
- **SOTA Domain ve Events Yapısı**:
  - `auth`, `chat`, `documents`, `evaluation`, `feedback`, `settings`, `system`, `users` olmak üzere tüm domainlerdeki boş `models.py` ve `schemas.py` dosyaları silinerek yerlerine `model/` ve `schema/` klasörleri oluşturuldu.
  - `documents` domain'i, Görev 1 (Sınıflandırma/Analiz) ve Görev 2 (Taslaklama/Yönlendirme) verilerini/şemalarını barındıracak şekilde iskelet halinde güncellendi.
  - Tüm domainlerin `router.py` dosyaları `api/router.py` (ana API yönlendiricisi) altına `/api/v1/...` rotasıyla bağlanarak FastAPI uygulamasına entegre edildi.
  - `events/events.py` silinerek yerine `events/event.py` oluşturuldu. Olay tabanlı gevşek bağlı mimari için asenkron `EventBus`, `EventPublisher` ve `EventSubscriber` iskeletleri yazıldı.

- **Kaynağa Bağlı Taslak Üretimi**: Draft Graph state yapısına gelen evrak, sınıflandırma sonucu, doğrulanmış RAG bağlamı, durum ve insan onayı alanları eklendi.
- **Resmî Yazışma Türleri**: Üst yazı, cevap yazısı, bilgilendirme metni ve diğer/alternatif resmî yazışma için `CorrespondenceType` sözleşmesi, Türkçe/İngilizce alias normalizasyonu ve türe özel üretim kuralları eklendi.
- **Güvenli Girdi ve Hata Yönetimi**: Eksik evrak, Writer/Editor/Evaluator hataları ve yetersiz bağlam artık sahte başarı üretmeden açık durum ve insan onayı sinyali döndürüyor.
- **Workflow Testleri**: Kaynak koruma, dört yazışma türü, çözümleme önceliği, Türkçe alias normalizasyonu, belirsiz tür fallback'i, editör revizyonu, eksik evrak, LLM/structured-output hatası, yetersiz bağlam, revizyon sınırı ve güven skoru doğrulaması testleri eklendi; toplam test sayısı 78'e çıkarıldı.

### Değişti
- Writer, Editor, Reflection ve Evaluator adımları gelen evrak ile doğrulanmış bağlamı tüm revizyon döngüsü boyunca koruyacak şekilde güncellendi.
- Writer sistem yönergesi, kaynaklarda bulunmayan kişi, kurum, tarih, mevzuat, tutar veya olayların üretilmesini engelleyen kurallarla güçlendirildi.
- Planning Graph, sınıflandırma ve RAG sonuçlarını Draft Graph'a aktarıyor; insan onayı gereken taslaklar Routing Graph üzerinden güvenli biçimde `HumanApproval` hedefine yönlendiriliyor.
- Classification ve Planning Graph, açıkça istenen yazışma türünü metadata üzerinden Draft Graph'a kayıpsız aktarıyor.

---

## [1.4.0] - 2026-07-29
### Eklendi
- **`core/enums/` Klasörü**: Son harfi "s" olan dosya yasağı gereği `enums.py` silindi; yerine `user_role.py` (`UserRole` StrEnum) ve `document_status.py` (`DocumentStatus` StrEnum) modülleri oluşturuldu.
- **`core/constants/` Klasörü**: `constants.py` silindi; sistem geneli sabitler (`MAX_FILE_SIZE_BYTES`, `ALLOWED_FILE_TYPES`, `DEFAULT_PAGE_SIZE`, `MAX_PAGE_SIZE`, `AI_WORKFLOW_TIMEOUT_SECONDS`, `CORS_ORIGINS`, `CACHE_TTL_SECONDS`) `constants/system.py` içine taşındı.
- **`core/permissions/` Klasörü**: `permissions.py` silindi; FastAPI `Depends` olarak çalışan rol tabanlı erişim denetleyicisi `RoleChecker` sınıfı `permissions/role_checker.py` içine yerleştirildi.
- **`core/security.py` İskeleti**: JWT erişim/yenileme jetonu üretimi (`create_access_token`, `create_refresh_token`, `decode_token`) ve bcrypt parola hashing (`hash_password`, `verify_password`) için hazır-aktive edilebilir iskelet fonksiyonlar yazıldı.
- **Core Birim Testleri**: `tests/unit/core/test_core.py` eklenerek toplam test sayısı 63'e çıkarıldı.

### Değişti
- `core/exceptions.py` silindi (`api/exceptions/` ile çakışmaması için).
- `core/__init__.py` tüm yeni modülleri tek noktadan dışa aktaracak şekilde güncellendi.
- Tüm kod içi yorum ve docstring'ler İngilizce'ye çevrildi ve `Args/Returns/Raises` biçimli Google-style docstring standardına uyarlandı.

---

## [1.3.0] - 2026-07-29
### Eklendi
- **SOTA API Core Yanıt Yapısı (`api/responses/`)**: Tüm uç noktaların tek tip JSON döndürmesini sağlayan `APIResponse[T]` Pydantic şeması, `APIErrorDetail` hata modeli, `SuccessResponse` ve `ErrorResponse` yardımcı fonksiyonları eklendi.
- **Modüler Özel İstisna Hiyerarşisi (`api/exceptions/`)**: `BaseAppException` taban sınıfından türeyen `NotFoundException` (404), `ValidationException` (422), `AuthenticationException` (401), `AuthorizationException` (403), `ConflictException` (409) ve `AIException` (502) sınıfları kendi bağımsız dosyalarında tanımlandı.
- **Küresel Hata Yakalayıcılar**: `app_exception_handler`, `validation_exception_handler`, `http_exception_handler` ve `generic_exception_handler` fonksiyonları `exceptions/handlers.py` içine eklendi.
- **Performans Middleware'leri (`api/middleware/`)**:
  - `ResponseTimeMiddleware`: Yanıt süresini `X-Response-Time-Ms` header'ına ve JSON meta alanına ekler.
  - `StructuredLoggingMiddleware`: Yöntem, yol, durum kodu ve gecikme süresini yapılandırılmış biçimde loglar.
- **`api/v1/health.py`**: `/health` ucu birleşik `SuccessResponse` formatına taşındı.
- **API Core Birim Testleri**: `tests/unit/api/test_core.py` eklenerek 6 yeni test senaryosu yazıldı.

### Değişti
- Eski boş `api/exceptions.py`, `api/responses.py` ve `api/middleware.py` dosyaları silindi; hepsi birer modüler klasöre dönüştürüldü.
- `backend/app/main.py` middleware ve küresel handler kayıtlarını içerecek şekilde güncellendi.

---

## [1.2.0] - 2026-07-29
### Eklendi
- **Reflection & Evaluator Ajanları**: Taslak parlatma ve kalite denetimi için `ReflectionAgent` (`reflection.py`) ve `EvaluatorAgent` (`evaluator.py`) sınıfları ile Türkçe `.md` şablonları eklendi.
- **Master Planning & Supervisor**: Kullanıcı isteğine göre çalıştırılacak alt akışları dinamik planlayan master grafik (`planning_graph.py`) kodlandı.
- **Gelişmiş LangGraph Alt Akışları**:
  - `classification_graph.py` (Classifier -> NER -> Metadata)
  - `rag_graph.py` (Query Rewrite -> Hybrid Retrieve -> Verify -> Loop)
  - `draft_graph.py` (Writer -> Editor -> Reflection -> Evaluator -> Loop)
  - `routing_graph.py` (Güven skoruna göre departmana veya `HumanApproval`'a yönlendirme)
  - `system_graph.py` (Arka plan önbellek ve günlük temizliği)
- **Kapsamlı Birim Testleri**: 5 iş akışını ve master grafiği kapsayan 6 yeni test senaryosu eklenerek toplam test sayısı 43'e çıkarıldı.
- **Paket Dışa Aktarımları**: Modüle kolay erişim sağlamak amacıyla `backend/app/ai/__init__.py` dosyası dolduruldu.

### Değişti
- **Dinamik Prompt Yükleme**: Tüm 10 uzman ajanın sistem yönergeleri (system prompts), `PromptManager` üzerinden Türkçe şablonlardan dinamik okunacak şekilde güncellendi.
- **Draft Akışı**: Eski geçici `EditorAgent` yerine asıl `ReflectionAgent` ve `EvaluatorAgent` entegre edildi.

---

## [1.1.0] - 2026-07-29
### Eklendi
- **Hibrid Arama (Hybrid Retrieval)**: Paralel Dense (Qdrant) ve Sparse (Türkçe tokenized BM25) aramayı birleştiren `HybridRetriever` eklendi.
- **Rank Fusion (RRF)**: Arama skorlarını birleştirmek için Reciprocal Rank Fusion algoritması kodlandı.
- **LLM Reranker**: Aday belgeleri alaka düzeyine göre sıralayan Pydantic tabanlı `LLMReranker` entegre edildi.
- **Arama Testleri**: `test_retrieval.py` birim test dosyası eklendi.

---

## [1.0.0] - 2026-07-29
### Eklendi
- **Temel Mimari**: Ajanlar (`BaseAgent` + Uzmanlar), hafıza katmanları (Redis, Mem0), LLM sağlayıcıları (Ollama, vLLM) ve önbellek/veritabanı altyapısı kuruldu.
