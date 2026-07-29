# AGENTS.md

> Bu dosya, bu repository üzerinde çalışan tüm AI ajanları ve geliştiriciler için ana çalışma rehberidir.

Bu doküman, proje içerisindeki tüm geliştirme kurallarını tek noktada toplar ve AI ajanlarının projeye tutarlı katkı sağlamasını amaçlar.

---

# Amaç

Bu repository;

* ölçeklenebilir,
* modüler,
* sürdürülebilir,
* AI destekli geliştirmeye uygun

bir yazılım mimarisi üzerine kurulmuştur.

Kod üretirken yalnızca çalışan kod yazmak yeterli değildir.

Üretilen kod;

* mimariye uygun,
* test edilebilir,
* dokümante edilmiş,
* okunabilir

olmalıdır.

---

# Repository Yapısı

Repository üç ana geliştirme alanından oluşur.

```text
backend/
frontend/
docs/
```

## backend/

Backend;

* API
* Business Logic
* AI Core
* Database
* Cache
* RAG
* MCP
* Infrastructure

katmanlarını içerir.

---

## frontend/

Frontend;

* kullanıcı arayüzü,
* sayfalar,
* bileşenler,
* servisler,
* durum yönetimi

katmanlarını içerir.

---

## docs/

Projenin tüm teknik dokümantasyonu burada bulunur.

Kod geliştirilirken gerekli durumlarda ilgili dokümanlar güncellenmelidir.

---

# Geliştirmeye Başlamadan Önce

Her geliştirme aşağıdaki sırayı takip etmelidir.

```text
1. README.md

↓

2. AGENTS.md

↓

3. docs/architecture/

↓

4. docs/development/

↓

5. İlgili Issue

↓

6. İlgili Milestone

↓

7. Geliştirme
```

Hiçbir AI ajanı veya geliştirici bu adımları atlamamalıdır.

---

# Doküman Okuma Sırası

## Genel

```text
README.md

↓

AGENTS.md
```

---

## Mimari

```text
architecture.md

↓

backend.md

↓

frontend.md

↓

ai.md
```

---

## Geliştirme Standartları

```text
project-rules.md

↓

backend-standards.md

↓

frontend-standards.md

↓

ai-standards.md

↓

naming.md

↓

testing.md

↓

documentation.md

↓

git-workflow.md

↓

code-review.md
```

---

# Çalışma Prensibi

Her geliştirme aşağıdaki döngüyü takip etmelidir.

```text
Issue

↓

Analiz

↓

Mimariyi İncele

↓

Kodla

↓

Test

↓

Dokümantasyonu Güncelle

↓

Commit

↓

Pull Request
```

---

# Mimari Kuralları

Her yeni kod mevcut mimariye uymalıdır.

Mimariyi ihlal eden çözümler tercih edilmemelidir.

Yeni klasörler yalnızca gerçekten gerekli olduğunda oluşturulmalıdır.

Katmanlar arasında gereksiz bağımlılık oluşturulmamalıdır.

---

# Backend Kuralları

Backend geliştirmelerinde;

* Router yalnızca HTTP katmanıdır.
* Service iş mantığını içerir.
* Repository veri erişiminden sorumludur.
* Business Logic Router içerisinde yazılmaz.
* Dependency Injection korunmalıdır.

Detaylar için:

```text
docs/development/backend-standards.md
```

---

# Frontend Kuralları

Frontend geliştirmelerinde;

* Component tek sorumluluklu olmalıdır.
* Hook yalnızca yeniden kullanılabilir mantık içermelidir.
* API çağrıları Service katmanında olmalıdır.
* Sayfalar gereksiz iş mantığı içermemelidir.

Detaylar için:

```text
docs/development/frontend-standards.md
```

---

# AI Kuralları

AI geliştirmelerinde;

* Workflow tek sorumluluğa sahip olmalıdır.
* Agent yalnızca uzman olduğu işi yapmalıdır.
* Prompt merkezi yönetilmelidir.
* Tool güvenli olmalıdır.
* Memory doğru kullanılmalıdır.

Detaylar için:

```text
docs/development/ai-standards.md
```

---

# İsimlendirme

Yeni oluşturulan;

* dosyalar,
* klasörler,
* sınıflar,
* fonksiyonlar,
* endpoint'ler

isimlendirme standartlarına uygun olmalıdır.

Detaylar için:

```text
docs/development/naming.md
```

---

# Test

Yeni geliştirilen her özellik uygun seviyede test edilmelidir.

Gerekli durumlarda;

* Unit Test
* Integration Test
* Component Test
* Workflow Test
* E2E Test

eklenmelidir.

Detaylar için:

```text
docs/development/testing.md
```

---

# Dokümantasyon

Kod değişiklikleri aşağıdaki dokümanları etkiliyorsa güncellenmelidir.

* README
* Architecture
* Development
* API
* AI

> [!IMPORTANT]
> **CHANGELOG Güncelleme Kuralı**: Projeye katkı sağlayan her geliştirici ve yapay zekâ ajanı (AI Agent), yaptığı anlamlı değişiklikleri ana dizindeki [CHANGELOG.md](file:///Users/gokdenizkuruca/Desktop/Projeler/Teknofest%20NLP/Ads%C4%B1z/KACHOW-Teknofest-2026/CHANGELOG.md) dosyasına uygun sürüm başlığı altında eklemek zorundadır.

Detaylar için:

```text
docs/development/documentation.md
```

---

# Git Süreci

Her geliştirme;

Issue

↓

Branch

↓

Development

↓

Commit

↓

Push

↓

Pull Request

↓

Review

↓

Merge

sürecini takip etmelidir.

Doğrudan main branch üzerinde geliştirme yapılmamalıdır.

Detaylar için:

```text
docs/development/git-workflow.md
```

---

# Code Review

Kod tamamlandıktan sonra aşağıdaki sorular cevaplanmalıdır.

* Mimariye uygun mu?
* Testler var mı?
* Dokümantasyon güncel mi?
* Güvenlik korunuyor mu?
* Performans etkileniyor mu?

Detaylar için:

```text
docs/development/code-review.md
```

---

# Yeni Feature Geliştirme

Yeni bir özellik geliştirirken aşağıdaki süreç uygulanmalıdır.

```text
Issue

↓

İlgili dokümanları incele

↓

Mevcut mimariyi analiz et

↓

Geliştirme planı oluştur

↓

Kod geliştir

↓

Test yaz

↓

Dokümantasyonu güncelle

↓

Commit

↓

Pull Request
```

---

# Yeni Dosya Oluşturma

Yeni dosya oluşturulmadan önce aşağıdaki sorular sorulmalıdır.

* Aynı işi yapan dosya mevcut mu?
* Bu dosya doğru klasörde mi?
* Mimariye uygun mu?
* Tek sorumluluğa sahip mi?

Gereksiz dosya oluşturulmamalıdır.

---

# Refactoring

Refactoring sırasında;

* davranış değiştirilmemelidir,
* testler korunmalıdır,
* isimlendirme iyileştirilmelidir,
* gereksiz tekrarlar kaldırılmalıdır.

---

# Güvenlik

Hiçbir AI ajanı;

* API anahtarı eklememeli,
* şifre yazmamalı,
* gizli bilgi üretmemeli,
* güvenlik kontrollerini kaldırmamalıdır.

---

# Performans

Yeni geliştirmelerde;

* gereksiz döngülerden,
* gereksiz render'lardan,
* gereksiz LLM çağrılarından,
* gereksiz veritabanı sorgularından

kaçınılmalıdır.

---

# AI Davranış Kuralları

Bu repository üzerinde çalışan AI ajanları aşağıdaki prensiplere uymalıdır.

* Mevcut mimariyi koru.
* Gereksiz dosya oluşturma.
* Gereksiz bağımlılık ekleme.
* Mevcut standartları ihlal etme.
* Kod tekrarından kaçın.
* En basit doğru çözümü tercih et.
* Gerektiğinde mevcut kodu yeniden kullan.
* Değişiklik kapsamını minimumda tut.
* Yeni teknoloji eklemeden önce mevcut çözümleri değerlendir.

---

# Yapılmaması Gerekenler

* Standartları okumadan kod üretmek
* Katman ihlali yapmak
* Testsiz geliştirme yapmak
* Dokümantasyonu güncellememek
* Gereksiz paket eklemek
* Büyük ve kontrolsüz refactoring yapmak
* Aynı problemi ikinci kez çözmek

---

# Tamamlanma Kontrol Listesi

Bir geliştirme tamamlanmadan önce aşağıdaki liste kontrol edilmelidir.

```text
☐ Issue incelendi

☐ İlgili dokümanlar okundu

☐ Mimariye uygun geliştirildi

☐ Naming kurallarına uyuldu

☐ Testler yazıldı

☐ Testler başarılı

☐ Dokümantasyon güncellendi

☐ Lint başarılı

☐ Build başarılı

☐ Commit Conventional Commits standardına uygun

☐ Pull Request hazır
```

---

# Öncelik Sırası

Kurallar arasında çelişki oluşursa aşağıdaki öncelik sırası uygulanmalıdır.

```text
1. AGENTS.md

↓

2. README.md

↓

3. docs/architecture/

↓

4. docs/development/

↓

5. Kaynak Kod
```

---

# Son Not

Bu doküman, repository üzerinde çalışan tüm geliştiriciler ve AI ajanları için ana referans niteliğindedir.

Kod üretirken amaç yalnızca çalışan bir özellik geliştirmek değil, projenin mimarisini, sürdürülebilirliğini ve kalite standartlarını korumaktır.

Her geliştirme bu dokümandaki kurallara ve referans verilen standartlara uygun olarak gerçekleştirilmelidir.
