# Docker Compose Dağıtımı

> `compose.prod.yml`, geliştirme için kullanılan `compose.yml` dosyasının üzerine binen bir **override (üzerine yazma)** dosyasıdır ve tek başına kullanılamaz. Prodüksiyon ortamı için optimize edilmiştir.

---

## Prodüksiyon (Prod) Dosyasının Farkları

- Kaynak kodları Container'a bind mount edilmez.
- `db`, `redis`, `qdrant` servis portları dış ağa açılmaz (İzole ağ).
- Container'lara kaynak limitleri (CPU/RAM) ve log rotasyonu eklenir.
- Migration'ı yöneten tek seferlik `migrate` servisi devreye girer.
- Sırlar `${VAR:?...}` formatıyla zorunlu kılınmıştır. Eksik değişken sessizce varsayılana düşmez, `docker compose up` hata verip durur.

---

## Dağıtım Adımları

```bash
# 1. Ortam Değişkenleri ve Sırların Hazırlanması
cp .env.prod.example .env.prod
nano .env.prod # ZORUNLU: Tüm alanları gerçek değerlerle doldurun.

# 2. Prodüksiyon İmajlarının İnşası (Build)
docker build -f deploy/docker/backend.prod.Dockerfile -t kachow-backend:latest .
docker build -f deploy/docker/frontend.prod.Dockerfile -t kachow-frontend:latest .

# 3. Servislerin Başlatılması
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod up -d

# 4. Migration Kontrolü
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod logs migrate

# 5. Sağlık (Liveness/Readiness) Kontrolü
curl -f http://localhost/api/v1/health
```

> **NOT:** `backend` servisi, `migrate` servisi başarıyla (`service_completed_successfully`) tamamlanmadan ayağa kalkmaz (`depends_on`). Başlatma sırası otomatik olarak yönetilir.

---

## `MEVZUAT_SOURCE` Ayarı

Prodüksiyon imajı (`backend.prod.Dockerfile`) varsayılan olarak canlı MCP servisini **inşa etmez** (`WITH_MEVZUAT_MCP=0`). Hızlı yanıt ve stabilite için:

1. `.env.prod` içinde `MEVZUAT_SOURCE=local` bırakılması önerilir.
2. Canlı sorgu (Mevzuat.gov.tr) isteniyorsa imaj aşağıdaki şekilde yeniden inşa edilmelidir:
   ```bash
   docker build --build-arg WITH_MEVZUAT_MCP=1 -f deploy/docker/backend.prod.Dockerfile -t kachow-backend:latest .
   ```
   Ve ardından ortam değişkeni `MEVZUAT_SOURCE=mcp` yapılmalıdır.

---

## Ölçeklendirme ve Limitler

Docker Compose üzerinde `backend` servisini `--scale backend=N` komutuyla ölçeklendirmeyiniz. Yerel disk (Local Volume) kullanan `backend_storage_data` birden fazla replikada paralel kullanıldığında compose seviyesinde ağ ve Service DNS çakışmalarına neden olur.

**Gerçek yatay ölçekleme istiyorsanız:** Lütfen Kubernetes manifestlerini ([kubernetes.md](kubernetes.md)) veya Swarm kullanınız.

---

## Servisleri Durdurma ve Veri Temizliği

Yalnızca servisleri durdurmak için:
```bash
docker compose -f compose.yml -f compose.prod.yml --env-file .env.prod down
```

> **UYARI (Veri Kaybı Riski):** `-v` parametresini kullanırsanız, `postgres_data`, `qdrant_data`, `redis_data` ve `backend_storage_data` kalıcı birimleri tamamen silinir. Sadece kasıtlı yıkım için kullanınız.
