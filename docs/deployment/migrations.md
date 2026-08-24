# Şema Göçleri (Migrations)

> Veritabanı (PostgreSQL) yapısını güncel tutmak için Alembic kullanılır. KACHOW sisteminde güvenlik gereği veritabanı bağlantıları çift rollü (Dual-Role) yapılandırılmıştır.

---

## Çift Rollü Bağlantı (Dual-Role Connection)

Row-Level Security (RLS) kalkanının kırılmaması için iki farklı bağlantı zorunludur:

| Değişken (Bağlantı) | Kullanılan Rol | Görevi ve Amacı |
| :--- | :--- | :--- |
| `DATABASE_URL` | Kısıtlı `kachow_app` rolü | Çalışan Backend'in tek kullandığı veri yoludur. Tablo sahibi olmadığı için RLS kısıtlamalarını bypass edemez. |
| `ALEMBIC_DATABASE_URL` | Sahip `postgres` (Owner) rolü | Yalnızca iki noktada kullanılır: 1. Şema güncellemeleri (DDL). 2. Ön-Kimlik sorgusu (Şirketi belli olmayan bir kullanıcının global aranması - Pre-tenant lookup). |

> **NOT:** Prodüksiyon ortamında bu iki URL birbirinden kesinlikle farklı olmalıdır. Aksi takdirde kısıtlı rol ile DDL (Tablo oluşturma) çalıştırılamaz veya yetki yükseltmesi tehlikesi oluşur.

---

## Docker Compose Migration

`compose.prod.yml` içindeki `migrate` servisi, bir kereye mahsus `alembic upgrade head` çalıştırır. `backend` servisi ise `condition: service_completed_successfully` kuralı sayesinde bu işlem bitmeden ayağa kalkmaz.

**Doğrulama:**
```bash
# Servis logunu izleyin
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod logs migrate

# Postgres içinden versiyon numarasını teyit edin
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod exec db \
  psql -U "$POSTGRES_USER" -d kachow -c "SELECT version_num FROM alembic_version;"
```

---

## Kubernetes Migration

Kubernetes tarafında migration bir Pod/Deployment InitContainer'ı olarak DEĞİL, tek seferlik bir **Job** (`deploy/kubernetes/migrate-job.yaml`) olarak çalışır. Bunun nedeni çoklu replikalarda (N adet Backend Pod'u) eşzamanlı Alembic çalışmasını (Race Condition) önlemektir.

**Çalıştırma Adımları:**
```bash
# 1. Job'u gönderin
kubectl apply -f deploy/kubernetes/migrate-job.yaml

# 2. Tamamlanmasını bekleyin
kubectl -n kachow wait --for=condition=Complete job/kachow-migrate --timeout=120s

# 3. Logları kontrol edin
kubectl -n kachow logs job/kachow-migrate
```

> **NOT:** Aynı isimli Kubernetes Job'ları immutable'dır (Değiştirilemez). Bir sonraki versiyon güncellemesinde (`v1.1 -> v1.2`) önce eski Job silinmeli (`kubectl delete job kachow-migrate -n kachow`), ardından yeni Job Apply edilmelidir.

---

## LangGraph (Yapay Zekâ) Tabloları İstisnası

`checkpoint*` önekli AI Agent bellek tabloları (`AsyncPostgresSaver`) Alembic tarafından **yönetilmez**.
Bu tablolar, uygulamanın başlatılması anında `app.infrastructure.checkpointing.init_checkpointer` metodu ile doğrudan (Native) yaratılır. Alembic `env.py` kuralı (include_object) bu tabloları özellikle hariç tutar. Migration geçmişinde görünmemeleri hata değildir, beklenen bir durumdur.
