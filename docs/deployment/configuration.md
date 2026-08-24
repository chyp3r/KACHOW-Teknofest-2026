# Yapılandırma ve Ortam Değişkenleri

> Tüm ortam değişkenlerinin tek ve kesin kaynağı `backend/app/core/config.py` içerisindeki `Settings` sınıfıdır. Bu belge, prodüksiyonda (**Production**) zorunlu olan ve değiştirilmezse güvenlik riski oluşturan değişkenlere odaklanır.

---

## Prodüksiyon Zorunlulukları

Aşağıdaki değişkenlerin varsayılan değerlerle (Production ortamında) kullanılması sistemin açılmasını doğrudan reddedecektir.

| Değişken | Varsayılan | Değiştirilme Nedeni ve Etkisi |
| :--- | :--- | :--- |
| `SECRET_KEY` | `supersecretkey...` | JWT imzalama anahtarıdır. Repoda açık (Public) olduğu için değiştirilmezse `_require_secret_key_in_production` kuralı boot'u iptal eder. |
| `REQUIRE_AUTH` | `true` | Asla `false` yapılmamalıdır. `_require_auth_in_production` kuralı sistemi korur. |
| `KACHOW_APP_DB_PASSWORD` | `kachow_app_dev_only` | RLS (Row-Level Security) için kısıtlı veritabanı rolünün şifresidir. |
| `POSTGRES_PASSWORD` | - | Schema-owner (postgres) rolünün süper şifresidir. (Kubernetes Secret veya Compose). |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Değiştirilmezse Grafana paneline herkes yetkisiz girebilir. |

---

## Ortam (Environment) Kontrolü

`ENVIRONMENT` değişkeni `development`, `staging` veya `production` alabilir. Sadece `production` modunda yukarıdaki korumalar devreye girer. Staging (Test) ortamlarında dahi `production` modunu kullanarak güvenlik mekanizmalarını test etmeniz önerilir.

---

## Depolama (`STORAGE_TYPE`)

Depolama mekanizması iki şekilde konfigüre edilebilir:

1. **`local` (Varsayılan):** Evraklar ve önbellek `./storage_data` klasörüne (PersistentVolumeClaim) yazılır. Sadece `replicas: 1` ile çalışır.
2. **`s3`:** Yatay ölçekleme (N Replika) isteniyorsa zorunludur. `S3_BUCKET_NAME`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY` ve `S3_SECRET_KEY` gerektirir.

---

## Mevzuat Kaynağı (`MEVZUAT_SOURCE`)

Canlı (`mcp`) veya Yerel (`local`). 
Eğer prodüksiyon imajınız `WITH_MEVZUAT_MCP=0` ile build edildiyse, bu değişkeni mutlaka `local` yapınız. Aksi halde her sorguda önce MCP denemesi yapılıp başarısız olunacak, gecikmeli olarak (Fallback) yerel korpusa düşülecektir.

---

## Zaman Aşımları (Timeouts)

Aşağıdaki değerler saniye cinsindendir. Yerel (CPU) modeller kullanılıyorsa artırılabilir, Ollama (GPU) kullanılıyorsa varsayılanlar yeterlidir.

| Değişken | Varsayılan (sn) | Etkilediği İşlem |
| :--- | :--- | :--- |
| `AI_WORKFLOW_TIMEOUT_SECONDS` | 480 | Toplam Workflow limiti |
| `EXTRACTION_TIMEOUT_SECONDS` | 300 | PDF OCR / Metin okuma |
| `DETAILED_SUMMARY_TIMEOUT_SECONDS` | 400 | Model özetleme süresi |
| `DRAFT_JUDGE_TIMEOUT_SECONDS` | 30 | LLM Yargıç onayı |
| `MEVZUAT_MCP_TIMEOUT_SECONDS` | 25 | Canlı mevzuat araması |

---

## Feature Flags (Özellik Aç/Kapat)

Prodüksiyon için şu ayarları göz önünde bulundurun:
- **`DRAFT_JUDGE_ENABLED` / `GUARDRAIL_JUDGE_ENABLED` (Varsayılan: true):** Kalite kapıları. Kapatılması sadece model arızası (Outage) anında düşünülmelidir.
- **`SEED_DEMO_COMPANY` / `SEED_DEFAULT_USERS` (Varsayılan: true):** Kaynak kodda şifreleri açık demo hesaplar üretir. Prodüksiyonda kesinlikle `false` olmalı veya şifreler (`SEED_ROOT_PASSWORD` vb.) ezilmelidir.

---

## Gözlemlenebilirlik (Observability)

- `LANGFUSE_PUBLIC_KEY` ve `LANGFUSE_SECRET_KEY` değerleri. Boş bırakılırsa Langfuse izleme sistemi hata vermeden sessizce kapanır.

> **NOT:** Compose ortamları eksik zorunlu değerlerde hata verirken, Kubernetes sırları (Secrets) eksikse Pod'lar başlatılamaz.
