import asyncio
import json
import logging
import re
import time
from typing import Any, Sequence, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.ai.adapters.company_adapter import AdapterProvider, CompanyAdapter
from app.ai.adapters.company_rules import CompanyRuleSet, RulesProvider
from app.ai.adapters.injection import format_adapter_block, format_rules_block
from app.ai.agents.judge import JudgeAgent
from app.ai.agents.reviser import ReviserAgent
from app.ai.agents.writer import WriterAgent
from app.ai.guardrails.injection import GuardrailViolation, assert_no_prompt_leak
from app.ai.guardrails.pii import find_pii, redact_pii
from app.ai.identity.company_profile import CompanyProfile, ProfileProvider
from app.ai.identity.injection import format_identity_brief_section
from app.ai.policy import get_policy
from app.ai.policy.budget import node_budget
from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.examples import ExampleRetriever
from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.revision.elision import detect_content_loss
from app.ai.verification import (
    DraftJudgeVerdict,
    InfoQuestion,
    UnsupportedClaim,
    build_missing_info_request,
    check_filler_sentences,
    check_meta_commentary,
    check_person_consistency,
    check_signature_block,
    fill_date_placeholders,
    judge_draft,
    merge_verdicts,
    normalize_role_placeholders,
    normalize_unfilled_markers,
    verify_draft,
)
from app.ai.verification.draft_verifier import LEGISLATION_PATTERN
from app.ai.workflows.attempt_tracking import best_of, recover_from_failed_attempt, snapshot_attempt
from app.ai.workflows.correspondence import (
    format_correspondence_profile,
    is_strict_sub_genre,
    resolve_correspondence_type,
)
from app.ai.workflows.events import (
    emit_node_end,
    emit_node_error,
    emit_node_skipped,
    emit_node_start,
    emit_partial,
)
from app.ai.workflows.resilience import IO_RETRY
from app.ai.workflows.writing_brief import format_writing_brief
from app.ai.reasoning_levels import ReasoningLevelPreset, get_reasoning_level_preset
from app.core.config import settings
from app.core.enums.reasoning_level import ReasoningLevel
from app.observability.ai_metrics import DRAFT_REVISIONS, DRAFT_SCORE, LLM_TOKENS, NODE_DURATION

logger = logging.getLogger(__name__)

#: "balanced" reasoning-level preset'i, bugünkü mevcut varsayılanları
#: olduğu gibi taşır (bkz. app.ai.reasoning_levels); bu iki sabiti
#: literal'leri tekrarlamak yerine ondan türetmek, "balanced bugünkü
#: davranışı birebir yeniden üretir" garantisini, zamanla birbirinden
#: sapabilecek bir şey yerine yapısal bir garantiye dönüştürür.
_BALANCED_PRESET = get_reasoning_level_preset(ReasoningLevel.BALANCED)

#: Bir taslak için üretim bütçesi. Antetli, gövdeli ve imza bloklu resmi
#: bir yazı 600-1200 token sürer; eski global tavan olan 1024, daha uzun
#: yazıları cümle ortasında kesiyordu.
DRAFT_MAX_TOKENS = _BALANCED_PRESET.draft_max_tokens

#: Bir ilk üretim artı en fazla bir revizyon. Her deneme tam bir yerel
#: üretimdir (~25-30sn); üçüncü bir deneme ~90sn'lik taslak gecikme
#: bütçesini aşar ve ikincisinin başaramadığı yerde nadiren başarır. "deep"
#: reasoning seviyesi, gecikmeyi ek bir onarım geçişiyle takas etmeye razı
#: çağıranlar için bu sınırı yükseltir -- bkz. app.ai.reasoning_levels.
MAX_DRAFT_ATTEMPTS = _BALANCED_PRESET.max_draft_attempts

#: Writer akış halindeyken istemciye gönderilen iki "draft" partial_result
#: önizlemesi arasındaki minimum büyüme (karakter cinsinden). 60-90sn'lik
#: bir üretim yine de yalnızca birkaç düzine kuyruk gidiş-dönüşüne mal
#: olacak kadar büyük, bekleme durumu arayüzünün (Faz B) ilk önizlemede
#: oturup kalmak yerine birkaç saniyede bir yeni bir şey göstermesine
#: yetecek kadar küçük.
_PARTIAL_PREVIEW_CHUNK_CHARS = 200


class DraftState(TypedDict, total=False):
    """Taslak oluşturma iş akışı için LangGraph durumu."""

    source_document: str
    classification: dict[str, Any]
    #: Bugünün tarihi (bkz. app.ai.workflows.dates.today_tr), graph
    #: çalışmadan önce çağıran tarafından bir kez çözümlenir ve içeride
    #: asla yeniden türetilmez -- writer'ın kendi "Tarih:" satırının her
    #: zaman kullanması gereken ve brief'e sorulmak yerine doğrudan
    #: enjekte edilen tek tarih değeri budur. Boş/yok olması hiçbir tarih
    #: yönlendirmesi olmamasına düşer (bunu geçirecek şekilde güncellenmemiş
    #: eski bir çağıran), çökmeye değil.
    today: str
    #: Kullanıcının kendi taslak talebi, orkestratör kalıp metniyle
    #: değiştirilmemiş -- bunun neden `instructions`'dan ayrı tutulması
    #: gerektiği için ``resolve_correspondence_type``'ın ``user_request``
    #: argümanına bakın.
    user_request: str
    correspondence_type: str
    correspondence_type_source: str
    #: Kullanıcı, dört spesifiye edilmiş CorrespondenceType değeri dışında
    #: belirli bir tür istediğinde ("itiraz dilekçesi") serbest metin tür
    #: etiketi. Temel bir tür için boş. Bkz.
    #: ``correspondence.resolve_correspondence_type``.
    correspondence_sub_genre: str
    context: str
    instructions: str
    #: Bu turun kendi `instructions`'ı artı önceki her kullanıcı turunun
    #: kendi mesaj metni ve bu oturumdaki her yerleşmiş yazım-briefi slot
    #: cevabı (bkz. `_build_instruction_haystack`) -- `verify_node`'un
    #: `verify_draft`'a `instructions=` olarak verdiği şey budur, böylece
    #: kullanıcının çok turlu bir müzakerenin *önceki* bir turunda verdiği
    #: bir isim/tarih/kurum, son mesajda birebir tekrarlanmadığı için
    #: dayanaksız bir `dayanaksiz_iddia` olarak puanlanmak yerine yine de
    #: kullanıcının kendi sözü olarak tanınır. Boşsa düz `instructions`'a
    #: geri döner (bunu doldurmak üzere henüz güncellenmemiş eski bir
    #: çağıran -- bkz. `app.ai.workflows.revise_graph`, sonraki bir fazda
    #: bağlanacak) böylece hiçbir şey "hiç talimat temellendirmesi yok"
    #: durumuna gerilemez.
    instruction_haystack: str
    draft: str
    previous_draft: str
    confidence_score: float
    combined_score: float
    requires_human_approval: bool
    requires_revision: bool
    evaluation_notes: str
    verification: dict[str, Any]
    judge: dict[str, Any]
    judge_available: bool
    repair_items: list[dict[str, Any]]
    pii_findings: list[dict[str, Any]]
    missing_information: list[dict[str, Any]]
    #: confidence_score'un arkasındaki tam, denetlenebilir kural dökümü --
    #: report'un kendi bulguları artı merge_verdicts'in kattığı her şey
    #: (PII, tahmin edilen yazışma türü, eksik mevzuat bağlamı, judge
    #: bulguları). Bkz. app.ai.verification.confidence_rules.
    applied_rules: list[dict[str, Any]]
    attempt_history: list[dict[str, Any]]
    #: Bu turda şimdiye kadar görülen en yüksek puanlı denemenin tam sonuç
    #: anlık görüntüsü (bkz. app.ai.workflows.attempt_tracking) -- taslağı
    #: *kötüleştiren* ya da tamamen çöken bir onarım geçişinin, önceki bir
    #: denemenin çoktan ürettiğinden daha kötü veya boş bir sonuç
    #: göndermesini engellemek için tutulur (C2, C3). İlk denemede yok.
    best_attempt: dict[str, Any]
    #: Yalnızca bir onarım geçişi çöktüğünde/zaman aşımına uğradığında ve
    #: writer_node tüm turu başarısız saymak yerine `best_attempt`'e geri
    #: döndüğünde ayarlanır (C3) -- route_after_writer'a bunun zaten tam
    #: doğrulanmış bir sonuç olduğunu, dolayısıyla "verify"den tekrar
    #: geçmek yerine doğrudan "end"e yönlendirmesi gerektiğini söyler.
    restored_from_best_attempt: bool
    status: str
    error: str
    attempts: int
    brief: str
    #: Taslak öncesi yazım-briefi geçidinden (bkz. app.ai.workflows.
    #: writing_brief) gelen nihai slot cevapları -- kim yazıyor, kime
    #: gidiyor, anlatım/kapanış. `_build_brief` tarafından `brief`'e
    #: (writer'ın gerçek prompt metni) işlenir; burada da dokunulmadan
    #: tutulur, böylece ortaya çıkan draft_result bunu SessionFocus.
    #: DraftVersion (bkz. planning_graph._draft_version_from_result) ve
    #: sonraki bir `revise` turu için taşır.
    writing_brief: dict[str, Any]
    #: Bu koşum için hız-kalite dengesi katmanı ("fast"/"balanced"/"deep");
    #: bkz. app.ai.reasoning_levels.get_reasoning_level_preset. Yok veya
    #: bilinmiyorsa "balanced"a çözümlenir, dolayısıyla bunu hiç
    #: ayarlamamış eski çağıranlar etkilenmez.
    reasoning_level: str
    #: Bu taslak için alınan few-shot stil örnekleri (bkz.
    #: retrieve_examples_node), her biri "text", "correspondence_type",
    #: "niyet", "kurum", "baslik" alanlı düz bir dict. İlk writer
    #: geçişinden önce bir kez ayarlanır ve revise_node tarafından
    #: dokunulmadan bırakılır, böylece bir onarım denemesi yeniden
    #: sorgulamak yerine orijinal taslakla aynı örnekleri görür. Alma
    #: devre dışıysa, hiçbir şey bulamazsa veya başarısız olursa boş
    #: (asla yok) -- few-shot bir bağımlılık değil, bir kalite artışıdır.
    style_examples: list[dict[str, Any]]
    #: Bu taslağın hangi kiracı için olduğu -- ``writer_node`` tarafından
    #: bu şirketin çalışma zamanı stil adaptörünü çözmek için okunur (Faz
    #: C2, bkz. ``create_draft_graph``'daki ``adapter_provider``). Yok/boş
    #: olması hiçbir adaptör yapılandırılmamış gibi davranır, asla hata
    #: vermez.
    company_id: str
    #: Çözümlenmiş adaptör (``CompanyAdapter.to_dict()``), ilk denemede
    #: ``writer_node`` tarafından bir kez ayarlanır ve taşınır, böylece
    #: ``verify_node`` ``preferred_examples``'ı ikinci kez yeniden
    #: çözümlemeden ``style_examples``'ın zaten geçtiği aynı
    #: ``ornek_sizintisi`` sızıntı kontrolüne katabilir.
    company_adapter: dict[str, Any]
    #: Çözümlenmiş zorunlu kural kümesi (``CompanyRuleSet.to_dict()``),
    #: ilk denemede ``writer_node`` tarafından bir kez ayarlanır ve
    #: taşınır, böylece ``verify_node`` yeniden çözümlemeden judge için
    #: aynı kurallar bloğunu render edebilir. Yok/boş olması hiçbir kural
    #: yapılandırılmamış gibi davranır, asla hata vermez.
    company_rules: dict[str, Any]
    #: Çözümlenmiş kimlik profili (``CompanyProfile.to_dict()``),
    #: ``validate_input_node`` tarafından bir kez ayarlanır (``display_
    #: name``/``letterhead``/``default_signer_title`` zaten ``brief``'in
    #: kendi "KURUM KİMLİĞİ" bölümüne işlenmiştir) ve taşınır, böylece
    #: ``verify_node`` aynı değerleri yeniden çözümlemeden ``verify_
    #: draft``'a ``trusted_facts`` olarak geçirebilir. Yok/boş olması
    #: hiçbir profil yapılandırılmamış gibi davranır, asla hata vermez.
    company_profile: dict[str, Any]
    #: Eklenen belgenin depolama yolu -- ``app.ai.tools.document_tools``'un
    #: ``search_document`` aracının, yükleme sırasında her parçanın
    #: etiketlendiği ``document_qa`` Qdrant koleksiyonu üzerinden kendi
    #: sorgusunu kapsadığı aynı id. Yok/boş olması tam olarak hiçbir belge
    #: eklenmemiş gibi davranır: alma atlanır, asla hata vermez.
    document_id: str
    #: Bu taslak için eklenen belgeden alınan birebir alıntılar (bkz.
    #: ``retrieve_source_chunks_node``), her biri "text" ve "metadata"
    #: alanlı düz bir dict. Writer, belgenin kısa AI tarafından üretilmiş
    #: özetini zaten ``_build_brief``'in 2. bölümünden görür -- bunlar
    #: bunun yerine kaynağın kendi sözleridir, böylece bir taslak özetin
    #: kısalttığı belirli bir rakamı, maddeyi veya ismi alıntılayabilir.
    #: İlk writer geçişinden önce bir kez ayarlanır ve revise_node
    #: tarafından dokunulmadan bırakılır, ``style_examples`` ile aynı
    #: yaşam döngüsü. Alma devre dışıysa, hiçbir belge eklenmemişse,
    #: hiçbir şey bulamazsa veya başarısız olursa boş (asla yok) --
    #: temellendirme kalitesidir, taslak turunun başarısız olabileceği
    #: bir bağımlılık asla değildir.
    source_chunks: list[dict[str, Any]]


def _format_classification(classification: dict[str, Any]) -> str:
    """Temellendirilmiş agent prompt'ları için analiz çıktısını serileştirir.

    Args:
        classification: Düz değerlerin yanı sıra LangChain Document'ları ve
            Pydantic modelleri içerebilen analiz sonucu.

    Returns:
        Düzgün biçimlendirilmiş JSON, ya da yapı serileştirmeye direnirse
        bir repr.
    """
    if not classification:
        return "Sınıflandırma bilgisi sağlanmadı."

    def _clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: _clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_clean(item) for item in value]
        if hasattr(value, "page_content") and hasattr(value, "metadata"):
            return {"page_content": value.page_content, "metadata": value.metadata}
        if hasattr(value, "model_dump"):
            return _clean(value.model_dump())
        return value

    cleaned = _clean(classification)
    try:
        return json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    except Exception:
        return str(cleaned)


def _coerce_fields(classification: dict[str, Any]) -> dict[str, Any]:
    """Çıkarılan başlık alanlarını düz bir dict olarak döndürür."""
    fields = classification.get("fields", {})
    if hasattr(fields, "model_dump"):
        return fields.model_dump()
    return fields if isinstance(fields, dict) else {}


def _format_entities(entities: Any) -> str:
    """Belge analizinin düz NER-tarzı varlık listesini brief için render eder.

    ``EvrakField.entities`` (kişi/kurum/tarih/tutar/ürün adları, bkz.
    ``app.ai.compliance.evrak_field``) belge analizi sırasında zaten
    çıkarılıyordu ama bu modül tarafından hiçbir zaman okunmuyordu -- "bu
    CV'de çalıştığı kurumları belirt" gibi bir istek, analiz adımının
    çoktan bulduğu işveren isimlerini görmenin bir yolunu bulamıyordu, bu
    yüzden writer bir ``[BİLGİ EKSİK: ...]`` yer tutucusu bırakıyor ve
    human gate, belgenin kendisinin zaten cevapladığı bir soruyu kullanıcıya
    soruyordu. Virgülle ayrılmış, numaralandırılmamış veya tiplendirilmemiş
    (kaynak liste varlık-başına bir kategori taşımıyor), bu yüzden writer
    kullanmadan önce yine de her ismi brief'in/RAG alıntılarının geri
    kalanıyla çapraz kontrol etmelidir -- bu bölüm nereye bakılacağına dair
    bir ipucudur, "yalnızca brief'te bulunan bilgileri kullan" temellendirme
    kuralının yerine geçmez.
    """
    if not isinstance(entities, (list, tuple)):
        return "(tespit edilmedi)"
    names = [str(entity).strip() for entity in entities if str(entity).strip()]
    return ", ".join(names) if names else "(tespit edilmedi)"


#: Bir kimlik-slotu sızıntısının (bkz.
#: `app.ai.verification.draft_verifier._check_identity_slot_leaks`), kural
#: id'sine göre hangi yer tutucuya dönüştüğü -- gerçek değer bilinmediğinde
#: `writer.md`'nin o slot için writer'a kullanmasını söylediği aynı yer
#: tutucu metin, böylece dönüştürülmüş bir sızıntı, akış aşağısındaki her
#: şey için (`build_missing_info_request`/`apply_answers`) sıradan
#: doldurulmamış bir alandan ayırt edilemez hale gelir.
_IDENTITY_LEAK_PLACEHOLDER: dict[str, str] = {
    "gonderen_muhatap_karisikligi": "[Gönderen kurumun adı]",
    "karsi_taraf_kimlik_sizintisi": "[İmzalayacak yetkilinin adı ve soyadı]",
}


def _convert_identity_leaks_to_placeholders(
    draft_text: str, identity_slot_leaks: list[UnsupportedClaim]
) -> tuple[str, bool]:
    """Birebir eşleşen bir kimlik-slotu sızıntısını, belirli bir kusur türü
    için ikinci bir çözümleme yolu inşa etmek yerine normal, sorulabilir bir
    yer tutucuya dönüştürür.

    Karşı tarafın kendi kurumunun/imza sahibinin bizim antetimizde veya
    imza bloğumuzda ortaya çıkması (bkz. ``draft_verifier.
    _check_identity_slot_leaks``), human gate'in zaten nasıl soracağını
    bildiği bir boşluk değildir -- bir yer tutucunun olması gereken yerde
    oturan *yanlış* bir değerdir. Sızan birebir metni, ``writer.md``'nin o
    slot için kullandığı aynı yer tutucuyla değiştirmek, mevcut eksik-bilgi
    geçidinin (``build_missing_info_request``/``apply_answers``) "bu yazıyı
    kimin adına, kime yazıyoruz?" diye tıpkı başka herhangi bir
    doldurulmamış alan hakkında sorduğu gibi sormasını sağlar -- ikinci,
    paralel bir çözümleme mekanizmasına hiçbir zaman gerek olmadı.

    Yalnızca sızan değerin **birebir** literal bir geçişini değiştirir (bu
    düzelttiği yaygın durum -- karşı tarafın adının birebir kopyalanması,
    tam olarak bildirilen hata). ``_check_identity_slot_leaks``'in yalnızca
    toleranslı token-örtüşmesi fallback'i üzerinden eşleştirdiği bir değerin
    güvenle değiştirilecek tek bir kesin aralığı yoktur; metinde bırakılır
    ve yine de puanı düşürür/onayı zorunlu kılar (bkz. ``confidence_rules.
    RULES``), yalnızca o belirli geçiş için etkileşimli bir soru olmadan.

    Args:
        draft_text: Dönüştürülecek taslak metni.
        identity_slot_leaks: Önceki bir ``verify_draft`` geçişinden
            ``VerificationReport.identity_slot_leaks``.

    Returns:
        (Muhtemelen dönüştürülmüş) taslak metni ve gerçekten bir şeyin
        değiştirilip değiştirilmediği -- çağıran yalnızca değiştirildiğinde
        yeniden doğrular.
    """
    changed = False
    for leak in identity_slot_leaks:
        placeholder = _IDENTITY_LEAK_PLACEHOLDER.get(leak.kind)
        if not placeholder or not leak.value:
            continue
        pattern = re.compile(re.escape(leak.value))
        if pattern.search(draft_text):
            draft_text = pattern.sub(placeholder, draft_text, count=1)
            changed = True
    return draft_text, changed


def _build_instruction_haystack(
    instructions: str,
    prior_user_turns: Sequence[str] = (),
    brief_answers: dict[str, Any] | None = None,
) -> str:
    """``verify_draft``'in yalnızca-talimattan-gelen-iddialar ayrımı için,
    bir iddianın meşru olarak "kullanıcının kendi sözü" sayılabileceği her
    şeyi bir araya getirir.

    Bundan önce ``verify_draft`` yalnızca mevcut turun kendi
    ``instructions``'ını görüyordu. Kullanıcının aynı çok turlu
    müzakerenin *önceki* bir turunda verdiği bir isim/tarih/kurum -- çok
    sıradan bir durum ("Berkay bey stajını bizim şirketimizde
    tamamlamış." bir turda, "şimdi cevap yazısı hazırla" bir sonrakinde)
    -- kullanıcı bu oturumda açıkça verdiği halde, salt son mesajda birebir
    tekrarlanmadığı için dayanaksız bir ``dayanaksiz_iddia`` (-12) olarak
    puanlanıyordu. Yerleşmiş yazım-briefi cevapları (bkz. ``app.ai.
    workflows.writing_brief`` -- insan onaylı, ``_build_brief``'in kendi 8.
    bölümüne göre) de aynı nedenle katılır: yazım-briefi kartına yazılan
    bir değer, sohbet kutusuna yazılan bir değer kadar güvenilirdir.

    Writer'ın kendi ``instructions`` prompt girdisinden bilerek ayrı
    tutulur -- writer, brief bölüm 7'de yine de yalnızca *bu turun*
    isteğini görmelidir; önceki turları oraya doldurmak "şimdi ne
    yapılacağı" ile "önce ne söylendiği"ni karıştırırdı, bu haystack'in
    sahip olmadığı bir sorun, çünkü asla bir prompt'a render edilmez,
    yalnızca karşılaştırılır.

    Args:
        instructions: Bu turun kendi taslak talimatları.
        prior_user_turns: Bu oturumdaki önceki turların kendi mesaj
            metinleri, en eskiden yeniye.
        brief_answers: Yerleşmiş yazım-briefi slot cevapları, varsa.

    Returns:
        Birleştirilmiş haystack metni.
    """
    parts = [instructions, *prior_user_turns]
    if brief_answers:
        parts.extend(str(value) for value in brief_answers.values() if value)
    return "\n".join(part for part in parts if part)


def _build_brief(
    classification: dict[str, Any],
    context: str,
    instructions: str,
    writing_brief: dict[str, Any] | None = None,
    today: str = "",
    profile: CompanyProfile | None = None,
) -> str:
    """Writer'a verilen temellendirme brief'ini oluşturur.

    Args:
        classification: Gelen belge için analiz çıktısı.
        context: Alınan mevzuat alıntıları.
        instructions: Kullanıcının taslak talimatları.
        writing_brief: Çözümlenmiş taslak-öncesi yazım-stili slotları (bkz.
            app.ai.workflows.writing_brief) -- kim yazıyor, kime gidiyor,
            anlatım/kapanış. Bölüm 7 olarak render edilir, insan onaylı
            kaynak bilgi olarak işaretlenir: "KACMAK ekibi olarak" hatasını
            çözen şey budur -- kullanıcının kendi metnindeki tek özel adın
            beyan edilmiş bir yönü yoktu ve writer onu bu brief'in tanımladığı
            tek slota (Muhatap) koydu.
        today: Bu taslağın yazıldığı tarih (bkz. app.ai.workflows.dates.
            today_tr), asla belgeden çıkarılan bir olgu değil. Bölüm 0
            olarak render edilir -- writer'ın kendi "Tarih:" satırı bunu
            bir yer tutucu bırakmak veya insana sormak yerine birebir
            kopyalamalıdır, çünkü bu asla eksik bilgi değildir, yalnızca
            daha önce kimsenin vermeyi düşünmediği bilgidir.
        profile: İsteği yapan şirketin kimlik profili (bkz. ``app.ai.
            identity.company_profile.CompanyProfile``), ya da None. Boş
            değilse bölüm 9 olarak render edilir (bkz. ``format_identity_
            brief_section``) -- bu, bu mektubu yazanın birincil, sistem
            tarafından doğrulanmış kimliğidir. ``app.ai.workflows.
            writing_brief.resolve_brief``, bölüm 8'in kendi "Yazan Taraf"
            slotunu çözerken zaten aynı profile (``app.ai.identity.parties.
            resolve_party_context`` üzerinden) başvurur, dolayısıyla bu
            render edildiğinde bölüm 8 normalde zaten aynı kimliği
            yansıtır -- bu bölüm bunu writer'ın antet/imza render'ı için
            açıkça yineler, yazım briefinin geçersiz kıldığı bir fallback
            olarak değil, writer'ın başlık/imza detayları için baktığı
            yerde belirtilen aynı olgu olarak.

    Returns:
        Brief metni.
    """
    fields = _coerce_fields(classification)
    missing = classification.get("missing_fields") or []
    missing_labels = ", ".join(
        item.get("label", "") for item in missing if isinstance(item, dict)
    )
    # Bölüm 9'a isimle yalnızca aşağıda gerçekten render edilecekse işaret
    # et (bkz. format_identity_brief_section'ın boşken "" döndürme kuralı)
    # -- bu brief'te var olmayan bir bölüme atıf yapmak sarkan bir işaretçi
    # olurdu ve ayrıca profil yapılandırılmış olsun olmasın "KURUM
    # KİMLİĞİ" literal string'ini her brief'e sızdırırdı.
    us_pointer = (
        "bölüm 9 KURUM KİMLİĞİ ve bölüm 8 Yazım Briefi'ndeki 'Yazan Taraf' satırıdır"
        if profile is not None and not profile.is_empty
        else "bölüm 8 Yazım Briefi'ndeki 'Yazan Taraf' satırıdır"
    )

    return (
        f"0. BUGÜNÜN TARİHİ: {today or '(bilinmiyor -- Tarih alanı için yer tutucu bırak)'}\n"
        f"   → Yanıtının KENDİ \"Tarih:\" alanına bu değeri AYNEN yaz. Bu bir çıkarım veya "
        f"tahmin değildir; sistem tarafından sağlanan gerçek tarihtir. Gelen evrakın tarihiyle "
        f"KARIŞTIRMA -- o bilgi yalnızca aşağıdaki bölüm 3'tedir ve İlgi satırı dışında hiçbir "
        f"yerde kullanılmaz.\n"
        f"1. Belge Türü: "
        f"{classification.get('document_type_label') or classification.get('document_type') or 'Belirtilmedi'}\n"
        f"2. Belge Özeti: {classification.get('summary') or 'Özet çıkarılamadı.'}\n"
        f"3. GELEN EVRAKIN KİMLİK BİLGİLERİ -- KARŞI TARAFA AİTTİR (bu bölümdeki ve bölüm "
        f"4'teki hiçbir isim/kurum/imza sahibi BİZ DEĞİLİZ -- biz kimiz sorusunun cevabı "
        f"yalnızca {us_pointer}. Buradaki sayı/"
        f"tarih, cevapladığın evrakın KENDİ sayı/tarihidir -- YALNIZCA aşağıdaki bir 'İlgi:' "
        f"satırında bu evraka atıf yapmak için kullanılabilir. SENİN YAZACAĞIN YANITIN KENDİ "
        f"Sayı/Tarih alanına ASLA yazma; o alan her zaman ilgili yer tutucudur, çünkü yanıtın "
        f"sayısını SENİN kurumunun evrak kaydı verir, gelen evrakın kaydı değil):\n"
        f"   - Gelen Evrakın Sayısı: {fields.get('sayi') or '(gelen evrakta belirtilmemiş)'}\n"
        f"   - Gelen Evrakın Tarihi: {fields.get('tarih') or '(gelen evrakta belirtilmemiş)'}\n"
        f"4. Diğer Çıkarılan Bilgiler (Konu dışındaki her alan KARŞI TARAFA AİTTİR -- gövde "
        f"metninde bir olgu olarak anılabilir, ama antet/imza bloğu/gönderen kurum alanlarına "
        f"ASLA yazılamaz; aşağıdaki parantez içi not bir alanın evrakta bulunmadığını belirtir "
        f"-- bu notu KENDİSİ bir değermiş gibi taslağa yazma, yanındaki yönergeye göre ilgili "
        f"yer tutucuyu bırak):\n"
        f"   - Konu: {fields.get('konu') or '(evrakta yok -- taslakta [Konu] yer tutucusunu bırak)'}\n"
        f"   - Muhatap (evrakın KENDİ muhatabı -- SENİN yanıtının muhatabı bölüm 8'deki "
        f"Yazım Briefi'nin kendi 'Muhatap' satırıdır, bu değer değil): "
        f"{fields.get('muhatap') or '(evrakta yok)'}\n"
        f"   - Gönderen Kurum (KARŞI TARAF -- bizim antetimiz asla bu olamaz): "
        f"{fields.get('gonderen_kurum') or '(evrakta belirtilmemiş)'}\n"
        f"   - İmza Sahibi (KARŞI TARAF -- bizim imza bloğumuz asla bu kişi olamaz): "
        f"{fields.get('imza_sahibi') or '(evrakta belirtilmemiş)'}"
        f" ({fields.get('imza_unvani') or '(unvan belirtilmemiş)'})\n"
        f"   - Belgede Geçen Diğer Önemli Varlıklar (KARŞI TARAFA AİT kişi, kurum, tarih, "
        f"tutar vb. -- örn. bir CV'deki çalışılan kurumlar; talimat bunlardan birine atıfta "
        f"bulunuyorsa burada ara, kullanıcıya SORMA -- ama bunları antet/imza/gönderen "
        f"kurum/muhatap alanlarımıza ASLA yazma, yalnızca gövdede olgu olarak kullan): "
        f"{_format_entities(classification.get('entities'))}\n"
        f"5. Evrakta Tespit Edilen Eksik Alanlar: {missing_labels or 'yok'}\n"
        f'6. Doğrulanmış Mevzuat Bağlamı:\n"""\n'
        f"{context or 'İlgili mevzuat bağlamı bulunamadı.'}\n\"\"\"\n"
        f"7. Kullanıcı Talebi ve Talimatlar: {instructions}\n"
        f"8. YAZIM BRİEFİ (İNSAN ONAYLI -- KAYNAK BİLGİ SAYILIR; 'Yazan Taraf' ve 'Muhatap' "
        f"satırları BİZ/KARŞI TARAF ayrımının kendisidir):\n"
        f"{format_writing_brief(writing_brief or {})}\n"
        f"{format_identity_brief_section(profile) if profile is not None else ''}"
    )


def _anti_fabrication_rules(is_other: bool) -> str:
    """Writer'ın kendi halüsinasyon-önleme kuralları, repair prompt'uyla
    paylaşılır.

    Bundan önce *ilk* writer geçişi bu kuralları taşıyordu (bkz.
    ``writer_node``'un kendi satır içi bloğu) ama ``_build_repair_prompt``
    taşımıyordu -- bir repair geçişi yalnızca kusur listesi dışındaki
    cümlelere dokunmayı yasaklıyordu, *düzelttiği* cümlelerin içinde yeni
    olgular uydurmayı hiç yasaklamıyordu. ``missing_structure`` kusurları
    özellikle yeni içerik yazmayı gerektirir (örn. "eksik Konu satırını
    ekle"), bu da hiç halüsinasyon-önleme kuralı olmayan bir reviser'ın
    tam olarak bir tahminle dolduracağı durumdur -- ve ``merge_verdicts``'in
    "en iyi deneme kazanır" çerçevesine göre (bkz. Faz 5), uydurulmuş bir
    tahmin, önceki bir denemenin doğru şekilde işaretlenmiş bir yer
    tutucusunu geçebilirdi.

    Args:
        is_other: Bunun, geleneksel kalıp metne izin verilen esnek
            ``other_official`` yazışma türü olup olmadığı.

    Returns:
        Kural madde listesi, writer'ın ilk geçişi ile sonraki her repair
        geçişi için özdeş.
    """
    if is_other:
        return (
            "- Yazışma türü 'Diğer resmî yazışma' olduğu için, brief'te bulunmayan "
            "tamamlayıcı bilgileri genel kurumsal bilgi birikiminle tamamlayabilirsin.\n"
            "- Resmî yazı standartlarına uygunluğu sağlamak için makul tamamlamalar yapabilirsin."
        )
    return (
        "- Yalnızca brief içindeki bilgilere ve mevzuat bağlamına sadık kal.\n"
        "- Gelen evrakta veya mevzuatta yer almayan hiçbir kişi, kurum, sayı, "
        "tarih veya olay uydurma. Tarih alanı bu kuralın istisnasıdır: brief'in "
        "\"0. BUGÜNÜN TARİHİ\" bölümündeki değeri her zaman kullan, uydurma.\n"
        "- Zorunlu olup brief'te bulunmayan bilgileri, kime ait olduğunu açıkça "
        "belirten köşeli parantezli bir yer tutucu olarak bırak (örn. "
        "'[Belge Sayısı]', '[İmzalayacak yetkilinin adı ve soyadı]') -- çıplak "
        "'Ad Soyad'/'Unvan' gibi kime ait olduğu belirsiz yer tutucular kullanma."
    )


def _build_repair_prompt(
    state: DraftState, adapter_block: str = "", rules_block: str = ""
) -> str:
    """Reviser'a verilen hedefli onarım prompt'unu oluşturur.

    Kusura göre koşullu bir dilim yerine tam brief'i gönderir. Brief zaten
    yoğunlaştırılmış bir temsildir (en fazla birkaç bin karakter -- writer
    ham ``source_document``'ı da hiç görmez, yalnızca bu brief'i görür), bu
    yüzden brief + önceki taslak + kusur listesi, çıktı için yer bırakarak
    modelin bağlam penceresi içinde rahatça kalır.

    Args:
        state: Önceki verify/revise geçişinden ``previous_draft`` ve
            ``repair_items`` taşıması beklenen mevcut taslak durumu.
        adapter_block: Render edilmiş şirket stil-tercihi bloğu (bkz.
            ``format_adapter_block``), ya da "".
        rules_block: Render edilmiş şirket zorunlu-kurallar bloğu (bkz.
            ``format_rules_block``), ya da "" -- stil bloğundan *önce*
            yerleştirilir, çünkü zorunlu bir kural öğrenilmiş bir stil
            tercihinin üzerindedir. Bir kural ihlali, bu prompt'a numaralı
            bir ``repair_items`` girdisi olarak ulaşan tam olarak bu türden
            bir kusurdur (bkz. ``llm_judge.REVISABLE_JUDGE_KINDS``), bu
            yüzden burada ``adapter_block``'un şirket-olguları eşdeğeridir
            de.

    Returns:
        Onarım prompt'u.
    """
    defects = state.get("repair_items") or []
    numbered = "\n".join(
        f"{index}. [{item.get('kind')}] {item.get('detail')}"
        + (f" -> Öneri: {item.get('suggested_fix')}" if item.get("suggested_fix") else "")
        for index, item in enumerate(defects, start=1)
    )
    # C16: katı bir alt-tür (itiraz dilekçesi, muvafakatname, taahhütname,
    # vekâletname, tutanak -- bkz. is_strict_sub_genre'ın kendi docstring'i),
    # türü other_official'a çözümlense bile halüsinasyon-önleme kurallarını
    # korur; yalnızca gerçekten genel bir "diğer resmî yazışma", "makul
    # geleneksel tamamlamalar yapabilirsin" esnekliğini alır.
    is_other = state.get("correspondence_type") == "other_official" and not is_strict_sub_genre(
        state.get("correspondence_sub_genre", "")
    )

    return (
        "### GÖREV:\n"
        "Aşağıdaki önceki taslağı, YALNIZCA numaralı kusur listesindeki maddeleri "
        "gidererek düzelt. Listede olmayan hiçbir cümleyi değiştirme.\n\n"
        f"### BRIEF BELGESİ:\n{state.get('brief', '')}\n\n"
        f"### YAZIŞMA TÜRÜ PROFİLİ:\n"
        f"{format_correspondence_profile(state.get('correspondence_type', 'other_official'), state.get('correspondence_sub_genre', ''))}\n\n"
        f"### ÖNCEKİ TASLAK:\n{state.get('previous_draft', '')}\n\n"
        f"### DÜZELTİLMESİ GEREKEN KUSURLAR:\n{numbered or '(kusur listesi boş)'}\n\n"
        "### KURALLAR:\n"
        f"{_anti_fabrication_rules(is_other)}\n"
        "- Yalnızca listelenen kusurları düzelt. Başka hiçbir cümleyi değiştirme. "
        "`[...]` yer tutucularını olduğu gibi bırak."
        f"{_format_style_examples(state.get('style_examples'))}"
        f"{rules_block}"
        f"{adapter_block}"
    )


def _format_style_examples(style_examples: list[dict[str, Any]] | None) -> str:
    """Alınan few-shot stil örneklerini bir prompt bloğu olarak render eder.

    Hiç örnek yoksa "" döndürür (boş bir bölüm değil) -- altında hiçbir şey
    olmayan bir "### ÜSLUP REFERANS ÖRNEKLERİ" başlığı, modele "bu sefer
    örnek alınamadı" değil, eksik-bağlam sinyali olarak okunurdu.

    Örnekler, ``ExampleRetriever`` aracılığıyla ``datasets/resmi_yazisma/
    ornekler.jsonl``'dan çekilen gerçek mektuplardır -- sentetik yer
    tutucular değil, gerçek kurum adları, tarihler ve dosya numaraları.
    Blok, modele bunların yalnızca bir stil referansı olduğunu, asla bir
    olgu kaynağı olmadığını açıkça söyler ve bu sınır, akış aşağısında
    ``draft_verifier``'ın ``ornek_sizintisi`` kontrolü (deterministik,
    yalnızca prompt'a dayalı değil) tarafından ikinci kez uygulanır, tam
    olarak tek başına bir prompt talimatının bir garanti olmaması nedeniyle.
    """
    if not style_examples:
        return ""

    blocks = "\n".join(
        f'<ornek tur="{example.get("correspondence_type", "")}" '
        f'niyet="{example.get("niyet", "")}">\n'
        f'{example.get("text", "")}\n'
        "</ornek>"
        for example in style_examples
    )

    return (
        "\n\n### ÜSLUP REFERANS ÖRNEKLERİ:\n"
        "Aşağıdaki metinler gerçek resmî yazılardan alınmış ÜSLUP VE YAPI örnekleridir. "
        "Bunlar brief'in bir parçası DEĞİLDİR ve doğrulanmış bilgi kaynağı DEĞİLDİR.\n\n"
        f"{blocks}\n\n"
        "KURAL (KRİTİK): Örneklerden YALNIZCA biçimi öğren -- alan sıralaması, ilgi satırı "
        "kalıbı, paragraf ritmi, kapanış ve imza bloğu düzeni, resmî üslup. Örneklerdeki "
        "hiçbir kurum adı, kişi adı, tarih, sayı, mevzuat atfı, tutar veya olayı taslağa "
        "TAŞIMA. Taslaktaki her somut bilgi yalnızca BRIEF BELGESİ'nden gelmelidir."
    )


def _format_source_chunks_section(chunks: list[dict[str, Any]]) -> str:
    """Render retrieved document excerpts as a brief section, appended to
    the already-built ``_build_brief`` text by ``retrieve_source_chunks_node``.

    Not folded into ``_build_brief`` itself: that function runs inside
    ``validate_input_node``, before any retrieval happens, so it has no
    chunks yet to render. Numbered "10." -- one past ``_build_brief``'s own
    0-8 *and* past ``format_identity_brief_section``'s section 9, appended
    right before this one -- rather than inserted positionally among them,
    for the same reason. Was previously also "9.", colliding with the
    identity section whenever both were present in the same brief.

    Returns "" (not an empty section) when there are no chunks -- same
    "absent signal, not an empty one" reasoning as ``_format_style_examples``.
    """
    if not chunks:
        return ""

    blocks = []
    for index, chunk in enumerate(chunks, start=1):
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        page = (chunk.get("metadata") or {}).get("page")
        page_note = f" (sayfa {page})" if page else ""
        blocks.append(f"[ALINTI {index}]{page_note}\n{text}")

    if not blocks:
        return ""

    return (
        "\n10. BELGEDEN İLGİLİ ALINTILAR (birebir alıntı -- özet değil; "
        "kaynak evrakın kendi metninden doğrudan aktarılmıştır. Bölüm 2'deki "
        "özetle çelişmez, onu somut ayrıntılarla tamamlar):\n"
        + "\n\n".join(blocks)
        + "\n"
    )


def _resolve_free_text_client(
    preset: ReasoningLevelPreset,
    llm_client: BaseLLMClient,
    fast_llm_client: BaseLLMClient | None,
) -> BaseLLMClient:
    """Pick the client that backs writer/reviser generation for a run.

    Module-level (rather than a closure inside ``create_draft_graph``) so it
    can be unit-tested and reasoned about independently of the compiled graph.
    Never introduces a third client: only ``fast_llm_client`` or
    ``llm_client``, the same two already handed to ``create_draft_graph``.
    """
    if preset.model_tier == "fast" and fast_llm_client is not None:
        return fast_llm_client
    return llm_client


def create_draft_graph(
    llm_client: BaseLLMClient,
    fast_llm_client: BaseLLMClient | None = None,
    example_retriever: ExampleRetriever | None = None,
    adapter_provider: AdapterProvider | None = None,
    profile_provider: ProfileProvider | None = None,
    rules_provider: RulesProvider | None = None,
    document_qa_retriever: HybridRetriever | None = None,
):
    """Create and compile the drafting workflow.

    Flow::

        START -> validate_input -+-> retrieve_examples -> retrieve_source_chunks -> writer -+-> verify -+-> revise -> writer
                                  \\-> END                                                     \\-> END     |-> END (needs_input)
                                                                                                            \\-> END

    The former single-pass "writer -> LLM editor" pipeline had no path back to
    the writer, so a low-scoring draft was only ever flagged, never repaired.
    ``verify`` now runs a hybrid gate -- the deterministic ``verify_draft``
    plus a fast-tier judge for what regex cannot see (request fit, arz/rica
    direction, register, muhatap consistency) -- and routes to a bounded
    ``revise -> writer`` loop when the defects found are the kind a targeted
    text edit can actually fix. Defects that aren't (an explicit placeholder
    the writer left because it doesn't know the value; a guessed
    correspondence type) go straight to human review or an information
    request instead of being retried into the same gap.

    Args:
        llm_client: The quality-tier LLM used by the writer and reviser.
        fast_llm_client: Optional fast-tier client for the judge. Falls back
            to ``llm_client`` when omitted.
        example_retriever: Optional few-shot style-example retriever (see
            ``retrieve_examples_node``). None reproduces pre-feature
            behaviour exactly -- the node short-circuits to zero examples
            without touching Qdrant.
        adapter_provider: Optional async callable resolving a company's
            runtime style adapter (Faz C2, see
            ``app.domains.companies.provider.get_company_adapter``) --
            injected the same way ``units_provider`` is on
            ``create_routing_graph``, so this module never imports
            ``app.domains`` directly. None reproduces pre-feature behaviour
            exactly (no adapter block, ever).
        profile_provider: Optional async callable resolving a company's
            identity profile (see
            ``app.domains.companies.provider.get_company_profile``) --
            injected the same way ``adapter_provider`` is. None reproduces
            pre-feature behaviour exactly (no "KURUM KİMLİĞİ" brief section,
            ever).
        rules_provider: Optional async callable resolving a company's
            mandatory drafting rules (see
            ``app.domains.companies.provider.get_company_rules``) --
            injected the same way ``adapter_provider`` is. A violation is
            fed to the judge (see ``judge_draft``'s ``company_rules_block``)
            and, when found, becomes a numbered ``repair_items`` entry the
            same ``verify -> revise`` loop already runs. None reproduces
            pre-feature behaviour exactly (no rules block, ever).
        document_qa_retriever: Optional retriever over the attached
            document's own chunks (see ``retrieve_source_chunks_node``),
            targeting the same ``document_qa`` Qdrant collection
            ``app.ai.tools.document_tools``'s ``search_document`` assistant
            tool already queries. None reproduces pre-feature behaviour
            exactly -- the writer sees only the document summary, as before.

    Returns:
        The compiled LangGraph workflow.
    """
    # Writer/reviser are *not* built once here: which client backs them
    # depends on the reasoning level of the run in progress (see writer_node),
    # so a fresh, cheap agent wrapper is constructed per call instead. The
    # judge always uses the fast tier regardless of level -- only whether it
    # runs at all varies (see verify_node) -- so it stays a single instance.
    judge_agent = JudgeAgent(fast_llm_client or llm_client)

    async def _resolve_profile(state: DraftState) -> CompanyProfile:
        """This company's identity profile, or an empty one when no
        ``profile_provider`` was configured, no ``company_id`` is on this
        turn's state, or resolution itself fails -- mirrors
        ``_resolve_adapter`` exactly."""
        company_id = state.get("company_id") or ""
        if not company_id or profile_provider is None:
            return CompanyProfile.empty(company_id)
        try:
            return await profile_provider(company_id)
        except Exception:
            logger.warning("Company profile resolution failed for %s", company_id, exc_info=True)
            return CompanyProfile.empty(company_id)

    async def validate_input_node(state: DraftState) -> dict[str, Any]:
        classification = state.get("classification") or {}
        instructions = (
            (state.get("instructions") or "").strip()
            or "Gelen evraka uygun resmî ve kurumsal bir yazışma taslağı oluştur."
        )
        # The user's own words, never the orchestrator's boilerplate framing
        # above -- resolve_correspondence_type matches against this, not
        # `instructions` (which always contains "yanıt taslağı oluştur" and
        # would otherwise resolve every chat-initiated draft to
        # RESPONSE_LETTER regardless of what was actually asked for).
        user_request = (state.get("user_request") or "").strip() or instructions
        source_document = (state.get("source_document") or "").strip()
        correspondence_type, type_source, sub_genre = resolve_correspondence_type(
            state.get("correspondence_type"),
            user_request,
            classification,
            has_source_document=bool(source_document),
        )

        if not source_document:
            error = "Gelen evrak içeriği sağlanmadığı için taslak oluşturulamadı."
            logger.error(error)
            return {
                "correspondence_type": correspondence_type.value,
                "correspondence_type_source": type_source,
                "correspondence_sub_genre": sub_genre,
                "draft": "",
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "FAILED",
                "error": error,
                "attempts": state.get("attempts", 0),
                "brief": "",
            }

        context = (state.get("context") or "").strip()
        profile = await _resolve_profile(state)
        return {
            "source_document": source_document,
            "classification": classification,
            "correspondence_type": correspondence_type.value,
            "correspondence_type_source": type_source,
            "correspondence_sub_genre": sub_genre,
            "context": context,
            "instructions": instructions,
            "brief": _build_brief(
                classification,
                context,
                instructions,
                state.get("writing_brief"),
                state.get("today", ""),
                profile,
            ),
            "company_profile": profile.to_dict(),
            "status": "IN_PROGRESS",
            "error": "",
            "attempts": state.get("attempts", 0),
        }

    def route_after_validation(state: DraftState) -> str:
        return "end" if state.get("status") == "FAILED" else "retrieve_examples"

    async def retrieve_examples_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        """Fetch few-shot style examples for the writer's first pass.

        Runs once per draft, before the writer/revise loop -- not inside
        ``node_timeout``'s decorator, deliberately: that decorator lets a
        timeout propagate out of the node and crash the whole graph run (see
        ``writer_node``'s own note on why it avoids it too), which is the
        opposite of what an optional quality boost should do on a slow
        Qdrant. The budget is still enforced, just with an inline
        ``asyncio.timeout`` whose failure path degrades to zero examples
        instead.
        """
        await emit_node_start(
            config,
            "examples",
            "Üslup Örnekleri",
            "Benzer resmî yazı örnekleri aranıyor...",
        )

        policy = get_policy().draft
        if example_retriever is None or not policy.style_examples_enabled:
            await emit_node_skipped(
                config, "examples", "Üslup Örnekleri", "Örnek getirimi devre dışı."
            )
            return {"style_examples": []}

        classification = state.get("classification") or {}
        fields = _coerce_fields(classification)
        query = " ".join(
            part
            for part in (
                fields.get("konu") or "",
                classification.get("summary") or "",
                state.get("instructions") or "",
            )
            if part
        ).strip()
        correspondence_type = state.get("correspondence_type") or "other_official"

        preset = get_reasoning_level_preset(state.get("reasoning_level"))
        budget = node_budget("retrieve_examples", preset.level)
        started = time.perf_counter()
        try:
            async with asyncio.timeout(budget):
                examples = await example_retriever.retrieve(
                    query=query,
                    correspondence_type=correspondence_type,
                    limit=policy.style_example_count,
                    char_budget=policy.style_example_char_budget,
                )
        except Exception:
            # ExampleRetriever.retrieve never raises on its own (it degrades
            # to []) -- the only thing this can catch is the asyncio.timeout
            # above firing. Caught broadly anyway so a future change to the
            # retriever can't turn an optional lookup into a failed draft.
            NODE_DURATION.labels(
                graph="node_budget", node="retrieve_examples", status="failed"
            ).observe(time.perf_counter() - started)
            logger.exception("Style example retrieval failed; continuing without examples.")
            await emit_node_error(
                config,
                "examples",
                "Üslup Örnekleri",
                "Örnek getirimi başarısız; taslak örneksiz devam ediyor.",
                fatal=False,
            )
            return {"style_examples": []}
        NODE_DURATION.labels(
            graph="node_budget", node="retrieve_examples", status="completed"
        ).observe(time.perf_counter() - started)

        style_examples = [
            {
                "text": example.text,
                "correspondence_type": example.correspondence_type,
                "niyet": example.niyet,
                "kurum": example.kurum,
                "baslik": example.baslik,
            }
            for example in examples
        ]
        await emit_node_end(
            config,
            "examples",
            "Üslup Örnekleri",
            f"{len(style_examples)} üslup örneği bulundu."
            if style_examples
            else "Uygun üslup örneği bulunamadı.",
            {"style_examples": style_examples},
        )
        return {"style_examples": style_examples}

    async def retrieve_source_chunks_node(
        state: DraftState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Fetch verbatim excerpts from the attached document for the writer.

        Same degrade-on-failure shape as ``retrieve_examples_node`` right
        above it (inline ``asyncio.timeout`` rather than the ``@node_timeout``
        decorator, broad ``except Exception``) -- for the same reason: an
        optional grounding boost must never be able to fail the whole draft.
        Runs after ``retrieve_examples`` rather than the writer's own quality
        boost, this is the writer's primary defense against fabricating
        details the summary alone doesn't carry, gated by its own
        ``DraftPolicy.source_chunks_enabled`` flag.
        """
        await emit_node_start(
            config,
            "source_chunks",
            "Kaynak Alıntılar",
            "İlgili belge bölümleri aranıyor...",
        )

        policy = get_policy().draft
        document_id = state.get("document_id")
        if document_qa_retriever is None or not policy.source_chunks_enabled or not document_id:
            await emit_node_skipped(
                config,
                "source_chunks",
                "Kaynak Alıntılar",
                "Belge alıntı getirimi devre dışı veya belge yüklü değil.",
            )
            return {"source_chunks": []}

        classification = state.get("classification") or {}
        fields = _coerce_fields(classification)
        query = " ".join(
            part
            for part in (
                state.get("user_request") or "",
                fields.get("konu") or "",
                classification.get("summary") or "",
            )
            if part
        ).strip()
        if not query:
            await emit_node_skipped(
                config, "source_chunks", "Kaynak Alıntılar", "Sorgulanacak metin yok."
            )
            return {"source_chunks": []}

        preset = get_reasoning_level_preset(state.get("reasoning_level"))
        budget = node_budget("retrieve_source_chunks", preset.level)
        started = time.perf_counter()
        try:
            async with asyncio.timeout(budget):
                documents = await document_qa_retriever.retrieve(
                    query,
                    limit=policy.source_chunk_count,
                    filter_dict={"storage_path": document_id},
                )
        except Exception:
            # HybridRetriever.retrieve never raises on its own (it degrades
            # to []) -- the only thing this can catch is the asyncio.timeout
            # above firing. Caught broadly anyway for the same reason
            # retrieve_examples_node is: a future change to the retriever
            # must never be able to turn an optional lookup into a failed
            # draft.
            NODE_DURATION.labels(
                graph="node_budget", node="retrieve_source_chunks", status="failed"
            ).observe(time.perf_counter() - started)
            logger.exception(
                "Source chunk retrieval failed; continuing with the summary alone."
            )
            await emit_node_error(
                config,
                "source_chunks",
                "Kaynak Alıntılar",
                "Belge alıntı getirimi başarısız; taslak yalnızca özetle devam ediyor.",
                fatal=False,
            )
            return {"source_chunks": []}
        NODE_DURATION.labels(
            graph="node_budget", node="retrieve_source_chunks", status="completed"
        ).observe(time.perf_counter() - started)

        trimmed = []
        used = 0
        for document in documents:
            content = getattr(document, "page_content", "") or ""
            if used + len(content) > policy.source_chunk_char_budget and trimmed:
                break
            trimmed.append(document)
            used += len(content)

        source_chunks = [
            {
                "text": getattr(document, "page_content", ""),
                "metadata": dict(getattr(document, "metadata", {}) or {}),
            }
            for document in trimmed
        ]
        chunks_section = _format_source_chunks_section(source_chunks)
        await emit_node_end(
            config,
            "source_chunks",
            "Kaynak Alıntılar",
            f"{len(source_chunks)} belge alıntısı bulundu."
            if source_chunks
            else "İlgili belge alıntısı bulunamadı.",
            {"source_chunks": source_chunks},
        )
        return {
            "source_chunks": source_chunks,
            "brief": state.get("brief", "") + chunks_section,
        }

    async def _resolve_adapter(state: DraftState) -> CompanyAdapter:
        """This company's runtime style adapter (Faz C2), or an empty one
        when no ``adapter_provider`` was configured, no ``company_id`` is on
        this turn's state, or resolution itself fails -- an adapter is a
        quality nicety, never a dependency the draft turn can fail on."""
        company_id = state.get("company_id") or ""
        if not company_id or adapter_provider is None:
            return CompanyAdapter.empty(company_id)
        try:
            return await adapter_provider(company_id)
        except Exception:
            logger.warning("Company adapter resolution failed for %s", company_id, exc_info=True)
            return CompanyAdapter.empty(company_id)

    async def _resolve_rules(state: DraftState) -> CompanyRuleSet:
        """This company's mandatory drafting rules, or an empty set when no
        ``rules_provider`` was configured, no ``company_id`` is on this
        turn's state, or resolution itself fails -- mirrors
        ``_resolve_adapter`` exactly."""
        company_id = state.get("company_id") or ""
        if not company_id or rules_provider is None:
            return CompanyRuleSet.empty(company_id)
        try:
            return await rules_provider(company_id)
        except Exception:
            logger.warning("Company rules resolution failed for %s", company_id, exc_info=True)
            return CompanyRuleSet.empty(company_id)

    async def writer_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        attempt_number = state.get("attempts", 0) + 1
        is_revision = bool(state.get("previous_draft"))
        preset = get_reasoning_level_preset(state.get("reasoning_level"))
        client = _resolve_free_text_client(preset, llm_client, fast_llm_client)
        meta = {
            "attempt": attempt_number,
            "reasoning_level": preset.level.value,
            "reasoning": preset.reasoning,
        }
        # Resolved once per attempt (Redis-cached in the real provider, see
        # app.domains.companies.provider.get_company_adapter, so repeat
        # attempts within one turn are cheap) rather than once per graph run:
        # a revision attempt still needs it for its own repair prompt below.
        adapter = await _resolve_adapter(state)
        adapter_block = format_adapter_block(adapter)
        company_ruleset = await _resolve_rules(state)
        rules_block = format_rules_block(company_ruleset)

        if is_revision:
            logger.info("Running Reviser Node (attempt %d)...", attempt_number)
            await emit_node_start(
                config,
                "draft",
                "Taslak Revizyonu",
                f"[Revizyon Ajanı] Taslak {attempt_number}. denemede düzeltiliyor...",
                meta=meta,
            )
            agent = ReviserAgent(client)
            prompt = _build_repair_prompt(state, adapter_block, rules_block)
            temperature = 0.2
        else:
            logger.info("Running Writer Node...")
            await emit_node_start(
                config,
                "draft",
                "Taslak Oluşturma",
                "[Yazar Ajanı] Taslak yazılıyor...",
                meta=meta,
            )

            # C16: see the identical guard in _build_repair_prompt.
            is_other = state.get("correspondence_type") == "other_official" and not is_strict_sub_genre(
                state.get("correspondence_sub_genre", "")
            )
            rules = _anti_fabrication_rules(is_other)

            prompt = (
                "### GÖREV:\n"
                "Aşağıdaki brief doğrultusunda resmî ve kurumsal bir Türkçe yazı taslağı yaz.\n\n"
                f"### BRIEF BELGESİ:\n{state['brief']}\n\n"
                f"### YAZIŞMA TÜRÜ PROFİLİ:\n"
                f"{format_correspondence_profile(state['correspondence_type'], state.get('correspondence_sub_genre', ''))}\n\n"
                f"### KURALLAR:\n{rules}"
                f"{_format_style_examples(state.get('style_examples'))}"
                f"{rules_block}"
                f"{adapter_block}"
            )
            agent = WriterAgent(client)
            temperature = 0.4

        # Called via .stream() rather than awaited whole -- not to forward
        # chunks live as chat tokens (the chat bubble still only ever shows
        # the validated final reply; see the module-level note on
        # final-reply streaming in app.domains.chat.chat_service), but
        # because the timeout below still needs partial text to hand back on
        # a budget overrun. The writer's budget is applied *inside* the node
        # rather than by the @node_timeout decorator. A decorator would raise
        # past the except clauses below and crash the draft graph; here a
        # timeout becomes a FAILED result carrying whatever was generated so
        # far, which is what the rest of the graph already knows how to
        # handle. This is also the first time the most expensive step in the
        # ~90s draft budget has had any node-level protection at all --
        # resilience.py has carried a "writer" entry since it was written,
        # and nothing ever read it.
        #
        # Chunks are buffered and never emitted as chat tokens: .stream()
        # cannot run BaseAgent.validators mid-stream (there is no single
        # response to check before tokens would be on screen), so nothing
        # reaches the *chat bubble* until assert_no_prompt_leak below has
        # cleared the accumulated text -- see
        # chat_service._enqueue_terminal_event, the one place a validated
        # final reply is streamed to the client. The waiting-state UI's
        # partial-draft preview (Faz B) is a narrower exception: every
        # _PARTIAL_PREVIEW_CHUNK_CHARS of growth, the buffer so far is run
        # through the *same* assert_no_prompt_leak check below and, only if
        # it passes, published as a "draft" partial_result -- a preview that
        # fails the check is silently skipped for that round rather than
        # shown, so the security invariant (nothing unvalidated reaches the
        # user) holds for the preview too, not just the final text.
        #
        # The preview is also PII-masked before publishing (redact_pii, same
        # deterministic TCKN/IBAN/phone/address scanner the output guardrail
        # uses -- see app.ai.guardrails.output_gate). This is deliberately
        # *not* applied to the final `draft` returned below: a legitimate
        # official letter (a personnel petition citing its own subject's
        # TCKN, say) is expected to carry PII, and that gets flagged for
        # human review via the `pii_bulgusu` confidence rule instead of
        # being silently rewritten. The preview has no such nuance to
        # preserve -- it is a disappearing progress indicator, never the
        # authoritative text -- so masking it unconditionally trades nothing
        # away and only shrinks the window a sensitive value is visible on
        # screen while the draft is still being written. No separate
        # sliding-window buffer is needed to catch a PII pattern split
        # across two raw generation chunks: `accumulated` below is always
        # the *entire* buffer re-scanned from the start, not an incremental
        # delta, so a pattern is only ever matched once it is fully present.
        budget = node_budget("writer", preset.level)
        chunks: list[str] = []
        last_preview_length = 0
        try:
            async with asyncio.timeout(budget):
                async for chunk in agent.stream(
                    messages=prompt,
                    temperature=temperature,
                    max_tokens=preset.draft_max_tokens,
                    reasoning=preset.reasoning,
                ):
                    chunks.append(chunk)
                    accumulated = "".join(chunks)
                    if len(accumulated) - last_preview_length >= _PARTIAL_PREVIEW_CHUNK_CHARS:
                        preview = accumulated.strip()
                        try:
                            assert_no_prompt_leak(preview)
                        except GuardrailViolation:
                            pass
                        else:
                            last_preview_length = len(accumulated)
                            masked_preview, _preview_pii = redact_pii(preview)
                            await emit_partial(
                                config,
                                "draft",
                                {"draft": masked_preview, "attempt": attempt_number},
                            )

            draft = "".join(chunks).strip()
            if not draft:
                raise ValueError("Ajan boş taslak döndürdü.")

            # .stream() cannot run BaseAgent.validators (there is no single
            # response to check before tokens are already emitted), so the
            # same guardrail runs here instead, against the accumulated text.
            # Fails closed: an apparent injection stops the run for human
            # review rather than being fed into an automatic revision pass.
            assert_no_prompt_leak(draft)

            LLM_TOKENS.labels(agent=agent.name, kind="prompt").inc(
                client.count_tokens(prompt)
            )
            LLM_TOKENS.labels(agent=agent.name, kind="completion").inc(
                client.count_tokens(draft)
            )

            return {
                "draft": draft,
                "attempts": attempt_number,
                "status": "IN_PROGRESS",
                "company_adapter": adapter.to_dict(),
                "company_rules": company_ruleset.to_dict(),
            }
        except TimeoutError:
            # Distinguished from a generic failure because str(TimeoutError())
            # is empty -- the user would have been shown "Taslak üretilemedi: ".
            logger.warning(
                "Writer node exceeded its %.0fs budget (attempt %d, level %s).",
                budget,
                attempt_number,
                preset.level.value,
            )
            if is_revision and state.get("best_attempt"):
                return recover_from_failed_attempt(
                    state["best_attempt"],
                    attempt_number,
                    f"Onarım denemesi {budget:.0f} saniyelik süre sınırını aştı; "
                    "önceki en iyi deneme korundu.",
                )
            return {
                "draft": "".join(chunks).strip(),
                "attempts": attempt_number,
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "FAILED",
                "error": (
                    f"Taslak üretimi {budget:.0f} saniyelik süre sınırını aştı; "
                    "daha düşük bir düşünme seviyesiyle yeniden deneyin."
                ),
            }
        except Exception as exc:
            logger.exception("Writer/Reviser node failed (attempt %d)", attempt_number)
            if is_revision and state.get("best_attempt"):
                return recover_from_failed_attempt(
                    state["best_attempt"],
                    attempt_number,
                    f"Onarım denemesi başarısız oldu ({exc}); önceki en iyi deneme korundu.",
                )
            return {
                "draft": "".join(chunks).strip(),
                "attempts": attempt_number,
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "FAILED",
                "error": f"Taslak üretilemedi: {exc}",
            }

    def route_after_writer(state: DraftState) -> str:
        # restored_from_best_attempt (C3): a repair pass crashed and
        # writer_node already fell back to a previous, fully-verified
        # attempt -- re-entering "verify" would re-check text that was
        # already checked (wasted work) and could itself crash again.
        if state.get("status") == "FAILED" or state.get("restored_from_best_attempt"):
            return "end"
        return "verify"

    async def verify_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        logger.info("Running Draft Verification Node...")
        await emit_node_start(
            config,
            "verify",
            "Taslak Doğrulama",
            "[Doğrulayıcı] Taslak kaynak evrak ve mevzuata karşı denetleniyor...",
        )

        # A prompt instruction is not a guarantee: the brief tells the
        # writer to leave a `[...]` placeholder for anything missing (see
        # `_build_brief`), but a smaller local model can still write a
        # header field's own line with a literal "bulunamadı"/"yok" value
        # instead. Normalized before anything else runs so the rest of this
        # node -- groundedness, the judge, missing-information detection --
        # all see the same, corrected text the human gate and the final
        # reply will show.
        draft_text, _ = normalize_unfilled_markers(state.get("draft", ""))
        # Same backstop role, one field earlier in the pipeline than
        # missing_info's [...] gate ever sees it -- the draft's own "Tarih:"
        # line must never reach a human as a question (see
        # app.ai.workflows.dates.today_tr's own docstring).
        draft_text, _ = fill_date_placeholders(draft_text, state.get("today", ""))
        sub_genre = state.get("correspondence_sub_genre", "")
        # Same backstop role again: writer.md tells the writer to name whose
        # a signature/institution placeholder is (see draft_graph.writer_node's
        # own rule), but a bare "[Ad Soyad]"/"[Unvan]"/"[İmza]"/"[Kurum Adı]"
        # is still possible -- fixed here so the human gate's own question
        # ("'Ad Soyad' bilgisi nedir?") never reaches the user unattributed.
        draft_text, _ = normalize_role_placeholders(
            draft_text, is_individual_petition="dilekçe" in sub_genre.lower()
        )
        classification = state.get("classification") or {}
        # C16: a strict sub-genre keeps forcing human approval on an
        # unsupported claim even though its type resolves to
        # other_official -- see is_strict_sub_genre's own docstring.
        strict = state.get("correspondence_type") != "other_official" or is_strict_sub_genre(
            sub_genre
        )
        preset = get_reasoning_level_preset(state.get("reasoning_level"))

        # The company adapter's own preferred_examples are real generated
        # text, same trust boundary as retrieved style_examples -- folded
        # into the same flat list so a leaked institution/date/name inside
        # one is caught by the exact same ornek_sizintisi check, no separate
        # detector needed (see CompanyAdapter's own docstring).
        adapter = CompanyAdapter.from_dict(
            state.get("company_id") or "", state.get("company_adapter")
        )
        profile = CompanyProfile.from_dict(
            state.get("company_id") or "", state.get("company_profile")
        )
        trusted_facts = [
            value
            for value in (
                profile.display_name,
                profile.short_name,
                profile.letterhead,
                profile.default_signer_title,
                profile.default_signer_name,
            )
            if value
        ]
        is_individual_petition = "dilekçe" in sub_genre.lower()
        style_example_texts = [
            example.get("text", "") for example in state.get("style_examples") or []
        ] + list(adapter.preferred_examples)
        # Falls back to plain `instructions` when the caller never populated
        # the wider haystack (see DraftState.instruction_haystack's own
        # docstring) -- never narrower than today's behaviour.
        instruction_haystack = state.get("instruction_haystack") or state.get("instructions", "")
        # The writer's only view of the document's raw text (see
        # retrieve_source_chunks_node) -- without folding these into the
        # grounding haystack too, a fact genuinely copied from a retrieved
        # chunk could still be flagged dayanaksiz_iddia if it isn't also a
        # verbatim substring of source_document.
        source_chunk_texts = [
            chunk.get("text", "") for chunk in state.get("source_chunks") or [] if chunk.get("text")
        ]
        report = verify_draft(
            draft_text,
            source_document=state.get("source_document", ""),
            context=state.get("context", ""),
            classification=classification,
            instructions=instruction_haystack,
            strict=strict,
            style_examples=style_example_texts,
            is_individual_petition=is_individual_petition,
            today=state.get("today", ""),
            trusted_facts=trusted_facts,
            source_chunks=source_chunk_texts,
        )

        # The counterparty's own institution/signatory leaked into our
        # antet/signature block (see draft_verifier._check_identity_slot_
        # leaks) is not a blank the missing-information gate already knows
        # how to ask about -- it's a *wrong* value sitting where a
        # placeholder should be. Converting an exact-match leak into the
        # same placeholder writer.md itself uses for that slot folds this
        # into the existing gate (build_missing_info_request/apply_answers)
        # rather than a second resolution path, and this is the narrow hard
        # gate an identity-class defect gets that a merely low-scoring or
        # guessed-type draft does not (see human_gate_node's own docstring
        # on why nothing else pauses the run).
        if report.identity_slot_leaks:
            draft_text, changed = _convert_identity_leaks_to_placeholders(
                draft_text, report.identity_slot_leaks
            )
            if changed:
                report = verify_draft(
                    draft_text,
                    source_document=state.get("source_document", ""),
                    context=state.get("context", ""),
                    classification=classification,
                    instructions=instruction_haystack,
                    strict=strict,
                    style_examples=style_example_texts,
                    is_individual_petition=is_individual_petition,
                    today=state.get("today", ""),
                    trusted_facts=trusted_facts,
                    source_chunks=source_chunk_texts,
                )

        # None means the level has no opinion; defer to the global setting.
        # True/False (fast forces off, deep forces on) overrides it outright.
        judge_on = (
            settings.DRAFT_JUDGE_ENABLED
            if preset.judge_enabled is None
            else preset.judge_enabled
        )

        verdict: DraftJudgeVerdict | None = None
        if judge_on:
            # A separate node id from "verify" (even though it runs inside the
            # same LangGraph node) so the frontend can show the hybrid gate as
            # two distinct mechanisms -- deterministic groundedness vs. the
            # fast-tier judge's reasoning-based checks -- rather than one
            # opaque "doğrulama" step.
            await emit_node_start(
                config,
                "judge",
                "Kalite Yargıcı",
                "[Yargıç] Talebe uygunluk, üslup ve kapanış yönü değerlendiriliyor...",
            )
            # Scaled by the level, same as every other budget: a `deep` run
            # buys more wall clock overall and the judge is part of what it
            # buys. settings.DRAFT_JUDGE_TIMEOUT_SECONDS stays the single owner
            # of the base value -- it is a deployment knob, not a policy one.
            company_ruleset = CompanyRuleSet.from_dict(
                state.get("company_id") or "", state.get("company_rules")
            )
            verdict = await judge_draft(
                judge_agent,
                draft=draft_text,
                brief=state.get("brief", ""),
                correspondence_type=state.get("correspondence_type") or "other_official",
                instructions=state.get("instructions", ""),
                timeout_s=settings.DRAFT_JUDGE_TIMEOUT_SECONDS * preset.timeout_multiplier,
                sub_genre=sub_genre,
                company_rules_block=format_rules_block(company_ruleset),
            )
            if verdict is None:
                await emit_node_error(
                    config,
                    "judge",
                    "Kalite Yargıcı",
                    "Kalite yargıcı kullanılamadı; deterministik doğrulama sonucuna göre devam ediliyor.",
                    fatal=False,
                )
            else:
                await emit_node_end(
                    config,
                    "judge",
                    "Kalite Yargıcı",
                    "Yargıç değerlendirmesi tamamlandı.",
                    verdict.model_dump(),
                )
        elif preset.judge_enabled is False:
            # Only announce a skip when the *level* is what turned it off --
            # the pre-existing settings.DRAFT_JUDGE_ENABLED=False case stays
            # silent, exactly as it behaved before this feature existed.
            await emit_node_skipped(
                config,
                "judge",
                "Kalite Yargıcı",
                "Hızlı modda kalite yargıcı atlandı.",
            )

        missing_information: list[InfoQuestion] = []
        if report.placeholder_count > 0:
            missing_information = build_missing_info_request(draft_text, report, classification)

        # Mirrors revise_graph.verify_node's content-loss check (see
        # app.ai.revision.elision's module docstring). A repair pass here
        # (writer_node's is_revision branch) hands the reviser's raw output
        # through as `draft` with no splice guarantee, same failure mode: the
        # model can stand in an ellipsis/shorthand for a paragraph it judges
        # "unchanged" instead of reproducing it. Only meaningful once there is
        # a `previous_draft` to compare against -- the first writer pass has
        # nothing prior to have elided.
        content_loss = None
        previous_draft = state.get("previous_draft", "")
        if previous_draft:
            content_loss = detect_content_loss(
                previous_draft, draft_text, state.get("instructions", "")
            )
            if content_loss is not None:
                logger.warning("Draft repair pass dropped content: %s", content_loss.detail)

        # Personal data (TCKN/IBAN/phone/address) surfacing in a generated
        # draft is grounds for review the same way an unresolved
        # correspondence type is: a resmi yazışma that echoes an applicant's
        # kimlik no or address needs a human's eyes before it goes out, not a
        # second automatic revision attempt (the draft path's revision loop
        # fixes groundedness/quality defects, not confidentiality ones).
        pii_findings = [
            finding
            for finding in find_pii(draft_text)
            if finding.confidence >= get_policy().guardrail.pii_confidence_floor
        ]

        # Register/consistency checks a regex can decide alone (see
        # app.ai.verification.style_checks's module docstring) -- run on the
        # same normalized draft_text everything else above already checked,
        # after the identity-leak placeholder conversion so a leak that was
        # just turned into a `[...]` placeholder isn't also flagged as a
        # bare signature meta-value or a person-consistency mismatch.
        style_findings = [
            *check_person_consistency(draft_text),
            *check_filler_sentences(draft_text),
            *check_signature_block(draft_text),
            *check_meta_commentary(draft_text),
        ]

        combined = merge_verdicts(
            report,
            verdict,
            missing_information=missing_information,
            pii_findings=pii_findings,
            correspondence_type_fallback=state.get("correspondence_type_source") == "fallback",
            has_context=bool(state.get("context")),
            cites_legislation=bool(LEGISLATION_PATTERN.search(draft_text)),
            content_loss=content_loss,
            judge_attempted=judge_on,
            style_findings=style_findings,
        )

        DRAFT_SCORE.labels(source="deterministic").observe(report.confidence_score)
        if verdict is not None:
            DRAFT_SCORE.labels(source="judge").observe(verdict.score)
        DRAFT_SCORE.labels(source="combined").observe(combined.combined_score)

        history_entry = {
            "attempt": state.get("attempts", 0),
            "deterministic_score": report.confidence_score,
            "judge_score": verdict.score if verdict is not None else None,
            "combined_score": combined.combined_score,
            "defect_count": len(combined.repair_items),
        }
        attempt_history = [*(state.get("attempt_history") or []), history_entry]

        if missing_information:
            status = "NEEDS_INPUT"
        elif combined.requires_human_approval:
            status = "NEEDS_HUMAN_APPROVAL"
        else:
            status = "COMPLETED"

        evaluation_notes = combined.notes
        if pii_findings:
            kinds = ", ".join(sorted({finding.kind for finding in pii_findings}))
            evaluation_notes = (
                f"{evaluation_notes} Taslakta {len(pii_findings)} adet kişisel veri "
                f"bulgusu tespit edildi ({kinds}); insan onayı gerekiyor."
            )
        if content_loss is not None:
            evaluation_notes = f"{evaluation_notes} {content_loss.detail}"

        update = {
            "draft": draft_text,
            "confidence_score": combined.combined_score,
            "combined_score": combined.combined_score,
            "requires_human_approval": combined.requires_human_approval,
            "requires_revision": combined.requires_revision,
            "evaluation_notes": evaluation_notes,
            "pii_findings": [finding.model_dump() for finding in pii_findings],
            "verification": report.model_dump(),
            "judge": verdict.model_dump() if verdict is not None else {},
            "judge_available": combined.judge_available,
            "repair_items": [item.model_dump() for item in combined.repair_items],
            "missing_information": [question.model_dump() for question in missing_information],
            "attempt_history": attempt_history,
            "status": status,
            "reasoning_level": preset.level.value,
            "applied_rules": [rule.model_dump() for rule in combined.applied_rules],
        }

        # C2: track the best-scoring attempt across this turn's loop (see
        # app.ai.workflows.attempt_tracking), and -- only when the loop is
        # about to exhaust its attempt budget with defects still open --
        # ship that best attempt instead of whichever one happened to run
        # last. Never touches a missing_information turn: that question is
        # about *this* draft's own placeholders, so swapping the draft out
        # from under it would make the question nonsensical.
        snapshot = snapshot_attempt(update, draft_text)
        best_attempt = best_of(snapshot, state.get("best_attempt"))
        update["best_attempt"] = best_attempt
        if (
            not missing_information
            and combined.requires_revision
            and state.get("attempts", 0) >= preset.max_draft_attempts
            and best_attempt is not snapshot
        ):
            update.update(best_attempt)

        await emit_node_end(
            config,
            "verify",
            "Taslak Doğrulama",
            "Taslak doğrulaması tamamlandı.",
            {"draft": draft_text, **update},
        )
        return update

    def route_after_verify(state: DraftState) -> str:
        if state.get("status") == "FAILED":
            return "end"
        if state.get("missing_information"):
            return "needs_input"
        if not state.get("requires_revision"):
            return "end"
        preset = get_reasoning_level_preset(state.get("reasoning_level"))
        if state.get("attempts", 0) >= preset.max_draft_attempts:
            return "end"
        return "revise"

    async def revise_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        """Prep the next writer pass. Pure and LLM-free -- the loop's only
        generation cost is the writer/reviser call, never a second one here."""
        repair_items = state.get("repair_items") or []
        logger.info("Preparing revision (%d defect(s))...", len(repair_items))
        trigger = (
            "deterministic"
            if any(item.get("source") == "deterministic" for item in repair_items)
            else "judge"
        )
        DRAFT_REVISIONS.labels(trigger=trigger).inc()
        await emit_node_start(
            config,
            "revise",
            "Revizyon Hazırlığı",
            f"{len(repair_items)} kusur tespit edildi; hedefli düzeltme hazırlanıyor...",
        )
        update = {"previous_draft": state.get("draft", "")}
        await emit_node_end(
            config,
            "revise",
            "Revizyon Hazırlığı",
            "Düzeltme talimatları hazırlandı.",
            {"repair_items": repair_items},
        )
        return update

    builder = StateGraph(DraftState)
    builder.add_node("validate_input", validate_input_node)
    builder.add_node("retrieve_examples", retrieve_examples_node, retry_policy=IO_RETRY)
    builder.add_node(
        "retrieve_source_chunks", retrieve_source_chunks_node, retry_policy=IO_RETRY
    )
    builder.add_node("writer", writer_node)
    builder.add_node("verify", verify_node)
    builder.add_node("revise", revise_node)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges(
        "validate_input",
        route_after_validation,
        {"retrieve_examples": "retrieve_examples", "end": END},
    )
    builder.add_edge("retrieve_examples", "retrieve_source_chunks")
    builder.add_edge("retrieve_source_chunks", "writer")
    builder.add_conditional_edges(
        "writer", route_after_writer, {"verify": "verify", "end": END}
    )
    builder.add_conditional_edges(
        "verify",
        route_after_verify,
        {"revise": "revise", "needs_input": END, "end": END},
    )
    builder.add_edge("revise", "writer")

    return builder.compile()
