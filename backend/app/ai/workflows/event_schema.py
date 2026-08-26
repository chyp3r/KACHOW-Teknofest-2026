"""SSE ilerleme-olayı (progress-event) kelime dağarcığı için tipli kontrat.

``app.ai.workflows.events`` bunları düz dict'ler olarak inşa edip gönderir
(kuyruk genel amaçlı bir taşıma katmanıdır, bir stream sırasında her token
için Pydantic doğrulama maliyeti ödenecek bir yer değildir). Bu modül, her
olay adının *şeklinin* yalnızca nesirde değil kodda bir kez yazılı olması
için var -- ve ``tests/unit/ai/test_event_contract.py``'ın (Faz 11), on olay
tipi için bir Pydantic-to-TypeScript kod üretim adımı kurmaksızın,
frontend'in elle yazılmış TypeScript union'ının backend'in gerçekte
yaydığından sapmadığını doğrulayabilmesi için.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SessionEvent(BaseModel):
    """Her stream'in ilk olayı: çözümlenmiş checkpointer thread_id'si."""

    event: Literal["session"] = "session"
    thread_id: str
    seq: Optional[int] = None


class NodeStartEvent(BaseModel):
    event: Literal["node_start"] = "node_start"
    node: str
    label: str
    message: str
    meta: dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None


class NodeEndEvent(BaseModel):
    event: Literal["node_end"] = "node_end"
    node: str
    label: str
    message: str
    result: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None


class NodeErrorEvent(BaseModel):
    event: Literal["node_error"] = "node_error"
    node: str
    label: str
    message: str
    fatal: bool = True
    detail: str = ""
    seq: Optional[int] = None


class NodeSkippedEvent(BaseModel):
    event: Literal["node_skipped"] = "node_skipped"
    node: str
    label: str
    reason: str
    seq: Optional[int] = None


class TokenEvent(BaseModel):
    event: Literal["token"] = "token"
    node: str
    text: str
    seq: Optional[int] = None


class ToolCallEvent(BaseModel):
    """Asistan ajan bu tur için bir araç çağırdı (bkz. ``app.ai.tools``)."""

    event: Literal["tool_call"] = "tool_call"
    node: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None


class PartialResultEvent(BaseModel):
    event: Literal["partial_result"] = "partial_result"
    key: str
    value: Any
    seq: Optional[int] = None


class PlanningCompletedEvent(BaseModel):
    event: Literal["planning_completed"] = "planning_completed"
    plan_steps: list[str]
    intent: str
    reasoning: str
    #: Bu kararı hangi mekanizmanın ürettiği (``fused``/``fused_semantic``/
    #: ``compound``/``clarification_resolved``/``model``/``model_failed``/
    #: ``clarify`` -- bkz. ``app.ai.workflows.planner.PlanDecision.source``).
    #: Frontend'in karar-akışı görünümünün yalnızca neye karar verildiğini
    #: değil, router'ın *nasıl* karar verdiğini gösterebilmesi için açığa
    #: çıkarılıyor.
    source: str = ""
    #: Kararın kendi güven değeri [0, 1] aralığında -- fusion yeniden
    #: yazımından beri her kaynak arasında karşılaştırılabilir (bkz.
    #: ``PlanDecision.confidence``).
    confidence: float = 1.0
    #: En yüksekten başlayarak, olasılıklarıyla birlikte ikinci sıradaki
    #: (runner-up) intent'ler.
    alternatives: list[tuple[str, float]] = Field(default_factory=list)
    seq: Optional[int] = None


class GuardrailEvent(BaseModel):
    """Yanıtı değiştiren ve canlı yayınlanan bir guardrail kararı.

    Zaten ``app.ai.workflows.events.emit_guardrail_event`` tarafından
    yayılıyordu ve frontend'in kendi ``GuardrailEvent`` tipi tarafından
    tüketiliyordu -- bu sınıf yalnızca eksik olan tipli kontrat girişini
    dolduruyor, böylece ``test_event_contract.py``, hatta üzerindeki diğer
    her olay gibi bunu da gerçekten kapsıyor.
    """

    event: Literal["guardrail"] = "guardrail"
    stage: Literal["input", "output"]
    kind: str
    decision: Literal["flagged", "blocked", "redacted", "needs_review"]
    reasons: list[str] = Field(default_factory=list)
    seq: Optional[int] = None


class InterruptEvent(BaseModel):
    event: Literal["interrupt"] = "interrupt"
    kind: Literal[
        "missing_information",
        "writing_brief",
        #: Faz 4 (#201) -- `planning_graph.transfer_gate_node`. Bir transferin
        #: kime/neye gittiğini onaylamak (`artifact_transfer_confirm`) ile
        #: alıcı çözümlemesi belirsiz olduğunda bir aday seçmek
        #: (`artifact_transfer_disambiguate`) ayrı türlerdir; böylece
        #: frontend'in `TransferConfirmCard`'ı, `payload`'ı incelemeye gerek
        #: kalmadan her şekli (tek bir teklif ile bir aday listesi) render
        #: edebilir.
        "artifact_transfer_confirm",
        "artifact_transfer_disambiguate",
    ]
    interrupt_id: str
    payload: dict[str, Any]
    seq: Optional[int] = None


class NoticeEvent(BaseModel):
    """Kendi sohbet turu olarak render edilen, engellemeyen bilgilendirici bir mesaj.

    ``InterruptEvent``'in karşılığı: bir interrupt çalışmayı duraklatır ve
    başka bir şey olabilmeden önce bir insan yanıtı talep eder (bkz.
    ``langgraph.types.interrupt``); bir notice hiçbir şeyi asla
    duraklatmaz -- grafik çalışmaya devam eder ve istemcinin yapması gereken
    tek şey bir balon daha render etmektir. Çalışmayı asla kapı gibi
    engellememesi gereken bir bulgunun (bir talimat/mevzuat çatışması --
    bkz. ``app.ai.revision.conflict``'in ``applied_anyway`` değişmezi)
    sessizce bir sonuç blob'unun içinde kaybolmak veya daha kötüsü, bir
    "revizyon" kapısının kısa süreliğine yaptığı gibi bir popup'a zorlamak
    dışında gidecek bir yeri olması için eklendi.
    """

    event: Literal["notice"] = "notice"
    node: str
    #: Bugün "info"; gelecekte farklı bir önem derecesinin (örn. bir
    #: guardrail-benzeri uyarı) ikinci bir olay tipine ihtiyaç duymaması
    #: için bu alan var.
    level: Literal["info"] = "info"
    title: str
    message: str
    seq: Optional[int] = None


class QuestionOption(BaseModel):
    """Bir ``PromptQuestion``/``QuestionEvent``'e tıklanabilir tek bir cevap."""

    value: str
    label: str
    #: Seçeneğin etiketinin altında gösterilen, isteğe bağlı ikinci açıklama satırı.
    description: str = ""


class PromptQuestion(BaseModel):
    """Her "kullanıcıya sor" yüzeyinin paylaştığı kanonik şekildeki tek bir soru
    -- taslak-öncesi yazım brifi (writing brief), eksik-bilgi istekleri ve
    clarify'ın intent sorusu, tek bir frontend kart bileşeninin üçünü de
    render edebilmesi için hepsi ``list[PromptQuestion]`` yayınlar.

    ``missing_information``, kendi ``InfoQuestion``'ını dahili olarak tutar
    (onun ``key``'i, ``apply_answers``'ın yer tutucuları (placeholder)
    yerine koyduğu birleştirme anahtarıdır) ve yalnızca yayın sınırında,
    ``InfoQuestion.to_prompt_question`` üzerinden bu şekle dönüştürür.
    """

    key: str
    question: str
    header: str = ""
    #: Bunun neden sorulduğu -- hukuki/mevzuat gerekçesi veya benzer
    #: bağlam. ``InfoQuestion.why``'ı yansıtır.
    help: str = ""
    example: Optional[str] = None
    options: list[QuestionOption] = Field(default_factory=list)
    multi_select: bool = False
    allow_free_text: bool = True
    required: bool = True


class QuestionEvent(BaseModel):
    """Çalışmanın kullanıcıdan ihtiyaç duyduğu, tıklanabilir seçenekler olarak sunulan bir karar.

    ``InterruptEvent``'ten farklı olarak, bu asla ``interrupt()`` üzerinden
    bir LangGraph çalışmasını duraklatmaz -- clarify adımı kendi turunu
    zaten deterministik olarak sonlandırır (bkz.
    ``PLAN_BY_INTENT["clarify"]``) ve yalnızca kullanıcının *bir sonraki*
    mesajını bekler; bu mesajı ``planner._try_resolve_pending_clarification``
    aynı seçeneklere karşı çözümler. Bu olay yalnızca, kullanıcının iki
    Türkçe etiketten birini harfiyen yeniden yazmasına bırakmak yerine,
    istemciye seçenekleri bir kart olarak render etmesini söyler.

    ``question``/``options``/``allow_free_text``, orijinal tek-soru
    alanlarıdır; geriye dönük uyumluluk için ``questions[0]``'ın dolu bir
    yansıması olarak tutulur; yeni istemciler ``questions``'ı okumalıdır.
    """

    event: Literal["question"] = "question"
    node: str
    question: str
    options: list[QuestionOption] = Field(default_factory=list)
    #: Serbest metin bir cevabın (``options``'tan biri değil) da bu soruyu
    #: çözüp çözemeyeceği. Bugün her zaman True -- her clarify sorusu,
    #: ``_try_resolve_pending_clarification``'a göre bir etiketi geri
    #: yansıtarak da çözülebilir -- istemcinin bunu asla varsaymak zorunda
    #: kalmaması için açıkça tutuluyor.
    allow_free_text: bool = True
    questions: list[PromptQuestion] = Field(default_factory=list)
    seq: Optional[int] = None


class FinalResultEvent(BaseModel):
    """Bir turun terminal olayı.

    ``details`` serbest biçimlidir (bkz.
    ``planning_graph._compile_final_output``), ama her zaman en azından
    ``status``, ``plan_steps`` (bu tur için çözümlenmiş adım id'leri, örn.
    ``["classification", "draft", "routing"]``) ve ``intent`` taşır --
    ``planning_completed`` SSE olayının canlı taşıdığı aynı alanlar, burada
    kalıcı hale getirilir; böylece geçmişten yeniden açılan bir oturum
    (yalnızca saklanan mesajları oynatır, onları üreten SSE stream'ini asla
    oynatmaz) yine de workflow adım göstergesini (stepper) yeniden
    kurabilir.
    """

    event: Literal["final_result"] = "final_result"
    reply: str
    workflow_status: str
    details: dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = None


class ErrorEvent(BaseModel):
    event: Literal["error"] = "error"
    message: str
    details: Any = None
    #: ``AIException.error_code``'u yansıtan, makine tarafından okunabilir
    #: ayırt edici (örn. ``"SESSION_PAUSED"``) -- frontend'in yerelleştirilmiş
    #: ``message`` metnini örüntü eşleştirmek yerine belirli bir hataya
    #: (interrupt panelini kurtarmak gibi) tepki verebilmesini sağlar. Genel
    #: (catch-all) yol için ``None``.
    error_code: Optional[str] = None
    seq: Optional[int] = None


#: Backend'in bir SSE stream'ine koyabileceği her olay adı. Dondurulmuş bir
#: set olarak tutuluyor (model sınıflarının Literal varsayılanlarından
#: reflection ile türetilmiyor); böylece bir model yeniden adlandırması,
#: kontrat testi fark etmeden bunu sessizce değiştiremez.
WORKFLOW_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "session",
        "node_start",
        "node_end",
        "node_error",
        "node_skipped",
        "token",
        "tool_call",
        "partial_result",
        "planning_completed",
        "guardrail",
        "interrupt",
        "notice",
        "question",
        "final_result",
        "error",
    }
)

__all__ = [
    "SessionEvent",
    "NodeStartEvent",
    "NodeEndEvent",
    "NodeErrorEvent",
    "NodeSkippedEvent",
    "TokenEvent",
    "ToolCallEvent",
    "PartialResultEvent",
    "GuardrailEvent",
    "NoticeEvent",
    "QuestionOption",
    "PromptQuestion",
    "QuestionEvent",
    "PlanningCompletedEvent",
    "InterruptEvent",
    "FinalResultEvent",
    "ErrorEvent",
    "WORKFLOW_EVENT_NAMES",
]
