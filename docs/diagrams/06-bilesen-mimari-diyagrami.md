# Bileşen / Mimari Diyagramı

Backend, alan-odaklı (domain-driven) bir yapı ile yapay zeka mantığını ayrıştırır: `app/domains/` iş kurallarını ve HTTP yüzeyini taşır, `app/ai/` ise hiçbir domain'e bağımlı olmayan, tamamen yeniden kullanılabilir bir ajan/LLM katmanıdır.

```mermaid
graph TB
    subgraph FE["Frontend (React + Vite)"]
        UI["Sayfalar / Bileşenler"]
        SSEClient["SSE İstemcisi<br/>(canlı ilerleme akışı)"]
    end

    subgraph API["app/api/"]
        Router["Ana Router"]
        Middleware["Middleware<br/>(auth, request_id, rate limit)"]
        Exceptions["Global Exception Handler'lar"]
    end

    subgraph Domains["app/domains/ (DDD katmanı)"]
        Documents["documents<br/>model / repository / service / router"]
        Drafts["drafts"]
        Routing["routing"]
        Units["units"]
        Companies["companies"]
        Chat["chat"]
        Auth["auth"]
        Diger["... (transfers, audit, quotas,<br/>feedback, notifications, vb.)"]
    end

    subgraph AI["app/ai/ (domain-bağımsız ajan katmanı)"]
        Agents["agents/<br/>classifier, writer, reviser,<br/>router, judge"]
        Workflows["workflows/<br/>LangGraph StateGraph'lar:<br/>document_analysis, draft,<br/>routing, revise, planning"]
        Compliance["compliance/<br/>alan çıkarımı, eksik alan kontrolü"]
        Verification["verification/<br/>doğrulama, missing_info, llm_judge"]
        Retrieval["retrieval/<br/>BM25 + dense hybrid, mevzuat"]
        Guardrails["guardrails/<br/>PII, prompt-injection, hassasiyet"]
        Prompts["prompts/<br/>Türkçe prompt şablonları (.md)"]
        Llms["llms/<br/>BaseLLMClient soyutlaması"]
    end

    subgraph Infra["app/infrastructure/"]
        Extractors["extractors/<br/>OCR / PDF çıkarımı"]
        Providers["providers/<br/>Ollama, Evren"]
        Storage["storage/<br/>local, S3"]
        VectorStore["vectorstore/<br/>Qdrant"]
        Cache["cache/<br/>Redis"]
        Checkpoint["checkpointing/<br/>Postgres (LangGraph HITL)"]
        DBLayer["database/<br/>SQLAlchemy + RLS"]
    end

    subgraph MCP["app/mcp/"]
        MCPClient["Mevzuat MCP İstemcisi"]
    end

    subgraph Obs["app/observability/"]
        Metrics["Prometheus metrikleri"]
        Tracer["OTel tracer"]
    end

    UI --> SSEClient
    SSEClient -->|REST + SSE| Router
    Router --> Middleware --> Domains
    Router --> Exceptions

    Documents --> Workflows
    Drafts --> Workflows
    Routing --> Workflows
    Chat --> Workflows

    Workflows --> Agents
    Workflows --> Compliance
    Workflows --> Verification
    Workflows --> Retrieval
    Workflows --> Guardrails
    Agents --> Prompts
    Agents --> Llms

    Llms --> Providers
    Documents --> Extractors
    Retrieval --> VectorStore
    Retrieval --> MCPClient
    Documents --> Storage
    Domains --> DBLayer
    Workflows --> Checkpoint
    Domains --> Cache

    Domains --> Metrics
    Workflows --> Tracer
```

## Notlar

- **`app/ai/`**, hiçbir yerde `app.domains` içe aktarmaz — bu, ajan/LLM mantığının domain'lerden bağımsız, test edilebilir ve yeniden kullanılabilir kalmasını sağlayan bilinçli bir mimari sınırdır.
- **`app/domains/*/router.py`** dosyaları HTTP yüzeyidir (FastAPI); asıl iş mantığı `service.py`'de, veri erişimi `repository.py`'de, ORM modeli `model/`'de yaşar — her domain aynı 4 katmanlı deseni tekrarlar.
- **LangGraph workflow'ları** (`app/ai/workflows/`), agent'ları (`app/ai/agents/`) düğüm (node) olarak kullanan yönlendirilmiş çizgeler (DAG); her düğüm zaman aşımı/yeniden deneme politikasına ve SSE olay yayınına sahiptir.
- Frontend, backend ile yalnızca REST + Server-Sent Events (SSE) üzerinden konuşur; WebSocket kullanılmaz.
