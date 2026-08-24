# Ön Koşullar (Prerequisites)

> Sistemin prodüksiyon (Staging/Prod) ortamlarına dağıtılmasından önce sahip olmanız gereken altyapı gereksinimlerini listeler.

---

## Ortak Gereksinimler (Tüm Ortamlar İçin)

- **Ollama Sunucusu:** Ollama hizmeti doğrudan KACHOW reposundan dağıtılmaz. Kendinize ait harici bir GPU sunucusunda çalışıyor olmalıdır. İlgili bağlantı `OLLAMA_BASE_URL` ile tanımlanır.
  - Sistemin başlaması için `OLLAMA_MODEL` (Qwen3.5) ve `OLLAMA_EMBEDDING_MODEL` (Nomic) imajlarının önceden `ollama pull` ile sunucuya indirilmiş olması gerekir (Aksi takdirde ilk çağrı (Timeout) zaman aşımına düşer).
- **Konteyner Registry:** Üretilen `backend.prod.Dockerfile` ve `frontend.prod.Dockerfile` imajlarının gönderileceği (Push) güvenli bir depolama (GHCR, Docker Hub, Harbor vb.) alanı.
- **Alan Adı (DNS) ve SSL/TLS:** Sistemin güvenliği (HTTPS) için kendi Reverse Proxy veya Ingress (Cert-Manager) altyapınızın hazır olması gereklidir.

---

## Docker Compose Ortamı

- **Yazılım:** Docker Engine ve Docker Compose v2 (`docker compose`).
- **Donanım:** LLM Client'larını (Yapay Zeka oturumlarını) bellekte tutacak en az **4GB RAM**. Postgres, Qdrant ve Redis Volume'leri (PVC benzeri Named Volumes) için minimum **20GB+ ayrılmış boş disk**.

---

## Kubernetes Ortamı

- **Yazılım:** K8s Cluster Sürüm v1.27 ve üzeri (Manifest uyumluluğu test edilmiştir) ve yetkili `kubectl` istemcisi.
- **Disk / Depolama (Storage):** Dinamik bir `StorageClass` sağlayan CSI sürücüsü. Postgres, Redis, Qdrant ve Backend hizmetlerinin hepsi `PersistentVolumeClaim` (ReadWriteOnce) talep edecektir.
- **Ağ (Networking):** 
  - Gelen trafik yönetimi için `ingress-nginx` (Anotasyonlar bu denetleyiciye özeldir).
  - Otomatik SSL temini için `cert-manager`.
- **Güvenlik (CNI):** Namespace bazlı `NetworkPolicy` desteğine sahip bir Container Network Interface (Örn: Calico, Cilium). Flannel veya bazı basit bulut CNI'ları varsayılan izolasyonları görmezden gelerek güvenlik açığı oluşturur.

---

## Depo Kapsamına Girmeyen Bileşenler

Bu proje, bulut servislerini taklit etmeye çalışmaz. Aşağıdaki bileşenler repoda bulunmaz veya haricen kullanılması önerilir:

1. **Yönetilen (Managed) Veritabanları:** Proje içerisindeki Postgres, Qdrant ve Redis manifestleri kendi-kendini (Self-hosted) barındırmak isteyenler içindir. Güçlü bir prodüksiyon altyapısında; kurumunuzun kendi yönetilen servislerini (AWS RDS vb.) kullanmanız tavsiye edilir. İlgili Yaml/Compose dosyalarını silip, `.env.prod` üzerinden harici URL bağlantılarınızı kurabilirsiniz.
2. **Object Storage (S3 / MinIO):** Sistem `STORAGE_TYPE=s3` değişkenini tam olarak desteklese de MinIO gibi bir hizmetin manifest/compose dosyasını barındırmaz. Kendi Kurumsal (On-Prem veya Bulut) nesne depolama servisinizi bağlamanız gerekir.
