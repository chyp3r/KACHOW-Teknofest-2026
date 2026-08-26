# Görev 2 Sıra Diyagramı — Resmî Yazı Taslaklama ve Birim Yönlendirme

Analiz tamamlandıktan sonra kullanıcı (veya otomatik akış) taslak oluşturmayı tetikler. `draft_graph`, yazma → doğrulama → revizyon döngüsünü çalıştırır; eksik bilgi varsa LangGraph'ın *interrupt* mekanizmasıyla akış duraklatılır ve kullanıcıdan cevap beklenir. Ardından `routing_graph` doğru birimi önerir.

```mermaid
sequenceDiagram
    actor Memur as Kamu Çalışanı
    participant FE as Frontend (React)
    participant API as FastAPI<br/>drafts/router.py
    participant DSvc as DraftService<br/>generate_draft_and_route()
    participant Brief as writing_brief.py<br/>(taslak öncesi bilgi kapısı)
    participant DGraph as draft_graph<br/>(LangGraph)
    participant Writer as WriterAgent
    participant Verify as verify_node<br/>(deterministik + LLM-judge)
    participant Reviser as ReviserAgent
    participant RGraph as routing_graph
    participant Router as RouterAgent
    participant CP as Postgres Checkpoint
    participant DB as PostgreSQL

    Memur->>FE: "Taslak oluştur" (analiz sonucundan)
    FE->>API: POST /drafts
    API->>DSvc: generate_draft_and_route(analysis)

    DSvc->>Brief: Yazma bilgisi yeterli mi?
    alt Kim yazıyor / kime hitap belirsiz
        Brief-->>FE: SSE: Ek bilgi soruları (InfoQuestion)
        FE-->>Memur: Soruları göster
        Memur->>FE: Cevapları gönder
        FE->>DSvc: Cevaplarla devam et
    end

    DSvc->>DGraph: create_draft_graph() çalıştır
    activate DGraph
    DGraph->>DGraph: validate_input → retrieve_examples<br/>→ retrieve_source_chunks
    DGraph->>Writer: Brief'ten taslak üret<br/>("biz kimiz" vs "evrak kime ait" ayrımı zorunlu)
    Writer-->>DGraph: Taslak metni
    DGraph->>Verify: Doğrula (stil, kişi tutarlılığı,<br/>imza bloğu, placeholder, grounding)
    Verify->>Verify: LLM-judge ikinci görüş

    alt Doğrulama başarısız — düzeltilebilir kusur
        Verify-->>DGraph: Numaralı kusur listesi
        DGraph->>Reviser: Hedefli düzeltme yap<br/>(listede olmayan cümlelere dokunmaz)
        Reviser-->>DGraph: Revize taslak
        DGraph->>Verify: Yeniden doğrula
    else Doldurulmamış placeholder var (eksik bilgi)
        DGraph->>CP: Graph durumunu checkpoint'e yaz, interrupt
        DGraph-->>FE: SSE: Eksik bilgi soruları (missing_info.py)
        FE-->>Memur: Soruları göster
        Memur->>FE: Cevapları gönder
        FE->>DGraph: apply_answers() ile resume<br/>(checkpoint'ten devam, yeniden üretim yok)
    else Doğrulama başarılı
        DGraph-->>DSvc: Onaylı taslak + confidence_score
    end
    deactivate DGraph

    DSvc->>RGraph: create_routing_graph() çalıştır
    RGraph->>Router: Uygun birimi seç<br/>(sadece tanımlı birim listesinden)
    alt Model belirsiz / liste dışı öneri
        Router->>Router: Deterministik yedek:<br/>token-overlap ile en iyi birim
    end
    Router-->>RGraph: Birincil + alternatif birim önerisi
    RGraph-->>DSvc: Yönlendirme kararı

    DSvc->>DB: Taslak + yönlendirme + audit_log kaydı
    DSvc-->>API: Sonuç
    API-->>FE: SSE tamamlandı + taslak/yönlendirme JSON
    FE-->>Memur: Taslak, güven skoru, önerilen birim gösterilir
```

## Notlar

- **İnsan onaylı akış (HITL)**, LangGraph'ın gerçek *interrupt/resume* mekanizmasıyla çalışır — akış bellekte beklemez, Postgres'e checkpoint'lenir; kullanıcı saatler sonra bile cevap verse akış kaldığı yerden devam eder.
- **Reviser**, verify adımının çıkardığı numaralı kusur listesi dışındaki hiçbir cümleye dokunmaz — bu, "düzeltirken başka yeri bozma" tasarım ilkesidir.
- **Router**, model hiçbir öneri veremese veya tanımlı birim listesi dışında bir şey önerse bile her zaman boş olmayan bir öneri döner (deterministik yedek sayesinde).
- `confidence_score` ve `applied_rules` (skorun arkasındaki kural dökümü) kullanıcıya şeffaf şekilde gösterilir — bu, Görev 2'nin "sürece dair açık bilgilendirme" maddesinin karşılığıdır.
