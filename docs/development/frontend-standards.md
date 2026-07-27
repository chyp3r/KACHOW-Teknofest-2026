# Frontend Standards

> Bu doküman Frontend geliştirme standartlarını tanımlar.

Frontend içerisinde geliştirilen tüm modüller bu kurallara uygun olmalıdır.

Bu doküman yalnızca Frontend katmanını kapsar.

---

# Amaç

Bu dokümanın amacı;

* Tutarlı kullanıcı deneyimi oluşturmak
* Ölçeklenebilir bir bileşen yapısı sağlamak
* Tekrarlayan kodları azaltmak
* Performansı korumak
* Bakımı kolaylaştırmaktır

---

# Frontend Felsefesi

Frontend;

* kullanıcı arayüzünü oluşturur,
* kullanıcı etkileşimlerini yönetir,
* Backend API ile iletişim kurar,
* uygulama durumunu yönetir.

Frontend;

* iş kurallarını yönetmez,
* veritabanına erişmez,
* AI mantığını içermez,
* Prompt oluşturmaz,
* MCP ile doğrudan haberleşmez.

---

# Mimari

Frontend Feature First Architecture yaklaşımını kullanır.

```text
Page

↓

Feature

↓

Component

↓

Hook

↓

Service

↓

Backend API
```

Her katman yalnızca kendi sorumluluğunu yerine getirir.

---

# Pages

Page yalnızca ekran seviyesindeki düzeni oluşturur.

Page;

* Layout kullanabilir.
* Feature çağırabilir.
* Sayfa seviyesinde yönlendirme yapabilir.

Page;

* API çağrısı yapmaz.
* Karmaşık iş mantığı içermez.
* Büyük bileşenler barındırmaz.

---

# Features

Her iş alanı bağımsız bir Feature olarak geliştirilmelidir.

Örnekler

```text
chat

documents

settings

authentication

dashboard
```

Feature kendi içerisinde izole çalışmalıdır.

Başka Feature'ların iç yapısına bağımlı olunmamalıdır.

---

# Components

Component yeniden kullanılabilir kullanıcı arayüzü elemanıdır.

Bir Component;

* mümkün olduğunca küçük olmalıdır,
* tek sorumluluğa sahip olmalıdır,
* yeniden kullanılabilir olmalıdır.

Component;

* API çağırmamalıdır.
* İş mantığı barındırmamalıdır.
* Başka Feature'ların durumunu yönetmemelidir.

---

# Hooks

Tekrarlayan davranışlar Hook içerisine taşınmalıdır.

Hook;

* veri çekebilir,
* state yönetebilir,
* servis çağırabilir.

Hook;

* kullanıcı arayüzü oluşturmaz.
* JSX döndürmez.

---

# Services

Backend ile tüm iletişim Service katmanında gerçekleştirilir.

Hiçbir Component doğrudan;

* fetch
* axios
* HTTP Client

kullanmaz.

API değişiklikleri yalnızca Service katmanını etkilemelidir.

---

# State Yönetimi

State aşağıdaki seviyelerde tutulmalıdır.

## Local State

Yalnızca ilgili Component tarafından kullanılır.

Örnekler

* input değeri
* modal durumu
* dropdown seçimi

---

## Feature State

Bir Feature içerisindeki Component'ler tarafından paylaşılır.

Örnekler

* aktif sohbet
* filtreler
* belge listesi

---

## Global State

Tüm uygulama tarafından kullanılan veriler.

Örnekler

* kullanıcı bilgisi
* tema
* oturum
* dil

Global State gereksiz büyütülmemelidir.

---

# Veri Yönetimi

Sunucu verisi ile kullanıcı arayüzü durumu birbirinden ayrılmalıdır.

Server State;

* Backend'den gelir.
* Cache yönetimi kullanır.

UI State;

* Component içerisinde tutulur.

Bu iki yapı karıştırılmamalıdır.

---

# Dosya Organizasyonu

Her dosya tek sorumluluğa sahip olmalıdır.

Feature yapısı örneği

```text
chat/

components/

hooks/

services/

types/

index.ts
```

Feature dışında ortak kullanılan bileşenler ortak klasörlere taşınmalıdır.

---

# Ortak Component

Ortak kullanılan UI elemanları yalnızca Components klasöründe bulunmalıdır.

Örnekler

* Button
* Modal
* Dialog
* Card
* Table
* Input
* Avatar

Feature'a özel Component'ler ortak klasöre taşınmamalıdır.

---

# Layout

Tekrarlayan sayfa düzenleri Layout olarak geliştirilmelidir.

Örnekler

* Dashboard
* Authentication
* Admin Panel

---

# Routing

Sayfa yönlendirmeleri merkezi olarak yönetilmelidir.

Route tanımları farklı dosyalara dağılmamalıdır.

---

# Form Yönetimi

Tüm formlar aynı doğrulama yaklaşımını kullanmalıdır.

Doğrulama;

* kullanıcı deneyimini iyileştirmeli,
* Backend doğrulamasının yerine geçmemelidir.

---

# Hata Yönetimi

Hatalar kullanıcı dostu şekilde gösterilmelidir.

Teknik hata mesajları doğrudan kullanıcıya gösterilmez.

Beklenen hata türleri

* doğrulama hatası
* ağ hatası
* yetkilendirme hatası
* sunucu hatası

---

# Loading Durumları

Uzun süren işlemler kullanıcıya gösterilmelidir.

Örnekler

* Skeleton
* Spinner
* Progress Indicator

Arayüz hiçbir zaman açıklamasız şekilde donmuş görünmemelidir.

---

# Gerçek Zamanlı İşlemler

Streaming yanıtlar desteklenmelidir.

Örnekler

* AI cevabı
* belge indeksleme
* tool çalıştırma
* workflow ilerleme durumu

Kullanıcı işlem durumunu her zaman görebilmelidir.

---

# Performans

Frontend aşağıdaki prensiplere göre optimize edilmelidir.

* Lazy Loading
* Code Splitting
* Memoization
* Virtualization
* Gereksiz Render'dan kaçınma

Performans optimizasyonu ölçülebilir olmalıdır.

---

# Responsive Tasarım

Tüm ekranlar farklı cihazlarda çalışmalıdır.

Desteklenen temel boyutlar

* Mobile
* Tablet
* Desktop

Responsive tasarım sonradan eklenmez.

Başlangıçtan itibaren düşünülmelidir.

---

# Accessibility

Arayüz erişilebilir olmalıdır.

Dikkat edilmesi gerekenler

* Klavye ile kullanım
* Odak yönetimi
* Anlamlı etiketler
* Kontrast
* ARIA desteği

Erişilebilirlik isteğe bağlı değildir.

---

# Tema

Tema sistemi merkezi olarak yönetilmelidir.

Renkler doğrudan Component içerisinde tanımlanmamalıdır.

---

# Dosya Boyutu

Yaklaşık öneriler

* Component ≤ 250 satır
* Hook ≤ 250 satır
* Service ≤ 250 satır
* Page ≤ 200 satır

Dosya büyüdüğünde parçalanmalıdır.

---

# Test

Frontend aşağıdaki seviyelerde test edilmelidir.

* Unit Test
* Component Test
* Integration Test
* End-to-End Test

Özellikle kullanıcı akışları test edilmelidir.

---

# Yeni Özellik Geliştirme

Yeni bir Frontend özelliği eklenirken aşağıdaki sıra izlenmelidir.

```text
Issue

↓

Feature

↓

Component

↓

Hook

↓

Service

↓

Test

↓

Documentation

↓

Pull Request
```

---

# Yapılmaması Gerekenler

Frontend içerisinde;

* SQL yazılmaz.
* Prompt oluşturulmaz.
* LLM çağrısı yapılmaz.
* MCP istemcisi geliştirilmez.
* Veritabanına erişilmez.
* İş kuralları yazılmaz.

Bu sorumluluklar Backend ve AI katmanlarına aittir.
