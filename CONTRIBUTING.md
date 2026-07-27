# Katkı Rehberi

Bu doküman projeye katkı sağlayacak geliştiriciler ve yapay zekâ araçları için geliştirme sürecini tanımlar.

---

# Geliştirme Akışı

Yeni geliştirme yapılırken aşağıdaki sıra izlenmelidir.

1. Güncel kodu al.
2. Yeni branch oluştur.
3. Geliştirmeyi yap.
4. Testleri çalıştır.
5. Dokümantasyonu güncelle.
6. Pull Request oluştur.

---

# Branch Kuralları

Yeni özellik

feature/<özellik>

Hata düzeltme

fix/<konu>

Refactor

refactor/<konu>

Dokümantasyon

docs/<konu>

Test

test/<konu>

---

# Commit Kuralları

Commit mesajları Conventional Commits standardını takip etmelidir.

Örnekler

feat: add document upload service

fix: resolve redis connection issue

refactor: simplify chat workflow

docs: update architecture documentation

test: add repository unit tests

chore: update dependencies

---

# Pull Request Kuralları

Her Pull Request

* Tek bir amaca hizmet etmelidir.
* Gereksiz dosya içermemelidir.
* Açıklayıcı başlığa sahip olmalıdır.
* Testlerden geçmiş olmalıdır.

---

# Kod İnceleme Kontrol Listesi

Kod incelenirken aşağıdaki maddeler kontrol edilir.

## Mimari

* Doğru domain kullanılmış mı?
* Katman ihlali var mı?
* Repository Pattern korunmuş mu?
* AI katmanı doğru kullanılmış mı?

## Kod Kalitesi

* Type Hint var mı?
* Kod okunabilir mi?
* Gereksiz tekrar var mı?
* Fonksiyonlar küçük mü?

## Performans

* Gereksiz sorgu var mı?
* Gereksiz nesne oluşturuluyor mu?
* Cache kullanılabilir miydi?

## Güvenlik

* Gizli bilgi eklenmiş mi?
* Yetkilendirme kontrol edilmiş mi?
* Input doğrulaması yapılmış mı?

## Test

* Yeni test eklendi mi?
* Eski testler geçiyor mu?

---

# Dokümantasyon

Yeni özellik geliştirildiğinde aşağıdaki dokümanlar gerekirse güncellenmelidir.

* README.md
* architecture.md
* API dokümantasyonu
* ilgili geliştirme dokümanları

---

# Kod Kalitesi Araçları

Kod gönderilmeden önce

* Ruff
* Black
* Pytest

çalıştırılmalıdır.

Frontend değişikliklerinde

* ESLint
* Prettier
* Build

başarılı olmalıdır.

---

# AI ile Geliştirme

Yapay zekâ tarafından üretilen kod doğrudan kabul edilmez.

Aşağıdaki kontroller yapılmalıdır.

* Mimariye uygun mu?
* Gereksiz dosya oluşturmuş mu?
* Mevcut kod tekrar edilmiş mi?
* Test yazılmış mı?
* Dokümantasyon güncellenmiş mi?

---

# Tamamlanmış Bir Özelliğin Tanımı

Bir geliştirme aşağıdaki şartları sağlıyorsa tamamlanmış kabul edilir.

* Kod çalışıyor.
* Testler başarılı.
* Lint hatası yok.
* Mimariye uygun.
* Dokümantasyon güncel.
* Kod incelemesinden geçti.
* Pull Request onaylandı.
