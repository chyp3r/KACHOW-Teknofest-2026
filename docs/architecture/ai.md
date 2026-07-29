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

# Workflow

Workflow sistemin giriş noktasıdır.

Workflow;

* isteği analiz eder
* gerekli agent'i belirler
* araç kullanımına karar verir
* işlem sırasını oluşturur
* sonucu toplar

Workflow doğrudan LLM çağırmaz.

---

# Agent

Agent, belirli bir görevi yerine getiren karar birimidir. Tüm uzman ajanlar, sistemin ortak davranışlarını belirleyen **BaseAgent** sınıfından türetilmiştir.

### Ajan Mimari Yapısı (BaseAgent)
`app/ai/agents/base.py` altında yer alan BaseAgent sınıfı şu SOTA özellikleri barındırır:
* **Unified Messaging**: Tek bir prompt veya konuşma geçmişi (mesaj listesi) ile çalışabilme.
* **Dinamik Prompting**: Sistem promptunun çalışma anında bağlama (context) göre dinamik olarak biçimlendirilmesi.
* **Post-Validation / Guardrails**: Çıktıların doğrulanması ve denetlenmesi için özelleştirilebilir validator desteği.
* **Self-Correction**: Pydantic model doğrulaması başarısız olduğunda otomatik hata geri-bildirimi ile kendini düzeltme döngüsü.

### Uzman Ajanlar
Sistemdeki tüm uzman ajanlar `app/ai/agents/` altında konumlandırılmıştır:
* **OrchestratorAgent** (`orchestrator.py`): İş akışlarını planlar, adımları belirler ve görevleri dağıtır.
* **NERAgent** (`ner.py`): Metinden varlık isimlerini (kişi, kurum, tarih vb.) çıkarır.
* **ClassifierAgent** (`classifier.py`): Girdileri kategorize eder, sınıflandırır ve duygu analizi yapar.
* **MetadataAgent** (`metadata.py`): Belgelerin meta verilerini ve anahtar kelimelerini ayıklar.
* **WriterAgent** (`writer.py`): Yüksek kaliteli rapor, özet ve makale taslakları yazar.
* **EditorAgent** (`editor.py`): Yazılan içeriklerin dil bilgisi, akış ve üslup düzeltmelerini yapar.
* **VerifierAgent** (`verifier.py`): Çıktıların doğruluk, güvenlik ve guardrail kontrollerini üstlenir.
* **RouterAgent** (`router.py`): İsteği en uygun ajana veya iş akışına yönlendirir.

Her agent yalnızca kendi görevinden sorumludur.

---

# Planner

Planner kullanıcının isteğini analiz eder.

Görevleri

* amacı belirlemek
* gerekli araçları seçmek
* işlem sırasını oluşturmak
* gereksiz işlemleri engellemek

Planner sistemin karar mekanizmasıdır.

---

# LLM Katmanı

LLM katmanı farklı model sağlayıcılarını tek bir arayüz altında toplar.

Uygulanan mimari yapıda aşağıdaki bileşenler yer almaktadır:
* **BaseLLMClient** (`app/ai/llms/base.py`): Tüm sağlayıcı istemcilerinin uygulaması gereken soyut taban sınıf. `generate`, `stream` ve `generate_structured` metotlarını içerir.
* **OllamaClient** (`app/ai/llms/ollama.py`): Yerel Ollama servisiyle (`ChatOllama` üzerinden) entegrasyonu sağlar. Qwen gibi yerel modelleri çalıştırır.
* **get_llm_client** (`app/ai/llms/__init__.py`): İstenen sağlayıcıya ve parametrelere göre doğru istemciyi döndüren fabrika fonksiyonu.

Örnek sağlayıcılar:
* OpenAI
* Ollama (Aktif)
* Anthropic
* Google
* OpenRouter

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
- **Singleton Yapısı**: `prompt_manager` adıyla dışa aktarılan tekil örnek, tüm uygulama genelinde tutarlı prompt yönetimi sağlar.

### Prompt Şablonları (`prompts/templates/`)
Her uzman ajanın ve akışın sistem yönergesi ilgili markdown dosyasında saklanır:
- `orchestrator.md`: Orkestrasyon ajanı yönergeleri (Türkçe).
- `ner.md`: Varlık ismi tanıma ajanı yönergeleri (Türkçe).
- `classifier.md`: Sınıflandırma ajanı yönergeleri (Türkçe).
- `metadata.md`: Metadata çıkarma ajanı yönergeleri (Türkçe).
- `writer.md`: Yazar ajanı yönergeleri (Türkçe).
- `editor.md`: Editör ajanı yönergeleri (Türkçe).
- `verifier.md`: Doğrulama ajanı yönergeleri (Türkçe).
- `router.md`: Yönlendirme ajanı yönergeleri (Türkçe).
- `chat.md`: Sohbet sistemi yönergeleri (Türkçe).

Bu sayede promptlar:
* kolayca sürümlenebilir
* kod değişikliği gerektirmeden güncellenebilir
* test edilebilir

---

# Tool Calling

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

Memory, sistemin geçmiş konuşmaları ve oturum bazlı bilgileri yönetmesini sağlar. Projede SOTA düzeyinde modüler üç farklı hafıza stratejisi sunulmuştur:

### 1. Kısa Süreli Hafıza (ConversationWindowMemory)
`app/ai/memory/conversation.py` altında yer alır:
- Redis önbellek katmanı üzerinde oturum bazlı çalışır.
- Belirlenen pencere boyutuna (`window_size`) göre sadece en son `N` adet sohbet turnünü (mesajını) saklar. LLM bağlam penceresini (context window) gereksiz geçmişle şişirmemek için otomatik kırpma yapar.

### 2. Özet Tabanlı Hafıza (SummaryMemory)
`app/ai/memory/summary.py` altında yer alır:
- Sohbet geçmişi belirli bir sınıra (`summary_threshold`) ulaştığında, asenkron olarak arka planda LLM çağrısı yaparak tüm eski konuşmayı tek bir paragraflık Türkçe özete sıkıştırır.
- Bir sonraki adımda ajana bağlam olarak `Geçmiş Sohbet Özeti + Son K adet Ham Mesaj` yapısını sunarak verimli bir uzun dönem hafıza sağlar.

### 3. Anlamsal Hafıza / Mem0-like Episodic Memory (VectorMemory)
`app/ai/memory/vector_memory.py` altında yer alır:
- **Custom Mem0** mantığıyla çalışır. Her konuşma turnünde kullanıcının kendisi hakkında doğrudan veya dolaylı olarak verdiği kişisel olguları, tercihleri, ilgileri ve projeleri (`MetadataAgent` veya LLM yardımıyla) Türkçe maddeler halinde çıkarır.
- Çıkarılan her bir bağımsız olguyu (`episodic_fact`) `EmbeddingService` üzerinden vektörleyerek Qdrant'ta `user_episodic_memory` koleksiyonunda saklar.
- Yeni bir istek geldiğinde, kullanıcının güncel sorusuyla en alakalı eski olguları vektör benzerlik araması ile bulur ve prompta enjekte eder (örn: "Kullanıcı Python dilini tercih ediyor", "Kullanıcının projesinin adı KACHOW").

Bu sayede hafıza katmanı:
- Oturum sınırlarını korur.
- LLM bağlam limitlerini verimli yönetir.
- Kullanıcıya ait kişisel tercihleri asla unutmayan akıllı bir kişiselleştirilmiş hafıza sunar.

---

# RAG

RAG süreci aşağıdaki adımlardan oluşmaktadır.

```text
Soru

↓

Query Processing

↓

Embedding

↓

Vector Search

↓

Ranking

↓

Context Builder

↓

LLM

↓

Cevap
```

LLM yalnızca ilgili bağlam ile çalışır.

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

* Prompt Injection koruması
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




