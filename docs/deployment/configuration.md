# Yapılandırma

Tüm ortam değişkenlerinin tanımlı olduğu tek kaynak:
`backend/app/core/config.py`'nin `Settings` sınıfı. Bu doküman onun
kopyası değil — production'da **zorunlu** olanları, **güvensiz
varsayılan** taşıyanları ve deploy yoluna özgü olanları listeler.

## Production'da zorunlu (varsayılanla asla çalıştırmayın)

| Değişken | Varsayılan | Neden değiştirilmeli |
|---|---|---|
| `SECRET_KEY` | `supersecretkeychangeinproduction` | Her JWT'yi imzalar; varsayılan public (bu reponun kaynağında). `app.lifespan._require_secret_key_in_production` `ENVIRONMENT=production` + varsayılan değerle **boot'u reddeder** — bu bir öneri değil, zorlanan bir kural. |
| `REQUIRE_AUTH` | `true` | Zaten güvenli varsayılan, ama açıkça `false`'a çekmeyin. `app.lifespan._require_auth_in_production` `ENVIRONMENT=production` + `false` ile de boot'u reddeder. |
| `KACHOW_APP_DB_PASSWORD` | `kachow_app_dev_only` | Postgres RLS'nin dayandığı kısıtlı rolün şifresi. |
| `POSTGRES_PASSWORD` (compose)/`POSTGRES_PASSWORD` (k8s secret) | — | Schema-owner rolü. |
| `GRAFANA_ADMIN_PASSWORD` (compose.yml) | `admin` | Değiştirilmezse Grafana dashboard'larınıza herkes `admin`/`admin` ile girer. |

## `ENVIRONMENT`

`development` (varsayılan) / `staging` / `production`. Yalnızca
`production` iki boot-time guard'ı tetikler (yukarıdaki tablo). Bir
staging ortamı gerçek sırlar kullanıyorsa yine de `production` set etmeyi
düşünün — guard'lar zarar vermez, yalnızca varsayılanları reddeder.

## Depolama (`STORAGE_TYPE`)

`local` (varsayılan) veya `s3`. `local` seçiliyken belge blob'ları ve
analiz cache'i (`LOCAL_STORAGE_DIR`, varsayılan `./storage_data`) bir
`PersistentVolumeClaim`/named volume üzerinde yaşar ve **`backend`'in tek
replika olmasını gerektirir** — bkz. [kubernetes.md](kubernetes.md)'nin
`replicas: 1` bölümü. `s3` için: `S3_BUCKET_NAME`, `S3_ENDPOINT_URL`,
`S3_ACCESS_KEY`, `S3_SECRET_KEY` (`app/infrastructure/storage/s3.py`).

## Mevzuat kaynağı (`MEVZUAT_SOURCE`)

`mcp` (varsayılan) veya `local`. `deploy/docker/backend.prod.Dockerfile`
`mevzuat-mcp`'yi (canlı mevzuat.gov.tr sorgusu, Playwright+Chromium)
**build etmez** (`WITH_MEVZUAT_MCP=0`, varsayılan). Prod imajınızı bu
varsayılanla build ettiyseniz `MEVZUAT_SOURCE=local` set edin — aksi
halde her sorgu önce başarısız olması kesin bir MCP denemesi yapıp
commit'li korpusa (`FallbackMevzuatRetriever`) düşer: çalışır ama
gereksiz gecikme ekler.

## Zaman aşımları (saniye)

`AI_WORKFLOW_TIMEOUT_SECONDS` (480), `DRAFT_JUDGE_TIMEOUT_SECONDS` (30),
`GUARDRAIL_JUDGE_TIMEOUT_SECONDS` (15), `REVISION_RERETRIEVAL_TIMEOUT_
SECONDS` (10), `MEVZUAT_MCP_TIMEOUT_SECONDS` (25), `EXTRACTION_TIMEOUT_
SECONDS` (300), `DETAILED_SUMMARY_TIMEOUT_SECONDS` (400). Yerelde
CPU-only bir modelle test ederken büyütülebilir; production'da GPU'lu bir
Ollama ile varsayılanlar genelde yeterlidir. `BudgetPolicy.node_seconds`
(kod içi, env değil) daha ince granülerlikte ayrı bütçeler tanımlar —
bkz. [observability.md](observability.md)'nin `KachowNodeBudgetExhaustion`
bölümü.

## Feature flag'ler (varsayılanları production için düşünün)

- `HITL_BRIEF_GATE_ENABLED` (true), `HITL_MAX_GATE_REVISIONS` (2)
- `AI_TRANSFER_ENABLED` (true)
- `REVISION_CONFLICT_AUDIT_ENABLED` / `REVISION_RERETRIEVAL_ENABLED` (true)
- `DRAFT_JUDGE_ENABLED` / `GUARDRAIL_JUDGE_ENABLED` (true) — kapatmak
  kaliteyi/güvenliği düşürür, yalnızca bir model outage'ında geçici
  fallback olarak düşünün.
- `SEED_DEMO_COMPANY` / `SEED_DEFAULT_USERS` (true, **varsayılan şifreli
  hesaplar üretir** — `SEED_ROOT_PASSWORD`/`SEED_ADMIN_PASSWORD`/vb.
  hepsi kaynak kodda görünür değerler taşır). Production'da bunları
  `false`'a çekin ya da kendi şifrelerinizle override edin; aksi halde
  bilinen kimlik bilgileriyle bir hesap açık kalır.

## Gözlemlenebilirlik

`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` (boşsa Langfuse sessizce
devre dışı kalır, hata vermez), `LANGFUSE_HOST`. `compose.yml`'in kendi
notu: sunucu `langfuse/langfuse:2`, SDK v4 — sürüm uyuşmazlığı henüz
çözülmedi, bkz. [observability.md](observability.md).

## Deploy yoluna özgü farklar

- Docker Compose: `.env.prod.example`'ı kopyalayıp `.env.prod` yapın,
  `${VAR:?...}` sözdizimi eksik zorunlu değerlerde `up`'ı reddeder.
- Kubernetes: `deploy/kubernetes/configmap.yaml` (sır olmayanlar) +
  `deploy/kubernetes/secrets.yaml` (sırlar) — bkz. [secrets.md](secrets.md).
