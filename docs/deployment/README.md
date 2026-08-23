# Deployment Dokümantasyonu

> Bu dizin, KACHOW'u yerel geliştirme dışında (staging/production) çalıştırmak isteyen operatörler içindir. Geliştirme ortamı kurulumu için kök `README.md`'ye bakın.

## İçindekiler

1. [prerequisites.md](prerequisites.md) — deploy etmeden önce ihtiyacınız olanlar.
2. [docker-compose.md](docker-compose.md) — `compose.prod.yml` ile tek makineye deploy.
3. [kubernetes.md](kubernetes.md) — `deploy/kubernetes/*.yaml` ile self-hosted bir cluster'a deploy.
4. [configuration.md](configuration.md) — her ortam değişkeni, hangileri zorunlu, hangi varsayılanlar güvensiz.
5. [secrets.md](secrets.md) — sırların nasıl yönetileceği (plain Secret / Sealed Secrets / External Secrets Operator).
6. [migrations.md](migrations.md) — şema migration'ları, iki-rollü DB bağlantısı.
7. [observability.md](observability.md) — dashboard'lar, alert kuralları, Langfuse.
8. [runbook.md](runbook.md) — her alert için "ne yapmalıyım" rehberi.
9. [backup-restore.md](backup-restore.md) — Postgres, Qdrant, belge depolamanın yedeklenmesi.
10. [upgrade.md](upgrade.md) — yeni bir sürüme geçiş.
11. [hardening.md](hardening.md) — bu deployment'ın güvenlik varsayımları ve sınırları.

## İki deploy yolu

Bu proje iki eşdeğer, birbirinden bağımsız deploy yolu sunar — ikisini birden çalıştırmayın:

| | Docker Compose | Kubernetes |
|---|---|---|
| Dosyalar | `compose.yml` + `compose.prod.yml` | `deploy/kubernetes/*.yaml` |
| Hedef kitle | Tek makine, küçük/orta ölçek | Self-hosted bir cluster |
| Ölçeklenebilirlik | `backend` tek replika | `backend` varsayılan 1, `STORAGE_TYPE=s3` ile 2+ |
| Migration | `migrate` servisi (tek seferlik, `backend`'den önce) | `migrate-job.yaml` (`Job`, `backend`'den önce elle/CI ile uygulanır) |
| İzleme | `prometheus`/`grafana` (compose.yml'den miras), `alertmanager` (yalnızca prod) | Bu repoda yok — kendi Prometheus operator'ünüzü kurmanız gerekir |

Her iki yol da aynı imajları (`deploy/docker/backend.prod.Dockerfile`,
`deploy/docker/frontend.prod.Dockerfile`) ve aynı Postgres RLS rol
ayrımını (`DATABASE_URL` / `ALEMBIC_DATABASE_URL`) kullanır — bkz.
[migrations.md](migrations.md).

## Hızlı başlangıç (Docker Compose)

```bash
cp .env.prod.example .env.prod   # her değeri gerçek bir değerle doldurun
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod up -d
```

Detaylar için [docker-compose.md](docker-compose.md)'ye bakın.
