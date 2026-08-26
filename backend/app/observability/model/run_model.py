from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import TimestampMixin


class RunModel(Base, TimestampMixin):
    """Tek bir planning-graph çağrısı (bir sohbet turu) ve onu şekillendiren karar.

    Prometheus (``app.observability.ai_metrics``) "sistem toplamda nasıl
    gidiyor" sorusunu yanıtlar; bu ise "bu spesifik istekte ne oldu"
    sorusunu yanıtlar -- bir kullanıcı kötü bir yanıt bildirdiğinde
    ("ne karar verdi ve neden") fiilen gündeme gelen soru.
    ``intent``/``source``/``confidence``/``evidence``/``alternatives``/
    ``clarification``, router'ın bu tur için çözdüğü ``PlanDecision``'ın
    her alanıdır (bkz. ``app.ai.workflows.planner.PlanDecision``) -- hiçbir
    şey iki kez hesaplanmaz, sadece isteğin ömrünü aşabileceği bir yerde
    kalıcı hale getirilir.

    Langfuse tracing'in (``app.observability.tracer``) yerini almaz; o
    isteğe bağlıdır ve LLM-çağrısı seviyesinde span'ler yakalar. Bu ise
    ürünün kendi denetim kaydıdır, her zaman açıktır ve üçüncü taraf bir
    hesap olmadan sorgulanabilir.
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: `0016_recorder_tables_rls` migration'ından beri NOT NULL --
    #: `PlanningState.company_id`'den yazılır (bkz.
    #: `app.observability.run_recorder.start_run`), planning graph'ın
    #: state'i boyunca `user_id` ile birlikte taşınır. Row-level security
    #: altındadır (aynı migration).
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    thread_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    document_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    input_text: Mapped[str] = mapped_column(String, nullable=False, default="")
    intent: Mapped[str] = mapped_column(String, nullable=False)
    plan_steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    alternatives: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    clarification: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    #: "running" | "completed" | "failed". Human-in-the-loop kapısında
    #: duraklayan ve bir daha devam ettirilmeyen bir run için "running"
    #: olarak kalır -- burada süpürülmeyen veya zaman aşımına
    #: uğratılmayan, terk edilmiş bir run'ın dürüst bir yansımasıdır.
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")


class RunStepModel(Base, TimestampMixin):
    """Bir run içindeki tek bir plan adımının sonucu (bkz. ``RunModel``).

    ``app.ai.workflows.planning_graph._execute_one_step`` içindeki her
    ``STEP_RUNNERS`` dispatch'i için bir satır -- bu kod tabanının zaten
    bir Prometheus gözlemine (``NODE_DURATION``) dönüştürdüğü aynı
    ``status``/süre, sadece toplu değil, run başına da tutulur.
    """

    __tablename__ = "run_steps"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    #: Üst run'dan denormalize edilmiştir; `0016_recorder_
    #: tables_rls`'den beri NOT NULL -- bkz. `RunModel.company_id`.
    company_id: Mapped[str] = mapped_column(
        String, ForeignKey("companies.id"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("runs.id"), nullable=False, index=True
    )
    step: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
