# Frontend Mimarisi

## Amaç

Bu doküman frontend uygulamasının mimarisini, katmanlarını ve bileşen organizasyonunu açıklamaktadır.

Frontend'in amacı;

* Kullanıcı ile sistem arasındaki etkileşimi sağlamak
* Modern ve tutarlı bir kullanıcı deneyimi sunmak
* Backend API ile güvenli iletişim kurmak
* Gerçek zamanlı AI etkileşimlerini yönetmek
* İş mantığını değil sunum katmanını yönetmektir.

Frontend yalnızca kullanıcı deneyiminden sorumludur.

İş kuralları Backend tarafından yürütülmektedir.

---

# Mimari Yaklaşım

Frontend aşağıdaki prensiplere göre geliştirilmektedir.

* Feature Based Architecture
* Component Based Design
* Atomic UI Yaklaşımı
* Separation of Concerns
* Single Responsibility Principle

Her bileşen yalnızca kendi sorumluluğunu yerine getirir.

---

# Genel Yapı

Frontend aşağıdaki ana klasörlerden oluşmaktadır.

```text
frontend/
│
├── src/
│   ├── app/
│   ├── pages/
│   ├── layouts/
│   ├── features/
│   ├── components/
│   ├── hooks/
│   ├── services/
│   ├── store/
│   ├── lib/
│   ├── providers/
│   ├── assets/
│   ├── styles/
│   ├── types/
│   └── utils/
│
├── public/
└── tests/
```

Her klasör belirli bir sorumluluğa sahiptir.

---

# Kullanıcı Akışı

Bir kullanıcı isteği frontend içerisinde aşağıdaki şekilde ilerler.

```text
Kullanıcı
      │
      ▼
Page
      │
      ▼
Feature
      │
      ▼
Component
      │
      ▼
Hook
      │
      ▼
API Service
      │
      ▼
Backend
```

Frontend doğrudan veritabanı veya AI sistemine erişmez.

---

# App

App klasörü uygulamanın başlangıç noktasıdır.

Başlıca görevleri;

* Routing
* Global Provider'lar
* Tema
* Yetkilendirme
* Global Error Boundary
* Uygulama başlatma

Tüm uygulama burada oluşturulur.

---

# Pages

Pages kullanıcı tarafından erişilen ekranlardır.

Örnekler

* Chat
* Login
* Dashboard
* Documents
* Settings

Page yalnızca ekranın iskeletini oluşturur.

İş mantığı içermez.

---

# Layouts

Layouts ortak ekran düzenlerini içerir.

Örnekler

* Main Layout
* Dashboard Layout
* Authentication Layout

Sayfalar aynı layout'u paylaşabilir.

---

# Features

Feature klasörü uygulamanın iş özelliklerini içerir.

Örnek yapı

```text
features/

chat/

documents/

authentication/

settings/
```

Her feature bağımsız geliştirilir.

Feature'lar birbirinden mümkün olduğunca bağımsız olmalıdır.

---

# Feature Yapısı

Örnek

```text
chat/

components/

hooks/

services/

types/

index.ts
```

Feature yalnızca kendi bileşenlerini kullanmalıdır.

---

# Components

Components tekrar kullanılabilir kullanıcı arayüzü elemanlarıdır.

Örnekler

* Button
* Modal
* Card
* Input
* Avatar
* Sidebar

Component yalnızca görünümden sorumludur.

İş mantığı minimum seviyede tutulmalıdır.

---

# Hooks

Hooks yeniden kullanılabilir davranışları içerir.

Örnekler

* useChat
* useAuth
* useDocuments
* useTheme

Hook veri yönetimini gerçekleştirir.

UI üretmez.

---

# Services

Services Backend API ile iletişim kurar.

Örnekler

* Chat API
* User API
* Document API
* Authentication API

HTTP istekleri yalnızca burada bulunmalıdır.

Component içerisinde fetch veya axios kullanılmaz.

---

# Store

Store uygulamanın global durumunu yönetir.

Örnekler

* Authentication
* Theme
* User
* Chat Session

Yalnızca gerçekten paylaşılması gereken veriler global tutulmalıdır.

Yerel durum mümkün olduğunca Component seviyesinde yönetilir.

---

# Providers

Providers uygulamanın ortak servislerini sağlar.

Örnekler

* Theme Provider
* Query Provider
* Authentication Provider
* Notification Provider

---

# Types

Frontend içerisinde kullanılan ortak TypeScript tipleri burada bulunur.

Örnekler

* User
* ChatMessage
* Document
* ApiResponse

Tip tanımları Backend modellerinden bağımsızdır.

---

# Assets

Statik dosyalar burada bulunur.

Örnekler

* Logo
* İkon
* Font
* Görseller

---

# Styles

Global stiller bu klasörde tutulur.

Tema sistemi de burada yönetilir.

Component bazlı stiller ilgili component içerisinde bulunmalıdır.

---

# Lib

Lib klasörü uygulama genelinde kullanılan yardımcı kütüphaneleri içerir.

Örnekler

* Axios Client
* Markdown Renderer
* Date Formatter
* Syntax Highlighter

Buraya iş mantığı eklenmez.

---

# API İletişimi

Frontend yalnızca Backend API ile haberleşir.

```text
Frontend

↓

API Service

↓

Backend

↓

Response

↓

UI
```

Frontend doğrudan

* PostgreSQL
* Redis
* Qdrant
* LLM

ile iletişim kurmaz.

---

# State Yönetimi

State aşağıdaki seviyelerde yönetilir.

## Local State

Yalnızca ilgili Component tarafından kullanılır.

Örnek

* Input değeri
* Modal durumu
* Açılır menü

---

## Feature State

Bir Feature içerisindeki Component'ler tarafından paylaşılır.

Örnek

* Aktif sohbet
* Belge listesi
* Filtreler

---

## Global State

Uygulamanın tamamı tarafından kullanılan verilerdir.

Örnek

* Kullanıcı bilgisi
* Tema
* Kimlik doğrulama
* Dil ayarları

---

# Veri Yönetimi

Sunucu verileri istemci durumundan ayrıdır.

Backend'den gelen veriler cache mekanizması üzerinden yönetilir.

Frontend aynı veriyi gereksiz yere tekrar istemez.

---

# Gerçek Zamanlı İşlemler

Uzun süren AI işlemleri kullanıcıya anlık olarak gösterilir.

Örnekler

* Streaming cevaplar
* Tool çalıştırma durumu
* Belge indeksleme
* Workflow ilerleme durumu

Frontend bu süreçleri kullanıcıya kesintisiz şekilde sunmalıdır.

---

# Hata Yönetimi

Hatalar kullanıcı dostu şekilde gösterilir.

Teknik hata mesajları doğrudan kullanıcıya gösterilmez.

Beklenen hata türleri

* Ağ hatası
* Yetkilendirme hatası
* Doğrulama hatası
* Sunucu hatası

Her hata uygun kullanıcı mesajına dönüştürülmelidir.

---

# Performans

Frontend aşağıdaki teknikleri kullanmalıdır.

* Lazy Loading
* Code Splitting
* Route Based Loading
* Memoization
* Virtualization
* Image Optimization

Gereksiz yeniden render işlemlerinden kaçınılmalıdır.

---

# Güvenlik

Frontend aşağıdaki prensipleri uygular.

* Token güvenli saklanmalıdır.
* Hassas bilgiler istemcide tutulmamalıdır.
* Input doğrulaması Backend tarafından tekrar yapılmalıdır.
* XSS ve CSRF riskleri dikkate alınmalıdır.

Frontend güvenlik açısından tek başına yeterli değildir.

---

# Test Yapısı

Frontend testleri aşağıdaki seviyelerde yazılır.

* Unit Test
* Component Test
* Integration Test
* End-to-End Test

Kritik kullanıcı akışları test edilmelidir.

---

# Ölçeklenebilirlik

Yeni özellikler mevcut feature yapısı korunarak geliştirilir.

Yeni ekranlar yeni page olarak eklenir.

Yeni iş alanları yeni feature altında geliştirilir.

Yeni ortak bileşenler components klasörüne eklenir.

Bu yapı frontend'in büyümesini kolaylaştırır.

