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
   repository.DocumentRepository`'nin kendi docstring'i). Postgres Row-Level
   Security ile ikinci savunma hattı sonraki bir fazda eklenecektir.
2. **Sahiplik/rol** -- `app.core.permissions.role_checker.bypasses_ownership`:
   ADMIN/MANAGER/ROOT bir kaynağı sahibi olmasalar bile görebilir, ama
   yalnızca **kendi şirketleri içinde** (kiracı kapsamı asla atlanmaz).
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
docstring'i).

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

