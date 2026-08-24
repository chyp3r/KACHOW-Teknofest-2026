# Güvenlik Sertleştirme (Hardening)

> Bu belge, mevcut manifest/compose yapılarında **zaten uygulanan** güvenlik önlemleri ile **operatörün manuel olarak sağlaması gereken** eksik parçaları ayırır.

---

## Dahili Olarak Uygulanan Önlemler (Built-in)

Mevcut yapılandırmalar tarafından otomatik zorlanan güvenlik kuralları:

- **Önyükleme (Boot-Time) Kalkanları:** Prodüksiyonda (`ENVIRONMENT=production`), zayıf/varsayılan `SECRET_KEY` veya kapalı `REQUIRE_AUTH` ayarı tespit edildiğinde sistem çalışmayı tamamen reddeder (`app.lifespan`).
- **Yetkisiz Kullanıcı (Non-Root):** Container'lar Root haklarıyla çalışmaz. Backend `uid=10001 gid=0`, Frontend (nginx-unprivileged) `uid=101` haklarıyla koşar.
- **Salt Okunur Dosya Sistemi (`readOnlyRootFilesystem`):** K8s tarafında container içindeki kök dosya sistemi kilitlidir. Yazma gerektiren yerlere (Örn: `/tmp`, Cache dizinleri) bilinçli `emptyDir` veya PVC bağlanmıştır.
- **Postgres RLS (Row-Level Security):** Uygulama veritabanına sınırlı (`kachow_app`) bir rol ile bağlanır. Multi-Tenant veri kalkanı bypass edilemez.
- **Sıfır Güven Ağı (Default-Deny NetworkPolicy):** K8s yapısında, DNS ve Ollama portu dışında podlar arası trafik varsayılan olarak kapalıdır.
- **Temiz Build Context (`.dockerignore`):** `.env` dosyaları prodüksiyon imajlarına sızmaz. İmaj içine Test Suite klasörleri bilerek kopyalanmaz, saldırı yüzeyi daraltılır.

---

## Operatörün Sorumluluğunda Olan Kısımlar (Action Required)

Prodüksiyon ortamında manuel yapılandırılması gerekenler:

| Bileşen | Eylem (Action) |
| :--- | :--- |
| **Sırlar (Secrets)** | Güvenli sır yönetimi (Vault, Sealed Secrets) sağlanmalı ve k8s placeholder'ları ezilmelidir. (Bkz: [secrets.md](secrets.md)). |
| **TLS / SSL** | Sistem sadece HTTP üzerinden haberleşir. Compose yolunda `Reverse Proxy` (Nginx/Traefik) ile, Kubernetes yolunda `cert-manager` destekli Ingress ile şifreleme sağlanmalıdır. |
| **Demo Hesaplar** | `SEED_DEMO_COMPANY` ve `SEED_DEFAULT_USERS` flag'leri `false` yapılmalı veya açık şifreler ezilmelidir. Aksi takdirde bilinen şifreli yönetici hesapları açık kalır. |
| **Grafana Yönetici Şifresi** | `GRAFANA_ADMIN_PASSWORD` (Varsayılan `admin`) değiştirilmelidir. |
| **Alertmanager Kanalları** | Sadece `null` receiver tanımlıdır. Slack/E-posta entegrasyonu kurulmalıdır. |
| **Görsel/İmaj Taraması (SBOM)**| İmajların zafiyet (Vulnerability) taramalarından geçirilmesi, CI ardışık düzeninize (Pipeline) Trivy vb. eklenmesi önerilir. |
| **Secret Rotasyonu** | Olası sızıntılara karşı periyodik JWT (`SECRET_KEY`) ve Veritabanı şifre rotasyonu iş akışları kurgulanmalıdır. |

---

## Bilinçli Olarak Kapsam Dışı Bırakılanlar

- **HPA (Yatay Pod Ölçekleyici):** CPU tabanlı HPA kullanılmamıştır. Çünkü LLM istekleri beklerken (Ollama), CPU kullanımı düşük kalabilir ancak kuyruk darboğaz olur. Bunun yerine metrik-tabanlı (Kuyruk uzunluğu vb.) Custom Metrics Adapter önerilir.
- **PDB (Pod Disruption Budget) Backend:** `replicas: 1` iken PDB kullanılması Node bakımlarını (Drain) süresiz kilitler. Sadece N replikaya geçildiğinde PDB aktifleştirilmelidir.
- **Helm Chart:** Bakım zorluğu ve kısıtlayıcı şablonlar nedeniyle düz (Plain) YAML manifestleri tercih edilmiştir.
