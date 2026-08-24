# Use Case Diyagramları

## 1. Sistem Genel Kullanım Durumu

```mermaid
usecaseDiagram
    actor "Memur (Kullanıcı)" as U
    actor "Sistem Yöneticisi" as A
    usecase "Evrak Yükle" as UC1
    usecase "Evrak Analizi Görüntüle" as UC2
    usecase "Taslak Üret" as UC3
    usecase "Onay/Revizyon Ver" as UC4
    usecase "Kullanıcı Yönetimi" as UC5
    U --> UC1
    U --> UC2
    U --> UC3
    U --> UC4
    A --> UC5
```

## 2. Evrak Analiz Süreci Use Case

```mermaid
usecaseDiagram
    actor Sistem as S
    usecase "Metin Çıkar (OCR)" as UC1
    usecase "Sınıflandır" as UC2
    usecase "Eksik Bul" as UC3
    usecase "Mevzuat Eşleştir" as UC4
    S --> UC1
    S --> UC2
    S --> UC3
    S --> UC4
```

## 3. Taslak Üretim Use Case

```mermaid
usecaseDiagram
    actor "LangGraph Ajanı" as A
    usecase "Bağlam Hazırla" as UC1
    usecase "Metin Üret" as UC2
    usecase "Güvenlik Kontrolü" as UC3
    A --> UC1
    A --> UC2
    A --> UC3
```

## 4. RAG ve MCP Use Case

```mermaid
usecaseDiagram
    actor Ajan as A
    usecase "Qdrant'ta Ara" as UC1
    usecase "Mevzuat MCP'yi Çağır" as UC2
    A --> UC1
    A --> UC2
```

## 5. Birim Yönlendirme Use Case

```mermaid
usecaseDiagram
    actor Kullanıcı as U
    usecase "Önerilen Birimi Gör" as UC1
    usecase "Birimi Onayla" as UC2
    usecase "Manuel Birim Seç" as UC3
    U --> UC1
    U --> UC2
    U --> UC3
```

