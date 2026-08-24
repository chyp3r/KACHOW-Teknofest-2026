# Sürüm Yükseltme (Upgrade & Rollout)

> KACHOW projesi yeni bir sürüme geçirilirken izlenmesi gereken adımları açıklar.

---

## Docker Compose

Sürüm yükseltme adımları ve (gerekliyse) şema göçü tek bir süreçte tamamlanır.

```bash
# 1. Yeni sürüm (Tag) ile imajları inşa edin veya registry'den çekin
docker build -f deploy/docker/backend.prod.Dockerfile -t kachow-backend:3.44.0 .
docker build -f deploy/docker/frontend.prod.Dockerfile -t kachow-frontend:3.44.0 .

# 2. Ortam değişkenini güncelleyin (Veya .env.prod dosyasına yazın)
export IMAGE_TAG=3.44.0

# 3. Yığını (Stack) güncelleyin
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod up -d
```

> **NOT:** `migrate` servisi her `up` komutunda çalışır. Alembic yeni bir göç dosyası yoksa hızlıca geçer. Eğer yeni göç (Migration) varsa uygulanır ve `backend` sadece işlem tamamlandıktan sonra yeni imajıyla ayağa kalkar (Rolling Restart).

### Geri Alma (Rollback) - Docker Compose

`IMAGE_TAG` değişkenini eski versiyona çekip `up -d` çalıştırmak imajı geri alır.
**ÖNEMLİ:** Eğer yapılan son Migration geri alınamaz (Irreversible, Örn: `DROP COLUMN`) bir işlem içeriyorsa kod eski, şema yeni kalır ve uyuşmazlık (Crash) yaşanır. Riskli dönüşlerden önce daima veritabanı yedeği alınız.

---

## Kubernetes

Kubernetes üzerinde sürüm yükseltme, Job ve Deployment objelerinin güncellenmesine dayanır.

```bash
# 1. Manifest dosyalarındaki (migrate-job, backend, frontend) image tag'lerini yeni sürüme göre güncelleyin.

# 2. Eski migrate-job objesini silin (Job'lar immutable'dır, üstüne yazılamaz)
kubectl delete job kachow-migrate -n kachow --ignore-not-found

# 3. Yeni şema güncellemelerini çalıştırıp bitmesini bekleyin
kubectl apply -f deploy/kubernetes/migrate-job.yaml
kubectl -n kachow wait --for=condition=Complete job/kachow-migrate --timeout=120s

# 4. Uygulama güncellemelerini (Rolling Update) başlatın
kubectl apply -f deploy/kubernetes/backend.yaml
kubectl apply -f deploy/kubernetes/frontend.yaml

# 5. Rollout durumlarını takip edin
kubectl -n kachow rollout status deployment/backend
kubectl -n kachow rollout status deployment/frontend
```

### Geri Alma (Rollback) - Kubernetes

K8s `undo` komutu kullanılarak bir önceki Deployment ReplicaSet'ine dönülebilir:

```bash
kubectl rollout undo deployment/backend -n kachow
```
*Şema geri dönüş riskleri Compose ile aynıdır.*

---

## Sürüm Takibi (Versioning)

Mevcut sürüm kod içerisinde (`__version__` vb.) gömülü değildir. Aktif versiyon numarası daima ana dizindeki `CHANGELOG.md` dosyasının en güncel başlığından takip edilmelidir. İmaj etiketlerini (Tag) bu numaralarla paralel götürmek sistem operatörünün sorumluluğundadır.
