# Runbook (Müdahale Rehberi)

> Bu rehber, Prometheus üzerinden tetiklenen (`kachow.rules.yml`) sistem alarmlarına (Alert) karşı operatörün atması gereken ilk adımları ve kök neden analizlerini içerir.

---

## 1. KachowBackendDown

**Durum:** Prometheus, `backend` servisinden 2 dakikadır metrik (`up`) alamıyor.

**Çözüm Adımları:**
1. Pod veya Container durumunu (`CrashLoopBackOff` vb.) kontrol edin.
2. Logları izleyin. En yaygın iki sebep:
   - Prodüksiyonda `SECRET_KEY` veya `REQUIRE_AUTH` varsayılan değerde bırakılmıştır ve güvenlik sistemi önyüklemeyi (Boot) iptal etmiştir (Bkz: [configuration.md](configuration.md)).
   - Postgres veritabanına erişim yoktur.
3. InitContainer Durumu: Kubernetes kullanıyorsanız, `wait-for-migrations` kontyneri veritabanı şemasının güncellenmesini (Job) bekliyor olabilir. Bu gerçek bir hata değildir.

---

## 2. KachowQdrantDown

**Durum:** Qdrant (Vektör Veritabanı) 2 dakikadır yanıt vermiyor. Yeni evrak indekslenemez ve yapay zekâ mevzuat/geçmiş evrakları arayamaz. Backend sağlığı (Readiness) düşer.

**Çözüm Adımları:**
1. Qdrant loglarına ve Pod statüsüne bakın.
2. Sıklıkla PVC (Disk) doluluğu kaynaklıdır. Disk alanını kontrol edin.
3. `curl qdrant:6333/readyz` endpoint'i `200` döndüğünde alarm otomatik olarak kapanacaktır.

---

## 3. KachowHighErrorRate

**Durum:** Son 5 dakika içindeki isteklerin %5'inden fazlası (5xx) hata veriyor.

**Çözüm Adımları:**
1. Backend loglarında yoğunlaşan hata kodunu/Endpoint'i bulun.
2. Hatalar alt katmanlardan (Postgres, Ollama, Qdrant) mi dönüyor inceleyin (Diğer alarmları kontrol edin).
3. Hata yeni bir deploy (Güncelleme) sonrası başladıysa, bir önceki sürüme geri dönün (Rollback).

---

## 4. KachowNodeBudgetExhaustion

**Durum:** Bir AI iş akışı düğümünün (`node`) işlem süresi (p95), belirlenen zaman bütçesinin (`BudgetPolicy.node_seconds`) %80'ini aşıyor. Zaman limitini aşan işlemler iptal (Timeout) edilir.

**Çözüm Adımları:**
1. Hangi düğümün (Örn: `analyze`, `writer`) yavaşladığını bulun.
2. Ollama sunucusundaki GPU kuyruğunu, sistem yükünü veya model değişikliği olup olmadığını denetleyin.
3. Gerekliyse kod (`BudgetPolicy.node_seconds`) üzerinden süreyi artırın; alarm eşiği (`kachow_node_budget_seconds`) otomatik güncellenecektir.

---

## 5. KachowJudgeDegraded ve KachowGuardrailJudgeDegraded

**Durum:** LLM Yargıç (Kalite veya Güvenlik Kapısı) sağlıklı bir yanıt veremiyor ve Fallback (Varsayılan/Sert düşüş) kararları uyguluyor. **GuardrailJudgeDegraded kritik seviyededir**, güvenlik ihlallerine yol açabilir.

**Çözüm Adımları:**
1. Ollama modelinin sağlığını (`ollama list`) ve erişilebilirliğini kontrol edin.
2. Model, verilen yapılandırılmış (JSON) çıktıyı parse edemiyor veya timeout yiyor olabilir. Loglardan hata detayını bulun.

---

## 6. KachowRouterSemanticUnavailable

**Durum:** Niyet çözümleyici (Router), Semantik Vektörlere (Layer 2) ulaşamıyor. 

**Çözüm Adımları:**
1. Prototip vektörleri (`.npy`) eski kalmış veya silinmiş olabilir.
2. Model veya Policy güncellendiyse: `scripts/build_prototypes.py` betiğini çalıştırarak vektörleri yeniden üretin.

---

## 7. KachowDraftQualityDrop

**Durum:** Üretilen taslakların (Draft) güven skorlarının medyanı 30 dakikadır 60'ın altında.

**Çözüm Adımları:**
1. Yeni model veya prompt değişikliği olup olmadığına bakın.
2. `evaluation/generate_report.py --suite drafts` testini çalıştırarak Gold Set'e (Referans Set) karşı regresyon olup olmadığını kıyaslayın.

---

## 8. KachowHITLBacklog

**Durum:** Son 1 saat içinde bekleyen İnsan Onayı (HITL) sayısı, çözülenlerden çok daha fazla. Taslaklar kuyrukta (Interrupted) birikiyor.

**Çözüm Adımları:**
1. Bu bir sistem değil kullanıcı davranışı anomalisidir. Kullanıcılara (Arayüze) bildirim gidip gitmediğini kontrol edin.

---

## 9. KachowStructuredRetryStorm

**Durum:** Model yapılandırılmış JSON çıktısı üretirken sürekli format hatası yapıyor ve Retry (Tekrar Deneme) mekanizmasına düşüyor.

**Çözüm Adımları:**
1. Modelin `JSON-mode` yeteneğini ve prompt formatlarını (`TEMPLATE_CONTRACTS`) gözden geçirin.

---

## 10. KachowGuardrailBlockSpike

**Durum:** Sistem Guardrail (Güvenlik Duvarı) engelleme oranları olağan dışı artış gösteriyor.

**Çözüm Adımları:**
1. Saldırı/Kötüye Kullanım veya Kuralların (Regex/Prompt) fazla agresif olması senaryolarını ayrıştırın.
2. Loglardan hataların belirli bir `company`'de (Şirket) mi yığıldığını analiz edin.

---

## 11. KachowLLMCallLatencyHigh

**Durum:** LLM (Ollama) çağrılarının p95 gecikme süresi 60 saniyeyi aşıyor.

**Çözüm Adımları:**
1. Ollama GPU/CPU limitlerine, Memory Swap durumlarına bakın.
2. `KachowNodeBudgetExhaustion` alarmıyla birlikte değerlendirin.
