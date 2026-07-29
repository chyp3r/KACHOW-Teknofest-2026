# KACHOW-Teknofest-2026

---

# Hoş Geldiniz

Bu depo, çok ajanlı yapay zekâ sistemleri geliştirmek amacıyla oluşturulmuş modern bir yazılım platformunun kaynak kodunu, teknik mimarisini ve geliştirme standartlarını içermektedir.

Proje yalnızca çalışan bir uygulama geliştirmeyi değil, sürdürülebilir, okunabilir ve uzun ömürlü bir yazılım ekosistemi oluşturmayı hedeflemektedir.

Kod tabanı uzun vadeli bakım kolaylığı göz önünde bulundurularak tasarlanmıştır ve tüm geliştirmeler ortak mimari prensiplere uygun olarak yürütülmektedir.

---

# Projenin Amacı

Platform;

* Büyük Dil Modelleri (LLM)
* Agentic AI
* Retrieval-Augmented Generation (RAG)
* Model Context Protocol (MCP)
* Çoklu ajan iş akışları
* Modern web teknolojileri

üzerine inşa edilmiş tam kapsamlı bir AI platformudur.

Sistem;

* kullanıcılarla doğal dil üzerinden iletişim kurabilir,
* belgeleri analiz edebilir,
* harici araçları kullanabilir,
* bilgiye erişebilir,
* uzun süren görevleri yönetebilir,
* farklı LLM sağlayıcıları arasında geçiş yapabilir.

---

# Temel Tasarım Hedefleri

Bu proje aşağıdaki hedefler doğrultusunda geliştirilmektedir.

* Ölçeklenebilir mimari
* Modüler geliştirme
* Düşük bağımlılık
* AI First yaklaşımı
* Test edilebilir kod
* Güvenli sistem mimarisi
* Kolay bakım
* AI destekli geliştirme süreçleri

---

# Mimari Genel Bakış

Sistem dört ana katmandan oluşmaktadır.

```text
                Kullanıcı
                    │
                    ▼
              Frontend (React)
                    │
                    ▼
            Backend API (FastAPI)
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    AI Core    Infrastructure  Database
        │
        ▼
LangGraph • MCP • RAG • LLM
```

Katmanlar birbirinden bağımsız geliştirilebilir.

Her katman yalnızca kendi sorumluluğunu yerine getirir.

---

# Repository Yapısı

```text
.
├── backend/
├── frontend/
├── deploy/
├── docs/
├── monitoring/
├── scripts/
├── datasets/
├── evaluation/
├── README.md
├── AGENTS.md
├── CONTRIBUTING.md
└── CHANGELOG.md
```

Repository domain bazlı geliştirme anlayışına göre organize edilmiştir.

---

# Dokümantasyon Haritası

Projeye başlamadan önce aşağıdaki dokümanların okunması önerilir.

## Sistem Mimarisi

```text
docs/architecture/

architecture.md
backend.md
frontend.md
ai.md
rag.md
mcp.md
database.md
deployment.md
```

Bu klasör sistemin nasıl çalıştığını açıklar.

---

## Geliştirme Standartları

```text
docs/development/

project-rules.md
backend-standards.md
frontend-standards.md
naming.md
testing.md
git-workflow.md
ai-workflow.md
```

Bu klasör kod yazım standartlarını içerir.

---

## API Dokümantasyonu

```text
docs/api/
```

REST API'lere ait teknik dokümantasyon burada bulunmaktadır.

---

# Nereden Başlamalıyım?

## Yeni ekip üyesiyim

Okuma sırası

```text
README.md

↓

architecture.md

↓

İlgili architecture dokümanı

↓

İlgili development dokümanı
```

---

## Backend geliştiricisiyim

```text
backend.md

↓

backend-standards.md

↓

git-workflow.md
```

---

## Frontend geliştiricisiyim

```text
frontend.md

↓

frontend-standards.md

↓

git-workflow.md
```

---

## AI geliştiricisiyim

```text
ai.md

↓

ai-workflow.md

↓

rag.md

↓

mcp.md
```

---

## AI ile kod üretiyorum

```text
AGENTS.md

↓

project-rules.md

↓

İlgili architecture dokümanı

↓

İlgili development dokümanı
```

Her AI aracı geliştirmeye başlamadan önce bu sırayı takip etmelidir.

> [!IMPORTANT]
> **CHANGELOG Kuralı**: Yapılan her türlü geliştirme (kod, şablon, veritabanı şeması veya mimari değişiklikler), geliştirme tamamlandığında ana dizindeki `CHANGELOG.md` dosyasına kaydedilmelidir. Diğer ekip üyelerinin ve AI ajanlarının tutarlı takip yapabilmesi için bu kural zorunludur.

---

# Teknoloji Yığını

## Frontend

* React
* TypeScript
* Tailwind CSS
* TanStack Query
* React Router

---

## Backend

* FastAPI
* Python
* SQLAlchemy
* Alembic
* Pydantic

---

## AI

* LangGraph
* LangChain
* Model Context Protocol (MCP)
* OpenAI Compatible API
* Ollama

---

## Veri Katmanı

* PostgreSQL
* Redis
* Qdrant
* MinIO

---

## Gözlemlenebilirlik

* Langfuse
* Prometheus
* Grafana

---

## Platform

* Docker
* Docker Compose
* Kubernetes

---

# Geliştirme Süreci

Her geliştirme aşağıdaki yaşam döngüsünü takip eder.

```text
Issue

↓

Milestone

↓

Branch

↓

Development

↓

Test

↓

Pull Request

↓

Code Review

↓

Merge
```

Bu süreç repository içerisindeki tüm geliştirmeler için geçerlidir.

---

# Ekip Yapısı

Proje dört kişilik bir ekip tarafından geliştirilmektedir.

Her geliştirici belirli bir uzmanlık alanına sahip olsa da ortak kod sahipliği yaklaşımı benimsenmektedir.

Temel sorumluluk alanları;

* Backend Development
* Frontend Development
* AI Engineering
* DevOps & Platform Engineering

Kod sahipliği bireysel değil, ekip seviyesindedir.

---

# Issue Yönetimi

Tüm geliştirmeler GitHub Issues üzerinden planlanır.

Her Issue aşağıdaki bilgileri içermelidir.

* Problem tanımı
* Amaç
* Beklenen çıktı
* Kabul kriterleri
* İlgili Milestone

Issue oluşturulmadan geliştirmeye başlanmamalıdır.

---

# Milestone Yönetimi

Issue'lar proje hedeflerine göre Milestone altında gruplanır.

Örnek Milestone'lar

* Project Setup
* Backend
* Frontend
* AI Core
* RAG
* MCP
* Authentication
* Testing
* Deployment
* Demo
* Release

Milestone'lar ilerleme takibi amacıyla kullanılmaktadır.

---

# Branch Stratejisi

Ana branch'ler

```text
main

develop
```

Feature branch örnekleri

```text
feature/chat

feature/rag

feature/mcp

feature/auth

feature/dashboard

feature/documents
```

Diğer branch türleri

```text
fix/

refactor/

docs/

test/

ci/

hotfix/
```

Hiçbir geliştirme doğrudan **main** branch'i üzerinde yapılmaz.

---

# Commit Standardı

Repository Conventional Commits standardını kullanmaktadır.

Örnekler

```text
feat(chat): sohbet sistemi eklendi

feat(rag): hibrit retrieval geliştirildi

fix(auth): token yenileme problemi düzeltildi

refactor(ai): workflow sadeleştirildi

docs(readme): mimari güncellendi

test(chat): servis testleri eklendi

ci(docker): compose dosyası güncellendi

chore(deps): bağımlılıklar güncellendi
```

Her commit yalnızca tek bir mantıksal değişikliği içermelidir.

---

# Pull Request Süreci

Tüm geliştirmeler Pull Request üzerinden birleştirilir.

Bir Pull Request;

* tek bir amacı kapsamalıdır,
* ilgili Issue ile ilişkilendirilmelidir,
* açıklayıcı bir özet içermelidir,
* gerekli testleri geçmiş olmalıdır,
* dokümantasyonu güncellemelidir.

Code Review tamamlanmadan birleştirme yapılmaz.

---

# Kod Kalitesi

Kod tabanı aşağıdaki prensiplere göre geliştirilmektedir.

* SOLID
* Clean Code
* Clean Architecture
* Domain Driven Design
* Single Responsibility
* Low Coupling
* High Cohesion

Her yeni özellik mevcut mimariyi koruyacak şekilde geliştirilmelidir.

---

# Test Politikası

Her geliştirme uygun testlerle birlikte sunulmalıdır.

Desteklenen test seviyeleri

* Unit Test
* Integration Test
* API Test
* End-to-End Test

Kod incelemelerinde test kapsamı değerlendirilmektedir.

---

# Gözlemlenebilirlik

Üretim ortamında aşağıdaki metrikler izlenmektedir.

* API çağrıları
* Workflow adımları
* LLM kullanımı
* Token tüketimi
* Tool çağrıları
* Performans
* Hata kayıtları

Bu bilgiler sistem davranışını analiz etmek amacıyla kullanılmaktadır.

---

# Güvenlik

Tüm geliştirmeler aşağıdaki prensiplere uygun olmalıdır.

* Authentication
* Authorization
* Least Privilege
* Secret Management
* Input Validation
* Audit Logging

Hiçbir gizli bilgi kaynak koduna eklenmemelidir.

---

# AI Destekli Geliştirme

Kod üreten tüm AI araçları aşağıdaki dokümanları referans almalıdır.

```text
AGENTS.md

↓

project-rules.md

↓

İlgili architecture dokümanı

↓

İlgili development dokümanı
```

Bu süreç proje genelinde üretilen kodların tutarlı olmasını sağlar.

---

# Katkı Sağlama

Katkı süreci, kod standartları ve geliştirme akışı hakkında ayrıntılı bilgi için aşağıdaki dokümanlara başvurulmalıdır.

```text
CONTRIBUTING.md

docs/development/project-rules.md
```

---

# Lisans

Bu proje ilgili lisans koşulları kapsamında geliştirilmektedir.
