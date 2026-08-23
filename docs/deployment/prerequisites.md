# Ön Koşullar

## Her iki yol için ortak

- **Bir Ollama sunucusu**, ağ üzerinden erişilebilir (`OLLAMA_BASE_URL`).
  Bu repo Ollama'yı deploy etmez — kendi GPU'lu makinenizde veya ayrı bir
  sunucuda çalıştırmanız gerekir. En az `OLLAMA_MODEL` (varsayılan
  `qwen3.5:9b`) ve `OLLAMA_EMBEDDING_MODEL` (varsayılan
  `nomic-embed-text:latest`) `ollama pull` ile önceden çekilmiş olmalı;
  aksi halde ilk çağrı modeli indirmeye çalışırken zaman aşımına uğrar.
- **Bir konteyner registry'si** (GHCR, Docker Hub, kendi private
  registry'niz) — `deploy/docker/backend.prod.Dockerfile` ve
  `deploy/docker/frontend.prod.Dockerfile`'ı build edip bu registry'ye
  push etmeniz gerekir; bu repo bunu sizin için otomatik yapmaz
  (Workstream I'in CI'ı şu an yalnızca `workflow_dispatch` ile elle
  tetikleniyor).
- **DNS + TLS sertifikası**, kullanıcı yüzü olan bir domain için (compose
  yolunda nginx'in önüne kendi reverse proxy'nizi/TLS terminasyonunuzu siz
  eklersiniz; k8s yolunda `deploy/kubernetes/ingress.yaml` cert-manager
  varsayıyor).

## Docker Compose yolu

- Docker Engine + Compose v2 (`docker compose`, tire olmadan).
- Tek makinede en az: backend (4GB RAM önerilir, LLM client'ları ve
  LangGraph workflow'larını bellekte tutar), Postgres, Qdrant, Redis için
  yeterli disk (`compose.prod.yml`'in PVC eşdeğeri olan named volume'lar
  20GB+ büyüyebilir).

## Kubernetes yolu

- `kubectl` + erişebildiğiniz bir cluster (1.27+; `deploy/kubernetes/*.yaml`
  bu sürümde test edildi — bkz. [kubernetes.md](kubernetes.md)'nin doğrulama
  bölümü).
- Bir `StorageClass` sağlayan bir CSI sürücüsü (`postgres.yaml`/
  `qdrant.yaml`/`redis.yaml`/`backend.yaml` hepsi `PersistentVolumeClaim`
  kullanır, `ReadWriteOnce`).
- **ingress-nginx** kurulu (`deploy/kubernetes/ingress.yaml`'in
  annotation'ları ingress-nginx'e özel) ve **cert-manager** kurulu (TLS
  için `ClusterIssuer`).
- Namespace-level `NetworkPolicy` desteği olan bir CNI (Calico, Cilium,
  vb.) — `deploy/kubernetes/namespace.yaml`'in default-deny politikaları
  bunu varsayar; desteklemeyen bir CNI'da (bazı bulut sağlayıcılarının
  varsayılan CNI'ları) bu politikalar sessizce hiçbir şey yapmaz, yani
  izolasyon *görünüşte* var ama gerçekte yok.

## Ne bu repoda YOK

- Bir yönetilen Postgres/Redis/Qdrant servisi — hepsi self-hosted olarak
  yazıldı (bkz. `deploy/kubernetes/postgres.yaml`'ın kendi yorumunda "gerçek
  bir deployment için managed Postgres tercih edilmeli" notu). Kendi
  yönetilen servislerinizi kullanacaksanız bu üç manifest'i/compose
  servisini uygulamayın, bunun yerine `configmap.yaml`/`.env.prod`'daki
  `QDRANT_URL`/`REDIS_URL`/`DATABASE_URL` değerlerini kendi servislerinize
  yönlendirin.
- Bir S3/MinIO servisi — `STORAGE_TYPE=s3` desteklenir
  (`backend/app/infrastructure/storage/s3.py`) ama compose/k8s
  manifest'lerinin hiçbiri bir MinIO servisi içermiyor; kendi
  S3-uyumlu depolamanızı getirmeniz gerekir.
