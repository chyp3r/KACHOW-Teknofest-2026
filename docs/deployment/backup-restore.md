# Yedekleme ve Geri Yükleme

Üç bağımsız veri kaynağı yedeklenmeli: Postgres (kayıtlar, kullanıcılar,
taslaklar, audit log, RLS tenant verisi), Qdrant (vektör indeksleri --
kaybı yalnızca retrieval kalitesini düşürür, kayıt kaybı değildir, ama
yeniden indekslemek zaman alır) ve belge depolama (`storage_data`
PVC/volume ya da S3 bucket'ı -- ham belge blob'ları + analiz cache'i).

## Postgres

```bash
# Docker Compose
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod \
  exec db pg_dump -U "$POSTGRES_USER" -Fc kachow > kachow-$(date +%F).dump

# Kubernetes
kubectl -n kachow exec postgres-0 -- pg_dump -U postgres -Fc kachow \
  > kachow-$(date +%F).dump
```

`-Fc` (custom format) tercih edilir -- `pg_restore` ile paralel restore
ve seçici tablo geri yüklemeyi destekler, düz SQL dump'ın aksine.

**Geri yükleme:**
```bash
pg_restore -U postgres -d kachow --clean --if-exists kachow-2026-08-23.dump
```
`--clean --if-exists`: hedef veritabanında zaten nesneler varsa önce
düşürür -- boş bir veritabanına geri yüklerken bu bayraklar zararsız.

**`langfuse` veritabanını unutmayın** -- aynı Postgres instance'ında ayrı
bir veritabanı (`scripts/init-db.sh`/`postgres.yaml`'ın initdb
ConfigMap'i tarafından oluşturulur), `kachow` dump'ının parçası değildir.

## Qdrant

Qdrant'ın kendi snapshot API'si:
```bash
curl -X POST http://qdrant:6333/collections/document_qa/snapshots
curl -X POST http://qdrant:6333/collections/mevzuat/snapshots
# ... her koleksiyon için (koleksiyon adları: document_qa, mevzuat,
# resmi_yazisma_ornek -- app/core/config.py'nin *_COLLECTION_NAME
# alanları)
```
Snapshot dosyaları container içinde `/qdrant/storage/snapshots/`
altında oluşur -- `qdrant.yaml`'ın PVC'sinden (ya da compose'un
`qdrant_data` volume'undan) dışarı kopyalanmalı.

**Not:** `mevzuat` ve `resmi_yazisma_ornek` koleksiyonları commit'li
korpustan (`datasets/`) yeniden indekslenebilir -- yedeklemek bir
kolaylık, zorunluluk değil. `document_qa` (kullanıcı yüklediği belgeler)
**kayıp telafisi olmayan** tek koleksiyon; asıl öncelik bu.

## Belge depolama (`storage_data`)

- `STORAGE_TYPE=local`: PVC/volume'un kendisini yedekleyin (Velero, CSI
  snapshot, ya da basitçe `docker run --rm -v backend_storage_data:/data
  -v $(pwd):/backup alpine tar czf /backup/storage-$(date +%F).tar.gz
  /data`).
- `STORAGE_TYPE=s3`: yedekleme sorumluluğu S3-uyumlu depolama
  sağlayıcınıza (bucket versioning/replication) geçer -- bu repo bir
  şey yapmaz.

## Geri yükleme sırası

1. Postgres'i geri yükleyin (`pg_restore`).
2. Qdrant koleksiyonlarını snapshot'tan geri yükleyin.
3. `storage_data`'yı geri yükleyin.
4. `backend`'i başlatın -- `migrate-job`/`migrate` servisini **çalıştırmayın**
   eğer geri yüklenen Postgres dump'ı zaten hedef şemadaysa (aksi halde
   `alembic upgrade head` zaten uygulanmış migration'ları tekrar
   uygulamaya çalışmaz, ama `alembic_version` tablosunun tutarlı olduğunu
   önce doğrulayın: `SELECT version_num FROM alembic_version;`).
