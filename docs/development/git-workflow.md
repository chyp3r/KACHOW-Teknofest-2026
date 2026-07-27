# Git Workflow

> Bu doküman proje içerisinde kullanılacak Git çalışma modelini tanımlar.

Tüm ekip üyeleri ve AI destekli geliştirme araçları bu iş akışına uymalıdır.

---

# Amaç

Bu iş akışının amacı;

* Düzenli geliştirme süreci oluşturmak
* Çakışmaları azaltmak
* Kod incelemelerini kolaylaştırmak
* Her değişikliği izlenebilir hale getirmek
* Güvenli sürüm yönetimi sağlamaktır.

---

# Ana Branch'ler

Repository içerisinde aşağıdaki ana branch'ler bulunur.

```text
main
develop
```

## main

Üretime hazır kodu içerir.

Doğrudan geliştirme yapılmaz.

Doğrudan commit atılmaz.

Force Push yapılmaz.

---

## develop

Güncel geliştirme branch'idir.

Yeni özellikler önce develop üzerinde birleştirilir.

---

# Branch Türleri

Her geliştirme uygun branch türünde yapılmalıdır.

## Feature

Yeni özellik geliştirmek için kullanılır.

```text
feature/chat-streaming

feature/document-upload

feature/rag-pipeline
```

---

## Fix

Hata düzeltmeleri.

```text
fix/login

fix/upload-timeout

fix/chat-history
```

---

## Refactor

Davranışı değiştirmeyen kod iyileştirmeleri.

```text
refactor/backend

refactor/chat-service

refactor/sidebar
```

---

## Docs

Dokümantasyon değişiklikleri.

```text
docs/readme

docs/api

docs/architecture
```

---

## Test

Test geliştirmeleri.

```text
test/chat

test/rag

test/workflow
```

---

## Chore

Bakım işlemleri.

Örnekler

* bağımlılık güncellemesi
* Docker düzenlemesi
* CI güncellemesi

```text
chore/docker

chore/github-actions
```

---

# Geliştirme Süreci

Her geliştirme aşağıdaki sırayı takip eder.

```text
Issue

↓

Branch

↓

Development

↓

Local Test

↓

Commit

↓

Push

↓

Pull Request

↓

Code Review

↓

Merge

↓

Delete Branch
```

---

# Issue Yönetimi

Her geliştirme bir Issue ile başlamalıdır.

Issue;

* amacı açıklamalıdır,
* kapsamı belirtmelidir,
* tamamlanma kriterlerini içermelidir.

Issue açılmadan geliştirme başlatılmamalıdır.

---

# Milestone Kullanımı

Issue'lar uygun Milestone altında toplanmalıdır.

Her Issue mümkünse bir Milestone'a bağlı olmalıdır.

---

# Branch Oluşturma

Her Branch yalnızca tek bir Issue'yu çözmelidir.

Bir Branch içerisinde farklı özellikler geliştirilmemelidir.

---

# Commit Kuralları

Projede Conventional Commits standardı kullanılır.

Format

```text
type(scope): message
```

---

## feat

Yeni özellik.

```text
feat(chat): add streaming support
```

---

## fix

Hata düzeltmesi.

```text
fix(auth): refresh expired token
```

---

## docs

Dokümantasyon.

```text
docs(ai): update workflow documentation
```

---

## refactor

Davranış değiştirmeyen iyileştirme.

```text
refactor(chat): simplify service layer
```

---

## test

Test geliştirmeleri.

```text
test(rag): add retrieval tests
```

---

## chore

Bakım işlemleri.

```text
chore(ci): update github actions
```

---

# Commit Boyutu

Commit mümkün olduğunca küçük olmalıdır.

Tek commit içerisinde;

* yeni özellik
* refactor
* bug fix

birlikte bulunmamalıdır.

---

# Push

Push işleminden önce;

* proje derlenmelidir,
* testler çalıştırılmalıdır,
* lint hataları giderilmelidir.

---

# Pull Request

Her geliştirme Pull Request üzerinden birleştirilir.

Doğrudan Merge yapılmaz.

---

# Pull Request Başlığı

Başlık kısa ve açıklayıcı olmalıdır.

Örnekler

```text
Add streaming chat support

Improve RAG retrieval performance

Refactor document indexing
```

---

# Pull Request Açıklaması

Her PR aşağıdaki bilgileri içermelidir.

* Amaç
* Yapılan değişiklikler
* Etkilenen modüller
* Test durumu
* Gerekli ekran görüntüleri (Frontend ise)

---

# Code Review

Merge öncesinde Code Review yapılmalıdır.

İnceleme sırasında aşağıdaki başlıklar değerlendirilmelidir.

* Mimari
* Kod kalitesi
* Güvenlik
* Performans
* Test
* Dokümantasyon

---

# Merge

PR yalnızca aşağıdaki şartlar sağlandığında birleştirilebilir.

* Review tamamlandı.
* Testler başarılı.
* CI başarılı.
* Çakışma yok.
* Dokümantasyon güncel.

---

# Branch Silme

Merge tamamlandıktan sonra ilgili Feature Branch silinmelidir.

Eski Branch'ler repository'de bırakılmamalıdır.

---

# Hotfix Süreci

Üretim ortamındaki kritik hatalar için ayrı Hotfix Branch'i oluşturulur.

```text
hotfix/login

hotfix/security

hotfix/api
```

Hotfix tamamlandıktan sonra hem main hem develop branch'ine geri taşınmalıdır.

---

# Çatışma Yönetimi

Merge Conflict oluştuğunda;

* geliştirici kendi Branch'ini günceller,
* çakışmaları çözer,
* yeniden test eder,
* tekrar Push eder.

Çakışmalar aceleyle çözülmemelidir.

---

# Yapılmaması Gerekenler

* Doğrudan main branch'ine commit atmak
* Büyük Pull Request oluşturmak
* Testsiz Merge yapmak
* Açıklamasız Commit yazmak
* Force Push kullanmak
* İlgisiz değişiklikleri aynı Branch'e eklemek

---

# Örnek Geliştirme Akışı

```text
Issue Aç

↓

Milestone Ata

↓

feature/chat-streaming

↓

Kod Geliştir

↓

Local Test

↓

Commit

↓

Push

↓

Pull Request

↓

Code Review

↓

Merge

↓

Branch Sil
```

---

# İlgili Dokümanlar

Bu doküman aşağıdaki dosyalar ile birlikte değerlendirilmelidir.

* README.md
* project-rules.md
* naming.md
* testing.md
* code-review.md
