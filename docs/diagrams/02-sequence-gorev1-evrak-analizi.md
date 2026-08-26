# Görev 1 Sıra Diyagramı — Evrak Sınıflandırma ve İçerik Analizi

Bir evrak yüklendiğinde `DocumentService.analyze_document` çağrılır, metin çıkarma zincirinden geçer ve `document_analysis_graph` (LangGraph) üzerinde sınıflandırma → alan çıkarımı → uyum kontrolü → mevzuat önerisi → hassasiyet taraması adımları sırayla/paralel çalışır. Her düğüm SSE üzerinden ilerleme olayı yayınlar.

```mermaid
sequenceDiagram
    actor Memur as Kamu Çalışanı
    participant FE as Frontend (React)
    participant API as FastAPI<br/>documents/router.py
    participant Svc as DocumentService<br/>analyze_document()
    participant Ext as Extractor Zinciri<br/>pdfium → tesseract → vision-LLM
    participant Graph as document_analysis_graph<br/>(LangGraph)
    participant Ret as Hybrid Retriever<br/>(BM25 + dense)
    participant MCP as Mevzuat Servisi (MCP)
    participant DB as PostgreSQL
    participant VDB as Qdrant

    Memur->>FE: Evrakı yükle (PDF/görüntü)
    FE->>API: POST /documents (multipart upload)
    API->>Svc: analyze_document(file)
    Svc->>Ext: Metin çıkar
    alt PDF metin katmanı yeterli
        Ext-->>Svc: Doğrudan metin
    else Taranmış / metin katmanı yetersiz
        Ext->>Ext: Tesseract OCR dene
        opt OCR de yetersizse
            Ext->>Ext: Vision-LLM (glm-ocr) ile oku
        end
        Ext-->>Svc: OCR ile çıkarılan metin (is_ocr_text=true)
    end

    Svc->>Graph: _run_analysis(text, is_ocr_text)
    activate Graph
    Graph->>Graph: analyze_node — tür + alan + özet<br/>(3 kademeli degradasyon)
    Graph-->>FE: SSE: "Evrak sınıflandırılıyor..."
    Graph->>Graph: check_compliance_node — eksik alan kontrolü<br/>(kural tabanlı, LLM'siz)
    Graph->>Ret: retrieve_mevzuat_node
    Ret->>MCP: İlgili mevzuat sorgula
    MCP-->>Ret: Mevzuat pasajları
    Ret-->>Graph: Gruplanmış / doğrulanmış alıntılar
    Graph->>Graph: suggest_mevzuat_node<br/>(citation grounding — uydurma alıntı reddedilir)
    Graph->>Graph: scan_sensitivity_node — PII/hassasiyet taraması
    Graph-->>FE: SSE: "Mevzuat önerileri hazırlanıyor..."
    deactivate Graph

    Graph-->>Svc: DocumentAnalysisOutput<br/>(tür, alanlar, eksikler, mevzuat, özet)
    Svc->>DB: Analiz sonucunu kaydet (DocumentModel)
    Svc->>VDB: Belgeyi document_qa koleksiyonuna indeksle
    Svc-->>API: Analiz sonucu
    API-->>FE: SSE tamamlandı + sonuç JSON
    FE-->>Memur: Sınıflandırma, eksik alanlar, mevzuat önerisi, özet gösterilir
```

## Notlar

- Her düğüm zaman aşımı ve yeniden deneme politikasına sahiptir (`app/ai/workflows/resilience.py`); bir adım başarısız olursa graf çökmez, kademeli olarak daha basit bir moda düşer.
- Mevzuat önerisi, alıntı doğrulaması (grounding) başarısız olursa yalnızca ham atıf (açıklamasız) döner — LLM'in uydurma gerekçe üretmesi engellenir.
- Detaylı özet (kısa özetten farklı olarak) bu akışın içinde **çalışmaz**; ayrı bir endpoint üzerinden istek üzerine üretilir çünkü ölçülen gecikmesi (184–288 sn) ana akışı yavaşlatır.
