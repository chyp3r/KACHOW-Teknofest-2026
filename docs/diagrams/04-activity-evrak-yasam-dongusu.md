# Aktivite Diyagramı — Evrak Yaşam Döngüsü

Bir evrakın sisteme girişinden taslağın onaylanıp ilgili birime yönlendirilmesine kadar geçen tüm süreç, karar noktalarıyla birlikte.

```mermaid
flowchart TD
    Start([Evrak Yüklendi]) --> Extract[Metin Çıkarma:<br/>pdfium → tesseract → vision-LLM]
    Extract --> Classify[Evrak Türünü Sınıflandır]
    Classify --> ExtractFields[Bilgi Unsurlarını Çıkar<br/>regex + LLM]
    ExtractFields --> CheckMissing{Zorunlu alan<br/>eksik mi?}

    CheckMissing -->|Evet| FlagMissing[Eksik Alanları İşaretle]
    CheckMissing -->|Hayır| Mevzuat
    FlagMissing --> Mevzuat[Mevzuat Önerisi Getir<br/>+ Alıntı Doğrulama]

    Mevzuat --> Sensitivity[Hassasiyet / PII Tarama]
    Sensitivity --> Summary[Kısa Özet Üret]
    Summary --> AnalysisDone([Görev 1 Tamamlandı:<br/>Sınıflandırma + Analiz Raporu])

    AnalysisDone --> UserAction{Kullanıcı<br/>taslak ister mi?}
    UserAction -->|Hayır| End1([Süreç Sona Erer])
    UserAction -->|Evet| BriefCheck{Yazan/muhatap<br/>bilgisi yeterli mi?}

    BriefCheck -->|Hayır| AskBrief[Kullanıcıdan Ön Bilgi İste<br/>writing_brief.py]
    AskBrief --> BriefCheck
    BriefCheck -->|Evet| DecideType[Yazı Türüne Karar Ver<br/>üst yazı / cevap / bilgilendirme / diğer]

    DecideType --> Draft[Resmî Üslupla Taslak Yaz<br/>WriterAgent]
    Draft --> Verify{Doğrulama:<br/>stil, tutarlılık,<br/>placeholder, grounding}

    Verify -->|Düzeltilebilir kusur var| Revise[Hedefli Revizyon<br/>ReviserAgent]
    Revise --> Verify

    Verify -->|Doldurulmamış placeholder var| AskMissing[Kullanıcıdan Eksik Bilgi İste<br/>LangGraph interrupt + Postgres checkpoint]
    AskMissing --> Resume[Cevaplarla Devam Et<br/>apply_answers - yeniden üretim yok]
    Resume --> Verify

    Verify -->|Onaylandı| Route[Birime Yönlendirme Önerisi<br/>RouterAgent + deterministik yedek]
    Route --> ScoreCheck{Güven skoru<br/>eşiğin altında mı?}

    ScoreCheck -->|Evet| HumanApproval[İnsan Onayı Gerekli<br/>olarak işaretle]
    ScoreCheck -->|Hayır| AutoApproved[Otomatik Onaylandı]

    HumanApproval --> Persist[Taslak + Yönlendirme + Audit Log<br/>Kaydet]
    AutoApproved --> Persist
    Persist --> Notify[Kullanıcıya / İlgili Birime Bildirim]
    Notify --> End2([Görev 2 Tamamlandı])
```

## Notlar

- Diyagramdaki her karar noktası, kodda gerçek bir dallanmaya karşılık gelir (örn. `CheckMissing` → `app/ai/compliance/checker.py`, `Verify` → `draft_graph.py` içindeki `verify_node`).
- Sistem hiçbir noktada "çöküp durmaz": LLM başarısız olursa her adımın deterministik/heuristik bir yedeği devreye girer (sınıflandırmada tür `OTHER`'a düşer, yönlendirmede token-overlap ile en iyi birim seçilir, mevzuat önerisinde ham atıfa geri dönülür).
- `AskMissing` adımı gerçek bir askıya alma (interrupt) noktasıdır — kullanıcı cevap verene kadar sistem kaynak tüketmeden bekler, süreç kesintiye uğramaz.
