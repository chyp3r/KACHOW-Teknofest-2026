# Gözlemlenebilirlik

## Prometheus + Grafana

`compose.yml` ikisini de sağlar (`prometheus:9090`, `grafana:3001`,
varsayılan admin şifresi `admin` — bkz. [configuration.md](configuration.md)).
Kubernetes yolunda bu ikisi için manifest **yok** — kendi Prometheus
operator'ünüzü (kube-prometheus-stack vb.) kurup
`monitoring/prometheus/rules/kachow.rules.yml`'i onun beklediği
`PrometheusRule` CRD şekline çevirmeniz gerekir.

`monitoring/prometheus/prometheus.yml`:
- `kachow-backend` job'ı `backend:8000/metrics`'i scrape eder.
- `qdrant` job'ı `qdrant:6333/metrics`'i scrape eder (Qdrant'ın kendi
  native Prometheus endpoint'i — ayrı bir exporter gerekmez, doğrulandı).
- **Postgres ve Redis için scrape yapılandırması yok.** İkisinin de bu
  repoda deploy edilen bir Prometheus exporter'ı yok
  (`postgres_exporter`/`redis_exporter`) — `up{job="postgres"}` gibi bir
  metrik hiçbir zaman var olmaz. Bu bilinçli bir kapsam sınırı, unutulmuş
  bir şey değil: `kachow.rules.yml`'in kendi üst yorumu bunu açıkça
  söylüyor. Eklemek isterseniz her ikisi de sidecar container olarak
  compose/k8s'e eklenip `prometheus.yml`'e scrape config'i yazılmalı.

## Alert kuralları

`monitoring/prometheus/rules/kachow.rules.yml` — 12 kural, 4 grup
(`kachow.availability`, `kachow.ai_workflow`, `kachow.guardrail`,
`kachow.llm_latency`). Her kural gerçek, doğrulanmış bir metrik adına
karşı yazıldı — `backend/tests/e2e/test_health_and_metrics_e2e.py`'nin
`_EXPECTED_METRIC_NAMES` listesi bu adların bir metrik yeniden
adlandırmasıyla sessizce kırılmasını engelleyen kontrat testidir.

Her alert bir `runbook_url` annotation'ı taşır — bkz.
[runbook.md](runbook.md).

**`KachowNodeBudgetExhaustion`**, `kachow_node_budget_seconds`
gauge'ını (H1, `app.observability.ai_metrics.init_ai_metrics`'te
`BudgetPolicy.node_seconds`'tan set edilir) `kachow_node_duration_
seconds`'ın p95'iyle karşılaştırır — policy katmanındaki bir bütçe
değişikliği otomatik olarak alert eşiğine yansır, elle senkronize
edilmesi gereken ikinci bir sayı yok.

Kuralları test etmek:
```bash
docker compose exec prometheus promtool check rules /etc/prometheus/rules/kachow.rules.yml
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
```

## Alertmanager

Yalnızca `compose.prod.yml`'de var (dev'de yok — Prometheus/Grafana'nın
kendi UI'ından firing alert'leri görmek yeterli, dev'de kimseye page
atmak gerekmiyor). `monitoring/alertmanager/alertmanager.yml`
**placeholder bir routing** ile gelir: her şey `null` receiver'a gider
(hiçbir yere bildirim gitmez), `severity: critical` `critical`
receiver'ına — o da varsayılan olarak boş. **Production'a almadan önce**
`critical` receiver'ına gerçek bir webhook (Slack/PagerDuty/Opsgenie)
veya `email_configs` ekleyin; aksi halde `KachowBackendDown` gibi kritik
bir alert Alertmanager UI'ında görünür ama kimseyi uyandırmaz.

Kubernetes yolunda Alertmanager de yok — kendi Prometheus operator'ünüzün
kendi Alertmanager'ını kullanın.

## OpenTelemetry (altyapı izleme)

Langfuse yalnızca LLM çağrılarını görür (LangChain callback'i üzerinden).
HTTP isteği, Postgres sorgusu, Redis komutu ve dışa giden `httpx` çağrısı
(Qdrant, Ollama) hiçbirinde Langfuse span'i yoktur -- yavaş bir chat turunun
modelde mi, veritabanında mı, vektör deposunda mı geçtiğini ayırt etmenin
tek yolu budur.

`backend/app/observability/otel.py::init_tracing` bunu sağlar:
`OTEL_EXPORTER_OTLP_ENDPOINT` boşsa **hiçbir SDK modülü import edilmeden**
no-op'a düşer -- Langfuse'un anahtar-yokken-degrade'iyle aynı ilke, eksik
bir collector backend'in açılmasını engellemez. `compose.yml`/
`compose.prod.yml` bu değişkeni varsayılan olarak kendi `jaeger`
servisine (`jaegertracing/all-in-one`, OTLP/gRPC alıcısı `4317`, UI
`16686`) işaret eder.

**Langfuse vs OTel -- hangi soruyu hangisine sorarsınız:**
- "Bu taslak neden düşük güven skoru aldı, prompt'a ne gönderildi?" →
  Langfuse.
- "Bu chat turu neden 8 saniye sürdü, zaman nerede geçti?" → OTel/Jaeger.

İkisi rakip değil, aynı anda çalışırlar; biri diğerinin yerine geçmez.

## Langfuse (LLM izleme)

`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` boşsa Langfuse sessizce devre
dışı kalır (`app/observability/tracer.py`'nin kendi no-op degrade'i).

**Bilinen sürüm uyuşmazlığı, çözülmedi:** `compose.yml` sunucu imajı
olarak `langfuse/langfuse:2` sabitliyor, ama `backend/requirements.txt`
Python SDK'sı olarak v4'ü taşıyor. `compose.yml`'in kendi yorumu "v2
server v4 SDK ile uyumsuz, v3 eşleşen hat" diyor — yani şu an ya sunucu
imajını v3'e çevirmek ya da SDK'yı v2-uyumlu bir sürüme indirmek gerekiyor.
Bu doküman bunu çözmüyor, yalnızca kaydediyor; production'a Langfuse ile
çıkmadan önce bu ikisini gerçekten uyumlu bir çiftle test edin.

## Dashboard'lar

`monitoring/dashboards/*.json` — `company_dashboard.json`,
`fastapi_dashboard.json`, `transfers_dashboard.json`. Grafana'ya
`monitoring/grafana/provisioning/dashboards/dashboards.yml` üzerinden
otomatik yüklenir (compose.yml'in volume mount'u).
