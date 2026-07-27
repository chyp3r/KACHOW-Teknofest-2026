# Code Review Standards

> Bu doküman proje genelindeki kod inceleme (Code Review) standartlarını tanımlar.

Bu kurallar Backend, Frontend, AI ve altyapı geliştirmelerinin tamamı için geçerlidir.

Kod incelemesi yalnızca hataları bulmak için değil, proje kalitesini korumak için yapılır.

---

# Amaç

Code Review sürecinin amacı;

* Kod kalitesini korumak
* Mimari bütünlüğü sağlamak
* Teknik borç oluşmasını engellemek
* Bilgi paylaşımını artırmak
* Güvenlik risklerini azaltmak
* Performans problemlerini erken yakalamaktır.

---

# Genel İlkeler

Her Pull Request incelenmelidir.

Kod yalnızca çalışıyor olduğu için kabul edilmez.

İnceleme;

* yapıcı,
* teknik,
* objektif

olmalıdır.

Kişiler değil kod değerlendirilir.

---

# Review Süreci

Her Pull Request aşağıdaki sırayla değerlendirilmelidir.

```text
Pull Request

↓

Kod İncelemesi

↓

Gerekli Düzeltmeler

↓

Tekrar İnceleme

↓

Onay

↓

Merge
```

---

# İnceleme Sırası

Kod aşağıdaki sırayla incelenmelidir.

```text
Mimari

↓

İş Mantığı

↓

Güvenlik

↓

Performans

↓

Kod Kalitesi

↓

Testler

↓

Dokümantasyon
```

---

# Mimari Kontrolü

Aşağıdaki sorular cevaplanmalıdır.

* Kod mevcut mimariye uygun mu?
* Yanlış katmana kod eklenmiş mi?
* Yeni dosya doğru klasöre eklenmiş mi?
* Domain sınırları korunmuş mu?
* Gereksiz bağımlılık oluşmuş mu?

---

# Backend Kontrolü

Kontrol edilmesi gerekenler.

* Router yalnızca HTTP katmanı mı?
* Service yalnızca iş mantığını mı içeriyor?
* Repository veri erişimi dışında iş yapıyor mu?
* Validation doğru yerde mi?
* Exception yönetimi uygun mu?
* Dependency Injection korunmuş mu?

---

# Frontend Kontrolü

Kontrol edilmesi gerekenler.

* Component tek sorumluluğa sahip mi?
* Hook doğru kullanılmış mı?
* API çağrıları Service katmanında mı?
* State doğru seviyede tutuluyor mu?
* Responsive yapı korunmuş mu?
* Accessibility etkilenmiş mi?

---

# AI Kontrolü

Kontrol edilmesi gerekenler.

* Yeni Workflow doğru tasarlanmış mı?
* Agent tek sorumluluğa sahip mi?
* Prompt merkezi olarak yönetiliyor mu?
* Tool gereksiz yetki kullanıyor mu?
* RAG doğru katmanda mı?
* Memory doğru kullanılıyor mu?
* Context gereğinden büyük mü?

---

# Güvenlik Kontrolü

Kontrol edilmesi gerekenler.

* Gizli bilgiler kaynak kodunda var mı?
* Yetkilendirme doğru uygulanmış mı?
* Kullanıcı girdileri doğrulanıyor mu?
* Hassas bilgiler loglanıyor mu?
* Dosya erişimleri güvenli mi?
* Tool çağrıları güvenli mi?

---

# Performans Kontrolü

Kontrol edilmesi gerekenler.

* Gereksiz döngüler var mı?
* Gereksiz LLM çağrıları var mı?
* Gereksiz API çağrıları var mı?
* Gereksiz render oluşuyor mu?
* Cache kullanılmalı mı?
* N+1 sorgusu oluşuyor mu?

---

# Kod Kalitesi

Kontrol edilmesi gerekenler.

* İsimlendirme standartlara uygun mu?
* Dosya gereğinden büyük mü?
* Fonksiyon tek sorumluluğa sahip mi?
* Kod okunabilir mi?
* Tekrarlayan kod var mı?

---

# Test Kontrolü

Kontrol edilmesi gerekenler.

* Yeni test yazılmış mı?
* Mevcut testler başarılı mı?
* Kritik senaryolar test edilmiş mi?
* AI Workflow testleri güncel mi?

---

# Dokümantasyon Kontrolü

Aşağıdaki sorular sorulmalıdır.

* README etkileniyor mu?
* Architecture güncellenmeli mi?
* Development dokümanları etkileniyor mu?
* Yeni API dokümante edilmiş mi?
* Yeni AI bileşeni açıklanmış mı?

---

# Pull Request Boyutu

PR mümkün olduğunca küçük olmalıdır.

Önerilen sınırlar

* Tek özellik
* Tek hata düzeltmesi
* Tek refactoring

Büyük PR'lar mümkün olduğunca bölünmelidir.

---

# Yapıcı Geri Bildirim

Yorumlar çözüm odaklı olmalıdır.

Doğru örnekler

* Bu sorumluluk Service katmanına taşınabilir.
* Bu Component iki parçaya ayrılabilir.
* Bu Tool daha güvenli hale getirilebilir.

Kaçınılması gerekenler

* Bu kötü olmuş.
* Baştan yaz.
* Beğenmedim.

---

# AI Tarafından Üretilen Kod

AI tarafından üretilen kodlar da aynı standartlara tabidir.

İnceleme sırasında özellikle aşağıdaki konular kontrol edilmelidir.

* Halüsinasyon
* Gereksiz karmaşıklık
* Tekrarlayan kod
* Yanlış mimari kullanımı
* Kullanılmayan kod
* Güvenlik açıkları

---

# Merge Kriterleri

Bir Pull Request aşağıdaki şartlar sağlanmadan birleştirilmez.

* Mimari uygun
* Testler başarılı
* CI başarılı
* Dokümantasyon güncel
* Kritik yorumlar çözüldü
* Çakışmalar giderildi

---

# Review Checklist

Merge öncesinde aşağıdaki liste tamamlanmalıdır.

```text
☐ Mimari uygun

☐ Doğru klasör kullanılmış

☐ Kod okunabilir

☐ İsimlendirme doğru

☐ Testler mevcut

☐ Testler başarılı

☐ Dokümantasyon güncel

☐ Güvenlik kontrol edildi

☐ Performans değerlendirildi

☐ Gereksiz kod yok

☐ Lint hatası yok

☐ Build başarılı
```

---

# AI Review Checklist

AI geliştirmeleri için ek kontrol listesi.

```text
☐ Prompt doğru yerde

☐ Workflow uygun

☐ Agent tek sorumluluklu

☐ Tool güvenli

☐ Memory doğru

☐ Context optimize

☐ Token kullanımı makul

☐ Gözlemlenebilirlik korunmuş
```

---

# Yapılmaması Gerekenler

* Testsiz Merge
* Dokümantasyonsuz özellik eklemek
* Çok büyük PR oluşturmak
* Review yapılmadan Merge
* Açıklamasız değişiklik yapmak
* Mimariyi ihlal eden kodu kabul etmek

---

# İlgili Dokümanlar

Bu doküman aşağıdaki dosyalar ile birlikte değerlendirilmelidir.

* project-rules.md
* backend-standards.md
* frontend-standards.md
* ai-standards.md
* naming.md
* testing.md
* documentation.md
* git-workflow.md
* AGENTS.md
