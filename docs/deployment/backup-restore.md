# Yedekleme ve Geri Yükleme (Backup & Restore)

> Sistemin kalıcı (Persistent) verileri üç ayrı kaynağa ayrılır: Postgres (İlişkisel), Qdrant (Vektörel) ve Object Storage (Dosyalar).

---

## 1. PostgreSQL (Kritik)

Kullanıcılar, kayıtlar, taslaklar, denetim izleri (Audit) ve RLS Tenant verilerini taşır. Mutlaka düzenli yedeklenmelidir.

Standart SQL (`.sql`) yerine `pg_dump`'ın Özel Formatı (`-Fc` Custom Format) kullanılmalıdır. Bu sayede geri yüklemede (Restore) seçici tablo aktarımı ve paralel işleme yapılabilir.

**Yedek Alma (Backup):**
```bash
# Docker Compose
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod \
  exec db pg_dump -U "$POSTGRES_USER" -Fc kachow > kachow-$(date +%F).dump

# Kubernetes
kubectl -n kachow exec postgres-0 -- pg_dump -U postgres -Fc kachow > kachow-$(date +%F).dump
```

**Geri Yükleme (Restore):**
```bash
pg_restore -U postgres -d kachow --clean --if-exists kachow-2026-08-23.dump
```
> **NOT:** `--clean --if-exists` parametresi mevcut (eski) tabloları tamamen ezip yenilerini yazar, boş veritabanlarında zararsızdır. 
> Ayrıca `langfuse` loglarını barındıran ayrı veritabanının da isteniyorsa benzer şekil de yedeklenmesi gerekir.

---

## 2. Qdrant (Vektör Deposu)

Qdrant indeksleri (`mevzuat`, `resmi_yazisma_ornek`, `document_qa`) kaybedilirse metinlerden tekrar oluşturulabilir ancak işlem uzun sürer (Özellikle Q&A Koleksiyonu). Qdrant Native Snapshot API'si kullanılmalıdır.

**Snapshot Alma:**
```bash
curl -X POST http://qdrant:6333/collections/document_qa/snapshots
curl -X POST http://qdrant:6333/collections/mevzuat/snapshots
# Diğer tüm koleksiyon isimleri için aynısı yapılmalıdır.
```
Snapshot'lar Qdrant içinde `/qdrant/storage/snapshots/` klasörüne (PVC) yazılır, oradan dış ortama kopyalanmalıdır.

---

## 3. Belge Depolama (Storage Data)

Ham PDF/Belgeleri ve metadata (Cache) içeriklerini tutar.

| Depolama Tipi | Yedekleme Yöntemi |
| :--- | :--- |
| `STORAGE_TYPE=local` | Yerel Disk veya PVC yedeği (CSI Snapshot, Velero). Veya basit TAR arşivi: `tar czf backup.tar.gz /data` |
| `STORAGE_TYPE=s3` | Bulut veya On-prem S3 sisteminizin otomatik Snapshot ve Replication (Versiyonlama) özelliklerine bırakılır. |

---

## 4. Tam Geri Yükleme Sırası (Restore Sequence)

Sistemi baştan (Disaster Recovery) ayağa kaldırmak için doğru sıralama:

1. **Postgres** yedeğini `pg_restore` ile yükleyin.
2. **Qdrant** Snapshot'larını API ile içe aktarın (Import).
3. **Storage** dosyalarını yerine koyun.
4. En son `backend` servislerini başlatın.

> **ÖNEMLİ:** `pg_restore` yaptıktan sonra `migrate` servisini/Job'ını **ÇALIŞTIRMAYIN**. Alembic zaten `alembic_version` tablosundan (Restore edilen veritabanı içindeki) Head (Güncel sürüm) numarasına ulaşıp şemanın son sürümde olduğunu görecektir. Hata olmaması için versiyonun tutarlı olduğunu teyit edin: `SELECT version_num FROM alembic_version;`
