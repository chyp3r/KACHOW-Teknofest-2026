"""Executor için deklaratif adım bağımlılıkları ve hazırlık (readiness) hesaplaması.

Eski `_STEP_DEPENDENCIES`'i (yalnızca `draft`/`routing`'i kapsayan, sadece
skip-vs-run kararı için başvurulan 2 girişli bir dict) genelleştirerek,
gönderilebilir (dispatchable) her adım adını kapsayan bir kataloğa dönüştürür
ve `current_step_idx` tabanlı dizi indekslemesini `state` üzerinde bir
hazırlık hesaplamasıyla değiştirir. Bu, dinamik bir executor'ın ihtiyaç
duyduğu temeldir -- gerçi bugün `PLAN_BY_INTENT`'in ürettiği her plan katı bir
doğrusal zincirdir ve "konuma göre sıradaki" ile "hazırlığa göre sıradaki"
arasındaki farkı hiçbir zaman gerçekten devreye sokmaz.
"""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class StepSpec:
    """Gönderilebilir tek bir adımın zamanlama (scheduling) meta verisi.

    Attributes:
        name: Adım adı; `planning_graph.py` içindeki bir `STEP_RUNNERS`
            anahtarıyla eşleşir.
        depends_on: Bu adımın uygun sayılabilmesi için -- sonucu ne olursa
            olsun: başarı, hata veya atlama -- önce çalışmış olması gereken
            diğer adım adları. Yalnızca mevcut turun planının da *parçası*
            olan bağımlılıklar geçerlidir: `assist`'in planı asla
            `classification` içermez, dolayısıyla `rag`'in ona bildirilen
            bağımlılığı orada bir hiçtir (no-op).
        parallel_safe: Bu adımın, aynı turda hazır olan başka bir
            `parallel_safe` adımla eşzamanlı çalışabilip çalışamayacağı.
            Bugün hiçbir adım `True` değil -- neden olduğu için
            `ready_steps`'in docstring'ine bakın.
    """

    name: str
    depends_on: tuple[str, ...] = ()
    parallel_safe: bool = False


#: `STEP_RUNNERS`'ın gönderebileceği her ad için bir giriş, ve `PLAN_BY_INTENT`
#: kombinasyonlarının gerçekten üretebileceği her ad için bir giriş. Burada
#: eskiden bağımsız bir `rag` adımı da tanımlıydı, ama hiçbir plan onu
#: içermedi -- classification alt-grafiği doküman için mevzuatı zaten
#: getiriyor ve `assist` adımının `search_legislation` aracı gerisini
#: karşılıyor -- yani hiç gönderilmeyen, "tutarlılık için" tutulan ölü
#: ağırlıktı. Bırakılmak yerine kaldırıldı: erişilemez bir `STEP_SPECS`
#: girişi, tam olarak `PLAN_BY_INTENT`'in üretebileceklerinden sessizce
#: sapan türden bir durumdur.
STEP_SPECS: dict[str, StepSpec] = {
    "classification": StepSpec(name="classification"),
    #: Deterministik, LLM kullanmıyor -- bkz. app.ai.workflows.writing_brief.
    #: Classification'dan sonra çalışır, böylece bir doküman-yanıt turunun
    #: rol-tersine çevirme (role-inversion) kuralı, karşılaştıracağı
    #: fields.gonderen_kurum/muhatap değerlerine sahip olur.
    "brief": StepSpec(name="brief", depends_on=("classification",)),
    "draft": StepSpec(name="draft", depends_on=("classification", "brief")),
    "routing": StepSpec(name="routing", depends_on=("draft",)),
    "assist": StepSpec(name="assist"),
    #: "classification"'a bağımlılık yok: revise, SessionFocus.active_draft
    #: üzerinde çalışır, asla yeniden sınıflandırma yapmaz. Bkz.
    #: app.ai.workflows.revise.
    "revise": StepSpec(name="revise"),
    #: Deterministik, LLM kullanmıyor -- bkz. planner._build_clarify_decision.
    "clarify": StepSpec(name="clarify"),
    #: Bu da deterministik ve LLM kullanmıyor: `app.ai.workflows.scope.
    #: CAPABILITY_MANIFEST`'i render eder ve turu sonlandırır. Her zaman
    #: kendi planındaki tek adımdır, dolayısıyla bağımlı olacağı bir şey yok.
    "refuse": StepSpec(name="refuse"),
    #: Planner tarafından hiç üretilmiyor -- assist adımının kendi
    #: `propose_transfer` araç çağrısı (bkz. `app.ai.tools.transfer_tools`)
    #: bekleyen bir teklif ürettiğinde ve yalnızca `transfer_gate_node`
    #: intent'i `CONFIRMED`'e taşıdıktan sonra, `planning_graph._step_assist`
    #: tarafından `plan_steps`'e dinamik olarak eklenir. Burada tanımlanacak
    #: bir bağımlılık yok: yapısı gereği yalnızca (araç içinde deterministik
    #: olarak, asla `interrupt()` yoluyla değil -- bu duraklamanın neden
    #: kendi grafik node'unda yaşadığı için bkz.
    #: `planning_graph.transfer_gate_node`'ın docstring'i) zaten bir
    #: alıcı/artifact çözümlemiş bir `transfer_resolve_result` ile birlikte
    #: `plan_steps`'e eklenir.
    "transfer_execute": StepSpec(name="transfer_execute"),
}


def _has_run(state: Mapping[str, Any], name: str) -> bool:
    """`state` içinde `name`'in sonucunun boş olmayıp olmadığı.

    `planning_node`, bir turun başında her `<step>_result` alanını anahtarı
    silmek yerine `{}`'e sıfırlar; bu yüzden sadece anahtarın varlığı, henüz
    çalışmamış bir adımı bu tur çalışmış olandan ayırt edemez -- truthiness
    (doğruluk değeri) edebilir, ve `_dependency_failed`'in çağıranlarının da
    aynı nedenle zaten dayandığı kontrol budur.
    """
    return bool(state.get(f"{name}_result"))


def ready_steps(
    plan_steps: list[str],
    state: Mapping[str, Any],
    specs: Mapping[str, StepSpec] = STEP_SPECS,
) -> list[str]:
    """`plan_steps` içinde henüz çalışmamış ve çalışmaya uygun olan adımlar.

    Uygunluk yalnızca "bu adımın plandaki bağımlılıkları, *herhangi bir*
    sonuçla çalışmış" anlamına gelir -- kasıtlı olarak bir bağımlılığın
    *başarılı olup olmadığını* kontrol etmez. Bir bağımlılığın hatasının,
    ona bağımlı adımı atlaması gerekip gerekmediği, `planning_graph.py`
    içindeki `_dependency_failed`'in işidir; bu liste üzerinden bir adım
    seçildikten sonra ayrıca değerlendirilir. İki kaygıyı ayırmak, bu
    fonksiyonu saf bir zamanlama sorusu olarak tutar.

    Bugün hiçbir `StepSpec` `parallel_safe=True` değil, çünkü gönderilebilir
    her adım bir noktada bir LLM çağrısına dokunuyor (hatta `classification`
    bile katmanlı bir model çağrısı yapıyor) -- bunlardan ikisini tek bir
    yerel Ollama örneğinde eşzamanlı çalıştırmak duvar-saati süresini
    kısaltmaz, aynı GPU/CPU'yu ikisi arasında böler. Bu bayrak ve üzerine
    kurulan çoklu-hazır yol, gelecekte gerçekten sadece I/O olan bir adım
    (bir önbellek okuması, deterministik bir kontrol) için var, şu haliyle
    `PLAN_BY_INTENT`'teki herhangi bir şey için değil.

    Args:
        plan_steps: Turun çözümlenmiş planı, `planner.py`'ın ürettiği sırada.
        state: Bu superstep'in başındaki haliyle grafik state'i.
        specs: Zamanlamanın yapılacağı katalog. Varsayılan olarak gerçek
            `STEP_SPECS`; bir testin, gerçek bir adım türü olmadan
            çoklu-`parallel_safe` dalını çalıştırabilmesi için
            değiştirilebilir.

    Returns:
        Hazır adım adları, `plan_steps` sırasında (stabil). Bugün başka bir
        adımla birlikte hazır olan hiçbir `parallel_safe` adım olmadığından,
        executor her zaman yalnızca ilkini alır ve eski katı konumsal sırayı
        birebir yeniden üretir.
    """
    ready = []
    for name in plan_steps:
        if _has_run(state, name):
            continue
        spec = specs.get(name, StepSpec(name=name))
        deps_in_plan = [dep for dep in spec.depends_on if dep in plan_steps]
        if any(not _has_run(state, dep) for dep in deps_in_plan):
            continue
        ready.append(name)
    return ready


def all_steps_settled(plan_steps: list[str], state: Mapping[str, Any]) -> bool:
    """`plan_steps` içindeki her adımın bu turda bir sonuç üretip üretmediği.

    Artık adımlama konumsal değil hazırlık-güdümlü olduğundan, eski
    `current_step_idx >= len(plan_steps)` sonlandırma kontrolünün yerini alır.
    """
    return all(_has_run(state, name) for name in plan_steps)
