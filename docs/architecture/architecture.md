# Sistem Mimarisi

## Amaç

Bu doküman projenin genel sistem mimarisini açıklamaktadır.

Amacı, projeye yeni katılan geliştiricilerin, yapay zekâ ajanlarının ve teknik değerlendiricilerin sistemin genel yapısını kısa sürede anlayabilmesini sağlamaktır.

Bu doküman yalnızca yüksek seviyeli (high-level) mimariyi açıklar. Backend, Frontend, AI ve diğer alt sistemlerin teknik detayları ilgili mimari dokümanlarında anlatılmaktadır.

---

# Proje Genel Bakış

Bu proje, yapay zekâ destekli ajanların kullanıcılarla doğal dil üzerinden etkileşim kurabildiği, bilgiye erişebildiği, belge analizi yapabildiği ve sistem araçlarını güvenli şekilde kullanabildiği modüler bir platformdur.

Sistem;

* Modern web teknolojileri
* Büyük Dil Modelleri (LLM)
* Retrieval-Augmented Generation (RAG)
* Model Context Protocol (MCP)
* Çoklu ajan mimarisi
* Olay tabanlı iş akışları

üzerine inşa edilmiştir.

---

# Mimari Yaklaşım

Proje aşağıdaki mimari prensiplere göre geliştirilmektedir.

* Modular Monolith
* Domain Driven Design (DDD)
* SOLID
* Clean Architecture
* Repository Pattern
* Dependency Injection
* AI First Development

Her katmanın tek bir sorumluluğu bulunmaktadır.

İş mantığı, kullanıcı arayüzü, yapay zekâ ve altyapı birbirinden ayrılmıştır.

---

# Sistem Bileşenleri

Sistem dört ana bileşenden oluşmaktadır.

* Frontend
* Backend
* AI Core
* Infrastructure

Her bileşen bağımsız geliştirilmekte ancak ortak bir mimari altında birlikte çalışmaktadır.

---

# Genel Sistem Akışı

Kullanıcı isteği sistem içerisinde aşağıdaki sırayla ilerler.

```text
Kullanıcı
        │
        ▼
Frontend
        │
        ▼
REST API
        │
        ▼
Backend
        │
        ▼
AI Core
        │
        ▼
LLM / MCP / RAG
        │
        ▼
Backend
        │
        ▼
Frontend
        │
        ▼
Kullanıcı
```

Bu akış sistemin temel veri dolaşımını temsil eder.

---

# Frontend

Frontend, kullanıcı ile sistem arasındaki etkileşim katmanıdır.

Başlıca sorumlulukları;

* Kullanıcı arayüzünü sunmak
* API isteklerini göndermek
* Sohbet deneyimini yönetmek
* Dosya yüklemek
* Sistem durumunu göstermek
* Gerçek zamanlı güncellemeleri göstermek

Frontend iş mantığı içermez.

Tüm iş kuralları Backend tarafından yönetilir.

Frontend mimarisinin detayları

```
docs/architecture/frontend.md
```

dokümanında açıklanmaktadır.

---

# Backend

Backend sistemin merkezidir.

Başlıca görevleri;

* API yönetimi
* Kimlik doğrulama
* İş kurallarını çalıştırma
* Veri erişimi
* AI sistemini yönetme
* Arka plan görevlerini yürütme
* Harici servislerle iletişim kurma

Backend modüler bir yapı kullanmaktadır.

Backend mimarisi

```
docs/architecture/backend.md
```

dokümanında açıklanmaktadır.

---

# AI Core

AI Core, sistemin karar verme katmanıdır.

Bu katman;

* LLM yönetimi
* Prompt yönetimi
* Agent yönetimi
* LangGraph iş akışları
* Tool Calling
* RAG
* Memory
* Planlama

gibi yapay zekâ ile ilgili tüm işlemleri yürütmektedir.

AI katmanı web frameworklerinden bağımsız geliştirilmektedir.

Detaylı açıklamalar

```
docs/architecture/ai.md
```

dokümanında bulunmaktadır.

---

# Infrastructure

Infrastructure katmanı sistemin dış servislerle iletişim kurmasını sağlar.

Örnek bileşenler

* PostgreSQL
* Redis
* Qdrant
* MinIO
* LLM Provider'ları
* Log servisleri

Bu katman yalnızca bağlantı ve entegrasyonlardan sorumludur.

İş kuralları Infrastructure içerisinde bulunmaz.

---

# Veri Akışı

Bir kullanıcı isteği aşağıdaki aşamalardan geçmektedir.

1. Kullanıcı Frontend üzerinden isteği başlatır.
2. Frontend isteği Backend API'ye gönderir.
3. Backend isteği doğrular.
4. Gerekli iş kuralları uygulanır.
5. AI gerekiyorsa AI Core devreye girer.
6. AI gerekli araçları kullanır.
7. Sonuç Backend'e döner.
8. Backend cevabı Frontend'e iletir.
9. Frontend sonucu kullanıcıya gösterir.

---

# AI Destekli İş Akışı

AI gerektiren işlemlerde aşağıdaki süreç uygulanmaktadır.

```text
İstek
      │
      ▼
Workflow
      │
      ▼
Planner
      │
      ▼
Tool Seçimi
      │
      ▼
RAG / MCP / LLM
      │
      ▼
Sonuç
```

Her AI isteği belirli bir iş akışı üzerinden yürütülmektedir.

---

# Katmanlar Arası Bağımlılık

Sistem tek yönlü bağımlılık prensibini kullanmaktadır.

```text
Frontend
      │
      ▼
API
      │
      ▼
Domain
      │
      ▼
Repository
      │
      ▼
Infrastructure
```

AI katmanı bu akıştan bağımsız olarak çalışmaktadır.

Katmanlar yukarı doğru bağımlılık oluşturamaz.

---

# Teknoloji Yığını

Proje modern ve modüler teknolojiler üzerine kurulmuştur.

## Frontend

* React
* TypeScript
* Tailwind CSS
* TanStack Query
* React Router

## Backend

* FastAPI
* Python
* SQLAlchemy
* Pydantic
* Alembic

## AI

* LangGraph
* LangChain
* OpenAI Compatible API
* Ollama
* MCP

## Veri

* PostgreSQL
* Redis
* Qdrant
* MinIO

## Gözlemlenebilirlik

* Langfuse
* Prometheus
* Grafana

## Altyapı

* Docker
* Docker Compose
* Kubernetes

---

# Tasarım İlkeleri

Sistem geliştirilirken aşağıdaki prensipler esas alınmaktadır.

* Modülerlik
* Düşük bağımlılık
* Yüksek uyumluluk
* Test edilebilirlik
* Ölçeklenebilirlik
* Güvenlik
* Gözlemlenebilirlik
* Sürdürülebilirlik

Bu prensipler proje boyunca tüm geliştirmelerde korunmalıdır.
