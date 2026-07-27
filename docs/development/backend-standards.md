# Backend Standards

> Bu doküman Backend geliştirme standartlarını tanımlar.

Backend içerisinde geliştirilen tüm modüller bu kurallara uygun olmalıdır.

Bu doküman yalnızca Backend katmanını kapsar.

---

# Amaç

Bu dokümanın amacı;

* Backend mimarisini korumak
* Tutarlı geliştirme sağlamak
* Domain bağımlılıklarını azaltmak
* Test edilebilir kod üretmek
* Ölçeklenebilir Backend oluşturmak

---

# Backend Felsefesi

Backend;

* iş kurallarını yönetir,
* API isteklerini karşılar,
* AI sistemini orkestre eder,
* veriye erişir,
* güvenliği sağlar.

Backend kullanıcı arayüzünü yönetmez.

Backend LLM mantığını içermez.

Backend Prompt içermez.

Backend Tool geliştirmez.

---

# Katmanlar

Backend aşağıdaki katmanlardan oluşur.

```text
Router

↓

Service

↓

Repository

↓

Infrastructure

↓

Database
```

Her katman yalnızca kendi sorumluluğunu yerine getirir.

---

# Domain Bazlı Geliştirme

Her özellik bir domain içerisinde geliştirilmelidir.

Örnek

```text
domains/

chat/

documents/

auth/

users/

settings/
```

Yeni özellikler mevcut domain içerisine eklenmelidir.

Yeni domain yalnızca gerçekten yeni bir iş alanı oluştuğunda oluşturulmalıdır.

---

# Router

Router yalnızca HTTP katmanıdır.

Router;

* endpoint tanımlar,
* request doğrular,
* response döndürür,
* Service çağırır.

Router içerisinde;

* SQL yazılmaz.
* AI çağrısı yapılmaz.
* iş kuralı bulunmaz.
* dosya işlemi yapılmaz.

---

# Service

Service uygulamanın iş mantığını içerir.

Service;

* Repository kullanabilir.
* AI Core çağırabilir.
* Event yayınlayabilir.
* Transaction yönetebilir.

Service;

* HTTP yönetmez.
* ORM sorgusu yazmaz.
* Response üretmez.

---

# Repository

Repository veri erişim katmanıdır.

Repository;

* CRUD
* filtreleme
* sıralama
* sayfalama
* transaction

işlemlerinden sorumludur.

Repository yalnızca veri erişimi yapar.

İş kuralları burada bulunmaz.

---

# Models

ORM modelleri yalnızca veritabanı yapısını temsil eder.

Model içerisinde;

* API doğrulaması
* HTTP mantığı
* AI işlemleri

bulunmaz.

---

# Schemas

Schema yalnızca API giriş ve çıkışlarını tanımlar.

Database modeli ile Schema aynı amaç için kullanılmaz.

Her API açık şekilde Request ve Response modelleri tanımlamalıdır.

---

# Dependency Injection

Bağımlılıklar Dependency Injection ile sağlanmalıdır.

Hiçbir servis bağımlılıklarını doğrudan oluşturmamalıdır.

Bu yaklaşım;

* test yazmayı,
* mock kullanmayı,
* bakım yapmayı

kolaylaştırır.

---

# AI ile İletişim

Backend AI'nın nasıl çalıştığını bilmez.

Backend yalnızca AI servisini çağırır.

Backend;

* Prompt oluşturmaz.
* Workflow yönetmez.
* Tool seçmez.
* MCP çağırmaz.

Bu sorumluluklar AI katmanına aittir.

---

# Veritabanı

Veritabanı işlemleri Repository katmanında gerçekleştirilir.

SQL sorguları farklı katmanlara dağılmamalıdır.

Migration işlemleri versiyon kontrollü olmalıdır.

---

# Background İşlemler

Uzun süren işlemler HTTP isteğinden ayrılmalıdır.

Örnekler

* embedding oluşturma
* belge indeksleme
* büyük dosya işleme
* rapor üretme

Bu işlemler arka planda çalıştırılmalıdır.

---

# API Tasarımı

API tasarımı tutarlı olmalıdır.

Genel ilkeler

* isimler açık olmalıdır.
* endpoint'ler kaynak odaklı olmalıdır.
* HTTP metodları doğru kullanılmalıdır.
* versiyonlama desteklenmelidir.

Örnek

```text
/api/v1/chat

/api/v1/documents

/api/v1/users
```

---

# Validation

Tüm kullanıcı girdileri doğrulanmalıdır.

Validation yalnızca Frontend'e bırakılmaz.

Backend her zaman son doğrulamayı yapmalıdır.

---

# Exception Yönetimi

Beklenen hatalar kontrollü şekilde yönetilmelidir.

Global Exception Handler kullanılmalıdır.

Ham Exception kullanıcıya gösterilmez.

---

# Authentication

Kimlik doğrulama merkezi olarak yönetilmelidir.

Hiçbir endpoint kendi doğrulama mekanizmasını yazmamalıdır.

---

# Authorization

Yetkilendirme iş kurallarından bağımsız düşünülmelidir.

Kim hangi işlemi yapabilir sorusu merkezi olarak yönetilir.

---

# Logging

Önemli işlemler loglanmalıdır.

Örnekler

* giriş
* çıkış
* hata
* AI çağrısı
* kritik servisler

Loglar okunabilir olmalıdır.

---

# Konfigürasyon

Hiçbir sabit değer kaynak koduna yazılmaz.

Aşağıdakiler yapılandırma dosyalarından okunmalıdır.

* URL
* Secret
* API Key
* Timeout
* Port
* Model Adı

---

# Performans

Repository gereksiz sorgu üretmemelidir.

Tekrarlayan sorgular azaltılmalıdır.

N+1 problemlerinden kaçınılmalıdır.

Cache uygun yerlerde kullanılmalıdır.

---

# Test

Backend aşağıdaki seviyelerde test edilmelidir.

* Unit Test
* Integration Test
* API Test

Service katmanı mümkün olduğunca izole test edilmelidir.

---

# Kod Organizasyonu

Backend içerisinde;

* utils klasörü büyütülmez.
* helper dosyaları rastgele oluşturulmaz.
* ortak kod shared katmanına taşınır.

Geçici çözümler kalıcı hale getirilmez.

---

# Dosya Boyutu

Yaklaşık öneriler

* Router ≤ 300 satır
* Service ≤ 500 satır
* Repository ≤ 300 satır

Bir dosya büyümeye başladığında bölünmelidir.

---

# Yeni Özellik Geliştirme

Yeni bir Backend özelliği eklenirken aşağıdaki sıra izlenmelidir.

```text
Issue

↓

Domain

↓

Schema

↓

Repository

↓

Service

↓

Router

↓

Test

↓

Documentation

↓

Pull Request
```

---

# Yapılmaması Gerekenler

Backend içerisinde;

* Prompt yazılmaz.
* HTML üretilmez.
* React mantığı bulunmaz.
* MCP Server geliştirilmez.
* LLM Provider kodu yazılmaz.
* Embedding algoritması geliştirilmez.

Bu sorumluluklar ilgili katmanlara aittir.