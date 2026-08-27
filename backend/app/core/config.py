import shlex
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "KACHOW-Teknofest-2026"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "supersecretkeychangeinproduction"

    #: Üretilen bir taslağın kendi Tarih alanı için "bugün"ü çözmekte
    #: kullanılan IANA bölgesi (bkz. app.ai.workflows.dates.today_tr) --
    #: kullanıcıdan bu tarih asla istenmez, bu yüzden bu bölgede çözülen
    #: sunucunun kendi saati, bunun için tek gerçek kaynaktır.
    APP_TIMEZONE: str = "Europe/Istanbul"

    # Veritabanı Yapılandırması
    #: Uygulamanın kendi çalışma zamanı bağlantısı. Faz 3'ten (Postgres RLS)
    #: itibaren bunun kısıtlı, owner olmayan bir rol (``kachow_app`` -- bkz.
    #: migration ``0013_rls``) olması beklenir: satır düzeyi güvenlik,
    #: yalnızca isteği yapan bağlantı tabloların sahibi olma erdemiyle onu
    #: atlayamadığında gerçek bir savunmadır; bir superuser/owner bağlantısı
    #: herhangi bir `ENABLE ROW LEVEL SECURITY` ifadesinden bağımsız olarak
    #: bunu her zaman yapabilir.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    #: Şema sahibi bağlantısı: Alembic migration'ları (DDL), ve bir satır
    #: düzeyi güvenlik politikasının kapsayacağı herhangi bir şirket bağlamı
    #: var olmadan *önce* `users`/`invited_emails`'i küresel olarak
    #: benzersiz bir `username`/`email` ile aramak zorunda olan dar
    #: tenant-öncesi kimlik arama seti (giriş, token yenileme, davet ile
    #: kapılı kayıt) -- bkz.
    #: `app.infrastructure.database.session.get_owner_db`. Varsayılan
    #: olarak boş, bu da `effective_alembic_database_url`'in
    #: `DATABASE_URL`'e düşmesini sağlar -- böylece Faz 3 rol ayrımını
    #: henüz benimsememiş bir dağıtım (her iki ayar da aynı owner
    #: bağlantısını gösterir) tam olarak önceki gibi çalışmaya devam eder.
    ALEMBIC_DATABASE_URL: str = ""
    #: Migration `0013_rls`'in oluşturduğu kısıtlı `kachow_app` Postgres
    #: rolü için parola. Bu deponun mevcut `POSTGRES_PASSWORD=postgres`
    #: kuralıyla eşleşen yalnızca geliştirme varsayılanı (bkz. `compose.yml`)
    #: -- gerçek bir dağıtımda asla bu değer olması amaçlanmamıştır.
    KACHOW_APP_DB_PASSWORD: str = "kachow_app_dev_only"

    #: SQLAlchemy async engine havuz ayarları. Ayarlanmadıkları için
    #: kod tabanı uzun süre SQLAlchemy varsayılanlarıyla (5 + 10 = 15
    #: bağlantı, 30 sn bekleme) çalıştı -- birkaç eşzamanlı, dakikalarca
    #: süren sohbet/analiz isteği (her biri bir bağlantıyı `idle in
    #: transaction` tutuyordu) havuzu tüketip diğer her isteği zaman
    #: aşımına uğratıyordu (bkz. #288).
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: float = 30.0
    #: Bağlantıları bu yaştan sonra sessizce geri dönüştür -- uzun ömürlü
    #: boşta bağlantıların bir load balancer / Postgres tarafından
    #: koparılıp havuzda ölü kalmasını önler.
    DB_POOL_RECYCLE_SECONDS: int = 1800
    #: Postgres tarafı emniyet ağı (yalnızca uygulamanın çalışma zamanı
    #: bağlantısına uygulanır, owner bağlantısına değil): bir bağlantı bu
    #: kadar milisaniye boyunca `idle in transaction` kalırsa Postgres onu
    #: koparır. Bir bağlantı sızıntısı 30 dakika yerine ~1 dakikada
    #: kendini toparlar, yani yığılma tüm uygulamayı düşürmek yerine
    #: kısmi bozulmayla atlatılır. 0 devre dışı bırakır.
    DB_IDLE_IN_TXN_TIMEOUT_MS: int = 60000
    #: Havuz doygunluğunu periyodik loglayan arka plan görevi (bkz.
    #: `app.lifespan`). Saniye cinsinden aralık; 0 devre dışı bırakır.
    #: Kullanılan bağlantı oranı %80'i geçtiğinde WARNING loglar.
    DB_POOL_MONITOR_INTERVAL_SECONDS: int = 30

    #: LangGraph'ın AsyncPostgresSaver'ı, planlama grafiğinde HITL'i (eksik
    #: bilgi istekleri) destekler. Başlangıçta en iyi çaba: False
    #: olduğunda veya Postgres ulaşılamaz olduğunda, grafikler bir
    #: checkpointer olmadan derlenir ve HITL dışında her şey çalışmaya
    #: devam eder.
    CHECKPOINTER_ENABLED: bool = True

    #: Taslak öncesi yazma özeti kesintisini (kim yazıyor, kime gidiyor,
    #: kapanış formülü -- bkz. app.ai.workflows.writing_brief) yukarıdaki
    #: taslak sonrası onay kapısından ayrı olarak kapılar. Akıllı-atlama,
    #: bunun yalnızca bir slot gerçekten çözülmemişken bir turu duraklattığı
    #: anlamına gelir, ama sıfır duraklama isteyen bir demo bunu tamamen
    #: devre dışı bırakabilir.
    HITL_BRIEF_GATE_ENABLED: bool = True

    #: Eksik bilgi kapısının kendi "revizyon iste" kaçış kapağının (bkz.
    #: planning_graph.human_gate_node'un "missing_information" dalı)
    #: kapının bunu sunmayı bırakmadan önce, aynı çalıştırma içinde
    #: taslağı revize alt grafiğinden kaç kez geri gönderebileceği (bkz.
    #: planning_graph.gate_revise_node/route_after_gate). Tur başına en
    #: kötü durum gecikmesini sınırlar -- bir üst sınır olmadan, inatçı bir
    #: taslakta tekrar tekrar "revizyon iste"ye tıklayan bir insan, tek bir
    #: istekte sınırsız sayıda LLM çağrısına mal olur.
    HITL_MAX_GATE_REVISIONS: int = 2

    #: Asist adımının `propose_transfer` aracını kapılar (Faz 4, #201):
    #: "son taslağı Ahmet'e gönder", zorunlu bir `transfer_gate`
    #: onayının arkasında AI kanalı üzerinden çözülür ve yürütülür.
    #: `HITL_BRIEF_GATE_ENABLED`'in kendi kapısı için belgelediği aynı
    #: gerekçe. False olduğunda, `planning_graph._run_assist` aracı hiç
    #: inşa etmez/sunmaz (bkz.
    #: `app.ai.tools.transfer_tools.build_transfer_tools`), bu yüzden
    #: modelin çağıracak bir şeyi yoktur ve "taslağı gönder" gibi bir mesaj
    #: diğer herhangi bir konuşma turu gibi yanıtlanır.
    AI_TRANSFER_ENABLED: bool = True

    #: Bir `artifact_transfer_intents` satırının, `TransferIntentService.
    #: confirm`'ün onu reddedip niyeti iptal etmesinden önce
    #: `AWAITING_CONFIRMATION`'da ne kadar süre bekleyebileceği (bkz.
    #: planın §I'i). On dakika -- bir insanın onay kartını gerçekten
    #: okuyabileceği kadar uzun, onay anındaki bir politika yeniden
    #: kontrolünün (favori kaldırıldı, yetki değişti) aksi halde sonsuza
    #: kadar yaşayabilecek bir niyete karşı teorik değil gerçek bir TOCTOU
    #: koruması kalması için yeterince kısa.
    TRANSFER_CONFIRMATION_TTL_SECONDS: int = 600

    #: Bir revizyonun, kullanıcının kendi talimatını alınan mevzuat/kaynak
    #: belgeye karşı çelişkiler açısından kontrol edip etmediği (bkz.
    #: app.ai.revision.conflict). Deterministik katman her zaman çalışır;
    #: bu yalnızca ek hızlı katman LLM geçişini kapılar. Kapalı olmak
    #: "uyarı yok" anlamına gelmez -- deterministik katmanın kendi
    #: bulgularına bakın -- bunların üzerinde ikinci, akıl yürütme tabanlı
    #: bir görüş olmadığı anlamına gelir.
    REVISION_CONFLICT_AUDIT_ENABLED: bool = True

    #: Talimatı yeni normatif içerik tanıtan (bir kanun/madde ataması, bir
    #: kurum, bir tarih) bir revizyonun, taslak ilk yazıldığında taşınan
    #: dondurulmuş bağlama tamamen güvenmek yerine yeniden yazmadan önce
    #: mevzuatı yeniden alıp almadığı. Bkz.
    #: app.ai.revision.retrieval.maybe_extend_context.
    REVISION_RERETRIEVAL_ENABLED: bool = True

    #: Koşullu yeniden alma çağrısı üzerinde sert bir tavan, böylece yavaş
    #: bir Qdrant sorgusu bir revizyonu durduramaz -- zaman aşımında
    #: engellemek yerine dondurulmuş bağlama düşer.
    REVISION_RERETRIEVAL_TIMEOUT_SECONDS: float = 10.0

    #: Tek bir planlama grafiği çalıştırmasının (sohbet, taslak üretimi,
    #: yönlendirme) tavanı. Env ile yapılandırılabilir, böylece yavaş/yalnız
    #: CPU'lu bir Ollama modeline karşı yerel bir çalıştırma, kod değişikliği
    #: olmadan daha fazla pay verilebilir; orkestre edilmiş sohbet akışı
    #: bunu çarpar (bkz.
    #: app.domains.chat.chat_service.ORCHESTRATION_TIMEOUT_SECONDS).
    AI_WORKFLOW_TIMEOUT_SECONDS: int = 480

    #: DocumentService.analyze_document'ın self.extractor.extract(...)
    #: çağrısı üzerinde bir tavan -- önceden sınırsızdı. Alan-farkında
    #: çıkarma-kabul kriteri (bkz.
    #: FallbackDocumentExtractor._has_enough_header_fields), zincirin son
    #: basamağı olan tam sayfa vision OCR'ı artık yükleme kritik yolunda
    #: gerçekten ulaşılabilir bir yol yapar, hiç metin katmanı olmayan
    #: belgeler için nadir bir yedek değil -- bu yüzden bu yol,
    #: AI_WORKFLOW_TIMEOUT_SECONDS'ın analiz grafiğini zaten sınırladığı
    #: şekilde kendi tavanına ihtiyaç duyar. 300s, ölçülen en kötü durumda
    #: (~83s/belge ortalama, MAX_OCR_PAGES tek bir yükselmenin kaç sayfayı
    #: transkribe etmesi istenebileceğini sınırlar) glm-ocr üzerinden çok
    #: sayfalı bir belgeyi kapsar. Buradaki bir zaman aşımı, isteği
    #: süresiz olarak asmak yerine, DocumentExtractionError'ın hemen
    #: altında zaten çevrildiği gibi normal bir ValidationException (400
    #: sınıfı, yeniden denenebilir) olarak yüzeye çıkar.
    EXTRACTION_TIMEOUT_SECONDS: float = 300.0

    #: DocumentService.generate_detailed_summary'nin talep üzerine
    #: build_detailed_summary çağrısı üzerinde tavan -- bir
    #: BudgetPolicy.node_seconds girdisi değil, çünkü bu tamamen analiz
    #: grafiğinin dışında çalışır (bunun nedeni için
    #: create_document_analysis_graph'ın kendi docstring'ine bakın). Uzun
    #: bir belgenin map-reduce özeti, Ollama'nın tek üretim yuvasına karşı
    #: sıralı çalıştırılan birkaç SummarizerAgent çağrısıdır (neden sıralı,
    #: eşzamanlı değil, olduğu ve buna dayanan gerçek çağrı başına
    #: rakamlar için app.ai.summarization.SUMMARY_MAX_MAP_CHUNKS'ın kendi
    #: yorumuna bakın). Bu tavanda en kötü durum 4 sıralı çağrıdır (3 map +
    #: 1 reduce); bu projenin donanımında gözlemlenen tekil çağrılar
    #: 20-185s arasında değişti, bu yüzden gerçekten kötü bir durumda 4
    #: çağrı 400s'ye yaklaşabilir. Buradaki bir zaman aşımı, isteği
    #: başarısız kılmak yerine kısa özete düşer, bu yüzden gerçekten tam
    #: bütçeye ihtiyaç duyan bir belge hiçbir faydası olmadan map ortasında
    #: kesilmez.
    DETAILED_SUMMARY_TIMEOUT_SECONDS: float = 400.0

    #: Çoklu-kiracılık çalışmasından itibaren zorunlu: her router'a giden
    #: her istek bir JWT bearer token gerektirir, ve sistemdeki her satır
    #: artık bir `company_id` taşır -- bir isteğin düşebileceği bir
    #: "kimlik doğrulamasız demo/dev yolu" artık yoktur, çünkü
    #: okuma/yazmalarını kapsayacak bir şirket olmazdı. Yalnızca
    #: `_require_auth_in_production`'ın (app.lifespan) yanlış
    #: yapılandırılmış bir dağıtımı başlatmayı reddedebilmesi için
    #: ayarlanabilir bir bayrak olarak tutulur; bunu False'a çevirmek
    #: desteklenen bir mod değildir ve çoğu rota basitçe onsuz her isteği
    #: reddeder.
    REQUIRE_AUTH: bool = True

    #: Varsayılan olarak kapalı. `rate_limit()` (app.api.rate_limit), bu
    #: açıkken `X-Forwarded-For` başlığından, kapalıyken
    #: `request.client.host`'tan (istemcinin sahtelenemeyeceği gerçek TCP
    #: eşi) okunan çağıranın IP'sine göre Redis sayacını anahtarlar. Önünde
    #: bir ters proxy olmadan X-Forwarded-For'a güvenmek, her isteğin kendi
    #: uydurma IP'sini taşımasına izin verir, bu yüzden her biri kendi
    #: Redis anahtarına düşer ve sınırlayıcı asla bir sayı biriktirmez --
    #: sınırsız giriş denemesi, sınırsız yükleme. Yalnızca uygulama, bu
    #: başlığı buraya ulaşmadan önce üzerine yazan (yalnızca eklemeyen) bir
    #: proxy'nin arkasında otururken True yapın.
    TRUST_PROXY_HEADERS: bool = False

    #: Her planlama grafiği çalıştırmasının karar izini Postgres'e
    #: kalıcılaştır (bkz. app.observability.run_recorder). Her gerçek
    #: dağıtımda varsayılan olarak açık; testler bunu genel olarak kapatır
    #: (bkz. conftest.py'nin `_disable_run_recording` autouse fixture'ı),
    #: böylece ilgisiz nedenlerle grafiği çalıştıran yüzlerce birim testi
    #: her biri de gerçek bir veritabanı yazımı denemez.
    RUN_RECORDING_ENABLED: bool = True

    #: Her sohbet turunu (kullanıcı mesajı + asistan yanıtı)
    #: chat_sessions/chat_messages'a kalıcılaştır (bkz.
    #: app.domains.chat.chat_recorder). RUN_RECORDING_ENABLED ile aynı en
    #: iyi çaba, testte-devre-dışı kuralı.
    CHAT_HISTORY_ENABLED: bool = True

    #: Her üretilen/revize edilen taslağı `drafts` sürüm zincirine
    #: kalıcılaştır (bkz. app.domains.drafts.draft_recorder).
    #: RUN_RECORDING_ENABLED ile aynı en iyi çaba, testte-devre-dışı kuralı.
    DRAFT_HISTORY_ENABLED: bool = True

    #: Henüz yoksa başlangıçta bir demo şirket oluştur (bkz.
    #: app.domains.companies.seeder) -- aşağıdaki seed'lenen diğer her
    #: satırın bağlı olduğu tenant, bu yüzden bu önce çalışmalıdır. Diğer
    #: SEED_* bayrakları gibi aynı idempotent, en iyi çaba,
    #: testte-devre-dışı kural.
    SEED_DEMO_COMPANY: bool = True
    SEED_DEMO_COMPANY_SLUG: str = "demo"
    SEED_DEMO_COMPANY_NAME: str = "Demo Kurum"

    #: Henüz yoksa başlangıçta bir ROOT, bir ADMIN, bir MANAGER ve bir
    #: EMPLOYEE hesabı oluştur (bkz. app.domains.users.seeder). ROOT'un
    #: hiç şirketi yoktur (bkz. UserModel.company_id); diğer üçü
    #: seed'lenen demo şirkete bağlıdır. RUN_RECORDING_ENABLED gibi
    #: idempotent ve en iyi çaba; testler bunu genel olarak devre dışı
    #: bırakır (conftest.py'nin `_disable_default_user_seeding`'i),
    #: böylece tam yaşam döngülü bir test de gerçek veritabanı yazımları
    #: denemez. Aşağıdaki parolalar geliştirme/demo varsayılanlarıdır --
    #: güvenilir bir demo ortamı dışında ulaşılabilir herhangi bir dağıtım
    #: için her SEED_* değerini geçersiz kılın.
    #:
    #: Alan adı `.local` değil (RFC 2606, dokümantasyon için ayrılmış)
    #: `.example`'dır -- `.local`, `email_validator`'ın
    #: SPECIAL_USE_DOMAIN_NAMES kara listesindedir (mDNS'e ayrılmış bir
    #: TLD, RFC 6762), bu yüzden seed'lenen bir hesabın gidip geldiği her
    #: `UserResponse` (örn. `GET /users/me`), gerçek bir HTTP isteği onu
    #: çalıştırdığı anda Pydantic'in `EmailStr` doğrulamasını 500 ile
    #: başarısız kılar -- birim testleri bunu asla yakalamadı çünkü servis
    #: katmanını mock'lar ve seed'lenen bir satırdan asla gerçek bir
    #: `UserResponse` inşa etmezler.
    SEED_DEFAULT_USERS: bool = True
    SEED_ROOT_EMAIL: str = "root@kachow.example"
    SEED_ROOT_PASSWORD: str = "Root123!"
    SEED_ADMIN_EMAIL: str = "admin@kachow.example"
    SEED_ADMIN_PASSWORD: str = "Admin123!"
    SEED_MANAGER_EMAIL: str = "manager@kachow.example"
    SEED_MANAGER_PASSWORD: str = "Manager123!"
    SEED_EMPLOYEE_EMAIL: str = "employee@kachow.example"
    SEED_EMPLOYEE_PASSWORD: str = "Employee123!"

    #: Henüz hiçbiri yoksa başlangıçta demo şirket içinde varsayılan
    #: yönlendirilebilir birimleri oluştur (bkz.
    #: app.domains.units.seeder). SEED_DEFAULT_USERS ile aynı idempotent,
    #: en iyi çaba, testte-devre-dışı kural -- bu olmadan yeni bir ortamın,
    #: bir admin `POST /units` aracılığıyla bir tane oluşturana kadar
    #: yönlendirilecek hiçbir birimi olmaz.
    SEED_DEFAULT_UNITS: bool = True

    #: Tüm sistem için AI sağlayıcı yığınını seçen tek anahtar: True ->
    #: yerel Ollama + yerel Qdrant (varsayılan, harici bağımlılık yok).
    #: False -> Evren (TEKNOFEST tarafından sağlanan barındırılan çıkarım
    #: API'si) + Evren'in özel Qdrant kümesi. `get_llm_client`/
    #: `get_fast_llm_client` (app.ai.llms), `get_embeddings_client`
    #: (app.ai.embeddings.models), ve `get_vector_store`
    #: (app.infrastructure.vectorstore) tarafından varsayılan
    #: sağlayıcılarını seçmek için okunur -- hiçbir çağrı noktasının
    #: açıkça `provider=` geçirmesi gerekmez.
    LOCAL_MODE: bool = True

    # Ollama Yapılandırması
    # Not: Docker içinde çalışırken, OLLAMA_BASE_URL'i
    # http://host.docker.internal:11434 olarak ayarlayın
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3.5:9b"
    OLLAMA_TEMPERATURE: float = 0.7
    # Bozuk taramaları OCR'lamak için kullanılan görsel dil modeli (bu
    # seçimin arkasındaki ölçümler için extractors/vision.py'ye bakın). O
    # modülün DEFAULT_PROMPT'una bağlıdır: bazı vision modelleri Türkçe bir
    # transkripsiyon prompt'u altında hiçbir şey döndürmez, bu yüzden ikisi
    # birlikte hareket etmelidir.
    OLLAMA_VISION_MODEL: str = "glm-ocr:latest"
    OLLAMA_REASONING: bool = False

    #: Üretim bütçesi. Önceki 1024 değeri resmi taslakları cümle ortasında
    #: kırpıyor ve editörün yapılandırılmış JSON'ını kesiyordu, bu da
    #: Pydantic doğrulamasını başarısız kılıyor ve tamamen başarısız
    #: olmadan önce üç yeniden deneme harcıyordu.
    OLLAMA_MAX_TOKENS: int = 4096

    #: Bağlam penceresi. Ollama varsayılan olarak 2048'dir ve *baştan
    #: itibaren* kırpar -- tam olarak sayı/tarih/konu/muhatabın yaşadığı
    #: sistem prompt'unu veya belge başlığını sessizce düşürür. Düğüm
    #: başına değil, genel olarak ayarlanmalıdır.
    OLLAMA_NUM_CTX: int = 8192

    #: Ollama'nın bir isteğin ardından bir modeli ne kadar süre bellekte
    #: tuttuğu. Bu olmadan model boru hattı adımları arasında tahliye edilir
    #: ve her adım yeniden yükleme maliyetini öder.
    OLLAMA_KEEP_ALIVE: str = "30m"

    #: Ucuz, düşük token'lı kararlar (niyet, yönlendirme, sorgu
    #: sınıflandırma) için isteğe bağlı küçük model. Ayarlanmadığında
    #: OLLAMA_MODEL'e düşer, böylece ikinci bir modeli çekmemiş bir ortam
    #: çalışmaya devam eder.
    OLLAMA_FAST_MODEL: str | None = None

    #: Hızlı model için üretim bütçesi. Niyet ve yönlendirme çıktıları bir
    #: etiket artı bir cümledir; daha büyük olan her şey modelin
    #: gevezelik yapmasıdır.
    OLLAMA_FAST_MAX_TOKENS: int = 512

    #: İlk kullanıcı isteğinin soğuk yükleme maliyetini ödememesi için
    #: başlangıçta her iki modeli de ısıt (Apple Silicon'da birkaç saniye).
    OLLAMA_WARMUP_ON_STARTUP: bool = True

    #: Hibrit taslak kalite kapısının LLM yargıcı bacağı için kaçış kapağı
    #: (hızlı katman, taslak başına ~5-7s). Kod değişikliği olmadan
    #: termal olarak kısıtlanmış bir demo makinesinde kapatın; deterministik
    #: doğrulayıcı her iki durumda da çalışmaya devam eder.
    DRAFT_JUDGE_ENABLED: bool = True

    #: Yargıç çağrısı üzerinde sert bir tavan, böylece tek bir yavaş üretim
    #: ~90s taslak gecikme bütçesini patlatamaz.
    DRAFT_JUDGE_TIMEOUT_SECONDS: float = 30.0

    #: Guardrail nüans katmanının LLM yargıcı (hızlı katman) için kaçış
    #: kapağı -- deterministik desen katmanının göremediği girdi
    #: hassasiyeti/çıktı sızıntısı yargıları için DRAFT_JUDGE_ENABLED ile
    #: aynı rol. Deterministik guardrail kontrolleri (PII regex,
    #: gizlilik_derecesi eşlemesi, temellendirme) her iki durumda da
    #: çalışmaya devam eder; bu yalnızca yalnızca-deterministiğe düşer,
    #: asla bir kontrolü kaldırmaz.
    GUARDRAIL_JUDGE_ENABLED: bool = True

    #: Guardrail yargıç çağrısı üzerinde sert bir tavan. İsteği
    #: engellemek yerine zaman aşımında açık başarısız olur
    #: (yalnızca-deterministik) -- bkz.
    #: app.ai.guardrails.llm_nuance'ın modül docstring'i.
    GUARDRAIL_JUDGE_TIMEOUT_SECONDS: float = 15.0

    # Embedding Yapılandırması
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text:latest"

    # --- Evren (TEKNOFEST barındırılan çıkarım) Yapılandırması ------------------
    # LOCAL_MODE=False olduğunda Ollama yerine seçilen, paylaşımlı H200'ler
    # üzerinde OpenAI uyumlu API. Aşağıdaki model takma adları Evren'in kendi
    # takma adlarıdır, https://evren-teknofest.ssyz.org.tr/model-kartlari
    # adresinde belgelenmiştir -- keyfi isimler değil, Evren'in sunduğuyla
    # tam olarak eşleşmelidir.
    EVREN_BASE_URL: str = "https://evren-llmapi.ssyz.org.tr/v1"
    #: Evren tarafından e-posta ile sağlanan takıma özel bearer token.
    #: LOCAL_MODE=False olduğunda gereklidir.
    EVREN_API_KEY: str | None = None
    #: Kalite katmanı (Qwen3.5-122B-A10B) -- Evren'in OLLAMA_MODEL karşılığı.
    EVREN_LLM_LARGE_MODEL: str = "llm-large"
    #: Hızlı katman (Qwen3.6-35B-A3B, ~0.91s medyan gecikme) -- Evren'in
    #: OLLAMA_FAST_MODEL karşılığı, her zaman kullanılabilir (Ollama hızlı
    #: katmanının aksine, ayarlanmadığında asla büyük modele düşmez).
    EVREN_LLM_FAST_MODEL: str = "llm-fast"
    #: Guardrail yargıcı için özel güvenlik sınıflandırma modeli
    #: (Qwen3Guard-Gen-4B) (bkz. app.ai.guardrails.llm_nuance). Yerel mod
    #: bunun yerine bunun için hızlı katman chat istemcisini yeniden
    #: kullanmaya devam eder -- bkz. get_guard_llm_client.
    EVREN_GUARD_MODEL: str = "guard"
    #: RouterAgent için özel hafif yönlendirme modeli (Qwen3-8B). Yerel mod
    #: bunun yerine hızlı katman chat istemcisini yeniden kullanmaya devam
    #: eder -- bkz. get_router_llm_client.
    EVREN_ROUTER_MODEL: str = "router"
    #: Yoğun embedding modeli (BAAI/bge-m3, 1024 boyut) -- OLLAMA_EMBEDDING_
    #: MODEL'in nomic-embed-text'i (768 boyut) ile DEĞİŞTİRİLEMEZ. Bir
    #: sağlayıcıdan gelen vektörler, diğeriyle inşa edilmiş bir
    #: koleksiyonda anlamsızdır; bu yalnızca Evren'in Qdrant'ı
    #: (EVREN_QDRANT_URL) yerel olandan tamamen ayrı bir sunucu olduğu için
    #: güvenlidir, bu yüzden her modun koleksiyonları asla karışmaz.
    EVREN_EMBED_MODEL: str = "bge-m3-embed"
    #: Evren'in kendi belgelenmiş istemci-zaman-aşımı önerisi -- paylaşımlı
    #: donanımda uzun süren üretimler 1800s'ye kadar sürebilir.
    EVREN_REQUEST_TIMEOUT_SECONDS: float = 1800.0

    #: Takım başına izole edilmiş, Evren'in özel Qdrant kümesi
    #: (evren-vektor.ssyz.org.tr). LOCAL_MODE=False olduğunda QDRANT_URL
    #: yerine kullanılır.
    EVREN_QDRANT_URL: str | None = None
    #: Evren tarafından sağlanan takıma özel Qdrant API anahtarı ("qdr-teamNN-...").
    EVREN_QDRANT_API_KEY: str | None = None

    # Redis Yapılandırması
    REDIS_URL: str = "redis://localhost:6379/0"

    # Qdrant Vektör DB Yapılandırması (yalnızca yerel mod -- bkz. EVREN_QDRANT_URL)
    QDRANT_URL: str = "http://localhost:6333"

    # Depolama Yapılandırması
    STORAGE_TYPE: str = "local"  # "local" veya "s3"
    LOCAL_STORAGE_DIR: str = "./storage_data"
    S3_BUCKET_NAME: str = "kachow-bucket"
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    #: SFT/DPO JSONL dışa aktarımları + LoRA adaptör ağırlıkları, her
    #: `{company_slug}/{run_id}` için bir alt dizin (Faz C3 Aşama 3, #191).
    #: Yalnızca eğitim worker'ı (`app.workers.training`) tarafından yazılır,
    #: asla ana backend süreci tarafından değil -- LOCAL_STORAGE_DIR'i
    #: yeniden kullanmak yerine kendi ayarı olarak tutulur, çünkü bunlar
    #: büyük, atılabilir eğitim çıktılarıdır, kullanıcıya yönelik belge
    #: depolaması değil.
    TRAINING_ARTIFACTS_DIR: str = "./artifacts/training"

    # Langfuse Yapılandırması
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    #: Backend'in kendi API uç noktası -- `compose.yml`'de bu, bu
    #: konteynerden erişilebilir ama bir tarayıcıdan *değil*, dahili
    #: Docker servis ana bilgisayar adıdır (`http://langfuse:3000`). Bunu
    #: bir insanın tıklaması amaçlanan bir bağlantı için yeniden
    #: kullanmayın; aşağıdaki `LANGFUSE_PUBLIC_URL`'e bakın.
    LANGFUSE_HOST: str = "http://localhost:3000"

    #: Aynı Langfuse örneği için tarayıcıdan erişilebilir URL -- yalnızca
    #: `GET /companies/{id}/analytics/links`'in derin bağlantısı tarafından
    #: kullanılır. İkisinin gerçekten aynı olduğu Docker-dışı/yerel bir
    #: çalıştırma için `LANGFUSE_HOST` ile aynı değere varsayılan olarak
    #: ayarlanır; `compose.yml` yalnızca `LANGFUSE_HOST`'u geçersiz kılar
    #: (dahili ana bilgisayar adına), bu yüzden bu, orada `localhost`
    #: varsayılanını korur ve ikisi Docker altında kasıtlı olarak ayrışır.
    LANGFUSE_PUBLIC_URL: str = "http://localhost:3000"

    #: `GET /companies/{id}/analytics/links`'in derin bağlantısı için taban
    #: URL -- `compose.yml`'nin `grafana` servisi 3001'de yayınlar
    #: (Prometheus/Postgres zaten 3000/5432 kullanıyor, bu yüzden Grafana
    #: varsayılan portu değil). `company` dashboard şablon değişkeni (bkz.
    #: `monitoring/dashboards/company_dashboard.json`), şirkete göre
    #: değiştiği için burada gömülü değil, analitik servisi tarafından eklenir.
    GRAFANA_URL: str = "http://localhost:3001"

    #: `GET /root/users/insights`'in global token-kullanım panelini beslediği
    #: Prometheus HTTP API taban adresi. Varsayılan host-facing'dir; Docker
    #: altında `compose.yml` bunu `http://prometheus:9090` ile geçersiz kılar
    #: (QDRANT_URL/REDIS_URL ile aynı desen). Ulaşılamazsa panel sessizce boş
    #: döner -- bkz. `app.observability.prometheus_query`.
    PROMETHEUS_URL: str = "http://localhost:9090"

    #: Altyapı düzeyi izleme için OTLP/gRPC toplayıcı uç noktası (örn.
    #: `http://jaeger:4317`) -- bkz. `app/observability/otel.py`. `None`
    #: (varsayılan) OpenTelemetry'yi tamamen devre dışı bırakır: SDK
    #: import'u yok, exporter yok, enstrümantasyon yaması yok. Yukarıdaki
    #: `LANGFUSE_*`'ı tamamlar, onun yerine geçmez -- her birinin hangi
    #: soruyu yanıtladığı için docs/deployment/observability.md'ye bakın.
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None

    # scripts/build_prototypes.py tarafından yazılan anlamsal prototip
    # vektörleri. Aşağıdaki korpusla aynı çalışma-dizinine-göreli kural,
    # bu da onu konteynerde (/workspace) ve depo kökünden bir host
    # çalıştırmasında aynı şekilde çözmesini sağlayan şeydir.
    PROTOTYPE_DIR: str = "./datasets/prototypes"

    # Mevzuat Korpusu Yapılandırması
    MEVZUAT_CORPUS_DIR: str = "./datasets/mevzuat"
    MEVZUAT_COLLECTION_NAME: str = "mevzuat"

    # scripts/curate_yazisma_examples.py tarafından datasets/resmi_yazisma'dan
    # derlenmiş taslak few-shot stil örnekleri. Parçalanmadan indekslenir
    # (bir resmi mektup = bir nokta) -- bkz. scripts/index_yazisma_examples.py.
    RESMI_YAZISMA_EXAMPLES_PATH: str = "./datasets/resmi_yazisma/ornekler.jsonl"
    RESMI_YAZISMA_COLLECTION_NAME: str = "resmi_yazisma_ornek"

    # MCP üzerinden canlı mevzuat araması (github.com/saidsurucu/mevzuat-mcp,
    # MIT), doğrudan mevzuat.gov.tr'yi sorgular.
    #
    # Aynı sunucuyu okuyan iki bağımsız anahtar:
    #
    # * MEVZUAT_SOURCE, belge analizinin mevzuat almasının
    #   (app.ai.retrieval.mcp_mevzuat) nereden okuduğuna karar verir.
    #   "mcp" (varsayılan) derlenmiş korpusun mevcut resmi metnini canlı
    #   getirir ve herhangi bir başarısızlıkta MEVZUAT_CORPUS_DIR altındaki
    #   commit'lenmiş korpusa düşer; "local" MCP'yi tamamen atlar ve her
    #   zaman commit'lenmiş korpusu kullanır, tam olarak bu ayar var
    #   olmadan önceki gibi. Hiçbir değer uyum kontrolüne dokunmaz:
    #   check_required_fields, sabit kodlanmış madde numaraları olan bir
    #   kural tablosu üzerinde küme çıkarmadır, ve hiçbir kaynak anahtarı
    #   o koda ulaşmaz.
    # * MEVZUAT_MCP_ENABLED (varsayılan kapalı), asistanın kendi anahtarıdır,
    #   yerel korpus aracı hiçbir şey bulamadığında bir yükselme olarak
    #   search_legislation_live sunar. Bilinçli olarak MEVZUAT_SOURCE'tan
    #   bağımsız -- bir dağıtım, sohbet modeline canlı bir devlet sitesi
    #   aracı vermeden canlı mevzuata karşı belge analizi çalıştırabilir,
    #   veya tersi.
    #
    # register_servers(), *her iki* anahtar da onu istediğinde sunucuyu
    # kaydeder, bu yüzden belgelenen varsayılan (MEVZUAT_SOURCE="mcp",
    # MEVZUAT_MCP_ENABLED=False) hâlâ gerçekten sunucuya ulaşır, sessizce
    # hiçbir şey kaydetmek yerine.
    #
    # Sunucu backend imajında değildir -- bağımlılık ağacı playwright'ı
    # sabitler ve bir tarayıcı ikilisi çeker -- bu yüzden her iki anahtar
    # da aşağıdaki komutun kurulu bir kopyaya (yerel olarak izole bir venv,
    # veya bir sidecar konteyner) işaret etmesine ihtiyaç duyar. Komut ve
    # argümanlar kodda değil burada yaşar, böylece o değişim yapılandırma olur.
    MEVZUAT_SOURCE: Literal["mcp", "local"] = "mcp"
    MEVZUAT_MCP_ENABLED: bool = False
    MEVZUAT_MCP_COMMAND: str = "mevzuat-mcp"
    #: Boşlukla ayrılmış, bir liste değil. pydantic-settings, yapılandırılmış
    #: bir türe (liste, sözlük, ...) bağlı herhangi bir env değişkenini
    #: modelin kendi doğrulayıcıları hiç çalışmadan *önce* JSON olarak
    #: çözer, bu yüzden düz bir `list[str]` alanı,
    #: `MEVZUAT_MCP_ARGS="--transport stdio"`'yı -- bariz kabuk-stili değeri
    #: -- `Settings()` inşasında sert bir çökmeye dönüştürdü: "error
    #: parsing value for field ... from source EnvSettingsSource", JSON'dan
    #: hiç bahsetmeden ve bir doğrulayıcıda düzeltme şansı olmadan. Düz bir
    #: `str` alanı ham bir dize olarak okunur, bu yüzden bu tür çökmeyi
    #: gerçekten önleyen şeydir; ayrıştırılmış listeyi almak için aşağıdaki
    #: `mevzuat_mcp_args`'ı kullanın.
    MEVZUAT_MCP_ARGS: str = ""
    #: Bir arama üzerinde tavan. Devlet sitesi hiçbir hız sınırı yayınlamaz
    #: ve asistan onu bekleyerek bir sohbet turunu durduramaz.
    MEVZUAT_MCP_TIMEOUT_SECONDS: float = 25.0
    #: `MEVZUAT_MCP_TIMEOUT_SECONDS`'tan bilinçli olarak daha küçük.
    #: Asistanın canlı aracı 25s'lik kendi tam bütçesine sahip tek bir
    #: sohbet turu adımı iken, evrak analizindeki canlı eskalasyon
    #: (`retrieve_mevzuat_node`) mevcut `mevzuat_retriever.retrieve(...)`
    #: çağrısıyla aynı düğüm bütçesini paylaşıyor -- ve o bütçe `fast`
    #: seviyesinde yalnızca 15s'ye kadar iniyor (`BudgetPolicy.node_seconds`
    #: `retrieve_mevzuat` × reasoning_levels.py'nin `fast` çarpanı). Bu
    #: bütçeyi aşmak `NodeBudgetExceeded` fırlatıp düğümü zarifçe değil,
    #: doğrudan iptal ediyor (bkz. app.ai.workflows.resilience.node_timeout),
    #: bu yüzden ayrı ve daha dar bir tavan gerekiyor.
    MEVZUAT_LIVE_SEARCH_TIMEOUT_SECONDS: float = 10.0

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    @property
    def effective_alembic_database_url(self) -> str:
        """``ALEMBIC_DATABASE_URL``, veya ayarlanmadığında ``DATABASE_URL``.

        Yedeği çözen tek yer -- diğer her okuyucu (``alembic/env.py``,
        aşağıdaki ``checkpointer_dsn``, ``app.infrastructure.
        database.session.get_owner_db``) ham ayarı değil, bu özelliği
        kullanır, bu yüzden yedek mantığı tam olarak tek bir yerde var olur.
        """
        return self.ALEMBIC_DATABASE_URL or self.DATABASE_URL

    @property
    def checkpointer_dsn(self) -> str:
        """psycopg3, checkpointer'ın sürücüsü için uyarlanmış şema sahibi bağlantısı.

        Bilinçli olarak ``DATABASE_URL`` değil, ``effective_alembic_database_url``:
        ``AsyncPostgresSaver.setup()``, her başlangıçta kendi checkpoint
        tabloları için ``CREATE TABLE IF NOT EXISTS`` çalıştırır, ki
        kısıtlı, owner olmayan bir ``DATABASE_URL`` rolünün (o ayarın kendi
        docstring'ine bakın) bunu yapmaya ayrıcalığı yoktur. Checkpoint
        tabloları zaten Alembic/RLS'den tamamen dışlanmıştır (bkz.
        ``alembic/env.py``'nin ``_CHECKPOINT_TABLE_PREFIX`` dışlaması) --
        her zaman kiracılık modelinin dışında kendi kendini yönetmesi
        amaçlanmıştı, bu yüzden uygulamanın satır düzeyi güvenlik
        duruşundan bağımsız kendi bağlantısına sahip olmak bir geçici
        çözüm değil, tutarlıdır.

        SQLAlchemy'nin asyncpg URL şeması (``postgresql+asyncpg://``),
        psycopg'nin tanıdığı bir sürücü değildir; soneki kaldırmak, her
        iki sürücünün de iki tanesini senkronize tutmak yerine tek bir
        bağlantı dizesini paylaşmasını sağlar.
        """
        return self.effective_alembic_database_url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def mevzuat_mcp_args(self) -> list[str]:
        """``MEVZUAT_MCP_ARGS``'ı `subprocess`/MCP için bir argv listesine böl.

        `str.split` değil `shlex.split`: içinde boşluk olan bir argüman
        (diyelim ki boşluklu tırnaklı bir yol), ikiye kesilmek yerine tek
        bir argüman olarak hayatta kalmalıdır.
        """
        return shlex.split(self.MEVZUAT_MCP_ARGS)


settings = Settings()
