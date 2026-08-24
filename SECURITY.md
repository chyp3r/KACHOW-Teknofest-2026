# KACHOW Güvenlik Politikası (Security Policy)

> Bu belge, KACHOW platformunun güvenlik standartlarını, zafiyet bildirim süreçlerini ve sistemin sağladığı yerleşik (built-in) güvenlik kalkanlarını tanımlar.

---

## Desteklenen Sürümler

Aşağıdaki tabloda, güvenlik güncellemelerinin aktif olarak sağlandığı KACHOW sürümleri listelenmektedir:

| Sürüm | Destek Durumu | Açıklama |
| :--- | :--- | :--- |
| `v3.x` | Destekleniyor | Aktif geliştirme dalı (Main branch). Güvenlik yamaları öncelikli olarak buraya uygulanır. |
| `v2.x` | Yalnızca Kritik | Sadece kritik güvenlik (0-day) açıklarında yama alır. Yeni özellik eklenmez. |
| `< v2.0` | Desteklenmiyor | Güvenlik desteği tamamen kesilmiştir (End-of-Life). |

---

## Güvenlik Zafiyeti Bildirimi (Reporting a Vulnerability)

Güvenlik açıklarını (Vulnerability) public Issue olarak açmak **kesinlikle yasaktır.** 
Zafiyetleri sorumlu bir şekilde ifşa etmek (Responsible Disclosure) için aşağıdaki adımları izleyin:

1. **İletişim:** Güvenlik ekibine GitHub Private Vulnerability Reporting üzerinden ulaşın.
2. **Kapsam:** Lütfen açığın nasıl tetiklendiğini, etki alanını (Scope) ve yeniden üretme (Reproduction) adımlarını detaylıca paylaşın.
3. **Süreç:** Ekip, bildirimi 48 saat içinde inceleyerek size bir geri dönüş yapacaktır.

---

## Sistemde Uygulanan Güvenlik Kalkanları (Hardening)

KACHOW sistemi mimari olarak "Sıfır Güven" (Zero-Trust) ve "En Az Yetki" (Least Privilege) prensipleri üzerine kurulmuştur.

### 1. Kimlik ve Erişim Yönetimi (IAM)
- **JWT Koruması:** Tüm API istekleri, süre sınırına (Expiration) sahip şifrelenmiş JWT token'ları ile korunur. Prodüksiyonda zayıf bir `SECRET_KEY` tespiti sistemin başlatılmasını engeller (`app.lifespan`).
- **Zorunlu Kimlik Doğrulama:** Prodüksiyon ortamında `REQUIRE_AUTH=false` olarak ayarlanamaz, sistem bu ayarı reddeder.

### 2. Veri İzolasyonu (Multi-Tenancy)
- **Postgres Row-Level Security (RLS):** Uygulama veritabanına sınırlı haklara sahip `kachow_app` rolü ile bağlanır. Her bir kullanıcının ve şirketin (Company) kendi dışındaki verilere erişimi (Yetki sızması) veritabanı motoru seviyesinde engellenmiştir.
- **Şema Göçleri (Migrations):** Kısıtlı uygulama rolü (`DATABASE_URL`) tablo yaratamaz (DDL çalıştıramaz). Bu işlem yalnızca sahip (Owner) rolü üzerinden güvenli Kubernetes Job'larıyla gerçekleştirilir.

### 3. Yapay Zeka (AI) Güvenliği
- **LLM Yargıçları (Guardrails):** Yapay Zekâ'nın dışarı sızdırabileceği Hassas Veriler (PII) ve Prompt Injection (Talimat Enjeksiyonu) saldırıları, özel Güvenlik Yargıçları (Guardrail Judges) tarafından filtrelenir.
- **Metin Temizliği:** OCR ile okunan evrak metinleri, ajan (Agent) istemlerine (Prompt) dahil edilmeden önce `scrub_extracted_text()` filtresinden geçer (Örn: Bidi karakter temizliği).

### 4. Altyapı ve Ağ Güvenliği
- **Non-Root Konteynerler:** Tüm Docker konteynerleri kısıtlı (Non-root) kullanıcı yetkileriyle (uid=10001 / uid=101) çalışır.
- **Ağ Politikaları (NetworkPolicies):** Kubernetes ortamında varsayılan "Reddet" (Default-Deny) politikası geçerlidir. Sadece izin verilen bileşenler arası trafiğe (Örn: API -> Qdrant, API -> Ollama) izin verilir.
- **Read-Only Dosya Sistemi:** Pod'lar salt okunur dosya sistemiyle çalışır, sadece belirlenmiş klasörlere (Örn: `/tmp`) geçici yazma izni verilir.

---

## Uyarılar (Disclaimer)

- Platformda kullanılan **Açık Kaynak LLM** modellerinin (Örn: Ollama üzerinden çalışan LLaMA/Qwen) üreteceği metinlerden doğabilecek halüsinasyon (Hallucination) ve mantık hataları kullanıcı sorumluluğundadır. Güvenlik kalkanları (Guardrails) bunu minimize etmek içindir, ancak %100 garanti vermez.
