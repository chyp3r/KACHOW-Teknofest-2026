# Gözlemlenebilirlik (Observability)

> Sistemin metrik, iz (Trace) ve sağlık verilerinin toplanması ve gösterilmesi için kullanılan altyapıyı açıklar.

---

## Prometheus ve Grafana

**Docker Compose:** `compose.yml` içinde hazır gelir (`prometheus:9090`, `grafana:3001`). Varsayılan Grafana şifresi `admin`'dir.
**Kubernetes:** Kubernetes yolunda (Manifestlerde) Prometheus/Grafana kasten **yoktur**. Kurumun kendi Prometheus Operator (Kube-prometheus-stack vb.) çözümünü kullanması beklenir.

### Scrape (Veri Çekme) Hedefleri

`monitoring/prometheus/prometheus.yml` dosyasındaki ayarlar:

| Hedef Servis | Uç Nokta (Endpoint) | Açıklama |
| :--- | :--- | :--- |
| `kachow-backend` | `backend:8000/metrics` | FastAPI ve uygulama seviyesi özel (AI) metrikleri. |
| `qdrant` | `qdrant:6333/metrics` | Qdrant Native exporter'ı üzerinden çekilir. Ek sidecar gerektirmez. |
| `postgres` / `redis` | Yok | Bilinçli olarak harici Exporter (postgres_exporter vb.) eklenmemiştir. İstenirse yan konteyner (Sidecar) olarak operatör tarafından eklenebilir. |

---

## Alert (Uyarı) Kuralları

`monitoring/prometheus/rules/kachow.rules.yml` dosyasında 4 grupta toplanmış 12 temel kural bulunur:
- `kachow.availability` (Kullanılabilirlik)
- `kachow.ai_workflow` (Yapay Zekâ Akışları)
- `kachow.guardrail` (Güvenlik Kalkanı Hataları)
- `kachow.llm_latency` (Gecikmeler)

> **NOT:** Her kural bir `runbook_url` etiketi taşır ve doğrudan [runbook.md](runbook.md) içindeki çözüm adımlarına yönlendirir. Alertler tetiklendiğinde ilk bakılacak yer Runbook olmalıdır.

---

## Alertmanager (Bildirim Yönlendirme)

Sadece `compose.prod.yml`'de mevcuttur. Geliştirme (Dev) ortamında devre dışıdır.
`monitoring/alertmanager/alertmanager.yml` dosyası **Placeholder** bir rota ile gelir. Tüm alarmlar sessize (`null` receiver) düşer. 

Prodüksiyona çıkmadan önce `critical` yönlendiricisine mutlaka bir webhook (Slack, Opsgenie) veya E-posta konfigürasyonu girilmelidir. Kubernetes kullanıcıları kendi kurulu Alertmanager'larını kullanmalıdır.

---

## OpenTelemetry (Sistem İzleme / Tracing)

Langfuse yalnızca LLM çağrılarını görür, ancak HTTP istekleri, veritabanı (Postgres) veya Qdrant sorgularının (ve yavaşlıkların) tespit edilebilmesi için OTel (OpenTelemetry) kullanılır.

`OTEL_EXPORTER_OTLP_ENDPOINT` ortam değişkeni boş bırakılırsa, OTel izleme modülü hiçbir kodu import etmeden kendini kapatır (No-op Fallback). Compose ile birlikte gelen Jaeger servisi (`jaegertracing/all-in-one`) üzerinden çalışır (OTLP/gRPC `4317`, UI `16686`).

| Araç | Kullanım Amacı ve Sorusu |
| :--- | :--- |
| **Langfuse** | "Bu taslak neden düşük güven skoru aldı? LLM'e ne prompt gitti?" |
| **OTel/Jaeger** | "Sistem neden yavaş? Zaman LLM'de mi, DB'de mi, Vektör aramasında mı geçti?" |

---

## Langfuse (LLM Metrikleri)

`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` değerleri girilmezse sessizce kapanır.

**Uyarı (Versiyon Uyuşmazlığı):** Compose üzerinde `langfuse/langfuse:2` sunucusu sabittir, ancak `backend` Python SDK'sı `v4` kullanmaktadır. Prodüksiyona çıkılmadan önce imajın `v3/v4` ile uyumlu olacak şekilde test edilip güncellenmesi operatörün sorumluluğundadır.

---

## Gösterge Panelleri (Dashboards)

Grafana panelleri `monitoring/dashboards/*.json` altındadır:
- `company_dashboard.json`
- `fastapi_dashboard.json`
- `transfers_dashboard.json`

Compose kullanıldığında Volume Mount üzerinden otomatik yüklenirler.
