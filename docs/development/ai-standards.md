# AI Standards

> Bu doküman AI katmanının geliştirme standartlarını tanımlar.

AI katmanında geliştirilen tüm modüller bu kurallara uygun olmalıdır.

Bu doküman yalnızca AI Core katmanını kapsar.

---

# Amaç

Bu dokümanın amacı;

* AI mimarisini tutarlı tutmak
* Agent geliştirme standartlarını belirlemek
* Workflow yönetimini standartlaştırmak
* Tool kullanımını güvenli hale getirmek
* Yeni AI bileşenlerinin sisteme kolayca eklenmesini sağlamaktır.

---

# AI Felsefesi

AI Core sistemin karar verme katmanıdır.

AI;

* görevleri planlar,
* araçları seçer,
* bilgi toplar,
* muhakeme yürütür,
* cevap üretir,
* workflow yönetir.

AI;

* HTTP isteği yönetmez,
* kullanıcı arayüzü oluşturmaz,
* veritabanına doğrudan erişmez,
* framework bağımlı iş mantığı içermez.

---

# Mimari

AI Core katmanları aşağıdaki yapıyı takip eder.

```text
Request

↓

Workflow

↓

Planner

↓

Agent

↓

Tool Selection

↓

Tool Execution

↓

Memory

↓

Response
```

Her katman yalnızca kendi sorumluluğunu yerine getirir.

---

# AI Modülleri

AI Core aşağıdaki temel modüllerden oluşur.

```text
llm_clients/

workflows/

agents/

tools/

memory/

prompts/

embeddings/

rag/

mcp/

evaluation/
```

Her modül bağımsız geliştirilebilir olmalıdır.

---

# Workflow

Workflow sistemin orkestrasyon katmanıdır.

Workflow;

* görevi planlar,
* Agent seçer,
* Tool çağırır,
* Memory kullanır,
* hata yönetir,
* sonucu döndürür.

Workflow;

* Prompt yazmaz,
* HTTP işlemez,
* kullanıcı arayüzü yönetmez.

---

# Agent

Her Agent tek bir uzmanlık alanına sahip olmalıdır.

Örnekler

```text
ChatAgent

RAGAgent

PlanningAgent

SystemAgent

CodingAgent

DocumentAgent
```

Bir Agent birden fazla görevi üstlenmemelidir.

---

# Planner

Planner görevin nasıl çözüleceğine karar verir.

Planner;

* adımları oluşturur,
* gerekli Agent'ları belirler,
* Tool ihtiyacını değerlendirir,
* yürütme sırasını oluşturur.

Planner doğrudan Tool çalıştırmaz.

---

# Tool

Her Tool yalnızca tek bir yetenek sunmalıdır.

Örnekler

* Dosya okuma
* Dosya yazma
* Web arama
* Terminal çalıştırma
* Hesaplama
* Kod çalıştırma

Tool'lar birbirini çağırmamalıdır.

Tool içerisinde AI çağrısı yapılmamalıdır.

---

# MCP

Harici sistemlerle iletişim mümkün olduğunca MCP üzerinden gerçekleştirilmelidir.

MCP;

* Tool erişimini standartlaştırır,
* entegrasyonları sadeleştirir,
* AI ile sistem arasındaki bağı azaltır.

MCP katmanı iş kuralları içermez.

---

# RAG

RAG yalnızca bilgi erişiminden sorumludur.

RAG;

* belge bulur,
* sıralama yapar,
* ilgili içerikleri döndürür.

RAG cevap üretmez.

RAG karar vermez.

---

# Embeddings

Embedding üretimi merkezi olarak yönetilmelidir.

Embedding modeli farklı modüller tarafından tekrar oluşturulmamalıdır.

Chunking ve embedding stratejileri standartlaştırılmalıdır.

---

# Memory

Memory sistemin geçmiş bilgisini yönetir.

Memory;

* kısa süreli,
* uzun süreli,
* oturum bazlı

olarak ayrılmalıdır.

Memory katmanı kullanıcı arayüzünü bilmez.

---

# Prompt Yönetimi

Prompt'lar merkezi olarak yönetilmelidir.

Prompt metinleri kod içerisine gömülmemelidir.

Her Prompt;

* isimlendirilmeli,
* sürümlenmeli,
* tekrar kullanılabilir olmalıdır.

---

# LLM Clients

LLM sağlayıcıları ortak bir arayüz üzerinden kullanılmalıdır.

AI katmanı belirli bir sağlayıcıya bağımlı olmamalıdır.

Sağlayıcı değişikliği diğer modülleri etkilememelidir.

---

# Model Bağımsızlığı

AI sistemi;

* OpenAI
* Ollama
* Anthropic
* Gemini
* Azure OpenAI

gibi farklı sağlayıcılarla çalışabilecek şekilde tasarlanmalıdır.

Model değişimi Workflow değişikliği gerektirmemelidir.

---

# Tool Çağrıları

Tool çağrıları deterministik olmalıdır.

Aynı giriş mümkün olduğunca aynı davranışı üretmelidir.

Tool çağrıları kayıt altına alınmalıdır.

---

# Context Yönetimi

Workflow yalnızca gerekli bağlamı modele göndermelidir.

Gereksiz bilgi modele aktarılmamalıdır.

Context mümkün olduğunca küçük tutulmalıdır.

---

# Token Yönetimi

Token kullanımı optimize edilmelidir.

Dikkat edilmesi gerekenler

* Gereksiz Prompt büyümesi
* Tekrarlayan bilgiler
* Kullanılmayan belge parçaları
* Gereksiz geçmiş konuşmalar

---

# Guardrails

AI çıktıları gerekli durumlarda doğrulanmalıdır.

Örnekler

* JSON doğrulama
* Şema doğrulama
* Format doğrulama
* Güvenlik kontrolü

Model çıktısına koşulsuz güvenilmez.

---

# Hata Yönetimi

Model hataları kontrollü şekilde yönetilmelidir.

Beklenen durumlar

* Timeout
* Rate Limit
* Tool Error
* MCP Error
* Context Overflow
* Invalid Response

Workflow mümkün olduğunca kurtarma stratejisi uygulamalıdır.

---

# Retry Politikası

Retry yalnızca güvenli işlemlerde uygulanmalıdır.

Sonsuz tekrar yapılmamalıdır.

Retry sayısı yapılandırılabilir olmalıdır.

---

# Gözlemlenebilirlik

AI işlemleri izlenebilir olmalıdır.

Takip edilmesi önerilen bilgiler

* Workflow
* Agent
* Tool
* Prompt
* Model
* Süre
* Token
* Hata

---

# Güvenlik

AI;

* gizli bilgilere doğrudan erişmemelidir,
* yetkisiz Tool çalıştırmamalıdır,
* kullanıcı girdilerine koşulsuz güvenmemelidir.

Her Tool gerekli yetki kontrolünü yapmalıdır.

---

# Performans

Performans artırılırken doğruluk korunmalıdır.

Dikkat edilmesi gerekenler

* Context küçültme
* Cache kullanımı
* Embedding yeniden kullanımı
* Gereksiz LLM çağrılarından kaçınma
* Paralel bağımsız işlemler

---

# Değerlendirme

Yeni Agent veya Workflow aşağıdaki kriterlerle değerlendirilmelidir.

* Doğruluk
* Tutarlılık
* Tekrarlanabilirlik
* Gecikme süresi
* Token tüketimi
* Tool başarısı

Değerlendirme sonuçları kayıt altına alınmalıdır.

---

# Test

AI katmanı aşağıdaki seviyelerde test edilmelidir.

* Unit Test
* Workflow Test
* Tool Test
* Prompt Test
* Evaluation Test

Mümkün olduğunca deterministik senaryolar tercih edilmelidir.

---

# Yeni AI Özelliği Geliştirme

Yeni bir AI özelliği geliştirilirken aşağıdaki süreç takip edilmelidir.

```text
Issue

↓

Workflow Tasarımı

↓

Agent Tasarımı

↓

Prompt

↓

Tool

↓

Memory

↓

Evaluation

↓

Test

↓

Documentation

↓

Pull Request
```

---

# Yapılmaması Gerekenler

AI katmanında;

* HTTP endpoint yazılmaz.
* React bileşeni geliştirilmez.
* SQL sorgusu yazılmaz.
* ORM kullanılmaz.
* Veritabanı erişimi doğrudan yapılmaz.
* HTML oluşturulmaz.
* API yönlendirmesi yapılmaz.

Bu sorumluluklar ilgili katmanlara aittir.

