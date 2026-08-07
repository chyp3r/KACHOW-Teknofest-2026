# Testing Standards

> Bu doküman proje genelindeki test stratejisini tanımlar.

Bu kurallar Backend, Frontend ve AI katmanlarının tamamı için geçerlidir.

---

# Amaç

Test stratejisinin amacı;

* Hataları erken yakalamak
* Güvenli refactoring yapmak
* Yeni özelliklerin mevcut sistemi bozmamasını sağlamak
* Üretim ortamındaki riskleri azaltmaktır.

---

# Test Piramidi

Projede aşağıdaki yaklaşım benimsenmektedir.

```text
            E2E

      Integration

         Unit
```

En fazla test Unit seviyesinde olmalıdır.

---

# Backend

Backend aşağıdaki seviyelerde test edilir.

## Unit Test

Test edilen yapılar

* Service
* Repository
* Utility
* Validation
* Business Rules

Bağımlılıklar Mock kullanılarak izole edilir.

---

## Integration Test

Test edilen yapılar

* Database
* API
* Cache
* Background Tasks

Gerçek sistem bileşenleri kullanılarak test edilir.

---

## API Test

Test edilen konular

* HTTP Status
* Request Validation
* Response Schema
* Authentication
* Authorization

---

# Frontend

## Component Test

Test edilen yapılar

* Button
* Form
* Modal
* Table
* Card

Component davranışı doğrulanmalıdır.

---

## Hook Test

Custom Hook'lar bağımsız test edilmelidir.

---

## Page Test

Kullanıcı akışları doğrulanmalıdır.

Örnekler

* giriş
* belge yükleme
* sohbet oluşturma
* ayarlar

---

## UI Test

Kontrol edilmesi gerekenler

* Loading
* Error
* Empty State
* Success State

---

# AI

AI katmanı klasik yazılımdan farklı olarak çok seviyeli test edilir.

---

## Tool Test

Her Tool bağımsız test edilmelidir.

Örnekler

* Dosya okuma
* Arama
* Terminal
* Hesaplama

---

## Workflow Test

Workflow'un doğru sırada çalıştığı doğrulanmalıdır.

---

## Agent Test

Her Agent kendi uzmanlık alanında test edilmelidir.

---

## Prompt Test

Prompt;

* doğru format üretmeli,
* beklenen şemaya uymalı,
* hatalı girişleri yönetebilmelidir.

---

## RAG Test

Kontrol edilmesi gerekenler

* Retrieval doğruluğu
* Chunk seçimi
* Ranking
* Context oluşturma

---

## MCP Test

Test edilen konular

* Tool erişimi
* Yetkilendirme
* Hata yönetimi
* Timeout

---

## Evaluation Test

Yeni Agent veya Workflow aşağıdaki metriklerle değerlendirilmelidir.

* Doğruluk
* Tutarlılık
* Başarı oranı
* Ortalama gecikme
* Token kullanımı
* Tool başarı oranı

### Deterministik Karar Katmanı Koşumu

LLM çağrısı yapmayan karar fonksiyonları (`resolve_plan` -- lexical + semantik füzyon,
model hariç -- `verify_draft`) `evaluation/` altındaki koşumla ölçülür.
Ayrıntı: `evaluation/README.md`.

```bash
make eval           # tüm suite'ler -> evaluation/reports/all-latest.{json,md}
make eval-baseline  # değişiklik öncesi referans noktası
```

Bu koşum **test değildir, ölçümdür** ve bilinçle `make test`ten ayrıdır:

* Başarısız bir altın küme vakası, katmanın nerede zayıf olduğu bilgisidir; kırmızı
  build'e çevrilmesi, kodu değil altın kümeyi zayıflatma baskısı yaratır.
* Tam koşum pytest'in 60 sn'lik test başına zaman aşımına sığmaz.

Regresyon kilidi `tests/unit/` altında kalır. Bir eşik veya karar kuralı
değiştiren PR'lar `make eval` çıktısını `--baseline` ile karşılaştırıp raporu
`evaluation/reports/` altına eklemelidir.

> **LLM-as-judge kullanılmaz.** Yerel modelde yüzlerce yargı çağrısı saatler
> sürer ve ölçüm aracının kendisi ölçümdeki en gürültülü terim olur; eşik
> kalibrasyonu için elle yazılmış deterministik altın küme kullanılır.

---

# Mock Kullanımı

Dış bağımlılıklar mümkün olduğunca Mock kullanılmalıdır.

Örnekler

* LLM
* API
* Redis
* PostgreSQL
* Qdrant
* MCP Server

---

# Test Verisi

Test verileri;

* tekrar üretilebilir,
* bağımsız,
* küçük,
* deterministik

olmalıdır.

Gerçek kullanıcı verisi kullanılmamalıdır.

---

# Test İsimleri

İsimler davranışı açıklamalıdır.

Doğru

```text
test_create_chat_session

test_upload_document

test_search_documents

test_stream_response
```

Yanlış

```text
test1

test_api

chat_test
```

---

# Test Organizasyonu

Her modül kendi testine sahip olmalıdır.

Örnek

```text
tests/

backend/

frontend/

ai/

integration/

e2e/
```

Testler üretim kodunun yapısını mümkün olduğunca takip etmelidir.

---

# Başarı Kriteri

Bir geliştirme tamamlanmış sayılabilmesi için;

* ilgili testler yazılmış olmalıdır,
* mevcut testler başarılı olmalıdır,
* yeni testler başarısız olmamalıdır.

---

# Yapılmaması Gerekenler

* Testsiz kritik özellik geliştirmek
* Gerçek API anahtarları kullanmak
* Ağ bağlantısına bağımlı test yazmak
* Rastgele sonuç üreten testler yazmak
* Birbirine bağımlı test senaryoları oluşturmak

---

# Sürekli Entegrasyon

Her Pull Request otomatik test sürecinden geçmelidir.

Başarısız test bulunan Pull Request birleştirilmez.

---

# İlgili Dokümanlar

Bu doküman aşağıdaki dosyalarla birlikte değerlendirilmelidir.

* project-rules.md
* backend-standards.md
* frontend-standards.md
* ai-standards.md
