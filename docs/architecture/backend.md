# Backend Mimarisi

## Amaç

Bu doküman backend uygulamasının mimarisini, katmanlarını ve veri akışını açıklar.

Backend'in amacı;

* API isteklerini yönetmek
* İş kurallarını uygulamak
* Yapay zekâ sistemini yönetmek
* Veritabanı işlemlerini gerçekleştirmek
* Harici servislerle iletişim kurmak

Backend, kullanıcı arayüzünden tamamen bağımsız olarak geliştirilmektedir.

---

# Mimari Yaklaşım

Backend aşağıdaki mimari prensiplere göre tasarlanmıştır.

* Modular Monolith
* Domain Driven Design (DDD)
* SOLID
* Clean Architecture
* Repository Pattern
* Dependency Injection

Her bileşen yalnızca kendi sorumluluk alanından sorumludur.

---

# Genel Yapı

Backend uygulaması aşağıdaki ana bileşenlerden oluşmaktadır.

```text
backend/
│
├── app/
│   ├── api/
│   ├── core/
│   ├── domains/
│   ├── ai/
│   ├── mcp/
│   ├── infrastructure/
│   ├── observability/
│   ├── shared/
│   ├── workers/
│   └── events/
│
├── tests/
├── scripts/
└── migrations/
```

Her klasör belirli bir sorumluluğa sahiptir.

---

# İstek Yaşam Döngüsü

Backend'e gelen bir istek aşağıdaki adımlardan geçer.

```text
HTTP Request
      │
      ▼
API Router
      │
      ▼
Validation
      │
      ▼
Service
      │
      ▼
Repository
      │
      ▼
Infrastructure
      │
      ▼
Database
```

AI gerektiren işlemlerde Service katmanı AI Core ile iletişim kurar.

---

# API Katmanı

API katmanı kullanıcıdan gelen HTTP isteklerini karşılar.

Görevleri;

* Request doğrulama
* Authentication
* Authorization
* Response oluşturma
* Service çağırma

API katmanında;

* SQL yazılmaz.
* AI çağrısı yapılmaz.
* İş mantığı bulunmaz.

API yalnızca giriş ve çıkış noktasıdır.

---

# Core

Core klasörü sistem genelinde kullanılan ortak bileşenleri içerir.

Örnekler;

* Config
* Security
* Middleware
* Exception Handler
* Dependency Injection
* Settings

Core herhangi bir domain'e bağlı değildir.

---

# Domains

Backend'in en önemli katmanıdır.

Her iş alanı bağımsız bir domain olarak geliştirilir.

Örnek yapı

```text
domains/

chat/

documents/

routing/

units/

users/

system/
```

Her domain kendi içerisinde izole çalışır. Boş, sıfır-route'lu iskelet domain'ler (eskiden `evaluation/`, `feedback/`, `settings/`) kaldırılmıştır — bir domain yalnızca gerçek bir uç nokta bağlandığında eklenir.

---

# Domain Yapısı

Her domain aşağıdaki yapıyı takip eder.

```text
chat/

router.py

service.py

repository.py

schemas.py

models.py
```

İhtiyaç halinde aşağıdaki dosyalar eklenebilir.

```text
validators.py

permissions.py

events.py

tasks.py

exceptions.py
```

---

# Router

Router yalnızca HTTP katmanıdır.

Görevleri

* Endpoint tanımlamak
* Request almak
* Validation yapmak
* Service çağırmak
* Response döndürmek

Router iş mantığı içermez.

---

# Service

Service katmanı uygulamanın iş kurallarını içerir.

Service;

* Repository kullanabilir.
* AI sistemini çağırabilir.
* Event yayınlayabilir.
* Transaction yönetebilir.

Service;

* SQL yazmaz.
* HTTP yönetmez.
* ORM modeli oluşturmaz.

---

# Repository

Repository veri erişim katmanıdır.

Görevleri

* CRUD işlemleri
* Filtreleme
* Sayfalama
* Transaction
* ORM yönetimi

Repository yalnızca veri erişiminden sorumludur.

İş kuralları burada bulunmaz.

---

# Models

Models klasörü veritabanı modellerini içerir.

Her model tek bir tabloyu temsil eder.

ORM dışında iş mantığı içermez.

---

# Schemas

Schemas klasörü API giriş ve çıkış modellerini içerir.

Tüm Request ve Response modelleri burada bulunur.

Veritabanı modelleri ile karıştırılmamalıdır.

---

# AI Katmanı

Backend içerisindeki AI işlemleri ayrı bir katmanda bulunmaktadır.

Backend yalnızca AI Core'u çağırır.

AI'nın nasıl çalıştığı

```text
docs/architecture/ai.md
```

dokümanında açıklanmaktadır.

---

# MCP

Backend, sistem araçlarına doğrudan erişmez.

Tüm sistem araçları MCP üzerinden kullanılmaktadır.

Örnekler

* Terminal
* Dosya sistemi
* Web Browser
* Git
* Harici servisler

Bu yapı AI katmanını güvenli ve genişletilebilir hale getirir.

---

# Infrastructure

Infrastructure katmanı, harici servisler ve veri saklama/erişim katmanlarıyla olan bağlantıları ve istemcileri yönetir. Projede bu katman tamamen asenkron (async) ve modüler olarak tasarlanmıştır.

### 1. Database (PostgreSQL)
`app/infrastructure/database/` dizininde konumlanmıştır:
* **Async Engine & Session**: SQLAlchemy `create_async_engine` ve `async_sessionmaker` kullanılarak asenkron PostgreSQL bağlantı havuzu kurulmuştur.
* **get_db**: FastAPI endpoint'lerinde veritabanı oturumlarını güvenli şekilde yöneten asenkron dependency fonksiyonu.
* **verify_db_connection**: Uygulama ayağa kalkarken PostgreSQL veritabanı bağlantısını kontrol eden asenkron doğrulama fonksiyonu.
* **TimestampMixin**: ORM modellerine `created_at` ve `updated_at` alanlarını otomatik ekleyen zaman damgası mixin sınıfı.

### 2. Cache (Redis)
`app/infrastructure/cache/` dizininde konumlanmıştır:
* **RedisCache**: `redis.asyncio` kütüphanesini sarmalayarak asenkron get, set, delete, exists ve clear operasyonlarını sunan cache istemcisi.
* **get_cache**: Global RedisCache tekil (singleton) örneğine erişim sağlayan fonksiyon.

### 3. Vectorstore (Qdrant)
`app/infrastructure/vectorstore/` dizininde konumlanmıştır:
* **BaseVectorStore**: Vektör veritabanları için soyut taban sınıfı.
* **QdrantStore**: `AsyncQdrantClient` aracılığıyla asenkron koleksiyon oluşturma (`create_collection`), vektör ve metin kaydetme (`upsert_documents`) ve anlamsal benzerlik araması (`similarity_search`) yeteneklerini sağlayan istemci.
* **get_vector_store**: Global QdrantStore tekil örneğini döndüren fabrika fonksiyonu.

### 4. Storage (Local / S3)
`app/infrastructure/storage/` dizininde konumlanmıştır:
* **BaseStorage**: Dosya yükleme, indirme ve silme için soyut arayüz.
* **LocalStorage**: Yerel disk üzerinde çalışır. Dizin dışı dosya erişimini (Directory Traversal) engelleyen güvenlik kontrolleri barındırır.
* **S3Storage**: AWS S3 ve MinIO ile uyumlu, asenkron `boto3` thread havuzu kullanan nesne depolama istemcisi.
* **get_storage_client**: Konfigürasyona göre doğru depolama istemcisini dönen fabrika fonksiyonu.

### 5. LLM Providers
`app/infrastructure/providers/` dizininde konumlanmıştır:
* **OllamaClient** (`ollama.py`): Yerel Ollama servisiyle entegrasyonu sağlar; `num_ctx`/`keep_alive` her çağrıda ayarlanır ve `ChatOllama` örnekleri parametre setine göre önbelleğe alınır. (Kullanılmayan `vllm.py` sağlayıcısı kaldırılmıştır — hiçbir yerde kurulmuyordu ve `OllamaClient`'ın aldığı sertleştirmelerin (client cache, `num_ctx`) hiçbirine sahip değildi.)

### 6. Checkpointing (Postgres)
`app/infrastructure/checkpointing/` dizininde konumlanmıştır:
* **`init_checkpointer` / `close_checkpointer` / `get_checkpointer`**: `AsyncPostgresSaver.from_conn_string()`'in kendisi bir async context manager olduğu için (doğrudan `await` edilip bir kenara bırakılamaz), bir `AsyncExitStack` etrafında en-iyi-çaba (best-effort) açılıp kapatılır. Postgres erişilemezse yalnızca HITL kesintileri devre dışı kalır; uygulama boot'u engellenmez.
* Yalnızca `planning_graph` bir checkpointer alır (bkz. `docs/architecture/ai.md` — HITL bölümü).

Bu katman yalnızca istemci bağlantılarından ve temel I/O işlemlerinden sorumludur.

---

# Shared

Shared klasörü proje genelinde ortak kullanılan yapıları içerir.

Örnekler

* DTO
* Base Classes
* Constants
* Enums
* Utility Types

İş mantığı Shared içerisine eklenmez.

---

# Events

Sistem bileşenleri arasında gevşek bağlı iletişim sağlamak amacıyla Event yapısı kullanılabilir.

Örnek olaylar

* UserCreated
* ChatCompleted
* DocumentIndexed
* EmbeddingGenerated

Event yapısı domain bağımlılığını azaltır.

---

# Workers

Uzun süren işlemler arka planda çalıştırılır.

Örnekler

* Embedding üretimi
* Büyük belge indeksleme
* Dosya dönüştürme
* Bildirim gönderme

Workers HTTP isteğinden bağımsız çalışır.

---

# Observability

Backend tüm önemli işlemleri izlenebilir hale getirir.

İzlenen bilgiler

* API istekleri
* Hata kayıtları
* AI çağrıları
* Tool kullanımı
* Performans metrikleri

Bu yapı hata ayıklamayı kolaylaştırır.

---

# Güvenlik

Backend aşağıdaki güvenlik prensiplerini uygular.

* Authentication
* Authorization
* Input Validation
* Rate Limiting
* Secret Management
* Audit Logging

Hiçbir gizli bilgi kaynak kodunda tutulmaz.

## Çok kiracılılık (Multi-Tenancy)

Sistem `root` / `admin` / `manager` / `employee` olmak üzere dört rollü,
şirket (`company`) bazlı çok kiracılı bir mimari kullanır (bkz.
`docs/api/companies.md`). Kimlik doğrulama zorunludur (`settings.
REQUIRE_AUTH`); açık/kimliksiz erişim modu yoktur.

Dört sabit denetim katmanı, bu sırayla:

1. **Kiracı kapsamı** -- her repository metodu açık bir `company_id`
   parametresi alır ve ona göre filtreler (bkz. `app.domains.documents.
   repository.DocumentRepository`'nin kendi docstring'i). Faz 3'ten itibaren
   Postgres Row-Level Security bunun **gerçek** bir ikinci savunma hattı --
   bkz. aşağıdaki "Postgres Row-Level Security (RLS)" bölümü.
2. **ABAC kararı** -- `app.core.authz.engine.authorize` (bkz. aşağıdaki "ABAC
   Yetkilendirme Motoru" bölümü). `role_checker.bypasses_ownership` hâlâ
   var ve list/filtre kararlarında (`GET /documents` gibi) kullanılıyor, ama
   tekil kaynak erişim kontrolleri artık bu motora taşındı: ADMIN/MANAGER/
   ROOT bir kaynağı sahibi olmasalar bile görebilir, ama yalnızca **kendi
   şirketleri içinde** (kiracı kapsamı asla atlanmaz).
3. **Gizlilik derecesi** -- `role_checker.clearance_for`/`assert_clearance`,
   şirket sınırından bağımsız, ortogonal bir merdiven (`SensitivityLevel`).
4. **Guardrail'ler** -- `app.ai.guardrails.output_gate`,
   `app.ai.tools.document_tools`'un retrieval-anında red mekanizması.

`users.company_id` yalnızca `role='root'` için NULL'dur (bir CHECK
constraint ile zorlanır) -- root herhangi bir şirkete bağlı değildir ve
şirket verisine yalnızca açık bir scope-switch akışıyla erişir (bkz.
`docs/api/companies.md`).

**Bilinen kapsam dışı**: `chat_sessions`/`chat_messages`/`drafts`/`runs`/
`run_steps`/`guardrail_events` tabloları `company_id` kolonunu taşır ama bu
alan henüz zorunlu değildir -- bu satırlar LangGraph orkestrasyon katmanının
derinlerinden (`PlanningState` üzerinden, `user_id`'nin bugün taşındığı
şekilde) yazılır ve `company_id`'nin oraya taşınması ayrı bir faz olarak
planlanmıştır (bkz. `app.observability.model.run_model.RunModel.company_id`
docstring'i). Bu tablolar henüz RLS'e de dahil değil -- bir tablo, kolonu her
satırda gerçekten dolu olmadan RLS'e alınmaz (aksi hâlde meşru satırlar bile
kimseye görünmez hâle gelir; bkz. migration `0013_rls`'in kendi docstring'i).

## Postgres Row-Level Security (RLS)

**Önce şunu oku**: RLS, bir tablonun **sahibi** için tamamen no-op'tur --
`ENABLE ROW LEVEL SECURITY` fark etmez. Backend ilk migration'dan beri
Postgres'e `postgres` (bu veritabanının sahibi, superuser) olarak
bağlanıyordu; bağlantı rolünü ayırmadan yalnızca policy eklemek hiçbir şeyi
korumayan saf tiyatro olurdu. Migration `0013_rls` bu yüzden ikisini birden
yapar:

1. **`kachow_app` rolü** -- `NOSUPERUSER`, tablo sahipliği yok, yalnızca
   `SELECT`/`INSERT`/`UPDATE`/`DELETE` yetkisi (+ `ALTER DEFAULT PRIVILEGES`,
   böylece sonraki her migration'ın yarattığı tablo da otomatik yetki alır).
   `settings.DATABASE_URL` artık bu role bağlanıyor (`compose.yml`).
   İdempotent (`DO $$ ... IF NOT EXISTS ...`) -- mevcut bir Postgres
   volume'ü `scripts/init-db.sh`'ı yeniden çalıştırmaz, o yüzden rol
   yaratımı hem orada (taze volume'ler için) hem migration'da (mevcut
   volume'ler için) tekrarlanır.
2. **`ENABLE`+`FORCE ROW LEVEL SECURITY`** ve tek bir `tenant_isolation`
   policy'si, Faz 1'in zaten `company_id NOT NULL` yaptığı tablolarda:
   `users`, `units`, `documents`, `invited_emails`, `permission_grants`
   (Faz 2). `FORCE` şart -- onsuz RLS tablo sahibi için zaten atlanıyor
   *ve* `BYPASSRLS` yetkili herhangi bir rol için de atlanır; `kachow_app`
   ikisi de değil, ama `FORCE` bunu gelecekte de öyle kalmaya zorluyor.

Policy: `company_id = current_setting('app.current_company_id', true) OR
current_setting('app.is_root', true) = 'on'`. `current_setting(key, true)`
GUC set edilmemişse hata fırlatmak yerine NULL döner -- `company_id = NULL`
SQL'in üçlü mantığında NULL'dır, TRUE değil, yani GUC'u hiç set etmemiş bir
oturum (unutulmuş bir middleware, başıboş bir ham SQL bağlantısı) her RLS'li
tabloda sıfır satır görür: `role_checker.clearance_for`'ın "bilinmeyen
gizlilik hiçbir şeyi açmaz" ile aynı fail-secure varsayılan.

### GUC mekaniği

`SET LOCAL` transaction kapsamlıdır ve bağlantılar havuzdan geldiği için her
transaction'da yeniden set edilmesi gerekir:

```python
await session.execute(
    text("SELECT set_config('app.current_company_id', :cid, true)"),
    {"cid": company_id or ""},
)
```

Üç çağrı yeri:

1. **İstek kapsamı** -- `app.api.middleware.tenant.TenantContextMiddleware`
   JWT'yi (zaten `company_id`/`role` claim'lerini taşıyor) request'e hiçbir
   dependency çalışmadan **önce** decode edip `app.core.context.
   current_tenant_var`'a yazıyor; `app.infrastructure.database.session.
   get_db` oturumu açar açmaz, ilk statement olarak bu değerleri GUC'a
   basıyor. "İlk statement" önemli: `AsyncSession` transaction'ı tembel
   başlatıyor, `SET LOCAL` de yalnızca kendi transaction'ında yaşıyor --
   GUC'u geç basmak, ondan önce başka bir statement'ın kendi transaction'ını
   başlatıp (request'in geri kalanında) GUC'suz bitirmesi riski taşırdı.
2. **Kiracısı bilinen istek-dışı yazıcılar** -- `app.domains.units.provider.
   get_active_units_for_routing`, `app.domains.users.seeder`, `app.domains.
   units.seeder`. Yeni `app.infrastructure.database.session.tenant_session
   (company_id, is_root)` context manager'ı, aynı GUC mantığını
   `current_tenant_var` yerine açık argümanlardan uyguluyor.
3. **Kiracı-öncesi kimlik çözümleme** -- `POST /auth/login`, `POST
   /auth/refresh`, `POST /users` (davet-kapılı kayıt). `username`/`email`
   sistem genelinde benzersiz (şirket bazında değil), yani bu üç uç nokta
   "hangi şirket" sorusu cevaplanmadan **önce** çalışmak zorunda -- RLS'in
   scope'layacağı bir kiracı henüz yok. Bu üçü `app.infrastructure.database.
   session.get_owner_db`'yi kullanıyor: şema sahibi bağlantısı, RLS'i
   tanım gereği atlıyor. Alembic de aynı bağlantıyı (`ALEMBIC_DATABASE_URL`,
   boşsa `DATABASE_URL`'e düşer) kullanıyor -- DDL zaten sahip gerektirir.

**Canlı doğrulama sırasında bulunan iki gerçek hata** (ikisi de bu değişiklik
öncesinde zaten vardı, RLS onları *ortaya çıkardı*, yaratmadı):
`app.domains.users.seeder._seed_one`'ın var-olma kontrolü başta
`tenant_session` (şirket-scope'lu) kullanıyordu -- `username`/`email` global
benzersiz olduğu için iki farklı şirkete aynı "admin" kullanıcı adıyla
seed atmaya çalışmak, kontrolü değil global unique constraint'i tetikliyordu.
Kontrol artık `get_owner_db` ile aynı gerekçeyle şema-sahibi bağlantısında
çalışıyor. Ayrı olarak, `AuthService.refresh_access_token`'ın ürettiği yeni
access token `company_id` claim'ini hiç taşımıyordu (yalnızca `authenticate_
user`'ınki taşıyordu) -- RLS öncesi zararsızdı, RLS sonrası bu token'la
yapılan her sonraki istek "User not found" ile patlıyordu (GUC boş kalıyor).
İkisi de düzeltildi ve gerçek, çalışan Docker yığınına karşı doğrulandı.

### Dürüst uyarı

RLS **ikinci** savunma hattıdır, birincisi değil: (a) diskteki analiz
blob'u ve Qdrant hiç RLS kapsamında değil, (b) `drafts`/`chat_sessions`/
`runs`/... hâlâ RLS dışı (yukarıdaki "bilinen kapsam dışı"), (c) alembic ve
`scripts/` şema-sahibi tarafında çalışıyor, RLS'ten etkilenmiyor. Asıl doğru
olması gereken şey hâlâ repository katmanındaki zorunlu `company_id`
filtresi -- `tests/integration/test_tenant_repository_scoping.py` bunu RLS
tamamen kapalıyken (şema-sahibi bağlantısıyla) doğruluyor, `tests/
integration/test_rls_isolation.py` de RLS'in kendisini `kachow_app` üzerinden.

## ABAC Yetkilendirme Motoru (`app.core.authz`)

Kendi PDP'imiz -- OPA/Casbin gibi harici bir policy engine değil.
`app.ai.policy.schema.Policy`'nin frozen/import-time-doğrulanan dataclass
deseniyle aynı: kurallar `app.core.authz.rules.BUILTIN_RULES` içinde
donmuş bir Python tuple'ı, saf fonksiyon değerlendirici `app.core.authz.
engine.authorize`. Neden harici bir motor değil: repo'nun test altyapısı
neredeyse tamamen mock tabanlı -- DB/ağ bağımlılığı olmayan saf bir
fonksiyon, gerçek Postgres/Redis'e ihtiyaç duymadan tamamen unit-test
edilebiliyor (bkz. `tests/unit/core/authz/test_engine.py`).

**Katmanlar**:

* `attributes.py` -- `Subject`/`Resource`/`Environment` dataclass'ları ve
  `Action` sabitleri (`"document:read"`, `"draft:send"`, ...).
* `rules.py` -- yerleşik rol/eylem kuralları. ROOT sınırsız (`"*"`);
  ADMIN/MANAGER her `Action` için şirket geneli (`scope="any"`); EMPLOYEE
  yalnızca kendi sahip olduğu kaynaklarda (`scope="own"`).
* `engine.py::authorize(subject, action, resource, env, grants)` -- karar
  algoritması: (0) kiracı kapısı, (1) açık `deny` yetkisi kazanır, (2) en
  yüksek `priority`'li `permit` yetkisi, (3) yerleşik kurallar, (4) örtük
  red. `grants` boş bırakılırsa (çoğu router çağrısı böyle yapar) yalnızca
  0/3/4 adımları çalışır -- DB'ye hiç gidilmez.
* `permission_grants` tablosu (`model/permission_grant_model.py` +
  `repository.py`) -- PAP (Policy Administration Point) deposu. Bir yönetici
  bir çalışana rol dışı bir yetki devrettiğinde (örn. `document:delete`,
  yalnızca kendi yüklediği evraklar üzerinde) burada bir satır oluşur.
  `valid_from`/`valid_until` aynı şema üzerinden süreli
  yetki/delegasyon/break-glass'i verir -- ayrı bir tablo yok.
* `cache.py::AuthzDecisionCache` -- Redis epoch-tabanlı karar önbelleği.
  Geçersizleştirme `INCR authz:epoch:{company_id}` ile -- asla `SCAN`/`DEL`
  değil (bkz. modülün kendi docstring'i). Zaman sınırlı (time-boxed) bir
  yetkiye dayanan kararlar hiç önbelleğe alınmaz.
* `service.py::AuthzService` -- önbellek + DB `permission_grants` + saf
  motoru saran async orkestrasyon katmanı. Yalnızca gerçekten
  `permission_grants`'a ihtiyaç duyan tüketiciler bunu kullanır (bugün:
  yetki yönetimi uçları) -- `documents`/`drafts` router'larındaki sahiplik
  kontrolleri saf `engine.authorize`'ı DB'siz çağırır (bkz. aşağıda).
* `dependency.py::require_permission` -- PEP #1, FastAPI dependency
  factory'si. `api/dependency.py::require_roles` artık bu paketin
  `engine.role_permitted`'ine ince bir shim -- davranış değişmedi, tek
  kaynak burada.

**İki tüketim şekli, kasıtlı olarak**:

1. **DB'siz (hot path)** -- `documents/router.py::_authorize_document`,
   `drafts/router.py::_assert_owns_draft`: `engine.authorize`'ı `grants=()`
   ile çağırır. `bypasses_ownership`'in eski davranışını birebir üretir,
   sıfır ek DB/Redis round-trip'i ile. Beş ayrı yerde tekrarlanan
   `if resource.owner_id != current_user.id and not bypasses_ownership(...)`
   deseni tek bir çağrıya indi.
2. **DB destekli** -- `AuthzService` üzerinden, yetki yönetimi uçlarında
   (`POST/GET /users/{id}/permissions`, `DELETE /users/permissions/{id}`).
   Yetki devri sırasında **ayrıcalık yükseltmesi önlenir**: devreden
   (granter) `authz.authorize()` ile kendi kimliğiyle aynı kontrolden
   geçirilir -- sahip olmadığı bir yetkiyi kimseye devredemez.

Gizlilik derecesi (`role_checker.clearance_for`/`assert_clearance`) bu
motora **katılmaz** -- yukarıdaki dört katman listesinin 3. maddesi olarak
ayrı, sıralı bir kapı olarak kalır. Sebep: `app.ai.tools.document_tools`
clearance'ı doğrudan karşılaştırıp modele bir red string'i döndürüyor
(exception fırlatmıyor) ve derlenmiş bir LangGraph node'unun içinden
çağrılıyor -- `app.ai.*`'nin `app.domains.*` import edemeyeceği katman
kuralı gereği oraya DB destekli bir PDP enjekte etmek bu kuralı ihlal
ederdi (bkz. `app.core.authz`'in kendi paket docstring'i).

---

# Test Yapısı

Backend testleri aşağıdaki seviyelerde yazılır.

* Unit Test
* Integration Test
* API Test

Kritik iş kuralları mutlaka test edilmelidir.

---

# Ölçeklenebilirlik

Backend modüler olarak tasarlanmıştır.

Yeni bir özellik eklenirken mevcut domain yapısı korunur.

Yeni iş alanları yeni domain olarak eklenebilir.

Yeni altyapı servisleri Infrastructure katmanına eklenir.

Yeni AI yetenekleri AI Core içerisinde geliştirilir.

Bu yapı mevcut kodu etkilemeden sistemin büyümesini sağlar.

