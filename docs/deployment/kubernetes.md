# Kubernetes ile Deploy

`deploy/kubernetes/*.yaml` — düz manifest'ler, Helm değil (`deploy/helm/`
ayrı, henüz tamamlanmamış bir takip işi). Her dosyanın kendi başında,
neden o şekilde yazıldığını anlatan yorumlar var; burada yalnızca
uygulama sırası ve manifest'lerin metinde yazmayan gerçek varsayımları
özetlenir.

Bu manifest seti `kind` ile gerçek bir Kubernetes API server'ına karşı
uçtan uca doğrulandı — bkz. `CHANGELOG.md`'nin `[3.43.0]` girdisi.

## Uygulama sırası

```bash
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl apply -f deploy/kubernetes/configmap.yaml
# secrets.yaml'daki placeholder'ları GERÇEK değerlerle DOLDURMADAN
# apply etmeyin -- bkz. secrets.md.
kubectl apply -f deploy/kubernetes/secrets.yaml
kubectl apply -f deploy/kubernetes/postgres.yaml
kubectl apply -f deploy/kubernetes/qdrant.yaml
kubectl apply -f deploy/kubernetes/redis.yaml

kubectl -n kachow wait --for=condition=Ready pod -l app=kachow-postgres --timeout=180s
kubectl -n kachow wait --for=condition=Ready pod -l app=kachow-qdrant --timeout=180s

# Şema -- backend'den ÖNCE tamamlanmalı.
kubectl apply -f deploy/kubernetes/migrate-job.yaml
kubectl -n kachow wait --for=condition=Complete job/kachow-migrate --timeout=120s

kubectl apply -f deploy/kubernetes/backend.yaml
kubectl apply -f deploy/kubernetes/frontend.yaml
kubectl apply -f deploy/kubernetes/pdb.yaml
kubectl apply -f deploy/kubernetes/ingress.yaml
```

`backend.yaml`'ın kendi `wait-for-migrations` initContainer'ı, `migrate`
Job'ı elle beklemeden `apply` edilse bile şemanın `head`'e ulaşmasını
bekler (`alembic current | grep '(head)'` döngüsü) — yukarıdaki `wait`
adımları bir güvence, zorunluluk değil.

## EDIT etmeniz gereken yerler

Hiçbir yerde "gerçek" bir değer icat edilmedi — placeholder'lar ya
apply'ı reddeder ya da açıkça yorumla işaretlenmiştir:

- `secrets.yaml` — her `stringData` değeri placeholder. Bkz.
  [secrets.md](secrets.md).
- `configmap.yaml`'ın `OLLAMA_BASE_URL`'i — `ollama.example.internal`
  gerçek bir host değil.
- `namespace.yaml`'ın `allow-backend-ollama-egress` NetworkPolicy'si —
  varsayılan olarak port 11434'e her yere izin verir (fonksiyonel ama
  gevşek); gerçek Ollama host'unuza daraltın.
- `backend.yaml`/`frontend.yaml`/`migrate-job.yaml`'ın `image:` alanları —
  `ghcr.io/chyp3r/kachow-backend:latest` bir placeholder; kendi
  registry'nize push ettiğiniz imajla değiştirin.
- `ingress.yaml`'ın `host`/`tls.hosts`/`cert-manager.io/cluster-issuer`'ı.

## `replicas: 1` neden varsayılan

`backend.yaml`'ın kendi yorumu tam gerekçeyi anlatıyor: J9 (#254) analiz
cache'ini `BaseStorage`'ın arkasına aldı, yani `STORAGE_TYPE=s3` artık
gerçekten "hiçbir yerel disk yazması yok" anlamına geliyor. Ama
`configmap.yaml`'ın varsayılanı hâlâ `STORAGE_TYPE=local` (gerçek bir
S3/MinIO endpoint'i bu repo tarafından varsayılamaz), ve yerel depolama
ile `replicas > 1`, `backend-storage-data` PVC'sinin `ReadWriteMany`
olmasını gerektirir (çoğu cluster'da yok).

**2+ replikaya çıkmak için:**
1. Bir S3-uyumlu depolama (MinIO veya bulut S3) kurun.
2. `configmap.yaml`'da `STORAGE_TYPE: "s3"` ve `S3_BUCKET_NAME`/
   `S3_ENDPOINT_URL`'i doldurun.
3. `secrets.yaml`'da `S3_ACCESS_KEY`/`S3_SECRET_KEY`'i doldurun.
4. `backend.yaml`'da `replicas`'ı yükseltin; `backend-storage-data`
   PVC/volumeMount'unu tamamen kaldırabilirsiniz (artık kullanılmıyor).

## `NetworkPolicy` gerçek bir varsayım gerektirir

`namespace.yaml`'ın default-deny + istisna politikaları yalnızca
NetworkPolicy'yi gerçekten uygulayan bir CNI'da işe yarar. Desteklemeyen
bir CNI'da bu manifest'ler sessizce hiçbir şey yapmaz (apply hata vermez,
ama izolasyon da olmaz) — cluster'ınızın CNI'ını kontrol edin.

## Kaynak sınırları

`namespace.yaml`'ın `ResourceQuota`'sı namespace genelinde bir tavan
koyar — bu quota aktifken **her** container'ın (initContainer'lar dahil)
kendi `resources.requests`/`limits`'i olmak zorunda, yoksa Pod oluşturma
tamamen reddedilir (`FailedCreate`). Bu manifest setinin kendi geliştirme
sürecinde gerçekten yakalanan bir hataydı; yeni bir container eklerken
unutmayın.

## Doğrulama

```bash
kubectl -n kachow get pods
kubectl -n kachow logs -l app=kachow-backend
curl -f https://<ingress-host>/api/v1/health
kubectl apply --dry-run=server -k deploy/kubernetes/
```
