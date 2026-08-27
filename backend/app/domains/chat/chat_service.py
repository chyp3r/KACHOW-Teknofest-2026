import asyncio
import logging
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

from app.ai.reasoning_levels import get_reasoning_level_preset
from app.ai.session.focus import DraftVersion
from app.ai.workflows.events import emit_reply_stream
from app.api.exceptions.ai_error import AIException
from app.api.exceptions.authorization import AuthorizationException
from app.core.config import settings
from app.core.enums.step_status import StepStatus
from app.domains.chat import chat_recorder
from app.domains.drafts import draft_recorder
from app.domains.chat.schema.chat_schema import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatResumeRequest,
)
from app.domains.drafts.model.draft_model import DraftModel
from app.observability.ai_metrics import HITL_RESUMES
from app.observability.run_recorder import end_run

logger = logging.getLogger(__name__)

#: Orkestrasyon akışı birden fazla alt-graf çalıştırdığı için tek bir analiz
#: geçişinden daha uzun bir süre bütçesine sahiptir.
ORCHESTRATION_TIMEOUT_SECONDS = settings.AI_WORKFLOW_TIMEOUT_SECONDS * 2

DEFAULT_REPLY = "İşleminiz tamamlandı."
INTERRUPTED_REPLY = "Devam etmek için ek bilgiye veya onayınıza ihtiyaç var."

#: `compact_session` sohbeti sıkıştırırken birebir bırakılan son tur sayısı --
#: süreklilik için (zamir/eksilti çözümü) yeterince yeni bağlam, ama pencereyi
#: gerçekten küçültecek kadar az.
COMPACT_KEEP_TURNS = 2

#: Modül seviyesinde, bir `ChatService` örnek özniteliği değil (C13/C14, Faz 8):
#: `api/dependency.get_chat_service` her istek için yeni bir `ChatService`
#: oluşturur; oysa sardığı planlama grafı paylaşılan, tembel oluşturulan bir
#: singleton'dır (`get_planning_graph`'ın kendi modül seviyesindeki
#: `_planning_graph`'ı) -- bir örnek özniteliği her isteğe kendi boş kilit
#: kaydını verir ve hiçbir şeyi sıraya sokmaz. Bir oturumun grafını
#: ilerletebilecek her giriş noktası (yeni bir mesaj ya da devam, akışlı ya
#: da değil) checkpointer'a dokunmadan önce aynı `thread_id` için kilidi
#: alır; böylece çift gönderim -- hızlı bir çift tıklama, ilk isteği yarışa
#: sokan bir istemci yeniden denemesi -- aynı checkpoint'e karşı iki eşzamanlı
#: `ainvoke()` çağrısını yarıştırmak yerine sıraya sokulur: ikinci çağrı
#: sadece birincinin bitmesini (kayıt dahil) bekler ve ardından onun
#: sonuçlanmış durumuna göre hareket eder; aynı bayat checkpoint'i bağımsız
#: olarak okuyup ikinci, birbirinden sapan bir devam üretmek yerine (iki
#: `drafts` satırı, iki kaydedilmiş sohbet turu).
#:
#: Yalnızca süreç içi -- bu, birden fazla worker süreci arasında sıraya
#: sokma sağlamaz. `drafts` tablosunun kendi `(session_id, version)` benzersiz
#: indeksi (migration 0028) süreçler arası yedek güvencedir: orada kaybeden
#: eşzamanlı bir yazıcı, sessiz bir yinelenen satır yerine gürültülü bir
#: `IntegrityError` alır.
_session_locks: dict[str, asyncio.Lock] = {}


def _session_lock(thread_id: str) -> asyncio.Lock:
    """Bir oturuma dokunan her grafik çağrısını sıraya sokan kilit.

    Birden fazla eşyordamdan senkronizasyonsuz çağrılması güvenlidir:
    buradaki her şey eşzamanlıdır (``await`` yok), bu yüzden asyncio'nun
    tek iş parçacıklı olay döngüsü altında, eşzamanlı bir çağrının yarım
    güncellenmiş bir ``_session_locks`` görmesi mümkün olmadan tamamlanır.

    Kayıtlar kasıtlı olarak hiç tahliye edilmez: sahiplenilmemiş bir
    ``asyncio.Lock`` birkaç bayttır ve birini güvenli şekilde kaldırmak
    (yalnızca kimse onu tutmuyor veya beklemiyorken) kendi senkronizasyonunu
    gerektirir -- eşzamanlı bir çağıranın alma işleminin ortasında olduğu bir
    kilidi düşürmemek için. "Bu sürecin bugüne kadar gördüğü farklı oturumlar"
    ile sınırlı bir kayıt için buna değmez; bu, ``draft_history``'nin
    tur başına, checkpoint başına büyümesinin çok uzağındadır.
    """
    lock = _session_locks.get(thread_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[thread_id] = lock
    return lock


class ChatService:
    """Sohbet ve yapay zeka iş akışlarını ana planlama grafı üzerinden yönetir."""

    def __init__(self, planning_graph: Any) -> None:
        """Servisi başlatır.

        Args:
            planning_graph: Derlenmiş ana planlama iş akışı.
        """
        self.planning_graph = planning_graph

    async def handle_message(
        self,
        request: ChatMessageRequest,
        user_id: Optional[str] = None,
        requester_clearance: Optional[str] = None,
        company_id: Optional[str] = None,
        revision_draft: Optional[DraftModel] = None,
        user_display_name: Optional[str] = None,
    ) -> ChatMessageResponse:
        """Bir kullanıcı mesajını işler ve tamamlanmış (ya da duraklatılmış) sonucu döndürür.

        Args:
            request: Sohbet isteği.
            user_id: ``REQUIRE_AUTH`` açıkken kimliği doğrulanmış çağıranın
                id'si -- bir kullanıcının başka birinin thread'ine
                session_id'sini tahmin ederek/yeniden kullanarak
                erişememesi için thread_id'nin içine katılır. Açık
                demo/geliştirme yolunda ``None``, bu özellik var olmadan
                önceki davranışla aynı.
            requester_clearance: Kimliği doğrulanmış çağıranın çözümlenmiş
                ``SensitivityLevel.value`` değeri (bkz.
                ``app.core.permissions.role_checker.clearance_for``),
                biliniyorsa. Açık demo/geliştirme yolunda ``None``.
            company_id: Kimliği doğrulanmış çağıranın kiracısı (tenant) --
                grafın kendi durumuna (``PlanningState.company_id``)
                taşınır, böylece run/draft/guardrail kayıt edicileri
                yazımlarını bir şirkete atfedebilir; ``user_id`` için
                zaten yapıldığı gibi.
            revision_draft: Bu turun revizyon hedefi olarak açıkça seçilmiş,
                yetkilendirilmiş kalıcı taslak, varsa.
            user_display_name: Kimliği doğrulanmış çağıranın ``username``
                değeri (bkz. ``UserModel``), asist ajanının çağırana ismiyle
                hitap edebilmesi için ``PlanningState.user_display_name``'e
                taşınır (bkz. ``app.ai.identity.injection.
                format_user_address``). Açık demo/geliştirme yolunda ``None``.

        Returns:
            Orkestre edilmiş yanıt.

        Raises:
            AIException: İş akışı başarısız olursa veya zaman aşımını aşarsa.
        """
        thread_id = self._thread_id(request.session_id, user_id)
        # C13/C14: bu turun tamamını (`_invoke` içindeki duraklama-durumu
        # kontrolü dahil) aynı oturuma dokunan başka herhangi bir çağrıya
        # karşı sıraya sokar -- bkz. `_session_lock`'ın kendi docstring'i.
        async with _session_lock(thread_id):
            config = self._trace_config(thread_id, user_id, company_id)
            state = await self._invoke(
                request,
                config=config,
                user_id=user_id,
                requester_clearance=requester_clearance,
                company_id=company_id,
                revision_draft=revision_draft,
                user_display_name=user_display_name,
            )
            response = await self._response_from_state(
                state, config, thread_id, user_id=user_id, document_id=request.document_id, company_id=company_id
            )
            await chat_recorder.record_turn(
                thread_id=thread_id,
                user_id=user_id,
                document_id=request.document_id,
                user_message=request.message,
                reply=response.reply,
                workflow_status=response.workflow_status,
                details=response.details,
                company_id=company_id,
            )
        return response

    async def handle_message_stream(
        self,
        request: ChatMessageRequest,
        user_id: Optional[str] = None,
        requester_clearance: Optional[str] = None,
        company_id: Optional[str] = None,
        revision_draft: Optional[DraftModel] = None,
        user_display_name: Optional[str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Bir kullanıcı mesajını işler, ilerleme olaylarını gerçekleştikçe yayınlar.

        Tüketici yinelemeyi durdurursa worker görevi iptal edilir. Daha önce
        görev yalnızca döngüden sonra beklenirdi, bu yüzden akış ortasında
        bağlantısı kopan bir istemci grafı çalışır durumda bırakıyordu --
        kimsenin alamayacağı bir yanıt için yerel modeli meşgul tutarak.

        Args:
            request: Sohbet isteği.
            user_id: Bkz. :meth:`handle_message`.
            requester_clearance: Bkz. :meth:`handle_message`.
            company_id: Bkz. :meth:`handle_message`.
            revision_draft: Bkz. :meth:`handle_message`.
            user_display_name: Bkz. :meth:`handle_message`.

        Yields:
            İlerleme ve sonuç olayları. İlk olay her zaman ``session``dır ve
            çözümlenmiş ``thread_id``'yi taşır -- çağıran sağlamadığında
            sunucu tarafında üretilir -- böylece istemci daha sonra devam
            edebilir.
        """
        thread_id = self._thread_id(request.session_id, user_id)
        yield {"event": "session", "thread_id": thread_id}

        queue: asyncio.Queue = asyncio.Queue()

        async def run_graph() -> None:
            try:
                # C13/C14: handle_message'daki aynı yorumu bakınız.
                async with _session_lock(thread_id):
                    config = self._trace_config(thread_id, user_id, company_id)
                    config.setdefault("configurable", {})["status_queue"] = queue

                    state = await self._invoke(
                        request,
                        config=config,
                        user_id=user_id,
                        requester_clearance=requester_clearance,
                        company_id=company_id,
                        revision_draft=revision_draft,
                        user_display_name=user_display_name,
                    )
                    reply, workflow_status, details = await self._enqueue_terminal_event(
                        queue,
                        state,
                        config,
                        thread_id,
                        user_id=user_id,
                        document_id=request.document_id,
                        company_id=company_id,
                    )
                    await chat_recorder.record_turn(
                        thread_id=thread_id,
                        user_id=user_id,
                        document_id=request.document_id,
                        user_message=request.message,
                        reply=reply,
                        workflow_status=workflow_status,
                        details=details,
                        company_id=company_id,
                    )
            except asyncio.CancelledError:
                raise
            except AIException as exc:
                await queue.put(
                    {
                        "event": "error",
                        "message": exc.message,
                        "details": exc.details,
                        "error_code": exc.error_code,
                    }
                )
            except Exception as exc:
                logger.exception("Streaming workflow failed")
                await queue.put(
                    {
                        "event": "error",
                        "message": "İş akışı sırasında bir hata oluştu.",
                        "details": str(exc),
                    }
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_graph())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
            # Worker'daki bir çökmeyi yutmak yerine yüzeye çıkar, ama iptal
            # edilmiş bir görevin sonlanmasının generator'dan dışarı bir
            # hata fırlatmasına asla izin verme.
            await asyncio.gather(task, return_exceptions=True)

    async def resume(
        self,
        session_id: str,
        request: ChatResumeRequest,
        user_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> ChatMessageResponse:
        """İnsan-döngüde kapısında duraklatılmış bir çalışmayı devam ettirir ve sonucunu bekler.

        Args:
            session_id: Duraklatılmış çalışmanın beklediği thread_id.
            request: İnsanın yanıtı/kararı.
            user_id: ``REQUIRE_AUTH`` açıkken kimliği doğrulanmış çağıranın
                id'si. Thread'in oluşturulduğu user_id ile eşleşmelidir
                (bkz. :meth:`_thread_id`), aksi halde devam işlemi
                reddedilir -- yoksa kimliği doğrulanmış bir çağıran, sadece
                session_id'yi bilerek/tahmin ederek başka bir kullanıcının
                duraklatılmış çalışmasını devam ettirebilirdi.
            company_id: Aşağıdaki kayıt edici yazımı için kimliği doğrulanmış
                çağıranın kiracısı -- grafın kendi ``company_id`` durum alanı
                zaten orijinal ``handle_message`` çağrısından ayarlanmıştır
                ve checkpointer devamında değişmeden kalır, bu yüzden burada
                yalnızca :func:`chat_recorder.record_turn` için gereklidir.

        Returns:
            Orkestre edilmiş yanıt; tamamlanmış ya da tekrar duraklatılmış
            (örn. bazı eksik bilgi yanıtları boş bırakıldığında).

        Raises:
            AIException: Devam etme başarısız olursa veya zaman aşımını aşarsa.
            AuthorizationException: ``session_id``, ``user_id``'den farklı
                bir kullanıcıya aitse.
        """
        from langgraph.types import Command

        self._verify_thread_ownership(session_id, user_id)
        HITL_RESUMES.labels(action=request.action).inc()
        # C13/C14: unlike handle_message, a resume never went through
        # _invoke's own pause-state check at all -- this lock is the only
        # thing serializing it against a concurrent resume or a fresh
        # message on the same session (see _session_lock's own docstring).
        async with _session_lock(session_id):
            config = self._trace_config(session_id, user_id, company_id)
            # No explicit escalation on this resume -> preset resolves to
            # BALANCED (multiplier 1.0), leaving today's fixed timeout unchanged.
            timeout = ORCHESTRATION_TIMEOUT_SECONDS * get_reasoning_level_preset(
                request.reasoning_level
            ).timeout_multiplier
            try:
                state = await asyncio.wait_for(
                    self.planning_graph.ainvoke(
                        Command(resume=self._resume_payload(request)), config=config
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as exc:
                raise AIException(
                    message="Devam işlemi zaman aşımına uğradı.",
                    details={"timeout_seconds": timeout},
                ) from exc
            except Exception as exc:
                logger.exception("Resume failed")
                raise AIException(
                    message="Devam işlemi sırasında bir hata oluştu.",
                    details={"reason": str(exc)},
                ) from exc

            # C14: PlanningState.document_id survives a checkpointer resume
            # unchanged (see its own docstring) -- a resumed turn that
            # settles a draft used to record it with document_id hardcoded
            # to None regardless, so every draft resolved through a gate
            # (missing-information, brief, approval) lost its attachment
            # even though the original turn had one.
            document_id = state.get("document_id")
            response = await self._response_from_state(
                state, config, session_id, user_id=user_id, document_id=document_id, company_id=company_id
            )
            await chat_recorder.record_turn(
                thread_id=session_id,
                user_id=user_id,
                document_id=document_id,
                user_message=self._resume_summary(request),
                user_details={"interaction_response": self._resume_payload(request)},
                reply=response.reply,
                workflow_status=response.workflow_status,
                details=response.details,
                company_id=company_id,
            )
        return response

    async def resume_stream(
        self,
        session_id: str,
        request: ChatResumeRequest,
        user_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Resume a paused run, yielding progress events as they happen.

        Same worker/queue shape as :meth:`handle_message_stream`; the only
        difference is that the graph resumes from its checkpoint via
        ``Command(resume=...)`` instead of starting a fresh run.

        Args:
            session_id: The thread_id the paused run is waiting on.
            request: The human's answer/decision.
            user_id: See :meth:`resume`.
            company_id: See :meth:`resume`.

        Yields:
            Progress and result events.

        Raises:
            AuthorizationException: If ``session_id`` belongs to a different
                user than ``user_id``.
        """
        from langgraph.types import Command

        self._verify_thread_ownership(session_id, user_id)
        HITL_RESUMES.labels(action=request.action).inc()
        timeout = ORCHESTRATION_TIMEOUT_SECONDS * get_reasoning_level_preset(
            request.reasoning_level
        ).timeout_multiplier
        queue: asyncio.Queue = asyncio.Queue()

        async def run_graph() -> None:
            try:
                # C13/C14: see resume's identical comment.
                async with _session_lock(session_id):
                    config = self._trace_config(session_id, user_id, company_id)
                    config.setdefault("configurable", {})["status_queue"] = queue

                    state = await asyncio.wait_for(
                        self.planning_graph.ainvoke(
                            Command(resume=self._resume_payload(request)), config=config
                        ),
                        timeout=timeout,
                    )
                    # C14: see resume's identical comment.
                    document_id = state.get("document_id")
                    reply, workflow_status, details = await self._enqueue_terminal_event(
                        queue, state, config, session_id, user_id=user_id, document_id=document_id,
                        company_id=company_id,
                    )
                    await chat_recorder.record_turn(
                        thread_id=session_id,
                        user_id=user_id,
                        document_id=document_id,
                        user_message=self._resume_summary(request),
                        user_details={"interaction_response": self._resume_payload(request)},
                        reply=reply,
                        workflow_status=workflow_status,
                        details=details,
                        company_id=company_id,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Streaming resume failed")
                await queue.put(
                    {
                        "event": "error",
                        "message": "Devam işlemi sırasında bir hata oluştu.",
                        "details": str(exc),
                    }
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_graph())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def get_session_state(
        self, session_id: str, user_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Report whether a session is idle, running, or paused on an interrupt.

        Args:
            session_id: The thread_id to inspect.
            user_id: See :meth:`resume`.

        Returns:
            ``{"status": "interrupted", "interrupt": {...}}`` when paused,
            ``{"status": "idle", "interrupt": None}`` otherwise (including
            when no checkpointer is configured, in which case a session can
            never be found paused).

        Raises:
            AuthorizationException: If ``session_id`` belongs to a different
                user than ``user_id``.
        """
        self._verify_thread_ownership(session_id, user_id)
        config = self._trace_config(session_id)
        try:
            snapshot = await self.planning_graph.aget_state(config)
        except Exception:
            return {"status": "idle", "interrupt": None}

        if not snapshot.next:
            return {"status": "idle", "interrupt": None}

        interrupt_payload = self._extract_interrupt(snapshot)
        if interrupt_payload is None:
            return {"status": "running", "interrupt": None}
        return {"status": "interrupted", "interrupt": interrupt_payload}

    async def cancel_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> dict[str, str]:
        """Stop a session and settle any checkpoint left by the aborted stream.

        Closing the SSE connection cancels the in-process worker, but LangGraph
        may already have persisted a checkpoint whose ``next`` node is still
        pending.  A later message on that thread would then be rejected as a
        paused/running session.  Cancellation therefore participates in the
        same per-session lock as send/resume and explicitly makes that
        checkpoint terminal.

        A genuine human interrupt is resumed with ``reject`` first so its
        domain cleanup still runs (for example, a pending transfer intent is
        cancelled and a draft awaiting input is rejected).  A checkpoint left
        between ordinary nodes has no interrupt to resume, so it is advanced
        as the graph's terminal ``consolidate_memory`` node and its audit run
        is closed as cancelled.
        """
        from langgraph.types import Command

        self._verify_thread_ownership(session_id, user_id)
        async with _session_lock(session_id):
            config = self._trace_config(session_id, user_id, company_id)
            try:
                snapshot = await self.planning_graph.aget_state(config)
            except Exception:
                # Without a readable checkpointer there is no persisted work
                # to settle; the disconnected stream's task cancellation is
                # sufficient.
                return {"status": "cancelled"}

            if not getattr(snapshot, "next", ()):
                return {"status": "idle"}

            if self._extract_interrupt(snapshot) is not None:
                try:
                    await asyncio.wait_for(
                        self.planning_graph.ainvoke(
                            Command(
                                resume={
                                    "action": "reject",
                                    "answers": {},
                                    "instructions": "",
                                    "reason": "İşlem kullanıcı tarafından durduruldu.",
                                    "reasoning_level": None,
                                }
                            ),
                            config=config,
                        ),
                        timeout=ORCHESTRATION_TIMEOUT_SECONDS,
                    )
                except Exception:
                    # The graph must not remain unusable even if an interrupt's
                    # domain-specific rejection path fails.  Keep the failure
                    # visible in logs, then close the checkpoint below.
                    logger.exception(
                        "Interrupt cleanup failed while cancelling session %s",
                        session_id,
                    )
                else:
                    if not await self._is_paused(config):
                        return {"status": "cancelled"}

            await self.planning_graph.aupdate_state(
                config,
                {
                    "final_output": {
                        "status": "CANCELLED",
                        "assist": {
                            "reply": "İşlem kullanıcı tarafından durduruldu.",
                            "status": "CANCELLED",
                        },
                    }
                },
                as_node="consolidate_memory",
            )
            await self._end_orphaned_run(config, "cancelled")
            return {"status": "cancelled"}

    async def compact_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Sohbeti sıkıştır: birebir geçmiş penceresini `history_summary`'ye katla.

        Kullanıcı tetikler (sohbetteki bağlam göstergesinin "Bağlamı sıkıştır"
        düğmesi). Son ``COMPACT_KEEP_TURNS`` turu birebir bırakır, öncesini
        yuvarlanan özete ekler ve ``history_summarized_through``'u ileri alır --
        böylece bir sonraki assist turu bu turları yalnızca özet olarak görür
        (bkz. ``planning_graph._run_assist``'in `_compacted_through` dilimi).
        ``history`` kanalı bir reducer (append-only) olduğundan trim edilmez;
        işaret + özet, birebir pencereyi küçültmeye yeter.

        Returns:
            ``{"status": "compacted"|"noop"|"busy"|"unavailable",
            "folded_turns": int, "context_usage": {...}}``.
        """
        self._verify_thread_ownership(session_id, user_id)
        async with _session_lock(session_id):
            config = self._trace_config(session_id, user_id, company_id)
            try:
                snapshot = await self.planning_graph.aget_state(config)
            except Exception:
                return {"status": "unavailable"}
            if getattr(snapshot, "next", ()):
                # Aktif bir tur ya da bekleyen bir HITL var; şimdi sıkıştırmak
                # yarıda kalmış durumu bozardı.
                return {"status": "busy"}

            values = getattr(snapshot, "values", None) or {}
            history: list[dict[str, str]] = list(values.get("history") or [])
            through = max(0, int(values.get("history_summarized_through") or 0))
            existing_summary = values.get("history_summary") or ""

            fold_end = max(through, len(history) - COMPACT_KEEP_TURNS)
            to_fold = history[through:fold_end]
            if not to_fold:
                return {
                    "status": "noop",
                    "folded_turns": 0,
                    "context_usage": self._context_usage_snapshot(
                        existing_summary, history[through:]
                    ),
                }

            from app.ai.agents.memory_summarizer import MemorySummarizerAgent
            from app.ai.llms import get_fast_llm_client

            summarizer = MemorySummarizerAgent(get_fast_llm_client())
            new_summary = await summarizer.summarize(
                existing_summary=existing_summary, new_turns=to_fold
            )
            await self.planning_graph.aupdate_state(
                config,
                {
                    "history_summary": new_summary,
                    "history_summarized_through": fold_end,
                },
                as_node="consolidate_memory",
            )
            return {
                "status": "compacted",
                "folded_turns": len(to_fold),
                "context_usage": self._context_usage_snapshot(
                    new_summary, history[fold_end:]
                ),
            }

    @staticmethod
    def _context_usage_snapshot(
        history_summary: str, kept_turns: list[dict[str, str]]
    ) -> dict[str, Any]:
        """Sıkıştırma sonrası bağlam doluluk dökümü (assist turu beklemeden).

        ``_run_assist``'in ürettiğiyle aynı biçim; frontend'in dairesel
        göstergesi bunu anında güncelleyebilsin diye.
        """
        try:
            from app.ai.agents.assistant import AssistantAgent
            from app.ai.context.usage import compute_context_usage
            from app.ai.llms import get_llm_client
            from app.ai.workflows.planning_graph import ASSIST_COMPLETION_RESERVE_TOKENS

            client = get_llm_client()
            return compute_context_usage(
                client,
                system_prompt=AssistantAgent(client).system_prompt,
                history_summary=history_summary or "",
                history_turns=kept_turns,
                reserved_tokens=ASSIST_COMPLETION_RESERVE_TOKENS,
            )
        except Exception:
            logger.exception("Could not compute post-compaction context usage")
            return {}

    async def _invoke(
        self,
        request: ChatMessageRequest,
        config: dict[str, Any],
        user_id: Optional[str] = None,
        requester_clearance: Optional[str] = None,
        company_id: Optional[str] = None,
        revision_draft: Optional[DraftModel] = None,
        user_display_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run the planning graph under a timeout.

        Args:
            request: The chat request.
            config: The LangGraph runnable config.
            user_id: The authenticated caller's id, when known -- carried
                into the graph's own state (not just the thread_id prefix)
                so the run-recording audit trail (see
                app.observability.run_recorder) can attribute a run to a
                user without parsing it back out of thread_id.
            requester_clearance: The authenticated caller's resolved
                clearance, carried into the graph state the same way --
                read by _run_assist to gate document tool calls and the
                output guardrail. Set once here; persists across a later
                human-in-the-loop resume via the checkpointer, same as
                user_id/document_id.
            company_id: The authenticated caller's tenant, carried into
                ``PlanningState.company_id`` the same way -- read by every
                recorder call inside the planning graph (``start_run``,
                ``record_step``, ``end_run``, the output guardrail's
                ``record_event``) so their writes can be attributed to a
                company. Also persists across a checkpointer resume.
            revision_draft: Authorized persisted target to load into
                ``SessionFocus.active_draft`` before planning this turn.
            user_display_name: The authenticated caller's ``username``,
                carried into ``PlanningState.user_display_name`` the same
                way -- read by ``_run_assist`` so it can address the caller
                by name. ``None`` in the open demo/dev path.

        Returns:
            The final (or paused) workflow state.

        Raises:
            AIException: On timeout, workflow failure, or when this session
                already has a pending human-in-the-loop interrupt -- starting
                a fresh run on a thread with an outstanding paused task is not
                a supported resume path; the caller must use ``/chat/resume``
                (or a new session_id) instead.
        """
        if await self._is_paused(config):
            thread_id = (config.get("configurable") or {}).get("thread_id")
            raise AIException(
                message=(
                    "Bu oturumda yanıt bekleyen tamamlanmamış bir adım var (eksik bilgi "
                    "talebi ya da bir onay adımı)."
                ),
                error_code="SESSION_PAUSED",
                details={"session_id": thread_id},
            )

        thread_id = (config.get("configurable") or {}).get("thread_id", "")
        await self._attach_direct_revision_draft(
            revision_draft, thread_id=thread_id, company_id=company_id
        )

        timeout = ORCHESTRATION_TIMEOUT_SECONDS * get_reasoning_level_preset(
            request.reasoning_level
        ).timeout_multiplier
        try:
            focus_update = self._revision_focus(revision_draft)
            return await asyncio.wait_for(
                self.planning_graph.ainvoke(
                    {
                        "input_text": request.message,
                        "document_id": request.document_id,
                        "reasoning_level": request.reasoning_level.value,
                        "user_id": user_id,
                        "requester_clearance": requester_clearance,
                        "company_id": company_id,
                        "user_display_name": user_display_name,
                        "focus": focus_update,
                    },
                    config=config,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            await self._end_orphaned_run(config, "timeout")
            raise AIException(
                message="Sohbet işlemi zaman aşımına uğradı.",
                details={"timeout_seconds": timeout},
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Orchestration workflow failed")
            await self._end_orphaned_run(config, "error")
            raise AIException(
                message="İş akışı sırasında bir hata oluştu.",
                details={"reason": str(exc)},
            ) from exc

    async def _end_orphaned_run(self, config: dict[str, Any], status: str) -> None:
        """Close out a run's ``runs`` row after its task never reached
        ``consolidate_memory_node`` -- the only place ``end_run`` is
        normally called (see that node's own docstring).

        A timed-out or crashed ``ainvoke`` leaves the graph task aborted
        mid-flight; without this, the row `planning_node`'s own
        ``start_run`` wrote stays ``"running"`` forever, indistinguishable
        from a genuinely still-in-progress turn.

        Best-effort and silent on any failure: recovering the ``run_id``
        needs a checkpointer (see ``aget_state``'s own tolerance of one
        being absent), and this must never raise a *second* exception on
        top of the one the caller is already handling.

        Args:
            config: The same runnable config the failed ``ainvoke`` call used.
            status: Recorded on the row -- ``"timeout"`` or ``"error"``.
        """
        try:
            snapshot = await self.planning_graph.aget_state(config)
            values = snapshot.values if snapshot else {}
            run_id = values.get("run_id") if isinstance(values, dict) else None
            company_id = values.get("company_id") if isinstance(values, dict) else None
        except Exception:
            return
        if not run_id:
            return
        try:
            await end_run(run_id=run_id, status=status, company_id=company_id)
        except Exception:
            logger.warning("Failed to close out orphaned run %s", run_id, exc_info=True)

    @staticmethod
    def _revision_focus(draft: Optional[DraftModel]) -> dict[str, Any]:
        """Build the partial session-focus update for an explicit draft pick.

        Persisted drafts intentionally store the settled text and quality
        metadata, not the graph's full source/context snapshot.  The selected
        row is therefore loaded as a revision target without inventing missing
        grounding; a newly produced version will carry whatever the revision
        workflow can verify from that honest baseline.
        """
        if draft is None:
            return {}
        created_from = "rejected" if (draft.status or "").upper() == "REJECTED" else "draft"
        active_draft = DraftVersion(
            version=draft.version,
            text=draft.content,
            correspondence_type=draft.correspondence_type or "other_official",
            confidence_score=float(draft.confidence_score or 0.0),
            created_from=created_from,
            supersedes=0,
            status=draft.status or "",
        )
        return {
            "active_draft": active_draft,
            "draft_history": (active_draft,),
            "active_draft_idle_turns": 0,
            "active_draft_id": draft.id,
            "writing_brief": None,
        }

    @staticmethod
    async def _attach_direct_revision_draft(
        draft: Optional[DraftModel], *, thread_id: str, company_id: Optional[str]
    ) -> None:
        if draft is None or draft.session_id is not None:
            return
        attached = await draft_recorder.attach_to_session(
            draft_id=draft.id,
            session_id=thread_id,
            company_id=company_id,
        )
        if attached:
            draft.session_id = thread_id

    async def _enqueue_terminal_event(
        self,
        queue: "asyncio.Queue",
        state: dict[str, Any],
        config: dict[str, Any],
        thread_id: str,
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> tuple[str, str, dict[str, Any]]:
        """Push the run's closing event: ``final_result``, or nothing if paused.

        A paused run already pushed its own ``interrupt`` event from inside
        ``human_gate_node`` (via ``emit_interrupt``) at the moment it actually
        suspended -- pushing a second, synthetic one here would duplicate it,
        and pushing ``final_result`` would be actively wrong, since a paused
        run's ``final_output`` is still empty. This only determines whether to
        stay silent (paused) or announce completion.

        Args:
            queue: The SSE progress queue.
            state: The state ``ainvoke``/resume returned.
            config: The config used for that call, reused to check pause state.
            thread_id: The session's thread_id, for logging only.
            user_id: See :meth:`handle_message`; forwarded to
                :meth:`_maybe_record_draft`.
            document_id: The document attached to this turn, if any;
                forwarded to :meth:`_maybe_record_draft`.

        Returns:
            ``(reply, workflow_status, details)`` for this turn -- the same
            values pushed (or that would have been pushed) as the SSE event,
            handed back so the caller can persist the turn without
            re-deriving them (and without re-checking pause state a second
            time).
        """
        if await self._is_paused(config):
            logger.info("Session %s paused at a human-in-the-loop gate.", thread_id)
            snapshot = await self.planning_graph.aget_state(config)
            interrupt_payload = self._extract_interrupt(snapshot) or {}
            return INTERRUPTED_REPLY, "INTERRUPTED", {"interrupt": interrupt_payload}

        final_output = state.get("final_output", {}) or {}
        reply = self._select_reply(final_output)
        workflow_status = final_output.get("status", "FAILED")
        # Recorded *before* the reply streams out: the persisted draft's own
        # id needs to already be sitting in `final_output["draft"]["id"]`
        # when `details` goes out below, not after -- a second round after
        # the client already has this turn's response is too late for it to
        # ever see the id.
        draft_id = await self._maybe_record_draft(
            final_output, config, thread_id, user_id, document_id, company_id
        )
        if draft_id and isinstance(final_output.get("draft"), dict):
            final_output["draft"]["id"] = draft_id
        # The only text ever streamed to the client this turn -- see
        # emit_reply_stream's docstring. Streamed *before* final_result so
        # the chat bubble fills in live rather than the whole reply
        # appearing at once with the "typing" state ending abruptly.
        await emit_reply_stream(queue, reply)
        await queue.put(
            {
                "event": "final_result",
                "reply": reply,
                "workflow_status": workflow_status,
                "details": final_output,
            }
        )
        return reply, workflow_status, final_output

    async def _response_from_state(
        self,
        state: dict[str, Any],
        config: dict[str, Any],
        thread_id: str,
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> ChatMessageResponse:
        """Build the non-streaming response, accounting for a paused run."""
        if await self._is_paused(config):
            snapshot = await self.planning_graph.aget_state(config)
            interrupt_payload = self._extract_interrupt(snapshot) or {}
            return ChatMessageResponse(
                reply=INTERRUPTED_REPLY,
                workflow_status="INTERRUPTED",
                session_id=thread_id,
                details={"interrupt": interrupt_payload},
            )

        final_output = state.get("final_output", {}) or {}
        draft_id = await self._maybe_record_draft(
            final_output, config, thread_id, user_id, document_id, company_id
        )
        if draft_id and isinstance(final_output.get("draft"), dict):
            final_output["draft"]["id"] = draft_id
        return ChatMessageResponse(
            reply=self._select_reply(final_output),
            workflow_status=final_output.get("status", "FAILED"),
            session_id=thread_id,
            details=final_output,
        )

    async def _maybe_record_draft(
        self,
        final_output: dict[str, Any],
        config: dict[str, Any],
        thread_id: str,
        user_id: Optional[str],
        document_id: Optional[str],
        company_id: Optional[str] = None,
    ) -> Optional[str]:
        """Persist a draft this turn produced or revised, if any.

        ``final_output["draft"]`` is ``PlanningState.draft_result`` -- the
        same shape ``app.domains.documents.draft_service.DraftService``
        builds ``DraftResponseSchema`` from for the direct-API path. A no-op
        when this turn's step wasn't drafting/revising (``draft_result`` is
        then ``{}``, so ``.get("draft")`` is falsy).

        Returns:
            The persisted ``drafts.id``, or ``None`` when nothing was
            recorded -- the caller injects this into ``final_output["draft"]
            ["id"]`` (see both call sites) so the frontend's chat response
            can address this exact draft (the "Birimi değiştir" picker,
            among other things) without a second round-trip to guess which
            of this session's drafts the turn just produced.
        """
        draft = final_output.get("draft") or {}
        content = draft.get("draft")
        if not content:
            return None
        if draft.get("status") == StepStatus.FAILED:
            # A FAILED result (a timed-out/errored draft or revise attempt)
            # carries the *previous*, unrevised text back verbatim -- see
            # e.g. `revise.py`'s FAILED return paths, which return
            # `active_draft.text` unchanged -- stamped with a 0.0
            # confidence score that has nothing to do with that text's real
            # quality. Persisting it would create a phantom new version,
            # byte-identical to the one before it but scored 0.0/FAILED,
            # which `DraftRepository.get_latest_for_session` would then
            # serve as "the current draft" ahead of the real one. Nothing
            # actually changed this turn; there is nothing to record.
            return None
        routing = final_output.get("routing") or {}
        # C29: `draft["verification"]` alone only ever carries
        # VerificationReport.applied_rules -- the deterministic verifier's
        # own findings. The fuller, auditable breakdown (PII, a guessed
        # correspondence type, missing mevzuat context, judge/style
        # findings) lives in `draft["applied_rules"]` instead (see
        # `merge_verdicts`'s own docstring), and DraftModel.verification has
        # no separate column for it -- folded in here the same way
        # `app.domains.documents.draft_service.DraftService`'s own
        # `verification_for_storage` does, so a persisted draft's stored
        # verification actually matches what the response schema's
        # top-level `applied_rules` field shows, for both a fresh draft and
        # a revision alike.
        verification_for_storage = {
            **(draft.get("verification") or {}),
            "applied_rules": draft.get("applied_rules") or [],
        }
        draft_id = await draft_recorder.record_draft(
            user_id=user_id,
            company_id=company_id,
            session_id=thread_id,
            document_id=document_id,
            content=content,
            correspondence_type=draft.get("correspondence_type"),
            destination=routing.get("final_destination"),
            destination_justification=routing.get("justification"),
            status=draft.get("status"),
            confidence_score=draft.get("confidence_score"),
            requires_human_approval=draft.get("requires_human_approval"),
            attempts=draft.get("attempts"),
            verification=verification_for_storage,
            judge=draft.get("judge"),
            missing_information=draft.get("missing_information"),
        )
        if draft_id:
            # Best-effort, same tolerance `_is_paused` already has for a
            # missing/unreachable checkpointer: `SessionFocus.active_draft_id`
            # is a convenience hint (see its own docstring), never load-bearing
            # -- the `propose_transfer` tool (`app.ai.tools.transfer_tools`)
            # falls back to `DraftRepository.get_latest_for_session` regardless.
            try:
                await self.planning_graph.aupdate_state(
                    config, {"focus": {"active_draft_id": draft_id}}
                )
            except Exception:
                logger.warning("Could not persist active_draft_id for thread %s", thread_id)
        return draft_id

    async def _is_paused(self, config: dict[str, Any]) -> bool:
        """Whether the last graph call left the run suspended on an interrupt.

        Safe to call even without a checkpointer configured: ``aget_state``
        raises in that case, which this treats as "never paused" -- correct,
        since ``route_after_step`` only ever detours to ``human_gate`` when a
        checkpointer is present in the first place.
        """
        try:
            snapshot = await self.planning_graph.aget_state(config)
        except Exception:
            return False
        return bool(snapshot.next)

    @staticmethod
    def _extract_interrupt(snapshot: Any) -> Optional[dict[str, Any]]:
        """Pull the pending interrupt's payload out of a state snapshot."""
        for task in getattr(snapshot, "tasks", ()) or ():
            task_interrupts = getattr(task, "interrupts", None) or ()
            for item in task_interrupts:
                value = getattr(item, "value", item)
                if isinstance(value, dict):
                    return value
        return None

    @staticmethod
    def _resume_payload(request: ChatResumeRequest) -> dict[str, Any]:
        """Shape a ChatResumeRequest into the dict human_gate_node's interrupt() expects."""
        return {
            "action": request.action,
            "answers": request.answers,
            "instructions": request.instructions,
            "reason": request.reason,
            "reasoning_level": (
                request.reasoning_level.value if request.reasoning_level else None
            ),
        }

    @staticmethod
    def _resume_summary(request: ChatResumeRequest) -> str:
        """A human-readable stand-in for the user's turn on a HITL resume.

        ``ChatResumeRequest`` carries structured answers/an action, not free
        text like ``ChatMessageRequest.message`` -- this renders it into
        something a chat history view can show in place of a message bubble.
        """
        if request.action == "answer" and request.answers:
            return "; ".join(
                f"{key}: {', '.join(value) if isinstance(value, list) else value}"
                for key, value in request.answers.items()
            )
        if request.action == "reject" and request.reason:
            return f"reject: {request.reason}"
        if request.instructions:
            return f"{request.action}: {request.instructions}"
        return request.action

    @staticmethod
    def _thread_id(session_id: Optional[str], user_id: Optional[str] = None) -> str:
        """Resolve the checkpointer thread_id for a request.

        Before ``user_id`` existed, the thread_id *was* the client-supplied
        ``session_id`` -- any caller who knew or reused another caller's
        session_id could resume/read that thread. Folding the authenticated
        user's id into the prefix makes that structurally impossible once
        ``REQUIRE_AUTH`` is on: no session_id an attacker can pick or guess
        starts with a user_id they don't have.

        Args:
            session_id: The client-supplied session id, if any.
            user_id: The authenticated caller's id, when ``REQUIRE_AUTH`` is
                on. ``None`` in the open demo/dev path, which keeps today's
                behaviour unchanged.

        Returns:
            ``f"{user_id}:{session_id}"`` when authenticated, otherwise
            ``session_id`` unchanged or a fresh server-generated id.
        """
        if user_id:
            return f"{user_id}:{session_id or uuid4()}"
        return session_id or f"anon:{uuid4()}"

    @staticmethod
    def _owns_thread(thread_id: str, user_id: Optional[str]) -> bool:
        """Whether an authenticated caller may resume/inspect ``thread_id``.

        ``user_id=None`` (``REQUIRE_AUTH`` disabled) is always allowed --
        unauthenticated mode has no concept of "someone else's thread" to
        guard against, matching the open demo/dev behaviour everywhere else
        in this phase. An authenticated caller may only touch threads
        carrying its own user_id prefix, the one :meth:`_thread_id` itself
        stamped on when the thread was first created.
        """
        if user_id is None:
            return True
        return thread_id.startswith(f"{user_id}:")

    @classmethod
    def _verify_thread_ownership(cls, thread_id: str, user_id: Optional[str]) -> None:
        """Raise if ``user_id`` is not allowed to resume/inspect ``thread_id``."""
        if not cls._owns_thread(thread_id, user_id):
            raise AuthorizationException(message="Bu oturuma erişim izniniz yok.")

    @staticmethod
    def _select_reply(final_output: dict[str, Any]) -> str:
        """Pick the text shown to the user from the completed workflow output.

        Args:
            final_output: The compiled workflow result.

        Returns:
            The reply text.
        """
        assist = final_output.get("assist") or {}
        if assist.get("reply"):
            return assist["reply"]

        draft = final_output.get("draft") or {}
        if draft.get("draft"):
            # The reply is the draft text alone -- routing unit, confidence
            # score, approval/rejection notes and the changelog summary all
            # used to be appended here as free text, but they are structured
            # data the frontend already receives via this same
            # final_output (as ``details`` on the chat message: see
            # ChatMessageResponse.details / the "final_result" SSE event)
            # and renders as its own meta strip -- see
            # frontend DraftMetaStrip. A conflict finding was never folded
            # in here either, for the same reason (see
            # app.ai.workflows.revise_graph.audit_node's "notice" event):
            # a structured finding belongs in a dedicated surface, not
            # concatenated onto the answer.
            return f"Resmî yazı taslağınız hazırlandı.\n\n{draft['draft']}"

        if draft.get("error"):
            return f"Taslak oluşturulamadı: {draft['error']}"

        classification = final_output.get("classification") or {}
        if classification.get("summary"):
            return (
                f"Evrak analizi tamamlandı.\n\n"
                f"**Tür:** {classification.get('document_type_label', 'Belirlenemedi')}\n\n"
                f"**Özet:** {classification['summary']}"
            )

        return DEFAULT_REPLY

    @staticmethod
    def _trace_config(
        thread_id: str, user_id: Optional[str] = None, company_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Build the LangGraph config: thread_id plus Langfuse tracing when available.

        Args:
            thread_id: The checkpointer thread id for this session.
            user_id, company_id: Attached as Langfuse trace metadata (see
                ``app.observability.tracer.build_trace_config``) when known
                -- omitted (not fabricated) at call sites that don't have
                one in scope, e.g. ``get_session_state``.

        Returns:
            A config dict with ``configurable.thread_id`` always set, and
            ``callbacks`` present only when tracing is available.
        """
        try:
            from app.observability.tracer import build_trace_config, company_tags

            return build_trace_config(
                thread_id=thread_id,
                langfuse_user_id=user_id,
                langfuse_session_id=thread_id,
                langfuse_tags=company_tags(company_id),
            )
        except Exception:
            logger.debug("Langfuse tracing unavailable; continuing without it.")
            return {"configurable": {"thread_id": thread_id}}
