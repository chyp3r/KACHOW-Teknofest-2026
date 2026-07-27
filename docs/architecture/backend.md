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

users/

settings/

system/
```

Her domain kendi içerisinde izole çalışır.

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

Infrastructure katmanı harici servisleri yönetir.

Örnekler

* PostgreSQL
* Redis
* Qdrant
* MinIO
* SMTP
* OpenAI
* Ollama

Bu katman yalnızca istemci bağlantılarından sorumludur.

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

