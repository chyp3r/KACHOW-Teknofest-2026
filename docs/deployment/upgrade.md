# Sürüm Yükseltme

## Docker Compose

```bash
# 1. Yeni imajları build edin/çekin, yeni bir tag ile
docker build -f deploy/docker/backend.prod.Dockerfile -t kachow-backend:3.44.0 .
docker build -f deploy/docker/frontend.prod.Dockerfile -t kachow-frontend:3.44.0 .

# 2. IMAGE_TAG'i .env.prod'da güncelleyin (ya da export edin)
export IMAGE_TAG=3.44.0

# 3. Migration + rolling restart tek komutla
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod up -d
```

`migrate` servisi her `up` çağrısında yeniden çalışır (alembic zaten
uygulanmış migration'ları no-op geçer) -- yeni migration'lar varsa
uygulanır, yoksa hızlıca `Complete` olur. `backend` yalnızca `migrate`
başarıyla bittikten sonra yeniden başlar.

**Geri alma (rollback):** `IMAGE_TAG`'i bir önceki değere döndürüp tekrar
`up -d` -- ama **yalnızca migration'lar geri alınabilirse** güvenlidir.
Bir migration `DROP COLUMN` gibi geri dönüşsüz bir işlem içeriyorsa, kod
rollback'i şema ile uyuşmaz. Bu proje şu an otomatik migration rollback
tutmuyor (`alembic downgrade` elle çalıştırılabilir ama her migration'ın
`downgrade()`'i test edilmiş değil) -- riskli bir rollback'ten önce
[backup-restore.md](backup-restore.md)'daki gibi bir yedek alın.

## Kubernetes

```bash
# 1. Yeni imajı push edin, migrate-job.yaml + backend.yaml + frontend.yaml'daki
#    image: alanlarını güncelleyin (ya da bir Kustomize overlay/CI ile).

# 2. Önceki migrate Job'ı temizleyin (Job spec'i immutable)
kubectl delete job kachow-migrate -n kachow --ignore-not-found

# 3. Yeni migration'ı çalıştırıp bitmesini bekleyin
kubectl apply -f deploy/kubernetes/migrate-job.yaml
kubectl -n kachow wait --for=condition=Complete job/kachow-migrate --timeout=120s

# 4. Rolling update
kubectl apply -f deploy/kubernetes/backend.yaml
kubectl apply -f deploy/kubernetes/frontend.yaml
kubectl -n kachow rollout status deployment/backend
kubectl -n kachow rollout status deployment/frontend
```

`backend.yaml`'ın kendi `wait-for-migrations` initContainer'ı, yeni
pod'ların şema `head`'e ulaşana kadar Ready olmasını zaten engeller --
adım 3'ü atlarsanız (CI sıralamasına güveniyorsanız) yeni pod'lar sadece
biraz daha uzun `Pending`/`Init` kalır, hatalı bir şemaya karşı
başlamazlar.

**Geri alma:** `kubectl rollout undo deployment/backend -n kachow` --
Compose'daki aynı uyarı geçerli: yalnızca migration'lar geriye uyumluysa
güvenli.

## Sürüm numarası nerede tutuluyor

Şu an kod içinde bir `__version__` sabiti yok (Workstream J10, henüz
yapılmadı) -- tek kaynak `CHANGELOG.md`'nin en üst başlığı. İmaj
tag'lerini bu numarayla eşleştirmek operatörün sorumluluğunda.
