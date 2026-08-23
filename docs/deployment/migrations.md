# Şema Migration'ları

## İki-rollü bağlantı ayrımı

Bu proje iki ayrı Postgres bağlantı dizesi tutar, ve ikisi de kasıtlı:

- **`DATABASE_URL`** — kısıtlı `kachow_app` rolü. Çalışan `backend`
  processinin bağlandığı tek bağlantı. Postgres Row-Level Security
  (migration `0013_rls`) yalnızca *tablonun sahibi olmayan* bir bağlantı
  için gerçek bir savunma — bir owner/superuser bağlantısı her zaman
  `RLS`'i bypass edebilir, `FORCE ROW LEVEL SECURITY` bile.
- **`ALEMBIC_DATABASE_URL`** — schema-owner rolü (genelde `postgres`).
  Yalnızca iki yerde kullanılır: Alembic migration'ları (DDL) ve
  `app.infrastructure.database.session.get_owner_db`'nin pre-tenant
  identity lookup'ları (login/refresh/registration — bir kullanıcı henüz
  hangi şirkete ait olduğu bilinmeden, global `username`/`email` ile
  aranmak zorunda).

`ALEMBIC_DATABASE_URL` boşsa `DATABASE_URL`'e düşer
(`Settings.effective_alembic_database_url`) — ama bu yalnızca RLS
öncesi/geliştirme senaryosu içindir; production'da ikisi ayrı olmalı,
aksi halde migration'lar kısıtlı rolle DDL çalıştırmaya çalışıp başarısız
olur.

## Docker Compose

`compose.prod.yml`'in `migrate` servisi `alembic upgrade head`'i tek
seferlik çalıştırır, `backend` ona `condition:
service_completed_successfully` ile bağlıdır — `docker compose ... up -d`
tek komutuyla doğru sırada çalışır, elle bir şey yapmanız gerekmez.

Migration'ın gerçekten çalıştığını doğrulamak için:
```bash
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod logs migrate
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod exec db \
  psql -U "$POSTGRES_USER" -d kachow -c "SELECT version_num FROM alembic_version;"
```

## Kubernetes

`deploy/kubernetes/migrate-job.yaml` bir `Job` — bir Deployment
initContainer'ı **değil**, bilerek: `backend.yaml`'ın `replicas`'ı 1'den
fazla olduğunda her pod'un kendi initContainer'ı aynı `alembic upgrade
head`'i eşzamanlı koşturup birbirleriyle yarışırdı. `backend.yaml`'ın
kendi initContainer'ı (`wait-for-migrations`) yalnızca bu Job'ın ürettiği
şemayı *bekler*, hiçbir DDL çalıştırmaz.

```bash
kubectl apply -f deploy/kubernetes/migrate-job.yaml
kubectl -n kachow wait --for=condition=Complete job/kachow-migrate --timeout=120s
kubectl -n kachow logs job/kachow-migrate
```

Bir sonraki deploy'da aynı isimle yeni bir `Job` oluşturmak isterseniz
öncekini silin (`kubectl delete job kachow-migrate -n kachow`) — bir
`Job`'ın `spec` alanı immutable'dır, `apply` üzerine yazamaz.

## Yeni bir migration yazmak

Bu doküman migration yazma sürecini kapsamaz (bkz.
`docs/development/backend-standards.md` ve `backend/alembic/`'in kendi
şablon dosyaları) — yalnızca üretime nasıl uygulandığını anlatır.

## LangGraph checkpoint tabloları — Alembic'in kapsamı dışında

`checkpoint*` önekli tablolar (`AsyncPostgresSaver`) Alembic'le değil,
uygulamanın kendi `app.infrastructure.checkpointing.init_checkpointer`'ı
tarafından `.setup()` ile başlangıçta oluşturulur —
`backend/alembic/env.py`'nin `include_object`'i bunları autogenerate'den
bilerek hariç tutar. Bir migration bu tabloları hiç görmez; bu normal.
