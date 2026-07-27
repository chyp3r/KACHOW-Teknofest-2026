# Project Rules

> Bu doküman proje genelinde geçerli olan geliştirme kurallarını tanımlar.

Bu kurallar Backend, Frontend, AI, DevOps ve gelecekte eklenecek tüm modüller için geçerlidir.

Her geliştirici ve AI destekli geliştirme aracı bu kurallara uymakla yükümlüdür.

---

# Amaç

Bu dokümanın amacı;

* Kod tabanının tutarlılığını korumak
* Uzun vadeli bakım maliyetini azaltmak
* Mimari bütünlüğü korumak
* Ekip içi geliştirme sürecini standartlaştırmak
* AI destekli geliştirmeyi güvenilir hale getirmektir.

---

# Temel İlkeler

Projede aşağıdaki prensipler esas alınır.

* Okunabilirlik
* Basitlik
* Modülerlik
* Test edilebilirlik
* Sürdürülebilirlik
* Genişletilebilirlik
* Tekrarsız geliştirme
* Açık dokümantasyon

Yeni geliştirilen her özellik bu prensiplere uygun olmalıdır.

---

# Tek Doğru Kaynak

Bir bilginin sistem içerisinde yalnızca tek bir sahibi olmalıdır.

Örnekler

* Bir endpoint yalnızca tek bir router içerisinde tanımlanır.
* Bir veri modeli yalnızca tek bir yerde tanımlanır.
* Bir sabit değer yalnızca tek bir dosyada bulunur.
* Bir iş kuralı yalnızca tek bir servis tarafından yönetilir.

Aynı bilginin birden fazla yerde tutulmasından kaçınılmalıdır.

---

# Mimariye Bağlılık

Kod mevcut mimariye uyum sağlamalıdır.

Hiçbir geliştirme mimariyi ihlal edecek şekilde uygulanmamalıdır.

Yeni gereksinimler mevcut yapıya uygun olarak sisteme entegre edilmelidir.

Mimari değişiklikleri doğrudan uygulanmaz.

Önce değerlendirilir, ardından dokümantasyonu güncellenir.

---

# Dokümantasyon Önceliklidir

Yeni bir geliştirme aşağıdaki durumlarda dokümantasyon gerektirir.

* Yeni modül
* Yeni servis
* Yeni API
* Yeni AI workflow'u
* Yeni altyapı bileşeni
* Mimari değişiklik

Kod ve dokümantasyon birlikte güncellenmelidir.

---

# Kod Sahipliği

Proje ortak kod sahipliği yaklaşımını benimser.

Hiçbir klasör veya modül belirli bir kişiye ait değildir.

Tüm ekip üyeleri gerekli incelemeleri yaparak herhangi bir modüle katkı sağlayabilir.

---

# Küçük Değişiklikler

Her Pull Request tek bir amacı gerçekleştirmelidir.

Kaçınılması gereken örnekler

* Yeni özellik + refactor
* Refactor + bug fix
* Bug fix + bağımlılık güncellemesi

Her değişiklik mümkün olduğunca küçük tutulmalıdır.

---

# Tek Sorumluluk

Her dosya tek bir sorumluluğa sahip olmalıdır.

Her sınıf tek bir amaç taşımalıdır.

Her fonksiyon tek bir işi yapmalıdır.

Bir dosya farklı amaçlar için büyümeye başladığında bölünmelidir.

---

# Yeniden Kullanılabilirlik

Tekrar eden kod kabul edilmez.

Ortak kullanılan yapılar merkezi hale getirilmelidir.

Kopyala-yapıştır geliştirme yaklaşımı kullanılmaz.

---

# Gereksiz Karmaşıklık

İhtiyaç duyulmayan yapı sisteme eklenmez.

Aşağıdakilerden kaçınılmalıdır.

* Gereksiz abstraction
* Kullanılmayan yardımcı fonksiyonlar
* Erken optimizasyon
* Kullanılmayan bağımlılıklar
* Kullanılmayan sınıflar

Basit çözümler her zaman önceliklidir.

---

# Dosya Organizasyonu

Kod mevcut klasör yapısına uygun olarak eklenmelidir.

Hiçbir dosya rastgele oluşturulmamalıdır.

Yeni klasör açılması gerekiyorsa önce mevcut mimari değerlendirilmelidir.

---

# Ortak Kod

Ortak kullanılan kod ilgili ortak modüle taşınmalıdır.

Aynı yardımcı fonksiyon farklı klasörlerde tekrar edilmemelidir.

---

# Bağımlılık Yönetimi

Yeni bağımlılık eklenmeden önce aşağıdaki sorular değerlendirilmelidir.

* Gerçekten gerekli mi?
* Mevcut çözüm yeterli değil mi?
* Bakım maliyeti nedir?
* Güvenilir mi?
* Lisansı uygun mu?

Her bağımlılık gerekçelendirilebilir olmalıdır.

---

# Konfigürasyon

Hiçbir yapılandırma doğrudan kaynak koduna yazılmaz.

Örnekler

* API anahtarları
* Şifreler
* URL'ler
* Token'lar
* Port numaraları

Bu bilgiler yapılandırma dosyalarından okunmalıdır.

---

# Hata Yönetimi

Hatalar gizlenmez.

Beklenen tüm hatalar kontrollü şekilde yönetilir.

Anlaşılır hata mesajları üretilmelidir.

Sessizce başarısız olan kod yazılmamalıdır.

---

# Loglama

Sistem önemli olayları kayıt altına almalıdır.

Log kayıtları;

* anlamlı,
* izlenebilir,
* filtrelenebilir

olmalıdır.

Gizli bilgiler loglara yazılmaz.

---

# Güvenlik

Tüm geliştirmeler güvenlik göz önünde bulundurularak yapılmalıdır.

Varsayılan yaklaşım en az yetki ilkesidir.

Hiçbir kullanıcı girdisine güvenilmez.

---

# Performans

Performans optimizasyonu ölçülebilir verilere dayanmalıdır.

Tahmine dayalı optimizasyon yapılmaz.

Önce doğru çalışan sistem geliştirilir.

Daha sonra ölçülerek optimize edilir.

---

# Test

Yeni geliştirilen özellik mümkün olduğunca test edilmelidir.

Hatalar üretim ortamında değil geliştirme sürecinde yakalanmalıdır.

Kritik iş kuralları testsiz bırakılmamalıdır.

---

# Git Kullanımı

Tüm geliştirmeler Git üzerinden takip edilir.

Doğrudan ana dala geliştirme yapılmaz.

Her geliştirme ayrı bir branch üzerinde gerçekleştirilir.

Git ile ilgili ayrıntılar `git-workflow.md` dokümanında açıklanmaktadır.

---

# Kod İnceleme

Kod incelemesi geliştirme sürecinin zorunlu bir parçasıdır.

Kod yalnızca çalışıyor olduğu için kabul edilmez.

Aşağıdaki kriterler değerlendirilir.

* Mimari uyumluluk
* Okunabilirlik
* Test kapsamı
* Güvenlik
* Performans
* Dokümantasyon

---

# AI Destekli Geliştirme

Projede AI destekli geliştirme kullanılmaktadır.

AI tarafından üretilen kodlar da insan tarafından yazılmış kodlarla aynı standartlara tabidir.

AI tarafından üretilen hiçbir kod doğrudan kabul edilmez.

Her çıktı geliştirici tarafından incelenmeli ve doğrulanmalıdır.

---

# Dokümantasyon Hiyerarşisi

Dokümanlar aşağıdaki sırayla okunmalıdır.

```text
README.md

↓

AGENTS.md

↓

docs/architecture/

↓

docs/development/

↓

İlgili modül
```

---

# Bu Dokümanın Kapsamı

Bu doküman yalnızca proje genelindeki kuralları tanımlar.

Alan bazlı geliştirme standartları aşağıdaki dokümanlarda açıklanmaktadır.

* backend-standards.md
* frontend-standards.md
* ai-standards.md

Bu doküman ile alan bazlı standartlar birlikte değerlendirilmelidir.
