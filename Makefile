.PHONY: setup-db bootstrap up down logs test test-e2e test-all eval eval-baseline eval-llm eval-retrieval \
	benchmark benchmark-baseline export-budgets perf-smoke perf-chat perf-document latency-report \
	migrate seed shell psql restart-backend \
	reset-db reset-checkpoints reset-cache reset-storage reset-document-qa reset-evren-qdrant reset

setup-db:
	docker compose exec db psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'langfuse'" | grep -q 1 || docker compose exec db psql -U postgres -c "CREATE DATABASE langfuse"

# Boş bir durumdan (container/volume/şema yok) tek komutla çalışır hale getirir:
# datastore'ları başlatır, Postgres'i bekler, langfuse DB'sini kurar,
# migration'ları koşar, backend'i başlatır. Varsayılan hesaplar backend
# lifespan hook'unda otomatik seed'lenir (bkz. config.py SEED_*). Her adım
# idempotent; çalışan sistemde de güvenle tekrar koşulur. frontend'i başlatmaz
# -- frontend.Dockerfile arm64'te build olmaz (ayrı bir bilinen hata); x64'te
# `make up`, aksi halde `cd frontend && npm run dev`.
bootstrap:
	docker compose up -d --build db redis qdrant
	@echo "Waiting for Postgres to accept connections..."
	@until docker compose exec -T db pg_isready -U $${POSTGRES_USER:-postgres} > /dev/null 2>&1; do sleep 1; done
	$(MAKE) setup-db
	docker compose run --rm --no-deps backend alembic upgrade head
	docker compose up -d --build backend
	@echo "Bootstrap complete: backend on http://localhost:8000."
	@echo "Default accounts were seeded automatically (see SEED_* in backend/app/core/config.py)."

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# Bootstrap'in geri kalanı olmadan yalnızca yeni migration'ları uygular.
# "Başkasının migration'ını çektim" komutu.
migrate:
	docker compose run --rm --no-deps backend alembic upgrade head

# lifespan'in her boot'ta koştuğu seed zincirini (demo şirket -> kullanıcı ->
# birim, hepsi idempotent) backend'i yeniden başlatmadan tekrar koşar. `migrate`
# sonrası ya da backend'i bounce etmek istemediğin bir `reset` sonrası kullanışlı.
seed:
	docker compose run --rm backend python scripts/seed_users.py

# Çalışan yığında elle bakmak için kısayol kabuklar.
shell:
	docker compose exec backend bash

psql:
	docker compose exec db psql -U $${POSTGRES_USER:-postgres} -d $${POSTGRES_DB:-kachow}

restart-backend:
	docker compose restart backend

# Varsayılan hızlı test şeridi. Yalnızca `integration` testleri gerçek (tek
# kullanımlık) Postgres ister; redis/qdrant fail-open olduğundan zorunlu değil.
# e2e ve performance pyproject.toml addopts ile hariç tutulur.
# --cov-fail-under=86: eklendiği gün ölçülen değer, aspirasyonel bir hedef
# değil. Yalnızca kapsam gerçekten arttıkça yükselir; bu sayıyı düşüren PR test
# silmiş demektir. Bilinçli olarak pyproject.toml'da değil burada.
test:
	docker compose run --rm backend pytest -q --cov-fail-under=86

# Gerçek ASGI HTTP e2e testleri (tests/e2e/): gerçek Postgres + RLS + gerçek
# lifespan, sahte LLM/embedding. db/redis/qdrant ayakta olmalı. --no-cov:
# marker ile filtrelenmiş bu alt küme farklı, çok daha küçük bir dilimi
# kapsar; kapsam yüzdesi anlamlı değil (asıl kapı `test` hedefinde).
test-e2e:
	docker compose run --rm backend pytest -q -m e2e --no-cov

# Her şey: integration + e2e + performance. `test-e2e` gibi tam yığın ister.
# --no-cov gerekçesi test-e2e ile aynı.
test-all:
	docker compose run --rm backend pytest -q -m "" --no-cov

# LLM'siz karar katmanının deterministik değerlendirmesi. Test değil ölçüm
# olduğundan ayrı hedef (pytest'in 60s test zaman aşımına takılmamalı).
# --no-deps doğru: saf karar fonksiyonları, hiçbir altyapıya dokunmaz.
eval:
	docker compose run --rm --no-deps backend python -m evaluation.generate_report --suite all

# Sonraki her koşunun karşılaştırılacağı değişiklik-öncesi sayıları kaydeder.
# Karşılaştır: make eval ARGS="--baseline evaluation/reports/all-baseline.json"
eval-baseline:
	docker compose run --rm --no-deps backend python -m evaluation.generate_report --suite all --label baseline

# Opt-in, `make eval`'in parçası değil: füzyon katmanının çekişmeli bıraktığı
# her intent için gerçek Ollama çağrısı yapar; daha yavaş ve tam tekrar
# üretilebilir değil. Ollama host.docker.internal üzerinden erişildiğinden
# --no-deps yine doğru.
eval-llm:
	docker compose run --rm --no-deps backend python -m evaluation.generate_report --suite intents --with-model --label with-model

# Chunking yapılandırması karşılaştırması (precision@k/recall@k/MRR/nDCG). Ön
# hesaplı embedding cache + sahte in-memory vektör deposu okur; canlı
# Qdrant/Ollama yok. retrieval.jsonl / retrieval_corpus düzenledikten sonra
# cache'i yenile: docker compose run --rm --no-deps backend python scripts/build_eval_embeddings.py --target retrieval
eval-retrieval:
	docker compose run --rm --no-deps backend python -m evaluation.generate_report --suite retrieval --label retrieval

# Duvar-saati mikro-benchmark'lar (tests/performance/): saf CPU, I/O'suz
# fonksiyonlar; --no-deps. Tek seferlik kurulum: bu makinenin bugünkü
# sayılarını kaydet ve baseline JSON'u commit et.
benchmark-baseline:
	docker compose run --rm --no-deps backend pytest -q tests/performance/test_benchmarks.py -m performance --benchmark-only --benchmark-storage=file://evaluation/benchmarks --benchmark-save=baseline

# Benchmark'ları tekrar koşar ve yalnızca commit'li baseline'a karşı >3x
# regresyonda hata verir (pytest-benchmark'ın kendi eşiği %99'da tıkandığı için).
benchmark:
	rm -f evaluation/benchmarks/*/*_latest.json
	docker compose run --rm --no-deps backend pytest -q tests/performance/test_benchmarks.py -m performance --benchmark-only --benchmark-storage=file://evaluation/benchmarks --benchmark-save=latest
	docker compose run --rm --no-deps backend python evaluation/benchmarks/report.py

# perf/k6/lib/budgets.json'u canlı BudgetPolicy'den yeniden üretir -- herhangi
# bir node_seconds/workflow_ceiling_seconds değiştikten sonra koş.
export-budgets:
	docker compose run --rm --no-deps backend python scripts/export_budgets.py

# k6 yük testleri (perf/k6/). Gerçek çalışan yığın + seed'li hesaplar ister.
# Docker Desktop'ta --network host desteklenmediğinden host.docker.internal +
# açık K6_BASE_URL kullanılır.
perf-smoke:
	docker run --rm -i -v "$(CURDIR)/perf/k6:/scripts" -e K6_BASE_URL=http://host.docker.internal:8000 grafana/k6 run /scripts/smoke.js

perf-chat:
	docker run --rm -i -v "$(CURDIR)/perf/k6:/scripts" -e K6_BASE_URL=http://host.docker.internal:8000 grafana/k6 run /scripts/chat_stream.js

perf-document:
	docker run --rm -i -v "$(CURDIR)/perf/k6:/scripts" -e K6_BASE_URL=http://host.docker.internal:8000 grafana/k6 run /scripts/document_upload.js

# Gözlenen düğüm-başına gecikme vs BudgetPolicy.node_seconds. Arkasında gerçek
# trafik olan çalışan bir backend ister (perf-chat/perf-document ya da gerçek
# kullanım); yeni boot edilmiş backend'e karşı raporlanacak bir şey yoktur.
latency-report:
	docker compose run --rm backend python -m evaluation.latency.budget_report

# ---------------------------------------------------------------------------
# Reset: uygulama verisini (şirket/kullanıcı/evrak/taslak/sohbet...) siler ve
# temiz bir sistemi yeniden seed'ler; mevzuat/örnek-yazışma Qdrant
# koleksiyonlarına dokunmaz (onları ayrı, pahalı indeksleme betikleri doldurur).
# Her hedef tek başına koşulabilir; `reset` hepsini doğru sırada koşar.
# ---------------------------------------------------------------------------

# Tüm Alembic tablolarını migration geçmişini baştan oynatarak siler/yeniden
# oluşturur -- her şirket/kullanıcı/birim/evrak/taslak/sohbet satırı gider.
# Elle tablo listesi tutmaya göre yapıca doğru.
reset-db:
	docker compose exec backend alembic downgrade base
	docker compose exec backend alembic upgrade head

# LangGraph checkpointer tabloları aynı Postgres'te ama bilerek Alembic
# dışıdır (AsyncPostgresSaver.setup() sahibidir), bu yüzden reset-db onlara
# dokunmaz. Burada düşürmek güvenli: backend bir sonraki boot'ta kendisi
# yeniden oluşturur.
reset-checkpoints:
	docker compose exec db psql -U $${POSTGRES_USER:-postgres} -d $${POSTGRES_DB:-kachow} \
		-c "DROP TABLE IF EXISTS checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations CASCADE;"

# Şirket profili/adapter/kuralları ve rate-limit durumu Redis'te kısa TTL ile
# önbelleklenir -- düşürmek zararsız, her şey bir sonraki istekte Postgres'ten
# yeniden okunur.
reset-cache:
	docker compose exec redis redis-cli FLUSHALL

# Yüklenen evraklar ve *_analysis.json önbellekleri host bind mount'unda
# (compose.yml); ne reset-db ne de volume silme bunlara dokunur. Bind-mount
# dosya izinlerinden bağımsız çalışsın diye backend container'ı içinde koşulur.
reset-storage:
	docker compose exec backend sh -c 'rm -rf storage_data/uploads/* storage_data/uploads/.[!.]*' 2>/dev/null || true

# document_qa Qdrant koleksiyonu belge-başına soru-cevap parçalarını tutar --
# mevzuat/örnek-yazışma koleksiyonlarından ayrı, buna dokunulmaz. Düşürmek
# güvenli: bir belge analiz edilince DocumentService yeniden oluşturur.
reset-document-qa:
	curl -sf -X DELETE http://localhost:6333/collections/document_qa || true

# Evren'in uzak Qdrant kümesindeki (EVREN_QDRANT_URL) TÜM koleksiyonları siler,
# yereli değil. `reset` zincirinin parçası DEĞİL (uzak gerçek altyapıya gider).
# Takıma izole olsa da geri alınamaz -- `reset` ile aynı CONFIRM=yes kapısı.
reset-evren-qdrant:
	@if [ "$(CONFIRM)" != "yes" ]; then \
		echo "This permanently deletes ALL collections on Evren's remote Qdrant"; \
		echo "cluster (EVREN_QDRANT_URL) -- mevzuat/örnek-yazışma/document_qa"; \
		echo "indexes built there are gone. Re-run as: make reset-evren-qdrant CONFIRM=yes"; \
		exit 1; \
	fi
	docker compose run --rm --no-deps backend python scripts/reset_evren_qdrant.py

# "Her şeyi uygulama düzeyinde sil ve bana temiz bir sistem ver" tek-komut
# girişi -- geri alınamaz, bu yüzden bare `make reset` yerine açık CONFIRM=yes
# ister. Sonunda backend'i yeniden başlatır; lifespan seed zinciri temiz bir
# demo şirket/root/admin/manager/employee setini yeniden doldurur.
reset:
	@if [ "$(CONFIRM)" != "yes" ]; then \
		echo "This permanently deletes ALL application data: companies, users,"; \
		echo "documents, drafts and chat history (mevzuat/örnek search indexes"; \
		echo "are left untouched). Re-run as: make reset CONFIRM=yes"; \
		exit 1; \
	fi
	$(MAKE) reset-db
	$(MAKE) reset-checkpoints
	$(MAKE) reset-cache
	$(MAKE) reset-storage
	$(MAKE) reset-document-qa
	docker compose restart backend
	@echo "Reset complete: backend restarted and reseeded a clean demo company + accounts."
