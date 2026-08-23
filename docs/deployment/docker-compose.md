# Docker Compose ile Deploy

`compose.prod.yml`, `compose.yml`'in üstüne bir **override** dosyasıdır —
tek başına kullanılmaz. Aradaki farklar için `compose.prod.yml`'in kendi
üst yorumuna bakın: kaynak bind mount yok, `db`/`redis`/`qdrant` portları
dışa açılmıyor, healthcheck'ler eklendi, tek seferlik `migrate` servisi var,
kaynak limitleri ve log rotasyonu var, ve — en önemlisi — `${VAR:?...}`
söz dizimiyle her sır zorunlu: eksik bir sırla `up` hemen reddedilir,
sessizce güvensiz bir varsayılanla açılmaz.

## Adımlar

```bash
# 1. Sırları hazırlayın
cp .env.prod.example .env.prod
# .env.prod içindeki HER değeri gerçek bir değerle doldurun -- boş
# bırakılan zorunlu bir değişken `up`'ı reddeder.

# 2. İmajları build edin (veya bir registry'den çekin -- IMAGE_TAG'i
#    kendi tag'inize ayarlayın)
docker build -f deploy/docker/backend.prod.Dockerfile -t kachow-backend:latest .
docker build -f deploy/docker/frontend.prod.Dockerfile -t kachow-frontend:latest .

# 3. Ayağa kaldırın
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod up -d

# 4. Migration'ın gerçekten tamamlandığını doğrulayın
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod logs migrate

# 5. Sağlık kontrolü
curl -f http://localhost/api/v1/health
```

`backend`, `migrate` servisinin `service_completed_successfully` koşulunu
sağlamadan başlamaz (`compose.prod.yml`'deki `depends_on`) — adım 3 tek
komutla hem migration'ı hem backend'i başlatır, sıralamayı siz elle
yönetmezsiniz.

## `MEVZUAT_SOURCE`

`backend.prod.Dockerfile` varsayılan olarak `mevzuat-mcp`'yi (canlı
mevzuat.gov.tr sorgusu) **build etmez** (`WITH_MEVZUAT_MCP=0`).
`.env.prod.example`'ın notu doğru: `MEVZUAT_SOURCE=local` bırakın, aksi
halde her mevzuat sorgusu önce başarısız olması kesin bir MCP denemesi
yapıp commit'li korpusa düşer — çalışır ama gereksiz gecikme ekler. Canlı
sorgu istiyorsanız `--build-arg WITH_MEVZUAT_MCP=1` ile yeniden build edip
`MEVZUAT_SOURCE=mcp`'ye çevirin.

## Ölçeklendirme

`backend` servisini `docker compose ... up -d --scale backend=N` ile
ölçeklendirmeyin — bkz. [configuration.md](configuration.md)'nin
`STORAGE_TYPE` bölümü: varsayılan `local` depolama ile birden fazla
`backend` container'ı aynı `backend_storage_data` named volume'unu paylaşsa
bile, her container'ın kendi Docker network kimliği farklı Service DNS'e
ihtiyaç duyar ve compose bunu native desteklemez (k8s'in aksine, tek bir
Service arkasında N replika koşturmak için tasarlanmamıştır). Gerçek
yatay ölçeklendirme için [kubernetes.md](kubernetes.md)'ye bakın.

## Durdurma / kaldırma

```bash
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod down
# Veri kaybı riski: -v veri hacimlerini (postgres_data, qdrant_data,
# redis_data, backend_storage_data) de siler. Yalnızca bilerek kullanın.
```
