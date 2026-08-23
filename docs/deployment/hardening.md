# Güvenlik Sertleştirme (Hardening)

Bu doküman, bu deployment yolunun **zaten yaptığı** şeyleri ve
**yapmadığı, sizin eklemeniz gereken** şeyleri ayırır.

## Zaten yapılıyor (kod/manifest tarafından zorlanıyor)

- **Boot-time guard'lar** — `ENVIRONMENT=production` iken varsayılan
  `SECRET_KEY` veya `REQUIRE_AUTH=false` ile process **başlamıyor**
  (`app.lifespan`). Bir log satırı değil, çalışmayan bir process.
- **Non-root container'lar** — backend `uid=10001 gid=0`, frontend
  (nginx-unprivileged) `uid=101`. `kubectl exec ... id` ile doğrulanabilir.
- **`readOnlyRootFilesystem: true`** (k8s) — her iki container da yazma
  ihtiyacı olan yerleri (`/tmp`, backend'in `storage_data`'sı, frontend'in
  nginx cache/run dizinleri) açık `emptyDir`/PVC mount'ları olarak alır;
  kalan her şey salt okunur.
- **Postgres RLS + rol ayrımı** — `kachow_app` (kısıtlı, çalışan
  process'in bağlandığı) vs. owner rolü (yalnızca migration + pre-tenant
  login lookup'ları) -- bkz. [migrations.md](migrations.md).
- **`NetworkPolicy` default-deny** (k8s, `namespace.yaml`) — DNS,
  namespace-içi trafik ve Ollama (port 11434) dışında her şey reddedilir.
  **Yalnızca NetworkPolicy'yi destekleyen bir CNI'da işe yarar** — bkz.
  [kubernetes.md](kubernetes.md)'nin uyarısı.
- **`.dockerignore`** — kök `.env`/`.env.prod` build context'ine girmez
  (imaja gömülmez).
- **Prod imaj, test suite'i/`evaluation/`'ı içermez** —
  `backend.prod.Dockerfile` yalnızca `app`/`alembic`/`datasets`'i
  kopyalar; imajın kendisi testleri çalıştıramaz, saldırı yüzeyini
  azaltır.

## Sizin yapmanız gerekiyor

- **Gerçek sırlar** — bkz. [secrets.md](secrets.md). Placeholder'larla
  apply etmeyin.
- **TLS terminasyonu** — Compose yolunda nginx'in önüne kendi reverse
  proxy'nizi/sertifikanızı eklemelisiniz (bu repo HTTP-only servis eder).
  K8s yolunda `ingress.yaml` cert-manager varsayıyor; kurulu ve
  yapılandırılmış olmalı.
- **`SEED_DEMO_COMPANY`/`SEED_DEFAULT_USERS`** — varsayılan `true`,
  kaynak kodda görünür şifrelerle demo hesaplar oluşturur. Production'da
  `false`'a çekin ya da şifreleri override edin -- bkz.
  [configuration.md](configuration.md).
- **`Alertmanager`'ın gerçek bir bildirim kanalı** — `monitoring/
  alertmanager/alertmanager.yml` placeholder receiver'larla gelir; hiçbir
  yere bildirim gitmez. Bkz. [observability.md](observability.md).
- **`GRAFANA_ADMIN_PASSWORD`** — varsayılan `admin`.
- **İmaj taraması** — bu repoda Trivy/SBOM üretimi henüz yok (Workstream
  J10'un parçası, yapılmadı). Kendi CI'ınızda bir tarama adımı ekleyin.
- **Secret rotasyonu** — otomatikleştirilmiş bir rotasyon mekanizması bu
  repoda yok; ESO + gerçek bir secret store (bkz. secrets.md) kendi
  rotasyon periyodunu sağlar, plain `Secret`/`.env.prod` yolu manuel
  rotasyon gerektirir.
- **`LICENSE`** — kök dizinde şu an boş (Workstream J10). Bir kurumsal/
  kamu deployment'ı için lisans metnini doldurun.

## Bilinçli olarak yapılmayanlar (ve neden)

- **HPA (Horizontal Pod Autoscaler)** — CPU-tabanlı autoscaling bu iş
  yükü için yanlış sinyal: bir backend pod'u çoğu zaman Ollama'da bloke
  bekliyor, CPU düşük kalırken istek hacmi artabilir. Doğru eksen (kuyruk
  derinliği/uçuştaki istek sayısı) özel bir metrics adapter gerektirir --
  bkz. `deploy/kubernetes/pdb.yaml`'ın kendi yorumu.
- **`backend` PodDisruptionBudget'ı** — `replicas: 1` iken bir PDB her
  voluntary eviction'ı (node drain, autoscaler scale-down) süresiz
  engellerdi. `replicas`'ı yükselttiğinizde ekleyin.
- **`deploy/helm/`** — manifest seti bilinçli olarak Helm değil; bkz.
  [kubernetes.md](kubernetes.md)'nin üst notu.
