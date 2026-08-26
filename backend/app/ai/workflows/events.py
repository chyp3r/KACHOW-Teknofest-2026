"""İş akışı düğümlerinin yaydığı ve SSE akışının tükettiği ilerleme olayları.

Her düğüm, ``config["configurable"]["status_queue"]``'a doğrudan erişmek
yerine bu modül üzerinden yayın yapar. İki nedeni var:

1. Kuyruk isteğe bağlıdır. Akış kullanmayan çağıranlar (belge yükleme,
   testler, değerlendirmeler) aynı grafikleri kuyruk bağlanmadan çalıştırır,
   bu yüzden her yayının bu durumda no-op olması gerekir -- bu kontrol daha
   önce her çağrı noktasında ayrı ayrı tekrarlanıyordu ve bazılarında
   unutuluyordu.
2. Alt grafik çağrıları üst ``config``'i iletmek zorundadır. İletmedikleri
   zaman kuyruk writer ve editor düğümlerine hiç ulaşmıyordu, bu yüzden UI
   pipeline'ın en uzun aşamasında hiç ilerleme göstermiyordu.
   :func:`child_config` doğru çağrı şeklini yanlış yapmayı zorlaştırır.
"""

import logging
import weakref
from typing import Any, Mapping, Optional

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

STATUS_QUEUE_KEY = "status_queue"

#: Kuyruk başına (yani SSE oturumu başına) monoton sayaç, böylece frontend
#: olayları sıralayıp tekilleştirebilir -- özellikle interrupt replay
#: durumunda gerekli: interrupt() devam ettirildiğinde kendinden önceki her
#: şeyi yeniden çalıştırır, bu yüzden emit_interrupt aynı interrupt_id ile
#: tekrar tetiklenir ve seq, istemcinin "aynı olayın tekrarı" ile "yeni bir
#: olay"ı ayırt etmesini sağlayan şeydir. WeakKeyDictionary kullanılıyor ki
#: biten bir oturumun sayacı, süreç boyunca birikmek yerine kuyruğuyla
#: birlikte serbest bırakılsın.
_SEQUENCE_COUNTERS: "weakref.WeakKeyDictionary[Any, int]" = weakref.WeakKeyDictionary()


def _next_seq(queue: Any) -> int:
    """Belirli bir ilerleme kuyruğu için bir sonraki monoton sıra numarasını döndürür."""
    current = _SEQUENCE_COUNTERS.get(queue, 0) + 1
    _SEQUENCE_COUNTERS[queue] = current
    return current


def get_status_queue(config: Optional[RunnableConfig]) -> Any:
    """Bir config'e bağlı ilerleme kuyruğunu, varsa döndürür.

    Args:
        config: LangGraph çalıştırılabilir config'i.

    Returns:
        Çağıranın sağladığı ``asyncio.Queue``, ya da None.
    """
    if not config:
        return None
    return (config.get("configurable") or {}).get(STATUS_QUEUE_KEY)


def child_config(config: Optional[RunnableConfig]) -> RunnableConfig:
    """Bir alt grafik çağrısına geçirilecek config'i türetir.

    İlerleme kuyruğunu ve izleme (tracing) callback'lerini iç içe grafiklere
    taşır. Hiçbir şey geçirmemek (önceki davranış) her ikisini de sessizce
    devre dışı bırakıyordu.

    Args:
        config: Üst düğümün config'i.

    Returns:
        ``sub_graph.ainvoke(..., config=...)``'a güvenle verilebilecek bir config.
    """
    if not config:
        return {}
    child: RunnableConfig = {"configurable": dict(config.get("configurable") or {})}
    callbacks = config.get("callbacks")
    if callbacks:
        child["callbacks"] = callbacks
    return child


async def emit(config: Optional[RunnableConfig], payload: Mapping[str, Any]) -> None:
    """Tek bir ilerleme olayı yayınlar; tüketici yoksa görmezden gelir.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        payload: Olayın gövdesi.
    """
    queue = get_status_queue(config)
    if queue is None:
        return
    try:
        enriched = dict(payload)
        enriched["seq"] = _next_seq(queue)
        await queue.put(enriched)
    except Exception:
        logger.warning("Could not publish progress event %s", payload.get("event"))


async def emit_node_start(
    config: Optional[RunnableConfig],
    node: str,
    label: str,
    message: str,
    meta: Optional[Mapping[str, Any]] = None,
) -> None:
    """Bir düğümün başladığını bildirir.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        node: Makine tarafından okunabilir düğüm tanımlayıcısı.
        label: Türkçe görünen etiket.
        message: UI için Türkçe durum satırı.
        meta: Sabit olay şekline uymayan isteğe bağlı ek alanlar (örn. bir
            taslak revizyonunda ``{"attempt": 2}``). İkinci bir taslak
            denemesi aynı ``"draft"`` düğüm id'sini yeniden kullanır ve
            altında tekrar akış yapar, bu yüzden frontend her
            ``node_start``'ta -- yalnızca ilkinde değil -- devam eden
            ``streamingText``'i temizler; iki taslağı birbirine eklemek
            yerine bunu güvenli kılan şey budur.
    """
    await emit(
        config,
        {
            "event": "node_start",
            "node": node,
            "label": label,
            "message": message,
            "meta": dict(meta) if meta else {},
        },
    )


async def emit_node_end(
    config: Optional[RunnableConfig],
    node: str,
    label: str,
    message: str,
    result: Any = None,
    meta: Optional[Mapping[str, Any]] = None,
) -> None:
    """Bir düğümün sonucuyla birlikte tamamlandığını bildirir.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        node: Makine tarafından okunabilir düğüm tanımlayıcısı.
        label: Türkçe görünen etiket.
        message: UI için Türkçe durum satırı.
        result: İstemci tarafından render edilecek düğüm çıktısı.
        meta: İsteğe bağlı ek alanlar; bkz. :func:`emit_node_start`.
    """
    await emit(
        config,
        {
            "event": "node_end",
            "node": node,
            "label": label,
            "message": message,
            "result": result if result is not None else {},
            "meta": dict(meta) if meta else {},
        },
    )


async def emit_token(config: Optional[RunnableConfig], node: str, text: str) -> None:
    """Canlı render için üretilen bir metin parçası yayınlar.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        node: Metni üreten düğüm.
        text: Parça (chunk).
    """
    await emit(config, {"event": "token", "node": node, "text": text})


#: :func:`emit_reply_stream` içindeki parça başına karakter sayısı. Hâlâ
#: canlı bir akış gibi okunacak kadar küçük, uzun bir taslağın yüzlerce
#: kuyruk gidiş-dönüşü harcamasını önleyecek kadar büyük.
_REPLY_STREAM_CHUNK_SIZE = 48


async def emit_reply_stream(
    queue: Any, text: str, *, node: str = "reply", chunk_size: int = _REPLY_STREAM_CHUNK_SIZE
) -> None:
    """Doğrulanmış nihai yanıtı istemciye parça parça akıtır.

    Draft/assist/revise doğrulama düzenlemesinden sonra bir ``token``
    olayının yayınlandığı *tek* yer burasıdır (bkz. ``draft_graph.writer_node``,
    ``planning_graph._run_assist``, ``revise_graph.rewrite_node`` -- hiçbiri
    artık ``emit_token`` çağırmıyor) -- ``app.domains.chat.chat_service.
    _enqueue_terminal_event``'ten, ``final_result``'ün taşıyacağı tam metin
    üzerinden bir kez çağrılır. Bu, "sohbet balonuna akıtılan şey" ile
    "turun nihai yanıtı"nın kural gereği değil, yapı gereği aynı metin
    olmasını sağlar: bu çağrının yukarısındaki hiçbir şey istemcinin token
    işleyicisine ulaşmaz, yani bir guardrail/doğrulama geçişinin kullanıcının
    zaten gördüğü şeyi sessizce değiştirmiş olması diye bir durum söz konusu
    olamaz.

    Bir ``RunnableConfig`` değil, doğrudan ham kuyruğu alır -- bu fonksiyon
    grafik çağrısı zaten döndükten sonra çalışır, dolayısıyla kapsamda bir
    düğüm config'i yoktur, yalnızca ``status_queue`` olarak ona bağlanmış
    olan aynı ``asyncio.Queue`` vardır.

    Args:
        queue: SSE ilerleme kuyruğu, ya da None (:func:`emit` ile aynı
            şekilde no-op).
        text: Doğrulanmış nihai yanıt.
        node: Her token olayında taşınan düğüm id'si -- yalnızca bilgi
            amaçlı; artık hiçbir düğüm kendi ``node_start``'ında canlı bir
            önizlemeyi temizlemiyor (yukarıda akış yapacak bir şey kalmadı).
        chunk_size: Yayınlanan parça başına karakter sayısı.
    """
    if queue is None or not text:
        return
    try:
        for start in range(0, len(text), chunk_size):
            await queue.put(
                {
                    "event": "token",
                    "node": node,
                    "text": text[start : start + chunk_size],
                    "seq": _next_seq(queue),
                }
            )
    except Exception:
        logger.warning("Could not stream final reply")


async def emit_node_error(
    config: Optional[RunnableConfig],
    node: str,
    label: str,
    message: str,
    *,
    fatal: bool = True,
    detail: str = "",
) -> None:
    """Bir düğümün başarısız olduğunu veya bozulduğunu bildirir.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        node: Makine tarafından okunabilir düğüm tanımlayıcısı.
        label: Türkçe görünen etiket.
        message: UI için Türkçe durum satırı.
        fatal: Bozulmuş ama devam eden bir sonuç için False (örn. taslak
            akışını durdurmayan judge çağrısı hatası), çalıştırmayı bitiren
            bir hata için True. Frontend düğümü her iki durumda da kırmızıya
            döner, ama fatal olmayan bir hata, çalıştırmanın geri kalanını
            bir çökme gibi değil okunabilir tutar.
        detail: İsteğe bağlı teknik detay, varsayılan olarak gösterilmez.
    """
    await emit(
        config,
        {
            "event": "node_error",
            "node": node,
            "label": label,
            "message": message,
            "fatal": fatal,
            "detail": detail,
        },
    )


async def emit_node_skipped(
    config: Optional[RunnableConfig], node: str, label: str, reason: str
) -> None:
    """İhtiyaç duyduğu bir bağımlılık başarısız olduğu için bir adımın
    atlandığını bildirir.

    Bu olmadan, bağımlılığı başarısız olan bir adım (örn. yönlendireceği
    taslak henüz başarısız olduğunda çalışan routing) sessizce boş girdi
    üzerinde yine de çalışıyordu ve ortaya çıkan insan onayı sonucu, gerçek
    bir routing kararından görsel olarak ayırt edilemiyordu. Adımı atlamak
    ve nedenini söylemek hem davranışı hem de görünürlüğünü düzeltir.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        node: Makine tarafından okunabilir düğüm tanımlayıcısı.
        label: Türkçe görünen etiket.
        reason: Adımın neden çalışmadığına dair Türkçe açıklama.
    """
    await emit(
        config,
        {"event": "node_skipped", "node": node, "label": label, "reason": reason},
    )


async def emit_interrupt(
    config: Optional[RunnableConfig],
    *,
    kind: str,
    interrupt_id: str,
    payload: Mapping[str, Any],
) -> None:
    """Çalıştırmanın durakladığını, bir insan yanıtı beklediğini bildirir.

    ``interrupt()`` çağıran bir düğüm, devam ettirildiğinde bu emit dahil o
    çağrıdan önceki her şeyi yeniden çalıştırır -- bu yüzden çağıranlar
    ``interrupt_id``'yi state'ten deterministik olarak türetir (asla yeni
    üretilmiş bir UUID'den değil) ve frontend her yayını yeni bir interrupt
    olarak ele almak yerine bu id üzerinden tekilleştirir.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        kind: ``"missing_information"``, ``"writing_brief"``,
            ``"artifact_transfer_confirm"`` veya
            ``"artifact_transfer_disambiguate"``.
        interrupt_id: Bu interrupt oluşumu için sabit id.
        payload: İnsanın yanıtlaması için gereken veri -- sorular, taslak
            metin, doğrulama/judge sonuçları.
    """
    await emit(
        config,
        {
            "event": "interrupt",
            "kind": kind,
            "interrupt_id": interrupt_id,
            "payload": dict(payload),
        },
    )


async def emit_tool_call(
    config: Optional[RunnableConfig], node: str, tool: str, args: Mapping[str, Any]
) -> None:
    """Asistan ajanının bu tur için bir araç çağırdığını yayınlar.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        node: Araç döngüsünü çalıştıran düğüm (``"assist"``).
        tool: Aracın ``ToolSpec``'inde belirtildiği şekliyle adı.
        args: Modelin sağladığı argümanlar.
    """
    await emit(
        config,
        {"event": "tool_call", "node": node, "tool": tool, "args": dict(args)},
    )


async def emit_guardrail_event(
    config: Optional[RunnableConfig],
    *,
    stage: str,
    kind: str,
    decision: str,
    reasons: Optional[list[str]] = None,
) -> None:
    """Bir guardrail kararını yayınlar, böylece frontend onu canlı olarak
    rozetleyebilir.

    Yalnızca gerçekten bir şey yapan bir karar için çağrılır -- flagged,
    blocked, redacted, needs_review -- UI'nin gösterecek bir şeyi olmadığı
    rutin bir "passed" için asla çağrılmaz. Bunu yayınlayan düğüm zaten
    Langfuse callback'ini taşıyan bir grafik çağrısı içinde çalışır (bkz.
    ``build_trace_config``), bu yüzden karar burada ekstra bir bağlantı
    kurulmadan o trace'e düşer; ``GuardrailEventModel``
    (``app.observability.guardrail_recorder``) kalıcı denetim kaydı olmaya
    devam eder, bu yalnızca canlı/UI tarafıdır.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        stage: "input" veya "output".
        kind: Bkz. ``guardrail_recorder.record_event``.
        decision: "flagged" | "blocked" | "redacted" | "needs_review".
        reasons: Kısa, insan tarafından okunabilir nedenler -- kararı
            tetikleyen ham hassas değer asla değil.
    """
    await emit(
        config,
        {
            "event": "guardrail",
            "stage": stage,
            "kind": kind,
            "decision": decision,
            "reasons": list(reasons or []),
        },
    )


async def emit_notice(
    config: Optional[RunnableConfig],
    *,
    node: str,
    title: str,
    message: str,
    level: str = "info",
) -> None:
    """Kendi sohbet turu olarak durdurmayan, bilgilendirici bir mesaj
    yayınlar.

    :func:`emit_interrupt`'ın durdurmayan karşılığı. Yüzeye çıkarılması
    gereken ama çalıştırmayı asla kapı gibi engellememesi gereken bir
    bulgu için kullanılır -- talimat/mevzuat çatışması bunun motive edici
    örneğidir (bkz. ``app.ai.revision.conflict``'in ``applied_anyway``
    değişmezi: düzenleme zaten gerçekleşti, bu yalnızca kullanıcıya
    içindeki bir kırışıklığı bildiriyor). Frontend bunu akışa akıtılan
    yanıta katmak yerine kendi asistan mesajı olarak render eder, böylece
    1. tur hakkındaki bir uyarı, ham token akışının yapacağı gibi 2. turun
    metnine asla eklenmez.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        node: Bu bildirimi hangi düğümün yükselttiği (örn. ``"revise_audit"``).
        title: Kısa Türkçe başlık.
        message: Bildirimin tam Türkçe metni.
        level: Önem derecesi; bugün için yalnızca ``"info"`` mevcut.
    """
    await emit(
        config,
        {
            "event": "notice",
            "node": node,
            "level": level,
            "title": title,
            "message": message,
        },
    )


async def emit_question(
    config: Optional[RunnableConfig],
    *,
    node: str,
    question: str,
    options: list[dict[str, str]],
    allow_free_text: bool = True,
    questions: Optional[list[dict[str, Any]]] = None,
) -> None:
    """Çalıştırmanın ihtiyaç duyduğu bir kararı, tıklanabilir seçenekler
    olarak sunarak yayınlar.

    :func:`emit_interrupt`'ın aksine, bu asla ``interrupt()`` üzerinden bir
    LangGraph çalıştırmasını duraklatmaz -- clarify adımı kendi turunu zaten
    deterministik olarak bitirir ve yalnızca kullanıcının bir sonraki
    mesajını bekler; bu mesaj da
    ``app.ai.workflows.planner._try_resolve_pending_clarification``
    tarafından aynı seçeneklere göre çözülür. Bu olay, istemciye yalnızca
    kullanıcının bir etiketi harfiyen yeniden yazmasını beklemek yerine
    bunları bir kart olarak render etmesini söyler.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        node: Bu soruyu hangi düğümün yükselttiği (bugün için ``"clarify"``).
        question: Türkçe soru metni.
        options: ``[{"value": ..., "label": ...}, ...]``.
        allow_free_text: Yazılmış bir yanıtın da bu soruyu çözebilip
            çözemeyeceği. Bugün için her zaman True.
        questions: Bu olayın taşıdığı, kanonik ``PromptQuestion`` şeklindeki
            liste. Bugün her çağıran tarafından atlanır (``_step_clarify``
            her zaman yalnızca tek bir soru sorar) -- yokluğunda,
            eski ve yeni istemcilerin her iki durumda da aynı içeriği
            görmesi için ``question``/``options``/``allow_free_text``'ten
            tek elemanlı bir liste oluşturulur.
    """
    await emit(
        config,
        {
            "event": "question",
            "node": node,
            "question": question,
            "options": list(options),
            "allow_free_text": allow_free_text,
            "questions": questions
            if questions is not None
            else [
                {
                    "key": node,
                    "question": question,
                    "options": list(options),
                    "allow_free_text": allow_free_text,
                    "multi_select": False,
                    "required": True,
                }
            ],
        },
    )


async def emit_partial(
    config: Optional[RunnableConfig], key: str, value: Any
) -> None:
    """UI'nin çalıştırma bitmeden render edebileceği ara bir sonucu yayınlar.

    İstemcinin, gerçek zamanın çoğunun harcandığı taslağı beklemek yerine,
    sınıflandırmayı var olduğu an göstermesini sağlar.

    Args:
        config: Düğümün çalıştırılabilir config'i.
        key: Sonuç tanımlayıcısı (örn. ``"classification"``).
        value: Kısmi payload.
    """
    await emit(config, {"event": "partial_result", "key": key, "value": value})
