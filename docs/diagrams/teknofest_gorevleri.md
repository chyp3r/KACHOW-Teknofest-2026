# TEKNOFEST 2026 Görev Analizi Diyagramları

Aşağıdaki diyagramlar, TEKNOFEST 2026 yarışma şartnamesinde belirtilen Görev 1 ve Görev 2'nin KACHOW platformunda nasıl teknik iş akışlarına dönüştürüldüğünü gösterir.

## Görev 1: Evrak Sınıflandırma ve İçerik Analizi

Bu görev, evrakın kuruma ulaştığı ilk anda yapılan dijital ön işleme (preprocessing) aşamasını modeller.

```mermaid
flowchart TD
    %% Stil Tanımlamaları
    classDef input fill:#2c3e50,stroke:#34495e,stroke-width:2px,color:#fff
    classDef process fill:#2980b9,stroke:#2980b9,stroke-width:2px,color:#fff
    classDef ai fill:#27ae60,stroke:#2ecc71,stroke-width:2px,color:#fff
    classDef output fill:#8e44ad,stroke:#9b59b6,stroke-width:2px,color:#fff

    Start([Evrak Sisteme Ulaştı]):::input --> OCR{Metin Okunabilir mi?}
    OCR -->|Evet| Parse[Doğrudan Metin Çıkarımı]:::process
    OCR -->|Hayır| Tesseract[OCR ile Görselden Metin Çıkarımı]:::process
    
    Parse --> AI_Classify
    Tesseract --> AI_Classify
    
    subgraph KACHOW Analiz Çekirdeği (Agent)
        AI_Classify[Evrak Türünü Belirle]:::ai
        AI_Extract[Önemli Bilgi Unsurlarını Çıkar]:::ai
        AI_Missing{Eksik Bilgi Var mı?}:::ai
        AI_Laws[İlgili Mevzuat/Yönetmelik Öner]:::ai
        AI_Summary[Kısa ve Öz Özet Oluştur]:::ai
        
        AI_Classify --> AI_Extract
        AI_Extract --> AI_Missing
        AI_Missing -->|Var| Alert[İnsan Kontrolü: Eksik Bilgi]:::output
        AI_Missing -->|Yok| AI_Laws
        Alert --> AI_Laws
        AI_Laws --> AI_Summary
    end
    
    AI_Summary --> Finish([Analiz Raporu Hazır]):::output
```

## Görev 2: Resmî Yazı Taslaklama ve Birim Yönlendirme

Bu görev, birinci aşamada elde edilen verilerle doğru birim yönlendirmesini yapmayı ve resmi cevabı taslaklamayı modeller.

```mermaid
stateDiagram-v2
    %% Durum Tanımlamaları
    state "Evrak İşleme Alındı" as s1
    state "Uygun Taslak Seçimi (Üst Yazı/Cevap vb.)" as s2
    state "Resmi Üslup Taslağı Üretimi (Writer)" as s3
    state "Doğrulama ve Üslup Kontrolü (Judge)" as s4
    state "Birim Yönlendirme (Router)" as s5
    state "Eksik Bilgi Talep Durumu" as s6
    
    [*] --> s1
    s1 --> s2
    s2 --> s3
    
    s3 --> s4
    s4 --> s3 : Üslup İhlali (Revizyon)
    s4 --> s5 : Taslak Onaylandı
    
    s5 --> s6 : Ek Bilgi Gerekiyor
    s6 --> s5 : Kullanıcı Bilgi Sağladı (Süreç Bilgilendirmesi)
    
    s5 --> Tamamlandı : Doğru Birime İletildi
    Tamamlandı --> [*]
```

## Görev 1 & Görev 2 Entegre Sistem Dizisi (Sequence)

İki görevin kesintisiz birleşik akışta nasıl çalıştığını anlatan sekans diyagramı.

```mermaid
sequenceDiagram
    participant User as Kullanıcı (Kamu Çalışanı)
    participant Core as KACHOW Sistemi
    participant G1 as Görev 1 (Analiz)
    participant G2 as Görev 2 (Taslak & Yönlendirme)
    
    User->>Core: Gelen Evrakı İlet
    Core->>G1: OCR / Metin Okuma
    G1->>G1: Tür Belirle & Bilgi Çıkar
    
    alt Eksik Bilgi Tespit Edildi
        G1-->>User: Eksik Bilgileri Tamamla
        User->>G1: Gerekli Bilgileri Gir
    end
    
    G1->>G1: Mevzuat Öner & Özetle
    G1-->>Core: Analiz Sonucu
    
    Core->>G2: Taslak Üretimi Başlat
    G2->>G2: Resmi Üsluba Uygun Yazı Hazırla
    G2->>G2: Doğru Birim Yönlendirmesini Belirle
    
    alt Kullanıcıdan Onay/Bilgi İhtiyacı
        G2-->>User: Süreç Bilgilendirmesi / Ek Talep
        User->>G2: Geri Bildirim
    end
    
    G2-->>Core: Hazır Taslak ve Birim Önerisi
    Core-->>User: Nihai Sonuçları Sun
```
