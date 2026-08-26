"""AI'ye özgü Prometheus toplayıcıları.

``prometheus-fastapi-instrumentator`` (bkz. ``observability/metrics.py``)
yalnızca HTTP katmanını kapsar -- istek sayısı/gecikme/durum. AI pipeline'ının
kendi davranışına dair her şey (bir taslağın revizyon döngüsü ne kadar sürer,
yargıç ne sıklıkla düşer, bir oturum insan-döngüde onay kapısına ne sıklıkla
takılır) daha önce log satırları dışında görünmezdi.

Kapsam notu: ``NODE_DURATION`` ve ``LLM_TOKENS`` eksiksiz bir metrik yüzeyi
için burada bildiriliyor ama henüz her yerde bağlanmış değil. Düğüm bazlı
zamanlama, mevcut genel ``emit_node_start``/``emit_node_end`` yardımcılarının
taşımadığı bir başlangıç/bitiş ilişkilendirmesi gerektirir (bir düğüm, aynı
kimlik altında eşleşen bir ``node_end`` olmadan meşru şekilde ``node_start``
yayınlayabilir; örn. taslak yazıcının tamamlanması ayrı ``verify`` düğümü
tarafından raporlanır) ve token sayıları bugün ``BaseLLMClient.generate()``
tarafından dışa açılmıyor. İkisini de dürüstçe bağlamak, tek bir paylaşılan
boğaz noktası yerine istemci soyutlamasına ya da düğüm başına çağrı
noktalarına tek tek dokunmayı gerektirir; uydurma sayılarla enstrümante
etmek yerine bildirilmiş ama doldurulmamış bırakıldı.
"""

import logging

from prometheus_client import Counter, Gauge, Histogram, Info

from app.ai.policy import POLICY_VERSION, get_policy

logger = logging.getLogger(__name__)

NODE_DURATION = Histogram(
    "kachow_node_duration_seconds",
    "Wall-clock duration of a single workflow node execution.",
    ["graph", "node", "status"],
    # prometheus_client'ın kendi varsayılan bucket'ları 10.0s'de tavan yapıyor
    # -- bu metriğin gerçek konuları için çok kaba: BudgetPolicy.node_seconds
    # 25s ile 180s arasında değişiyor ve workflow_ceiling_seconds 480s. Her
    # gerçek gözlem sessizce +Inf bucket'ına çöküyordu; bu durum,
    # evaluation/latency/budget_report.py (Workstream E3) canlı bir analyze
    # çalıştırmasına karşı çalıştırılırken keşfedildi -- p50/p95/p99 gerçek
    # süreden bağımsız olarak hep aynı taban değeri (10.0) okuyordu. En hızlı
    # düğümün (retrieve_mevzuat, ~12ms) altına inen saniyenin altındaki
    # değerlerden workflow tavanının ötesine kadar uzanır ve gerçek
    # bütçelerin yaşadığı 25-180s bandında p95-vs-bütçe karşılaştırmasını
    # anlamlı kılacak yeterli çözünürlük sağlar.
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 240.0, 300.0, 480.0),
)

#: BudgetPolicy.node_seconds, PromQL içinde NODE_DURATION'ın kendi
#: gözlemleriyle `join` edilebilsin diye Prometheus'a yansıtılır (bkz.
#: monitoring/prometheus/rules/kachow.rules.yml'nin KachowNodeBudgetExhaustion
#: kuralı) -- bu olmadan "bir düğümün p95'i bütçesine yaklaşıyor mu" sorusunu
#: yalnızca evaluation/latency/budget_report.py (Workstream E3) çevrimdışı ve
#: olay sonrasında cevaplayabilir. Counter/Histogram değil bir Gauge: bu,
#: politikanın kendi değeridir, süreç başlangıcında bir kez ayarlanır
#: (init_ai_metrics), çalışma boyunca biriken bir gözlem değildir.
NODE_BUDGET_SECONDS = Gauge(
    "kachow_node_budget_seconds",
    "Configured BudgetPolicy.node_seconds budget for a workflow node.",
    ["node"],
)

LLM_DURATION = Histogram(
    "kachow_llm_call_duration_seconds",
    "Wall-clock duration of a single BaseAgent call.",
    ["agent", "method"],
)

LLM_TOKENS = Counter(
    "kachow_llm_tokens_total",
    "Tokens generated per agent call, by kind.",
    ["agent", "kind"],
)

DRAFT_SCORE = Histogram(
    "kachow_draft_confidence_score",
    "Draft quality score at verification time.",
    ["source"],
    buckets=(0, 20, 40, 60, 70, 80, 90, 100),
)

DRAFT_REVISIONS = Counter(
    "kachow_draft_revisions_total",
    "Draft reflexion-loop revisions triggered, by cause.",
    ["trigger"],
)

JUDGE_FAILURES = Counter(
    "kachow_judge_failures_total",
    "LLM judge calls that degraded instead of returning a verdict.",
    ["reason"],
)

#: JUDGE_FAILURES ile aynı rol, eklenen bir etiket yerine ayrı tutuldu:
#: koruma katmanı yargıcının (app.ai.guardrails.llm_nuance) düşmesi, "bu
#: karar yalnızca deterministik karara geri döndü" anlamına gelir; bu,
#: taslak-kalitesi yargıç hatalarına katılmak yerine kendi sinyalini hak eden
#: güvenlikle ilgili bir olaydır.
GUARDRAIL_JUDGE_FAILURES = Counter(
    "kachow_guardrail_judge_failures_total",
    "Guardrail nuance-layer LLM judge calls that degraded to deterministic-only.",
    ["reason"],
)

#: Koruma sisteminin genel karar yüzeyi -- yalnızca yargıç katmanının kendi
#: hataları değil (yukarıdaki GUARDRAIL_JUDGE_FAILURES), her aşama (yüklemede
#: girdi, yanıt zamanında çıktı) ve her tür (pii, sensitivity, injection,
#: magic_byte, archive_bomb, groundedness, leakage, llm_judge). Üç çağrı
#: noktasının her birinde değil, tek bir boğaz noktasından
#: (app.observability.guardrail_recorder.record_event) artırılır; böylece
#: yeni koruma kontrolleri eklendikçe eşleşen bir metrik değişikliği
#: gerekmeden doğru kalır.
GUARDRAIL_DECISIONS = Counter(
    "kachow_guardrail_decisions_total",
    "Guardrail decisions made, by stage, kind, and outcome.",
    ["stage", "kind", "decision"],
)

HITL_INTERRUPTS = Counter(
    "kachow_hitl_interrupts_total",
    "Human-in-the-loop interrupts raised, by kind.",
    ["kind"],
)

HITL_RESUMES = Counter(
    "kachow_hitl_resume_total",
    "Human-in-the-loop resume calls received, by action.",
    ["action"],
)

STRUCT_RETRIES = Counter(
    "kachow_structured_retry_total",
    "Structured-output retries beyond the first attempt, by agent.",
    ["agent"],
)

EXTRACTION = Counter(
    "kachow_extraction_total",
    "Document text extraction attempts, by extractor and outcome.",
    ["extractor", "outcome"],
)

#: Deterministik taslak kapısının kendi davranışı, daha önce görünmezdi:
#: DRAFT_SCORE ürettiği sayıyı kaydeder ama *nasıl* ürettiğini hiçbir şey
#: kaydetmiyordu. `method` etiketi, `draft_verifier._support_for` içindeki
#: üst kademe (exact -> canonical -> token_overlap -> none) merdivenidir;
#: böylece bir tür için `none` oranındaki artış, bir dayanaklılık
#: gerilemesini tek bir iddia türüne yerelleştirir ve `canonical` payı, tür
#: farkında normalleştirmenin ne kadar iş yaptığını ölçer. Her iki etiket de
#: kapalı kümedir -- kardinaliteyi patlatacak serbest metin yok.
CLAIM_MATCH = Counter(
    "kachow_claim_match_total",
    "Draft claims checked against source material, by claim kind and match method.",
    ["kind", "method"],
)

#: Niyet merdiveninin anlamsal basamağının (app.ai.semantic.prototype_matcher)
#: gerçekten yüklenip yüklenmediği; diskteki vektör dosyası eski
#: (farklı bir gömme modeli ya da farklı bir POLICY_VERSION altında
#: derlenmiş) veya tamamen eksik olduğu için sessizce kendini devre dışı
#: bırakmasının aksine. Katman 2'nin kendini devre dışı bırakması *doğru*
#: davranıştır -- eski vektörlerden karar vermek bir model çağrısına para
#: ödemekten daha kötüdür -- ama sessiz olmamalıdır: sözcüksel katmanın
#: çekimser kaldığı her mesaj, anlamsal bir ikinci görüş almak yerine
#: doğrudan clarify/guess yedeğine atlar. Grafik oluşturma zamanında bir kez
#: ayarlanır (bkz. planning_graph.py'nin PrototypeMatcher kurulumu), istek
#: başına değil; bu yüzden bir Counter değil Gauge'dur.
ROUTER_SEMANTIC_AVAILABLE = Gauge(
    "kachow_router_semantic_available",
    "Whether the intent ladder's semantic prototype layer loaded successfully (1) or disabled itself (0).",
)

#: Çözümlenen niyete ve onu üreten mekanizmaya göre her yönlendirici kararı
#: (``fused``/``fused_semantic``/``compound``/``clarification_resolved``/
#: ``model``/``model_failed``/``clarify`` -- bkz.
#: ``app.ai.workflows.planner.PlanDecision.source``). Bu, daha önce bir
#: `run_recorder` DB satırı dışında görünmeyen sayıdır: üretimin gerçekte ne
#: sıklıkla açıklayıcı bir soru sorduğu ve hangi basamağın karar verdiği.
ROUTER_DECISIONS = Counter(
    "kachow_router_decisions_total",
    "Router decisions, by resolved intent and by the mechanism that produced them.",
    ["intent", "source"],
)

#: Kaynağa göre `PlanDecision.confidence` dağılımı. Füzyon yeniden yazımı
#: hepsine tek bir kalibre edilmiş ölçek verdiğinden (bkz.
#: `PlanDecision.confidence`'ın docstring'i) tüm kaynaklar arasında
#: karşılaştırılabilir -- ondan önce aynı histogramda üç uyumsuz ölçeğin
#: buluşması anlamsız olurdu.
ROUTER_CONFIDENCE = Histogram(
    "kachow_router_confidence",
    "Router decision confidence in [0, 1], by source.",
    ["source"],
    buckets=(0.0, 0.2, 0.35, 0.5, 0.55, 0.7, 0.85, 0.95, 1.0),
)

#: `resolve_plan`'in ödeyebileceği her aşamanın gerçek zaman maliyeti;
#: böylece anlamsal basamağın tekrar çevrimiçi olması (bkz.
#: `ROUTER_SEMANTIC_AVAILABLE`) eklediği gecikmeye bağlı bir sayıya sahip
#: olur ve (şu anda altın kümede boş, bkz.
#: `evaluation/harness/intent_suite.py::run_with_model`) model bandının
#: gerçek trafik maliyeti, tetiklendiğinde görünür hale gelir.
ROUTER_STAGE_DURATION = Histogram(
    "kachow_router_stage_duration_seconds",
    "Wall-clock duration of one router decision stage.",
    ["stage"],
)

#: "assist"e çözümlenen ama assist adımını gerçekten çalıştırmak yerine
#: draft/revise'a devredilen her tur (Faz 7, bkz. planning_graph._step_assist)
#: -- "reason"a göre (``fallback_source``: assist hiç çalışmadan önce
#: deterministik bir yeniden puanlama bunu yakaladı, çünkü yönlendirme
#: kararının kendisi arkasında gerçek kanıt olmayan bir yedek kaynaktan
#: geldi; ``model_tool``: asistan modelinin kendisi tur ortasında
#: ``request_handoff`` çağırdı) ve taşındığı "target"a göre. Buradaki
#: yükselen bir oran, füzyon ağırlıklarının (app.ai.policy.router_weights)
#: mevcut trafik için eskimiş olduğunun bir işaretidir, bu düzeltmenin
#: başarısız olduğunun değil -- bu düzeltme o sapmanın çaresi değil,
#: *belirti dedektörü*dür.
ROUTER_ASSIST_HANDOFFS = Counter(
    "kachow_router_assist_handoffs_total",
    "Turns routed to assist that were handed off to draft/revise instead, by reason and target.",
    ["reason", "target"],
)

#: İnsan onay kapısının "revizyon iste" döngüsünün (planning_graph
#: gate_revise_node/route_after_gate) nasıl sonuçlandığı: başka bir tur
#: üretildi (hâlâ HITL_MAX_GATE_REVISIONS içinde) mi yoksa tur sınırına
#: ulaşıldı ve kapı onu sunmayı bıraktı mı. "Kullanıcılar revize etmeye devam
#: ediyor ve işe yarıyor" ile "kullanıcılar sınıra takılıp duruyor" ayrımını
#: yapar; bunlar farklı yanıtlar gerektirir (daha iyi yeniden yazımlar mı
#: yoksa daha yüksek bir sınır mı).
GATE_REVISIONS = Counter(
    "kachow_gate_revisions_total",
    "Human approval gate revision rounds, by outcome.",
    ["outcome"],
)

#: app.ai.revision.conflict'ten gelen bulgular -- alınan mevzuatla veya
#: kaynak dokümanla çelişmesine rağmen uygulanan bir kullanıcı revizyon
#: talimatı. Her bulgu yine de uygulanır ve yalnızca bir insan kapısını
#: zorlar (bkz. ConflictReport.applied_anyway); bu metrik, "bu gerçekte ne
#: sıklıkla ve hangi türde oluyor" sorusunu, bağlamsız fazladan bir
#: HITL_INTERRUPTS sayısı olarak görünmek yerine görünür kılar.
REVISION_CONFLICTS = Counter(
    "kachow_revision_conflicts_total",
    "Instruction-vs-mevzuat/source conflicts detected during a revision, by kind, severity and source.",
    ["kind", "severity", "source"],
)

#: Bir revizyonun koşullu mevzuat yeniden getirmesinin
#: (app.ai.revision.retrieval.maybe_extend_context) sonuca göre gerçekten
#: çalışıp çalışmadığı -- çoğu revizyonun atlaması gerekir (saf ton/uzunluk
#: düzenlemeleri), bu yüzden yükselen bir "extended" payı, kullanıcıların
#: revizyonlarla yeni normatif içerik getirmesini ne sıklıkla istediğini
#: izler, "failed" ise getiricinin sağlığını taslağın kendi kalite kapısından
#: bağımsız olarak izler.
REVISION_RETRIEVAL = Counter(
    "kachow_revision_retrieval_total",
    "Revision-time conditional legislation re-retrieval outcomes.",
    ["decision"],
)

#: Yukarıdaki deterministik kararların üretildiği parametre kümesi. Bu
#: olmadan DRAFT_SCORE veya CLAIM_MATCH'teki bir kayma, "trafik değişti" ile
#: "bir eşiği taşıdık" arasında belirsizdir -- ve bunlar birbirine zıt
#: yanıtlar gerektirir. Kardinalite maliyeti olmasın diye bir etiket yerine
#: Info kullanılır.
POLICY_INFO = Info(
    "kachow_decision_policy",
    "Active version of the deterministic decision layer's parameter set.",
)
POLICY_INFO.info({"version": POLICY_VERSION})


def router_semantic_available() -> bool:
    """``/system/health?deep`` probu için ``ROUTER_SEMANTIC_AVAILABLE``'ı geri oku.

    ``prometheus_client`` gauge'larının herkese açık bir getter'ı yoktur;
    ``_value``, durumu iki kez izlemek yerine diğer enstrümantasyon kodunun
    tam olarak bu "kendi gauge'umu geri oku" durumu için kullandığı
    belgelenmiş kaçış yoludur.
    """
    return bool(ROUTER_SEMANTIC_AVAILABLE._value.get())


def init_ai_metrics() -> None:
    """Toplayıcılarının Prometheus'a kaydolması için bu modülün import
    edilmesini zorla.

    ``Counter``/``Histogram`` tanımlanma anında kendilerini varsayılan
    registry'ye kaydeder; bu fonksiyon yalnızca ``main.py``'nin bir import'un
    yan etkisine güvenmek yerine ``init_metrics(app)`` ile simetrik, açık ve
    grep'lenebilir bir çağrı noktasına sahip olması için var.

    Ayrıca ``NODE_BUDGET_SECONDS``'ı aktif politikadan ayarlar -- yukarıdaki
    Counter/Histogram'ların aksine bir Gauge'un kaydedilecek "tanım anı"
    değeri yoktur; burada açıkça, bir kez ayarlanması gerekir.
    """
    for node, seconds in get_policy().budget.node_seconds.items():
        NODE_BUDGET_SECONDS.labels(node=node).set(seconds)

    logger.debug("AI metrics registered.")
