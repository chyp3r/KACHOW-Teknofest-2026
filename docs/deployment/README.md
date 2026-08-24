# Dağıtım (Deployment) Dokümantasyonu

> Bu dizin, KACHOW'u yerel geliştirme ortamı dışında (Staging/Production) çalıştırmak isteyen altyapı operatörleri içindir. Geliştirme ortamı kurulumu için kök dizindeki `README.md` dosyasına bakınız.

---

## İçindekiler

1. [prerequisites.md](prerequisites.md) — Dağıtım öncesi gereksinimler.
2. [docker-compose.md](docker-compose.md) — `compose.prod.yml` ile tek makine (Single-Node) dağıtımı.
3. [kubernetes.md](kubernetes.md) — Self-hosted Kubernetes kümesine (Cluster) dağıtım.
4. [configuration.md](configuration.md) — Ortam değişkenleri, zorunlu alanlar ve güvensiz varsayılanlar.
5. [secrets.md](secrets.md) — Sır (Secret) yönetimi (Plain, Sealed Secrets, External Secrets).
6. [migrations.md](migrations.md) — Veritabanı şema göçleri (Migrations) ve 2 rollü DB bağlantısı.
7. [observability.md](observability.md) — İzlenebilirlik (Grafana, Prometheus, Langfuse).
8. [runbook.md](runbook.md) — Olası altyapı alarmları ve müdahale rehberi.
9. [backup-restore.md](backup-restore.md) — Postgres, Qdrant ve MinIO (Storage) yedekleme/geri yükleme stratejileri.
10. [upgrade.md](upgrade.md) — Yeni sürüme geçiş ve Rollout.
11. [hardening.md](hardening.md) — Güvenlik varsayımları, sınırlar ve sıkılaştırma (Hardening).

---

## İki Ana Dağıtım Stratejisi

Sistem birbirine alternatif iki bağımsız dağıtım yolu sunar. Lütfen altyapınıza uygun olan **sadece birini** seçiniz.

| Özellik | Docker Compose | Kubernetes |
| :--- | :--- | :--- |
| **Gerekli Dosyalar** | `compose.yml` + `compose.prod.yml` | `deploy/kubernetes/*.yaml` |
| **Hedef Kitle** | Tek makine (Single-node), küçük/orta ölçek | Self-hosted k8s kümesi, büyük ölçek |
| **Ölçeklenebilirlik**| `backend` tek replika (Önerilir) | Varsayılan 1 replika, `STORAGE_TYPE=s3` ile N replika |
| **Şema (Migration)** | `migrate` servisi (`backend` öncesi çalışır) | `migrate-job.yaml` (Job olarak elle/CI ile çalışır) |
| **İzleme (Monitoring)**| Compose içinden miras `prometheus`/`grafana` | Repo dışı. Operatör kendi Prometheus Operator'ünü kurmalıdır |

> **NOT:** Her iki yol da aynı imajları (`backend.prod.Dockerfile`, `frontend.prod.Dockerfile`) ve aynı Postgres RLS prensiplerini kullanır.

---

## Hızlı Başlangıç: Docker Compose

```bash
# 1. Prodüksiyon ortam değişkenlerini hazırlayın
cp .env.prod.example .env.prod

# 2. Değerleri doldurun (Boş zorunlu alanlar başlatmayı reddeder)
nano .env.prod

# 3. Yığın (Stack) olarak ayağa kaldırın
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod up -d
```

Detaylar için [docker-compose.md](docker-compose.md) dokümanına bakınız.
