# Katkı Rehberi (Contributing Guidelines)

> Bu doküman, KACHOW projesine katkı sağlayacak geliştiriciler (İnsan) ve otonom Yapay Zekâ (AI) araçları için kodlama, branch, commit ve PR süreçlerini standartlaştırır.

---

## 1. Geliştirme Yaşam Döngüsü

Yeni bir geliştirme yapılırken aşağıdaki sıra izlenmelidir. Mimari kararların korunması esastır.

1. **Görev (Issue):** Geliştirmeye başlamadan önce bir Issue oluşturun veya atanmış bir Issue üzerinden ilerleyin.
2. **Kodu Senkronize Et:** Güncel `main` veya `develop` dalını çekin.
3. **Branch Oluştur:** Kurallara uygun bir feature/fix dalı oluşturun.
4. **Geliştirme & Test:** Kodu yazın ve Unit/Integration testlerini tamamlayın.
5. **Kalite Kontrol (Lint):** Ruff, Black, ESLint vb. araçlardan geçirin.
6. **Dokümantasyon:** Eğer API veya Mimari etkilendiyse, ilgili `docs/` klasöründeki belgeleri ve `CHANGELOG.md` dosyasını güncelleyin.
7. **Pull Request (PR):** İnceleme için PR açın.

---

## 2. İsimlendirme ve Şablon Kuralları

### Branch Kuralları

| Amaç | Format | Örnek |
| :--- | :--- | :--- |
| Yeni Özellik | `feature/<konu>` | `feature/document-upload` |
| Hata Düzeltme | `fix/<konu>` | `fix/redis-timeout` |
| Yeniden Düzenleme| `refactor/<konu>` | `refactor/chat-workflow` |
| Dokümantasyon | `docs/<konu>` | `docs/update-architecture` |
| Test Yazımı | `test/<konu>` | `test/auth-services` |
| Altyapı / CI | `ci/<konu>` veya `chore/<konu>` | `chore/update-deps` |

### Commit Kuralları (Conventional Commits)

Commit mesajları Semantic Versiyonlama prensiplerini takip etmelidir.

- `feat(chat): sohbet sistemi eklendi`
- `fix(auth): token yenileme problemi düzeltildi`
- `refactor(ai): workflow sadeleştirildi`
- `docs(readme): mimari güncellendi`
- `test(chat): servis testleri eklendi`
- `ci(docker): compose dosyası güncellendi`
- `chore(deps): bağımlılıklar güncellendi`

> **Kural:** Her commit tek bir mantıksal değişikliği kapsamalıdır. 50 dosyalık devasa (Spaghetti) commit'ler reddedilir.

---

## 3. Pull Request (PR) Süreci

Bir Pull Request açarken aşağıdaki kriterleri sağlamanız beklenir:

- Tek bir Issue'yu (Problemi) çözmelidir.
- PR başlığı açıklayıcı olmalıdır (Örn: `feat: Add S3 Storage Support`).
- Gerekli tüm testler (CI/CD) başarılı olmalıdır.
- Kod incelemesinden (Code Review) geçmeden ve en az 1 onay almadan asla merge edilemez.

---

## 4. Kod İnceleme (Code Review) Kriterleri

İncelemeyi yapan mühendis veya AI ajanı şu sorulara yanıt aramalıdır:

| Kategori | Kontrol Listesi |
| :--- | :--- |
| **Mimari (Architecture)** | Doğru Domain kullanılmış mı? Katman ihlali (Örn: Router'da iş mantığı yazmak) var mı? Repository ve Service kalıpları korunmuş mu? |
| **Kod Kalitesi (Quality)** | Type Hint (Tip belirtimleri) tam mı? Fonksiyonlar Single Responsibility (Tek sorumluluk) ilkesine uyuyor mu? |
| **Performans (Performance)** | N+1 sorgu problemi var mı? Redis Cache kullanılabilir miydi? Gereksiz re-render (Frontend) var mı? |
| **Güvenlik (Security)** | Sırlar koda gömülmüş mü? (Yasak). Endpoint Authorization kontrolü yapılmış mı? User Input sanitize edilmiş mi? |
| **Test Edilebilirlik (Testing)**| Edge-case'ler için (Sınır durumları) yeni Unit Test yazılmış mı? Mevcut testler bozulmuş mu? |

---

## 5. Yapay Zeka (AI) Katkı Kuralları

Projeye katkı sağlayan tüm AI ajanları (Aider, Antigravity, Cursor vb.) aşağıdaki politikalara sıkı sıkıya uymalıdır:

1. Kodu üretmeden önce daima `AGENTS.md` ve `docs/development/project-rules.md` referanslarını oku.
2. Yeni bir kütüphane (Dependency) eklemeden önce mevcut standart kütüphaneler ile çözülüp çözülemeyeceğini kontrol et.
3. Kodu üretmekle kalma; testini yaz ve etkilenen dokümanları (**CHANGELOG.md dahil**) güncelle.
4. Emojileri dokümantasyonlarda ve resmi metinlerde kesinlikle kullanma.
5. Kullanıcıdan onay (Review) almadan sistem dosyalarını silme veya büyük Refactor'lar yapma.
