# Sekans (Sequence) Diyagramları

## 1. Kullanıcı Giriş (Login) Sekansı

```mermaid
sequenceDiagram
    participant U as Kullanıcı
    participant A as API (Auth)
    participant DB as Postgres
    U->>A: POST /auth/login
    A->>DB: Kullanıcı Doğrula
    DB-->>A: OK (Hash Eşleşti)
    A-->>U: 200 OK + JWT Token
```

## 2. Evrak Yükleme ve Analiz Sekansı

```mermaid
sequenceDiagram
    participant F as Frontend
    participant A as API
    participant W as Worker
    F->>A: POST /documents/analyze (PDF)
    A->>W: İş Emri
    W-->>A: Analiz Kimliği (ID)
    A-->>F: 202 Accepted + ID
    F->>A: GET /documents/{id} (Polling)
    A-->>F: Analiz Sonucu (JSON)
```

## 3. LangGraph Orkestrasyon Sekansı

```mermaid
sequenceDiagram
    participant Router
    participant Orchestrator
    participant Node
    Router->>Orchestrator: State Başlat
    Orchestrator->>Node: İşlemi Çalıştır
    Node-->>Orchestrator: State Güncellemesi
    Orchestrator-->>Router: Nihai Sonuç
```

## 4. Mevzuat MCP Arama Sekansı

```mermaid
sequenceDiagram
    participant Agent
    participant MCP
    participant MevzuatGovTr
    Agent->>MCP: call_tool(search, query)
    MCP->>MevzuatGovTr: HTTP GET (Playwright)
    MevzuatGovTr-->>MCP: HTML Response
    MCP-->>Agent: Parsed Markdown
```

## 5. HITL (Human in the Loop) Sekansı

```mermaid
sequenceDiagram
    participant Agent
    participant API
    participant User
    Agent->>API: forces_approval=True
    API->>User: İnsan Onayı Bekleniyor
    User-->>API: Onay/Revizyon
    API-->>Agent: Resume State
```

## 6. LLM Judge (Güvenlik) Sekansı

```mermaid
sequenceDiagram
    participant Writer
    participant Guardrail
    participant Output
    Writer->>Guardrail: Üretilen Metin
    Guardrail->>Guardrail: PII/Injection Kontrolü
    Guardrail-->>Output: Pass / Block
```

## 7. Vektör Arama (RAG) Sekansı

```mermaid
sequenceDiagram
    participant Agent
    participant Qdrant
    Agent->>Qdrant: Dense + BM25 Query
    Qdrant-->>Agent: Top-K Sonuç (Skorlar)
```

## 8. Veritabanı Şema Göçü (Migration) Sekansı

```mermaid
sequenceDiagram
    participant K8s as Kubernetes Job
    participant Alembic
    participant DB as Postgres
    K8s->>Alembic: alembic upgrade head
    Alembic->>DB: DDL Çalıştır
    DB-->>Alembic: OK
    Alembic-->>K8s: Job Complete
```

## 9. Frontend SSE (Server-Sent Events) Sekansı

```mermaid
sequenceDiagram
    participant Browser
    participant API
    Browser->>API: GET /stream
    API-->>Browser: Event: start
    API-->>Browser: Event: progress
    API-->>Browser: Event: end
```

## 10. Token Yenileme (Refresh) Sekansı

```mermaid
sequenceDiagram
    participant App
    participant API
    App->>API: POST /auth/refresh (Refresh Token)
    API-->>App: Yeni Access Token
```

