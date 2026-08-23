# Runbook

Her başlık, `monitoring/prometheus/rules/kachow.rules.yml`'deki alert
adıyla birebir eşleşir — her alert'in `runbook_url` annotation'ı
doğrudan buradaki ilgili bölüme işaret eder.

## KachowBackendDown

**Anlamı:** Prometheus, `backend` job'ından 2 dakikadır `up` sinyali
alamıyor.

**İlk adımlar:**
1. `kubectl -n kachow get pods -l app=kachow-backend` / `docker compose ps backend` — pod/container `CrashLoopBackOff`/`Restarting` mi?
2. Loglara bakın. En sık iki sebep: `SECRET_KEY`/`REQUIRE_AUTH` guard'ının reddi (`app.lifespan`, bkz. [configuration.md](configuration.md)) ya da Postgres'e bağlanamama.
3. `kubectl -n kachow logs -l app=kachow-backend -c wait-for-migrations` (k8s) — initContainer migration'ı bekliyor da olabilir, henüz gerçek bir arıza olmayabilir.

## KachowQdrantDown

**Anlamı:** Qdrant 2 dakikadır scrape edilemiyor.

**Etki:** Retrieval (mevzuat önerisi, belge Q&A) ve yeni belge indeksleme
çalışmaz; `?deep=true` health check `qdrant: down` raporlar, `backend`
readiness'i düşer (k8s'te trafik almayı bırakır).

**İlk adımlar:**
1. `kubectl -n kachow get pods -l app=kachow-qdrant` / `docker compose ps qdrant`.
2. Disk doldu mu? Qdrant'ın PVC/volume kullanımını kontrol edin.
3. Kurtarma sonrası: `curl qdrant:6333/readyz` 200 dönene kadar bekleyin, alert otomatik `inactive`'e döner (elle bir müdahale gerekmez).

## KachowHighErrorRate

**Anlamı:** 5 dakikalık pencerede isteklerin %5'inden fazlası 5xx.

**İlk adımlar:**
1. `backend` loglarında hangi endpoint/exception tekrar ediyor bakın (`app.api.middleware.logging`'in `http_request_finished` satırları `http_status` taşır).
2. Yakın zamanda bir deploy oldu mu? Bir önceki imaja rollback edilebilir (bkz. [upgrade.md](upgrade.md)).
3. Downstream (Ollama/Postgres/Qdrant) bir outage'ı mı yansıtıyor -- diğer alert'lere bakın.

## KachowNodeBudgetExhaustion

**Anlamı:** Bir workflow node'unun (`{{ $labels.node }}`) p95 süresi
kendi `BudgetPolicy.node_seconds` bütçesinin %80'ini aşıyor.

**Etki:** Bütçeyi tamamen aşan çalışmalar `NodeBudgetExceeded` ile
başarısız olur (bkz. `app/ai/workflows/resilience.py`'nin kendi
docstring'i — bilerek retry edilmez, tekrar denemek daha da yavaş bir
modelde aynı sonucu üretir).

**İlk adımlar:**
1. Hangi node olduğuna bakın (`analyze`, `writer`, `suggest_mevzuat`, vb.) -- `evaluation/latency/budget_report.py`'yi çalıştırıp aynı görüntüyü daha ayrıntılı görün.
2. Ollama gerçekten yavaşladı mı (GPU kuyruğu, başka bir model paylaşımlı mı çalışıyor) yoksa gerçek bir regresyon mu (yakın zamanda bir prompt/model değişikliği) kontrol edin.
3. Bütçe gerçekten değiştirilmesi gerekiyorsa `backend/app/ai/policy/schema.py`'deki `BudgetPolicy.node_seconds`'ı güncelleyin -- bu, `kachow_node_budget_seconds` gauge'ına otomatik yansır (H1), elle senkronize edilecek ikinci bir yer yok.

## KachowJudgeDegraded

**Anlamı:** Taslak kalite yargıcı (LLM judge) sık sık gerçek bir verdict
yerine degrade ediyor.

**İlk adımlar:** Ollama model sağlığını kontrol edin (`OLLAMA_MODEL`
gerçekten yüklü mü, `ollama list`). Yapılandırılmış çıktı parse hataları
mı, zaman aşımı mı olduğuna loglardan bakın.

## KachowGuardrailJudgeDegraded

**Anlamı (kritik):** Guardrail nüans katmanı deterministik-yalnız
verdict'e düşüyor -- bu bir performans sorunu değil, **güvenlik ilgili**:
sistem hassasiyet/PII kararlarını modelin nüanslı değerlendirmesi olmadan
veriyor.

**İlk adımlar:** `KachowJudgeDegraded` ile aynı kök sebepler (Ollama
sağlığı) daha yüksek öncelikle araştırılmalı -- bu alert `critical`.

## KachowRouterSemanticUnavailable

**Anlamı:** Niyet çözümleme ladder'ının semantik katmanı (Layer 2)
devre dışı -- prototip vektör dosyası bayat (farklı embedding modeli/
policy sürümü altında build edilmiş) veya hiç yok.

**Etki:** Lexical katmanın abstain ettiği her mesaj doğrudan clarify/model
fallback'e düşer, ikinci bir semantik görüş almadan.

**Çözüm:** `scripts/build_prototypes.py`'yi çalıştırın (gerçek bir Ollama
embedding çağrısı gerektirir).

## KachowDraftQualityDrop

**Anlamı:** Taslak güven skorunun medyanı 30 dakikadır 60'ın altında (50
= route edilemez, 70 = incelemesiz gönderilebilir eşikleri arasında).

**İlk adımlar:** Yakın zamanda bir prompt/model değişikliği oldu mu?
`evaluation/generate_report.py --suite drafts` ile gold set'e karşı
regresyon var mı kontrol edin.

## KachowHITLBacklog

**Anlamı:** Son 1 saatte açılan human-in-the-loop duraklamaları
(`kachow_hitl_interrupts_total`) kapananlardan (`kachow_hitl_resume_
total`) 5'ten fazla geride.

**Etki:** Kullanıcılar cevap bekleyen taslaklarda takılı kalıyor.

**İlk adımlar:** Bu bir uygulama arızası değil, genelde bir kullanıcı
davranışı sinyali -- bildirim sistemi (`kachow_hitl_interrupts_total`'ın
kaynağı olan gate'ler) kullanıcılara ulaşıyor mu kontrol edin.

## KachowStructuredRetryStorm

**Anlamı:** Model, yapılandırılmış (JSON) çıktı üretmede sık sık ilk
denemede başarısız oluyor, `BaseAgent.run_structured`'ın retry döngüsüne
düşüyor.

**İlk adımlar:** Model değişti mi (farklı bir model JSON-mode'u farklı
destekliyor olabilir)? Prompt şablonlarında yakın zamanlı bir değişiklik
var mı (`backend/app/ai/prompts/manager.py`'nin `TEMPLATE_CONTRACTS`'ı).

## KachowGuardrailBlockSpike

**Anlamı:** Guardrail engelleme (block) oranı normalin üzerinde.

**İlk adımlar:** Toplu bir yanlış-pozitif mi (bir kural/regex çok
agresif hale geldi) yoksa gerçek bir kötüye kullanım denemesi mi ayırt
edin -- `kachow_company_guardrail_blocks_total`'ı `company`/`kind`
kırılımıyla inceleyin, tek bir şirkette mi yoğunlaşıyor.

## KachowLLMCallLatencyHigh

**Anlamı:** Bir agent'in (`{{ $labels.agent }}`) LLM çağrısı p95 süresi
60 saniyeyi aşıyor.

**İlk adımlar:** Ollama'nın kendi kaynak kullanımına (GPU/CPU/bellek)
bakın. `KachowNodeBudgetExhaustion` ile birlikte tetikleniyorsa aynı kök
sebep muhtemelen.
