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

---

# Uygulanan Entegrasyon Kararları

## Routing ve Erişim

Uygulama rotaları React Router ile yönetilir ve sayfa bazında lazy loading uygulanır. Kimliği doğrulanmamış kullanıcılar login rotasına, rolü yetersiz kullanıcılar güvenli bir uygulama rotasına yönlendirilir. Admin/manager görünürlük kontrolleri yalnızca arayüz kolaylığıdır; backend yetkilendirmesinin yerine geçmez.

## Sunucu Durumu

TanStack Query; belge listesi ve analizleri, sohbet oturumları ve mesajları, interrupt state, taslaklar, yönlendirme önerileri ve sistem sağlığı için sunucu cache'ini yönetir. Anahtarlar `frontend/src/query/queryKeys.ts` içinde merkezidir. Mutation başarıları yalnızca ilgili cache alanlarını invalidate eder. Kalıcı domain verisi için backend tek doğruluk kaynağıdır; localStorage cache'i kullanılmaz.

## API Sözleşmesi

Backend OpenAPI çıktısı `openapi-typescript` ile `frontend/src/api/generated.ts` dosyasına üretilir. Üretim ve drift kontrol komutları frontend package script'lerinde bulunur. OpenAPI dışındaki SSE olay aileleri backend event şemalarına göre ayrı discriminated union olarak tutulur.

## Kimlik Doğrulama

Access ve refresh token'ları `sessionStorage` içinde saklanır. API istemcisi eşzamanlı 401 cevaplarını tek refresh isteğinde birleştirir, isteği en fazla bir kez tekrarlar ve refresh başarısızsa token'ları temizleyip merkezi oturum-sonlandı olayını yayınlar. Token veya hassas içerik loglanmaz.

## Streaming

Chat akışı parçalanmış SSE chunk'larını bir buffer içinde birleştirir. Bilinen olay aileleri çalışma zamanında doğrulanır; bozuk veya ileri sürüm bilinmeyen frame'ler sonraki geçerli olayı düşürmeden atlanır. `seq` tekrarları idempotent biçimde yok sayılır. AbortController kullanıcı iptali ve route/oturum değişimi sırasında bağlantıyı kapatır.

İlk `session` SSE olayı backend thread kimliğini çözüp URL'yi `/chats/:sessionId` biçimine taşır. Bu iç route güncellemesi kullanıcı tarafından başka bir oturum seçilmesinden ayrı değerlendirilir; aktif stream iptal edilmez ve iyimser kullanıcı mesajı korunur. Stream sürerken kalıcı mesaj/state sorguları bekletilir; böylece yeni oturum henüz yazılırken dönebilecek boş veya eksik geçmiş canlı konuşma durumunun üzerine yazılmaz. Kullanıcının gerçekten başka bir oturuma geçmesi ise aktif isteği iptal edip seçilen oturumu backend'den yüklemeye devam eder.

Taslak onay interrupt'ının isteğe bağlı revizyon alanları runtime'da daraltılır. İlk taslakta backend'in gönderdiği boş `changelog` nesnesi geçerli kabul edilir; değişiklik günlüğü yalnızca gerçek bir `entries` listesi bulunduğunda gösterilir.

## Sağlık ve Gözlemlenebilirlik

Normal health kontrolü otomatik ve hafiftir. Postgres, Redis, Qdrant, Ollama, checkpointer ve semantik router kontrollerini çalıştıran deep health yalnızca admin/manager ekranındaki açık kullanıcı eylemiyle çağrılır.

## Konuşma Odaklı Bilgi Mimarisi

Varsayılan masaüstü kabuğu yalnızca birincil navigasyon ve ana çalışma alanından oluşur. Navigasyon; Sohbetler, Evraklar, Taslaklar, Yönlendirme, Hesabım ve yetkili kullanıcılar için Yönetim girişlerini taşır. Evrak yükleme, arama ve ayrıntı kontrolleri kalıcı navigasyonda değil, Evraklar sayfasında bulunur. Masaüstü navigasyonu 248 piksel genişliğinde açılır; 76 piksellik dar tercih `localStorage` içinde yalnızca sunum tercihi olarak saklanır. Dar durumda üstte her zaman görünür 44×44 genişletme kontrolü, ortalanmış 44×44 navigasyon hedefleri ve taşmayan tema/oturum kontrolleri kullanılır. Mobilde masaüstü dar tercihi görsel düzeni etkilemez; navigasyon tam içerikli çekmeceye dönüşür ve çekmece açıkken hamburger tetikleyicisi marka alanının üzerine binmez.

Sohbet geçmişi varsayılan düzende sütun ayırmaz; kullanıcının Geçmiş eylemiyle viewport'un sol kenarından açılan ve birincil navigasyonu örten bir modal çekmecedir. Masaüstünde 380 piksel, dar mobil ekranlarda tam genişlik kullanır. Çekmece açıldığında sayfa kaydırması kilitlenir, klavye odağı içeride tutulur; Escape, backdrop veya kapatma düğmesiyle kapanınca odak Geçmiş tetikleyicisine döner. İlk yükleme, hata, boş, başarı ve arka plan yenileme durumları birbirini dışlar; hata varken boş durum gösterilmez. Başarılı liste Bugün, Dün ve Daha eski gruplarına ayrılır; arama yalnızca en az on oturum olduğunda görünür. Sohbet içindeki evrak erişimi, seçilen evrakı kaldırılabilir bir çip olarak gösteren kompakt seçiciyle sağlanır. Evrak arama ve seçim arayüzü modal, mobilde tam ekran katman olarak açılır; yeni yükleme ve kapsamlı yönetim Evraklar sayfasına yönlendirilir.

Ana konuşma ve mesaj oluşturucu aynı, en fazla 860 piksel okunabilir genişlikte hizalanır. Boş durum yalnızca backend'in desteklediği taslak ve yönlendirme başlangıçlarını gösterir; evrak analizi eylemi ancak bir evrak seçildiğinde görünür. Yerel sohbet/geçmiş hataları konuşma bağlamında kompakt ve yeniden denenebilir biçimde sunulur.

Taslaklar sayfası tek sütunlu ve liste odaklıdır. Yeni taslak formu varsayılan olarak kapalıdır; sayfa başlığındaki birincil eylemle açılan tam genişlikte, kompakt bir panel kullanır. Kalıcı taslak satırları `document_id` ile aynı değeri taşıyan evrak `storage_path` alanından kaynak dosya adını çözer. Satır seçimi mevcut `/drafts/:draftId` rotasını koruyarak ayrıntıyı satırın altında açar; sürümler yeniden eskiye sıralanır ve her sürüm 420 karakterlik önizlemeden erişilebilir chevron eylemiyle tam metne genişletilebilir.

Evrak Kütüphanesi aynı tek sütunlu progressive-disclosure desenini kullanır. Sayfa başlığında açıklama metni bulunmaz; sağ üstteki “Evrak yükle” eylemi kompakt tam genişlikte yükleme alanını açar. Arama, tür filtresi ve tarih sıralaması kalıcı evrak listesinin üzerinde korunur. Evrak satırı seçildiğinde mevcut `/documents/:storagePath` rotası üzerinden analiz ayrıntısı aynı satırın altında açılır; satıra yeniden basılması seçimi ve derin rotayı kapatır.

İş akışı varsayılan olarak kapalıdır. Kullanıcı açtığında 1500 pikselin altındaki ekranlarda 400 piksellik bir örtü/çekmece, mobilde tam ekran katman kullanılır; geniş ekranlarda isteğe bağlı üçüncü bölge olabilir. İlk görünüm Evrak analizi, Taslak oluşturma, Doğrulama, İnsan onayı ve Yönlendirme adımlarından oluşan durum listesidir. Tam düğüm grafiği, araç çağrıları, guardrail olayları ve teknik meta veriler açık bir “Teknik grafiği görüntüle” ayrıntısının arkasında korunur. Teknik grafik %60–%300 aralığında buton, tekerlek veya pinch ile ölçeklenebilir; boş tuval sürüklenerek ya da odaklıyken ok tuşlarıyla kaydırılabilir ve tek eylemle başlangıç görünümüne döndürülebilir. Zoom ve pan CSS compositing yerine SVG `viewBox` koordinatlarında uygulanır; böylece yüksek yakınlaştırmada vektör keskinliği korunur. Edge'ler `non-scaling-stroke` ile ekranda sabit kalınlık taşır; bekleyen bağlantılar nötr yüksek kontrastla, çalışan/tamamlanan/hatalı bağlantılar durum rengi ve hafif vurguyla ayrıştırılır. Düğüm tıklama ve klavye seçimi bu viewport hareketlerinden ayrı tutulur.

Yüzey sistemi açık ve koyu temada nötr uygulama zemini, tek ana yüzey ve ince sınırlar kullanır. Vurgu rengi birincil eylem, aktif navigasyon, seçim ve anlamlı durumlarla sınırlıdır. 760 piksel ve altında uygulama tek sütuna iner; navigasyon, geçmiş, evrak seçimi ve iş akışı birbirinden bağımsız katmanlar olarak açılır.

## Typography Sistemi

Frontend typography ölçeğinin tek kaynağı `frontend/src/styles/typography.css` dosyasıdır. Boyut, satır yüksekliği, ağırlık ve harf aralığı tokenları `rem` tabanlıdır; kök yazı boyutu tarayıcı varsayılanı olan yüzde 100'de korunur. Sayfa başlığı, bölüm başlığı, birincil içerik, arayüz gövdesi, kontrol etiketi, ikincil metin, caption ve overline rolleri bütün sayfalarda aynı token eşlemesini kullanır. `App.css` ve `integration.css` yalnızca yüzey, yerleşim ve bileşen geometrisini yönetir.

Inter temel arayüz ailesidir; Outfit yalnızca marka ve başlık hiyerarşisinde kullanılır. Yalnız kullanılan 400–700 ağırlıkları yüklenir ve sistem fontu fallback zinciri web fontu yüklenirken metni görünür tutar. Açık/koyu/sistem temaları okunabilir semantik metin renklerini paylaşır. Mobilde yalnız büyük sayfa ve boş-durum başlıkları küçülür; gövde, form, navigasyon ve kontrol metinleri masaüstü rollerini korur. Uzun sohbet, taslak, analiz ve resmi metin içerikleri 75 karakterlik okunabilir genişlikle sınırlanır ve Türkçe dizeler kırpılmak yerine sarılır.

## Design System Temeli

Spacing, kontrol yüksekliği, ikon, radius, border, focus ve elevation değerlerinin tek kaynağı `frontend/src/styles/design-system.css` dosyasıdır. Ortak primitive, composite ve layout bileşenleri `frontend/src/components/` altında tutulur; sayfalar kendi button/input/select/textarea implementasyonlarını oluşturmaz. Uygulama kabuğu, sohbet/composer, evraklar, taslaklar, yönlendirme, hesap, yönetim, workflow, drawer ve dialog alanları bu ortak katmanı compose eder.

Desktop/tablet/mobile sayfa gutterları sırasıyla 32/24/16 pikseldir. Varsayılan control 40 piksel, mobil ve öne çıkan eylemler 44 piksel, kompakt ikincil arayüzler 32 pikseldir. Ortak overlay bileşenleri focus trap, Escape, scroll lock ve focus dönüş davranışının tek sahibidir. Ayrıntılı token, component API, denetim envanteri ve belgelenmiş istisnalar `docs/development/frontend-design-system.md` içindedir.

