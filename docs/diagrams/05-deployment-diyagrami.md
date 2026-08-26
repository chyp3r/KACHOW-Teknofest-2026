# Dağıtım (Deployment) Diyagramı

`compose.yml` (geliştirme) ve `compose.prod.yml` (üretim) dosyalarına dayanan gerçek servis topolojisi. Üretimde ayrıca `deploy/kubernetes` altında bir Kubernetes kurulumu bulunur (bkz. [docs/deployment/kubernetes.md](../deployment/kubernetes.md)).

```mermaid
graph TB
    subgraph Client["İstemci Katmanı"]
        Browser["🌐 Tarayıcı<br/>(Kamu Çalışanı)"]
    end

    subgraph DockerHost["Docker Compose / Kubernetes Ortamı"]
        subgraph Web["Web Katmanı"]
            Frontend["frontend<br/>React + Vite"]
        end

        subgraph App["Uygulama Katmanı"]
            Backend["backend<br/>FastAPI + Uvicorn<br/>(app.main:app)"]
            Worker["worker<br/>İndeksleme + Eğitim Kuyruğu"]
        end

        subgraph Data["Veri Katmanı"]
            DB[("db<br/>PostgreSQL<br/>+ Row-Level Security")]
            Redis[("redis<br/>Önbellek + Rate Limit")]
            Qdrant[("qdrant<br/>Vektör Veritabanı")]
        end

        subgraph Obs["Gözlemlenebilirlik"]
            Prometheus["prometheus<br/>Metrik Toplama"]
            Grafana["grafana<br/>Dashboard"]
            Langfuse["langfuse<br/>LLM İzleme"]
            Jaeger["jaeger<br/>Dağıtık İzleme (Tracing)"]
        end
    end

    subgraph External["Harici Servisler"]
        Ollama["Ollama<br/>(yerel LLM sunucusu)<br/>qwen3.5:9b, glm-ocr, nomic-embed-text"]
        Evren["Evren API<br/>(TEKNOFEST bulut model sunucusu)<br/>llm-large, llm-fast, guard, router, bge-m3-embed"]
        Mevzuat["Mevzuat MCP Servisi"]
    end

    Browser -->|HTTPS| Frontend
    Frontend -->|REST + SSE| Backend
    Backend --> DB
    Backend --> Redis
    Backend --> Qdrant
    Backend -.->|LOCAL_MODE=true| Ollama
    Backend -.->|LOCAL_MODE=false| Evren
    Backend -->|MCP protokolü| Mevzuat
    Worker --> DB
    Worker --> Qdrant
    Worker -.-> Ollama
    Worker -.-> Evren

    Backend -.->|/metrics| Prometheus
    Prometheus --> Grafana
    Backend -.->|OTel| Jaeger
    Backend -.->|LLM run kayıtları| Langfuse
```

## Notlar

- **`LOCAL_MODE`** ayarı, backend'in Ollama (yerel) ile Evren (TEKNOFEST'in barındırdığı bulut API) arasında hangi LLM sağlayıcısını kullanacağını belirler; ikisi de `BaseLLMClient` soyutlaması arkasında birbirinin yerine geçebilir.
- **`db`** servisi, çok kiracılı izolasyon için Postgres Row-Level Security (RLS) ile çalışır (`alembic/versions/0013_rls.py` ve sonrasında güçlendirilir).
- **`worker`**, kullanıcı isteğini bloklamayan arka plan işlerini (belge indeksleme, LoRA/DPO eğitim işleri) yürütür.
- Üretim ortamında (`compose.prod.yml` / Kubernetes) aynı servis kümesi, ek sertleştirme (hardening), sır yönetimi (secrets) ve yedekleme/geri yükleme (backup-restore) prosedürleriyle çalışır — ayrıntılar için [docs/deployment/](../deployment/) altındaki ilgili dosyalara bakınız.
