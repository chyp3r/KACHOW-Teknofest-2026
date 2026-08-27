"""Turlar boyunca hayatta kalan, oturum kapsamlı durum.

``PlanningState``'in diğer alanları tur kapsamlıdır -- ``planning_node`` her
turun başında her ``*_result`` anahtarını sıfırlar (bkz.
``app.ai.workflows.planning_graph``). ``SessionFocus`` bilinçli bir
istisnadır: asla sıfırlanmayan, bir görevin bir mesajdan diğerine hayatta
kalması gereken her şeyi taşıyan bir LangGraph kanalıdır -- şu an "asıl"
taslak hangisi, kullanıcı çok turlu bir görüşme boyunca neyi başarmaya
çalışıyor ve (sonraki fazlar bunları tüketen akışları ekleyince) açık bir
netleştirme sorusu ile kullanıcının en son bahsettiği belge konumu.

Bu olmadan, tamamen tur kapsamlı durumdan inşa edilmiş bir sistemin "şu an
ne üzerinde çalışıyoruz" diye bir kavramı yoktur -- her mesaj sanki ilkiymiş
gibi cevaplanır, ki bu tam olarak konuşma içi bir revizyonun ("3. paragrafı
daha resmi yap") bu var olmadan önce tutunacak hiçbir yerinin olmamasının
sebebidir.
"""

import dataclasses
from typing import Any, Literal, Optional

#: Gerçek, kullanıcıya görünür bir taslak metni temsil eden -- versiyon olarak
#: kaydedilmeye değer -- draft_result durumları. FAILED hariç tutulur: yeni
#: bir metin taşımaz. REVISE_REQUESTED dahildir -- "henüz metin yok" gibi
#: duyulsa da sezgiye aykırı bir şekilde -- çünkü bunun bu fonksiyona bir
#: *turun nihai* durumu olarak ulaşmasının tek yolu, insan onay kapısının
#: revizyon turu üst sınırına ulaşılmasıdır (bkz.
#: planning_graph.route_after_gate/gate_revise_node): yapısı gereği, hâlâ
#: turu kalan her "revizyon iste" tıklaması, tur bitmeden önce gerçek bir
#: gate_revise_node sonucuyla hemen değiştirilir, bu yüzden buraya ulaşan bir
#: REVISE_REQUESTED durumu her zaman *gerçekten üretilmiş son* revizyonun
#: metnini taşır, sadece bir tur daha denemekten men edilmiştir -- arkasında
#: hiçbir şey olmayan bir istek değildir.
_VERSIONABLE_DRAFT_STATUSES = frozenset(
    {"COMPLETED", "NEEDS_HUMAN_APPROVAL", "NEEDS_INPUT", "APPROVED", "REVISE_REQUESTED"}
)

#: Metni yeni, kabul edilmiş bir versiyon olarak ele almadan üzerine bir
#: hüküm kaydeden draft_result durumları (bkz. compute_focus_update'in
#: reddetme dalı). Tek örneği REJECTED'dir. Bir reddetme active_draft'ı
#: None'a TEMİZLEMEZ -- reddedilen metin, onaylanmış biriyle tamamen aynı
#: şekilde, bir sonraki turda revize edilebilir "asıl" aktif taslak olarak
#: kalır. Ondan gerçekten vazgeçmenin tek yolu açık bir RESET_SURFACES
#: ifadesidir. Bu her zaman böyle değildi: bu dalın daha önceki bir sürümü
#: *önceki* turun versiyonunu arşivliyor (bu turun revizyonunun gerçekte
#: ürettiği yeni metni her ne ise atarak) ve ardından active_draft'ı None'a
#: temizliyordu; bu da kullanıcının aynı turda kalan, alakasız bir şikayeti
#: reddettiği anda kendi kabul ettiği düzenlemelerini sessizce
#: kaybettiriyordu.
_ARCHIVE_ONLY_DRAFT_STATUSES = frozenset({"REJECTED"})

#: Mesajı oturumun hedefine katmaya değer intent'ler. Bir selamlama ya da bir
#: belge sorusu "kullanıcının ne inşa edilmesini istediği"nin parçası değil;
#: bir draft/analyze/revise isteği ise öyle.
_OBJECTIVE_INTENTS = frozenset({"draft", "analyze", "revise"})

#: Kullanıcının açık taslakla yalnızca bir arada var olmak yerine üzerinde
#: aktif olarak çalıştığı sayılan intent'ler. Yukarıdaki `_OBJECTIVE_INTENTS`'ten
#: farklıdır: `analyze` de tıpkı `draft`/`revise` gibi oturumun beyan edilmiş
#: hedefine katılır, ama başka bir belgeyi incelemek, aktif taslağın hâlâ
#: kullanıcının şu an yaptığı şey olduğuna dair bir kanıt değildir.
_DRAFT_TOUCHING_INTENTS = frozenset({"draft", "revise"})

#: `objective`'in üst sınırı. Birkaç kısa tur kadar -- "taslak hazırla" +
#: "kime" + "Valiliğe'ye" ifadelerinin hepsinin hâlâ mevcut olması için
#: yeterli, ama uzun bir oturumun hedefinin sınırsız büyümesine izin
#: vermeyecek kadar az.
OBJECTIVE_CHAR_CAP = 500

#: `draft_history`'nin üst sınırı (C24) -- bu aynı nesnedeki her komşu kanal
#: zaten sınırlıydı (`history`'nin kendi penceresi, `objective`'in karakter
#: sınırı), ama `draft_history`'nin sınırı yoktu: uzun süredir çalışan, çok
#: kez revize edilmiş bir oturumun checkpoint'i üretilen her versiyonu
#: sonsuza dek, her biri kendi `source_document` ve `classification`
#: kopyasıyla (revize'nin kendi temellendirmesi için gerekli, bkz.
#: `DraftVersion`'ın docstring'i) taşıyordu -- belge ağırlıklı bir oturumun
#: checkpoint boyutu sadece tur sayısıyla değil, tur sayısı çarpı belge
#: boyutuyla büyüyordu. En eski girdiler, canlı bir oturumun en az ihtiyaç
#: duyduğu girdilerdir: `active_draft` (her zaman en yenisi) önemli olan her
#: okuyucunun -- revize'nin kendi brief'i, onay kapısı, bir devir teklifi --
#: gerçekten başvurduğu şeydir; daha eskisi denetim izidir. `DraftRepository`'nin
#: kendi `drafts` tablosu, her versiyonda tam, sınırsız zinciri zaten
#: veritabanına kalıcı olarak yazar (bkz. `chat_service._maybe_record_draft`);
#: bu sınır yalnızca bellek içi/checkpoint'lenmiş kopyayı kırpar, kalıcı
#: kaydı asla.
DRAFT_HISTORY_CAP = 20

#: Bir aktif taslağın, terk edilmiş sayılmadan önce bir draft/revise turu
#: tarafından dokunulmadan kalabileceği tur sayısı. Bu olmasaydı,
#: `active_draft` -- bir kez ayarlandıktan sonra -- asla kendini temizlemez
#: (bu modülde başka hiçbir şey ona `None` yazmaz), böylece `has_active_draft`
#: thread'in geri kalanı boyunca kalıcı olarak true kalır ve her
#: `REVISE_RULES` yüzeyi, konuşma alakasız bir şeye geçtikten çok sonra bile
#: tetiklenmeye devam eder.
ACTIVE_DRAFT_IDLE_LIMIT = 10


@dataclasses.dataclass(frozen=True)
class DraftVersion:
    """Aktif taslağın bir noktada oturmuş (settled) hâli.

    Attributes:
        version: 1'den başlar, yeni bir versiyon öncekinin yerini her
            aldığında birer birer artar. Asla tekrar kullanılmaz.
        text: Bu versiyondaki taslak metni.
        correspondence_type: Yazının altında yazıldığı, çözümlenmiş yazışma
            türü.
        confidence_score: Bu versiyondaki doğrulayıcının bileşik skoru.
        created_from: Bu versiyonun nasıl ortaya çıktığı.
        classification: Bu versiyonun temellendirildiği belge analizi.
            Sonraki bir `revise` turunun sınıflandırmayı yeniden çalıştırmadan
            aynı temellendirme brief'ini yeniden kurabilmesi için taşınır --
            revise asla yeniden sınıflandırma yapmaz (bkz.
            `app.ai.workflows.revise`).
        context: Bu versiyonun temellendirildiği, doğrulanmış mevzuat
            alıntıları; aynı sebeple.
        source_document: Bu versiyonun cevap verdiği gelen belge metni; aynı
            sebeple -- bu olmadan, bir revize turunun temellendirme
            kontrolünün, orijinal taslağınkine kıyasla iddiaları
            eşleştirecek kesinlikle daha az malzemesi olur.
        style_examples: Bu versiyonun yazıldığı few-shot üslup örneği
            metinleri (bkz. ``retrieve_examples_node``); sonraki bir
            `revise` turunun doğrulayıcısının, orijinal taslağın geçtiği
            aynı ``ornek_sizintisi`` sızıntı kontrolünü çalıştırabilmesi
            için taşınır -- bu olmadan bir revizyonun doğrulama geçişi,
            revize ettiği taslağa kıyasla kesinlikle daha zayıf
            temellendirme kontrollerine sahip olurdu.
        source_chunks: Bu versiyonun yazıldığı, kelimesi kelimesine belge
            alıntıları (bkz. ``retrieve_source_chunks_node``);
            ``style_examples`` ile aynı sebeple taşınır -- bu olmadan,
            orijinal taslakta gerçekten getirilen bir parçadan kopyalanmış
            bir gerçek, taslak revize edildiği anda ``dayanaksiz_iddia``
            olarak işaretlenebilirdi, çünkü ``revise_graph``'ın bunları
            kendi ``verify_draft`` çağrısına geri katmanın bir yolu yoktu.
        correspondence_type_source: ``correspondence_type``'ın açık bir
            sinyalden mi çözümlendiği yoksa tahmin mi edildiği
            (``"fallback"``, bkz. ``resolve_correspondence_type``).
            Sonraki bir revize turunun onay kapısının, ``draft_graph.
            verify_node``'un her zaman uyguladığı "tahmin edilmiş bir tür
            insan gerektirir" kuralını uygulayabilmesi için taşınır.
        correspondence_sub_genre: Bu versiyon, dört tanımlı CorrespondenceType
            değerinin dışında belirli bir türü ("itiraz dilekçesi") hedefliyorsa
            serbest metin bir tür etiketi -- temel bir tür için boş. Sonraki bir
            `revise` turunun genel "diğer resmî yazışma" ifadesine geri
            kaymak yerine aynı türde yazmaya devam etmesi için taşınır (bkz.
            ``resolve_correspondence_type``).
        status: Bu versiyonun altında kaydedildiği ``draft_result`` durumu
            (ör. ``"COMPLETED"``, ``"NEEDS_HUMAN_APPROVAL"``,
            ``"REJECTED"``). Bilgilendirme amaçlıdır -- burada hiçbir şey
            ondan davranış türetmez; ``created_from``/``rejection_reason``'dan
            yeniden türetmeden ne olduğunu göstermek isteyen bir çağıran
            (bir geçmiş görünümü, bir log) içindir.
        rejection_reason: ``created_from == "rejected"`` olduğunda bu
            versiyonun neden reddedildiği. Aksi halde boş.
        conflicts: Bir revizyon tarafından üretildiğinde bu versiyonun
            kendi talimat-vs-mevzuat/kaynak çatışma bulguları (bkz.
            ``app.ai.revision.conflict``). Taze bir taslak için boş.
        changelog: Bir revizyon tarafından üretildiğinde bu versiyonun
            yerini aldığı versiyona karşı kendi değişiklik günlüğü (bkz.
            ``app.ai.revision.changelog``). Taze bir taslak için boş.
        supersedes: Bu versiyonun yerini almak üzere yazıldığı
            ``DraftVersion``'ın ``version`` numarası, ya da böyle biri
            yoksa (oturumun ilk taslağı, ya da başka bir taslak hâlâ
            aktifken gelen alakasız bir taze taslak isteği) ``0``. Yalnızca
            bu versiyon gerçekten ``focus.active_draft``'ı revize ederek
            üretildiyse (``created_from`` ``"revise"`` ya da
            ``"gate_revise"``) ayarlanır -- asla "zaten bir taslak vardı"
            varsayımından çıkarılmaz, bu da alakasız bir taslağı hiç ilgisi
            olmayan birinin devamı olarak yanlış etiketlerdi. Bu, sonraki
            bir tüketicinin (bkz. geri bildirim/eğitim hattı) metin
            benzerliğinden tahmin etmeden -- reddedilen bir versiyonun
            ardından onu gerçekten düzelten revizyon dahil -- gerçek bir
            düzenleme zincirini takip edebilmesini sağlayan şeydir.
    """

    version: int
    text: str
    correspondence_type: str
    confidence_score: float
    created_from: Literal["draft", "revise", "human_fill", "gate_revise", "rejected"]
    supersedes: int = 0
    classification: dict[str, Any] = dataclasses.field(default_factory=dict)
    context: str = ""
    source_document: str = ""
    style_examples: tuple[str, ...] = ()
    source_chunks: tuple[str, ...] = ()
    correspondence_type_source: str = ""
    correspondence_sub_genre: str = ""
    #: Bu versiyonun altında yazıldığı, taslak öncesi yazım brief'i (bkz.
    #: app.ai.workflows.writing_brief) -- kim yazıyor, kime gidiyor,
    #: anlatım/kapanış. classification/context/source_document ile aynı
    #: sebeple taşınır: sonraki bir `revise` turu, yeniden çözümlemeden aynı
    #: temellendirme brief'ini yeniden kurar ve orijinal "KACMAK ekibi
    #: olarak" hatasının yaptığı gibi belirtilmemiş bir yöne geri
    #: kaymamalıdır.
    writing_brief: dict[str, Any] = dataclasses.field(default_factory=dict)
    #: Bu taslak soyunda daha önceki bir eksik-bilgi (``human_gate``) turunda
    #: verilmiş cevaplar; ``InfoQuestion.key`` -> gerçek değer, ya da kullanıcı
    #: "Sen karar ver" seçtiyse ``AUTO_ANSWER``. ``writing_brief`` ile aynı
    #: sebeple taşınır: sonraki bir ``revize`` turunun
    #: ``build_missing_info_request`` çağrısı, kullanıcının zaten cevapladığı
    #: veya bilerek ertelediği bir yer tutucuyu tekrar sormamalıdır.
    resolved_placeholder_answers: dict[str, Any] = dataclasses.field(default_factory=dict)
    status: str = ""
    rejection_reason: str = ""
    conflicts: tuple[dict[str, Any], ...] = ()
    changelog: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class SessionFocus:
    """Aynı thread üzerinde turlar boyunca kalıcı olan görev düzeyi durum.

    Attributes:
        active_document_id: Oturumun şu anda üzerinde çalıştığı belgenin
            depolama yolu.
        active_draft: Şu anda revizyon veya onay için açık olan taslak
            versiyonu, ya da sürmekte olan bir taslak yoksa ``None``. Bir
            reddetmeden sonra bile ayarlı kalır (``status == "REJECTED"``
            ile) -- bir reddetme metin üzerine bir hükümdür, onu unutma
            talimatı değildir, bu yüzden sonraki turun "üslubunu düzelt"
            ifadesinin hâlâ tutunacak bir şeyi olur. Yalnızca açık bir
            ``RESET_SURFACES`` ifadesi ya da ``ACTIVE_DRAFT_IDLE_LIMIT``
            kadar boşta kalan tur, onu ``None``'a temizler.
        draft_history: En son oturmuş versiyonlar, en eskiden başlayarak,
            ``DRAFT_HISTORY_CAP``'e sınırlı (ayarlıyken ``active_draft``
            her zaman ``draft_history[-1]``'dir) -- tam, sınırsız zincir
            ``drafts`` veritabanı tablosunun işidir (bkz.
            ``app.domains.drafts.repository.DraftRepository``); bu, canlı
            oturum için bir çalışma kümesidir, kalıcı kayıt değil.
        objective: Kullanıcının çok turlu bir görüşme boyunca neyi
            başarmaya çalıştığına dair kısa, birikimli bir ifade.
            Sınırsız bir günlük yerine sınırlıdır (bkz.
            ``OBJECTIVE_CHAR_CAP``).
        pending_clarification: Sistem netleştirici bir soru sorduğunda ve
            cevabı beklerken ayarlanır. ``clarify`` akışı için ayrılmıştır;
            o var olana kadar kullanılmaz.
        last_referenced_anchor: Bir işaret zamiri referansının ("bu madde",
            "burası") çözümlenmesi gereken belge konumu. Belge adresleme
            için ayrılmıştır; o var olana kadar kullanılmaz.
        last_intent: En son çözümlenen intent. ``PlanningState``'in kendi
            ``plan_intent`` kanalı bunu zaten turdan tura taşır (hiçbir şey
            onu sıfırlamaz), ama o "bu turun sonucu" anlamına gelen alanlar
            arasında yaşar -- bu, "oturumun durumu" anlamına gelen yerden
            okunan aynı değerdir; bu ayrımı bilmesi gerekmeyen gelecekteki
            bir tüketici içindir.
        active_draft_idle_turns: ``active_draft``'ın en son üretildiği ya da
            üzerinde çalışıldığı andan bu yana geçen tur sayısı (bkz.
            ``_DRAFT_TOUCHING_INTENTS``). Kullanıcı aktif olarak taslak
            hazırlarken ya da revize ederken 0'a sıfırlanır;
            ``ACTIVE_DRAFT_IDLE_LIMIT``'e ulaştığında ``active_draft``
            kendini temizler. ``active_draft`` ``None`` iken anlamsızdır.
        last_rejection: Bir ``REJECTED`` draft_result aktif taslağı
            arşivlediğinde ayarlanan, en son reddedilen versiyonun kendi
            özeti (``{"version", "reason", "draft"}``) (bkz.
            ``compute_focus_update``). Bir cevabın ya da sonraki bir turun,
            onu bulmak için ``draft_history``'de dolaşmadan "az önce
            reddettiğin taslağa" atıfta bulunmasını sağlar.
        writing_brief: Taslak öncesi yazım-brief'i kapısından gelen
            cevaplar (bkz. ``app.ai.workflows.writing_brief``); aynı
            oturumdaki ikinci bir draft/revise turunun kime yazıldığını
            tekrar sormaması için turlar boyunca taşınır. ``active_draft``
            sıfırlandığında temizlenir (bkz. ``compute_focus_update``'in
            ``reset_requested`` dalı) -- aksi halde "yeni bir taslak
            yazalım" sessizce önceki mektubun alıcısını devralırdı.
        active_draft_id: ``active_draft``'ı üreten graph turu aynı zamanda
            veritabanına da kaydedildiyse, onun kalıcı ``drafts.id``'si
            (bkz. ``app.domains.chat.chat_service.ChatService.
            _maybe_record_draft``, tek yazıcı). ``active_draft``'ın
            kendisi asla bir veritabanı id'si taşımaz -- ``DraftVersion``,
            herhangi bir DB yazımı gerçekleşmeden önce graph'ın inşa
            ettiği saf, bellek içi bir anlık görüntüdür (bkz. kendi
            docstring'i) -- bu yüzden burası, ``propose_transfer``
            aracının (``app.ai.tools.transfer_tools``) yeniden türetmeden
            gerçek, aktarılabilir bir id bulabileceği tek yerdir. Yalnızca
            bir kolaylık ipucudur, plandaki §C2'ye göre: bir çözümleme
            merdiveninin güvendiği tek kaynak asla değildir, çünkü
            ``DraftRepository.get_latest_for_session``'ın
            bayatlayamayacağı şekillerde (boşta kalınca temizlenmiş bir
            ``active_draft``, başarısız olmuş bir ``record_draft``
            çağrısı) bayatlayabilir -- "hangi taslak" çözümlemesini
            gerçekten destekleyen o sorgudur; bu alan yalnızca *işaret
            zamiri* bir referansın ("bu taslağı gönder") yeniden
            türetmeden doğrudan aynı cevaba atlamasına yardımcı olur.
            ``active_draft``'ın temizlendiği şekilde (boşta kalma sınırı,
            açık sıfırlama) ``compute_focus_update`` tarafından bilinçli
            olarak asla temizlenmez -- buradaki bayat bir id zararsızdır,
            çünkü her okuyucu onu güvenilir bir işaretçi değil, doğrulanacak
            bir aday olarak ele alır.
    """

    active_document_id: Optional[str] = None
    active_draft: Optional[DraftVersion] = None
    draft_history: tuple[DraftVersion, ...] = ()
    #: Atanacak bir sonraki versiyon numarası, `len(draft_history)`'den
    #: bağımsız (C24): `draft_history` sınırlandıktan sonra (bkz.
    #: `DRAFT_HISTORY_CAP`), uzunluğu artık "bu oturumun şimdiye kadar
    #: kaç versiyonu oldu" anlamına gelmez -- bir sonraki versiyonu
    #: bundan türetmek, kırpılıp atılmış girdilerin zaten kullandığı
    #: numaraları yeniden vermeye başlardı. Monotonik olarak artar,
    #: kendisi asla kırpılmaz (çıplak bir int'i sonsuza dek tutmanın
    #: hiçbir maliyeti yoktur).
    draft_version_counter: int = 0
    objective: str = ""
    pending_clarification: Optional[dict[str, Any]] = None
    last_referenced_anchor: Optional[str] = None
    last_intent: Optional[str] = None
    active_draft_idle_turns: int = 0
    last_rejection: Optional[dict[str, Any]] = None
    writing_brief: Optional[dict[str, Any]] = None
    active_draft_id: Optional[str] = None


def _accumulate_objective(existing: str, addition: str) -> str:
    """``existing``'e yeni bir parça ekler, en eski taşan kısmı düşürür.

    Args:
        existing: Oturumun mevcut hedef metni.
        addition: Yeni turun katkısı.

    Returns:
        Baştan düşürülerek ``OBJECTIVE_CHAR_CAP`` karaktere sınırlanmış
        birleşik hedef -- en yeni parça, cümle ortasından kesilen kısım
        olmak yerine her zaman bütün olarak korunur.
    """
    addition = addition.strip()
    if not addition:
        return existing
    combined = f"{existing} | {addition}" if existing else addition
    if len(combined) <= OBJECTIVE_CHAR_CAP:
        return combined
    return combined[-OBJECTIVE_CHAR_CAP:]


def _revision_origin(
    plan_intent: Optional[str], draft_result: dict[str, Any]
) -> Literal["draft", "revise", "gate_revise"]:
    """Bu turun oturmuş taslak metninin nasıl ortaya çıktığı.

    ``compute_focus_update``'in olağan versiyonlama dalı ve reddetme dalı
    tarafından paylaşılır -- ikisi de aynı sebeple aynı ayrıma (taze,
    alakasız bir taslak mı yoksa zaten aktif olanın gerçek bir revizyonu
    mu) ihtiyaç duyar: ``created_from``/``supersedes``, "zaten bir taslak
    vardı" değil, gerçekte ne olduğunu yansıtmalıdır.
    """
    if draft_result.get("instruction_origin") == "human_gate":
        return "gate_revise"
    if plan_intent == "revise":
        return "revise"
    return "draft"


def _append_history(
    history: tuple[DraftVersion, ...], entry: DraftVersion
) -> tuple[DraftVersion, ...]:
    """`DRAFT_HISTORY_CAP`'e sınırlı bir versiyon ekler (C24).

    *Baştan* kırpar -- en eski girdiler canlı bir oturumun en az ihtiyaç
    duyduğu şeylerdir (bkz. `DRAFT_HISTORY_CAP`'in kendi docstring'i); en
    yenisi (`active_draft` olan `entry`'nin kendisi) her zaman korunur.
    """
    return (*history, entry)[-DRAFT_HISTORY_CAP:]


def _supersedes_of(
    created_from: Literal["draft", "revise", "gate_revise"],
    active_draft: Optional["DraftVersion"],
) -> int:
    """Bir revizyonun yerini aldığı versiyon numarası, ya da yoksa 0.

    Yalnızca ``active_draft``'ın gerçek bir revizyonu için ayarlanır (bkz.
    ``DraftVersion.supersedes``) -- başka bir taslak hâlâ açıkken gelen
    taze, alakasız bir taslak isteği, onun yerini aldığını iddia
    etmemelidir.
    """
    if created_from in ("revise", "gate_revise") and active_draft is not None:
        return active_draft.version
    return 0


def _draft_version_from_result(
    draft_result: dict[str, Any],
    *,
    version: int,
    created_from: Literal["draft", "revise", "human_fill", "gate_revise", "rejected"],
    rejection_reason: str = "",
    supersedes: int = 0,
) -> DraftVersion:
    """Oturmuş bir ``draft_result``'tan doğrudan bir ``DraftVersion`` inşa eder.

    ``compute_focus_update``'in olağan versiyonlama dalı ve reddetme dalı
    tarafından paylaşılır -- ikisi de aynı ham malzemeden başlar, yalnızca
    ``created_from``, ``supersedes`` ve (bir reddetme için) sebep
    bakımından farklılık gösterirler.
    """
    return DraftVersion(
        version=version,
        text=draft_result.get("draft", ""),
        correspondence_type=draft_result.get("correspondence_type") or "",
        confidence_score=(
            draft_result.get("combined_score") or draft_result.get("confidence_score") or 0.0
        ),
        created_from=created_from,
        supersedes=supersedes,
        classification=draft_result.get("classification") or {},
        context=draft_result.get("context") or "",
        source_document=draft_result.get("source_document") or "",
        style_examples=tuple(
            example.get("text", "") if isinstance(example, dict) else str(example)
            for example in (draft_result.get("style_examples") or [])
        ),
        source_chunks=tuple(
            chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
            for chunk in (draft_result.get("source_chunks") or [])
        ),
        correspondence_type_source=draft_result.get("correspondence_type_source") or "",
        correspondence_sub_genre=draft_result.get("correspondence_sub_genre") or "",
        writing_brief=draft_result.get("writing_brief") or {},
        resolved_placeholder_answers=draft_result.get("resolved_placeholder_answers") or {},
        status=str(draft_result.get("status") or ""),
        conflicts=tuple(draft_result.get("conflicts") or ()),
        changelog=draft_result.get("changelog") or {},
        rejection_reason=rejection_reason,
    )


def compute_focus_update(
    focus: SessionFocus,
    *,
    document_id: Optional[str],
    plan_intent: Optional[str],
    input_text: str,
    draft_result: dict[str, Any],
    assist_result: Optional[dict[str, Any]] = None,
    reset_requested: bool = False,
    brief_answers: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Derive this turn's partial ``SessionFocus`` update.

    Pure function -- the graph node wrapping this only reads ``state`` and
    passes it a dict, so the actual decision of what changes is unit
    testable without a compiled graph.

    Args:
        focus: The session's focus as of the start of this turn.
        document_id: This turn's attached document, if any.
        plan_intent: The intent resolved for this turn.
        input_text: The user's message this turn.
        draft_result: This turn's settled ``draft_result``, if the plan
            included a draft step. Empty when it didn't.
        assist_result: This turn's settled ``assist_result``, if the plan
            included an assist step. Carries ``last_referenced_anchor`` when
            a document tool read a specific page this turn (see
            ``app.ai.tools.document_tools``).
        reset_requested: Whether this turn's message explicitly asked to
            abandon the open draft (see ``app.ai.workflows.intent_rules.
            RESET_SURFACES``). Takes effect only when this turn didn't also
            produce a new version -- an explicit reset and a settled draft
            in the same turn cannot both be true of a real message, and a
            freshly produced version winning that contradiction is the safer
            of the two readings.
        brief_answers: This turn's settled ``brief_result["answers"]``, if
            the plan included a ``brief`` step. Written unconditionally
            whenever a ``brief`` step ran this turn -- including replacing
            an existing ``focus.writing_brief`` with an empty dict -- so a
            turn whose brief resolved silently (no gate needed) still
            persists it for the next turn, and a fresh ``draft`` turn
            (whose ``_step_brief`` deliberately starts from no prior
            brief, see its own docstring) never leaves the previous
            draft's answers sitting in ``focus.writing_brief`` unwritten.
            The gate itself already writes the same value directly when it
            does fire (see ``planning_graph.brief_gate_node``); this is
            what covers the no-gate path. ``None`` means no ``brief`` step
            ran at all this turn (not "it ran and produced nothing"), so
            the existing value is left untouched. Overridden by an
            explicit ``reset_requested`` below, which always wins.

    Returns:
        A partial update for the ``focus`` channel (see ``merge_focus``).
        Empty when nothing changed.
    """
    update: dict[str, Any] = {}

    # `is not None`, not truthy -- an empty dict is a real "brief step ran
    # and resolved nothing" result that must still overwrite whatever
    # `focus.writing_brief` carried in from a prior, unrelated draft (see
    # this parameter's own docstring); only `None` (no brief step this
    # turn at all) leaves the existing value alone.
    if brief_answers is not None:
        update["writing_brief"] = brief_answers

    anchor = (assist_result or {}).get("last_referenced_anchor")
    if anchor:
        update["last_referenced_anchor"] = anchor

    if document_id:
        update["active_document_id"] = document_id

    if plan_intent:
        update["last_intent"] = plan_intent
        if plan_intent in _OBJECTIVE_INTENTS:
            update["objective"] = _accumulate_objective(focus.objective, input_text)

    draft_status = (draft_result or {}).get("status")
    produced_version = draft_status in _VERSIONABLE_DRAFT_STATUSES
    # A rejection reachable with no prior `focus.active_draft` is not an edge
    # case -- it is the *ordinary* first-approval reject: a turn that both
    # drafts and gets rejected within the same turn (gate interrupts before
    # focus_node ever runs, see focus_node's own docstring) never had a
    # chance to become `focus.active_draft` first. `draft_result["draft"]`
    # is what carries the real text either way.
    archived_rejection = draft_status in _ARCHIVE_ONLY_DRAFT_STATUSES and bool(
        focus.active_draft is not None or draft_result.get("draft")
    )
    if produced_version:
        # Keyed off which step actually produced this turn's result, not
        # inferred from "a draft already existed" -- the latter mislabeled
        # any second, entirely unrelated draft request in a later turn as a
        # "revise" of the first. A result from the human approval gate's own
        # "revizyon iste" loop (see planning_graph.gate_revise_node) is
        # distinguished from an ordinary revise turn -- both are still a
        # revision, but one happened inside the gate, not the plan.
        created_from = _revision_origin(plan_intent, draft_result)
        supersedes = _supersedes_of(created_from, focus.active_draft)
        # C24: from a monotonic counter, not `len(focus.draft_history) + 1``
        # -- once draft_history is capped (see DRAFT_HISTORY_CAP), its
        # length is no longer "how many versions this session has ever
        # had", and deriving the next number from it would start reissuing
        # numbers a trimmed-away entry already used.
        next_version = focus.draft_version_counter + 1
        version = _draft_version_from_result(
            draft_result, version=next_version, created_from=created_from,
            supersedes=supersedes,
        )
        update["active_draft"] = version
        update["draft_history"] = _append_history(focus.draft_history, version)
        update["draft_version_counter"] = next_version
    elif archived_rejection:
        # A rejection is a verdict on the *text*, not an instruction to
        # forget it -- the rejected draft stays `active_draft`, revisable in
        # the next turn exactly like an approved one (see
        # _ARCHIVE_ONLY_DRAFT_STATUSES's docstring). Whenever this turn
        # actually produced text (`draft_result["draft"]` -- true on every
        # path reachable through the router: the gate only ever reaches
        # REJECTED after the step that ran this turn already settled a
        # draft, whether that was a fresh write or a gate_revise round), a
        # NEW version is appended rather than overwriting whatever was
        # `focus.active_draft` at the *start* of the turn -- otherwise a
        # revision that fixed the content but not the tone, then rejected
        # for its tone, would silently discard the content fix along with
        # it (this was the bug: the prior turn's version was archived in
        # place and this turn's real revised text was never recorded
        # anywhere). Whether this rejection actually supersedes the prior
        # active_draft (vs. coexists with an unrelated one) follows the same
        # origin test `produced_version` above uses.
        reason = (draft_result.get("rejection_reason") or "").strip()
        new_text = draft_result.get("draft") or ""
        if new_text:
            created_from = _revision_origin(plan_intent, draft_result)
            supersedes = _supersedes_of(created_from, focus.active_draft)
            # C24: see the identical comment in the `produced_version`
            # branch above.
            next_version = focus.draft_version_counter + 1
            rejected_version = _draft_version_from_result(
                draft_result, version=next_version, created_from="rejected",
                rejection_reason=reason, supersedes=supersedes,
            )
            history = _append_history(focus.draft_history, rejected_version)
            update["draft_version_counter"] = next_version
        else:
            # No new text this turn -- not reachable through the router
            # today (`archived_rejection`'s own guard requires this only
            # when `focus.active_draft is not None`, see its definition
            # above), kept as a defensive fallback: annotate the existing
            # active_draft in place rather than manufacture a duplicate
            # entry with no text of its own.
            rejected_version = dataclasses.replace(
                focus.active_draft, created_from="rejected", status=str(draft_status),
                rejection_reason=reason,
            )
            # C26: `==` (value equality), not `is` (identity) -- `focus` can
            # come back from a checkpointer round-trip (LangGraph persists
            # PlanningState as serialized data and reconstructs it), which
            # always produces a *new* DraftVersion instance even when every
            # field is identical to what was saved. `is` failed silently
            # across that boundary and fell through to the `else` branch
            # below, appending a spurious duplicate entry to draft_history
            # instead of replacing the one being rejected. DraftVersion is a
            # frozen dataclass, so `==` already compares every field by
            # value, which is exactly "the same logical draft" here.
            if focus.draft_history and focus.draft_history[-1] == focus.active_draft:
                history = (*focus.draft_history[:-1], rejected_version)
            else:
                history = (*focus.draft_history, rejected_version)
        update["draft_history"] = history
        # Stays the active draft -- see this branch's opening comment. The
        # only way to truly clear it is an explicit RESET_SURFACES phrase,
        # handled below exactly as it already was for every other case.
        update["active_draft"] = rejected_version
        update["last_rejection"] = {
            "version": rejected_version.version, "reason": reason, "draft": rejected_version.text,
        }

    # The active draft's lifetime: touching it (producing a version, or a
    # draft/revise turn even when that particular attempt didn't settle one --
    # e.g. it needs more input) keeps its idle clock at zero; an explicit
    # reset phrase or ACTIVE_DRAFT_IDLE_LIMIT turns of anything else clears
    # it. `draft_history` is untouched either way -- this only decides which
    # version, if any, counts as "the" open one right now.
    if produced_version or archived_rejection:
        update["active_draft_idle_turns"] = 0
    elif reset_requested and focus.active_draft is not None:
        update["active_draft"] = None
        update["active_draft_idle_turns"] = 0
        update["writing_brief"] = None
    elif focus.active_draft is not None:
        if plan_intent in _DRAFT_TOUCHING_INTENTS:
            update["active_draft_idle_turns"] = 0
        else:
            idle_turns = focus.active_draft_idle_turns + 1
            if idle_turns >= ACTIVE_DRAFT_IDLE_LIMIT:
                update["active_draft"] = None
                update["active_draft_idle_turns"] = 0
            else:
                update["active_draft_idle_turns"] = idle_turns

    return update


def merge_focus(
    left: Optional[SessionFocus], right: Optional[dict[str, Any]]
) -> SessionFocus:
    """LangGraph reducer: apply a partial update onto the session's focus.

    Args:
        left: The channel's existing value.
        right: A partial update, e.g. ``{"active_draft": ...}`` -- a node
            returns only the fields it changed, the same convention every
            other ``PlanningState`` update already follows.

    Returns:
        The merged ``SessionFocus``.
    """
    base = left or SessionFocus()
    if not right:
        return base
    return dataclasses.replace(base, **right)
