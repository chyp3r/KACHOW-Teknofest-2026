"""Deterministik karar katmanı için tipli, sürümlenmiş parametreler.

LLM olmayan karar katmanının kullandığı her eşik değer eskiden onu okuyan
kodun yanında yaşıyordu: ``draft_verifier`` içinde ``70.0``, ``routing_graph``
içinde ``50.0``, ``llm_judge`` içinde ``0.6/0.4``, ``planning_graph`` içinde
``12``, ``40`` ve ``4``. Tek tek makul ama toplu olarak gözden geçirilemez
durumdaydılar -- bunlardan ikisi, aralarında belirtilmiş bir ilişki olmadan
*aynı* kavramdı ("bunun bir insana ihtiyacı var mı?") ve bir tabloda hiçbir
şeyin okumadığı girdiler vardı.

Neden YAML değil de dondurulmuş (frozen) veri sınıfları
--------------------------------------------------------
Bir yapılandırma dosyası, kodu değiştirmeden bir eşiği değiştirme imkanı
sağlar; burada tam olarak *istenmeyen* şey de budur. Bu sayılar
``evaluation/datasets``'e karşı kalibre edilmiştir; birini değiştirmek bir
CHANGELOG girdisi ve bir değerlendirme (eval) çalıştırması gerektirmeli,
bir yeniden dağıtım değil. Tipli veri sınıfları aşağıdaki değişmezlerin
yaşayabileceği bir yer sağlar, mypy ve IDE bunlar üzerinde bedavaya çalışır
ve production ile testlerin birbirinden sapabileceği bir ayrıştırma yolu
yoktur.

Bu modülün gerçek ürünü değişmezlerdir (invariants). Bunlar, daha önce yalnızca
tesadüfen doğru olan ilişkileri kodlar -- daha önce hiçbir şey birinin
yönlendirme eşiğini otomasyon eşiğinin üzerine çıkarıp geçidi tersine
çevirmesini engellemiyordu.
"""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.enums.user_role import UserRole

__all__ = [
    "BudgetPolicy",
    "ChunkingPolicy",
    "DraftPolicy",
    "GuardrailPolicy",
    "IntentPolicy",
    "MemoryPolicy",
    "Policy",
    "SemanticPolicy",
    "RoutingPolicy",
    "VerificationPolicy",
]


@dataclass(frozen=True)
class VerificationPolicy:
    """Deterministik taslak geçidi için eşik değerleri.

    Bir taslağın karşı puanlandığı ceza *değerleri* (iddia başına, sızıntı
    başına, eksik yapısal öge başına, ...) artık burada yaşamıyor -- bunlar
    ``app.ai.verification.confidence_rules.RULES`` içindeki tek kural
    tablosunda, bu veri sınıfına ve onu okuyan modüllere dağılmış gevşek
    float'lar yerine kendi koşullarında sürümlenip gözden geçiriliyor. Bu
    veri sınıfı yalnızca bir kuralın kendi cezası olmayan eşikleri tutar:
    otomatik/insan incelemesi çizgisinin nerede olduğu ve dayanaklılık
    (groundedness) kontrolünün kendisinin kullandığı eşleşme toleransları.
    Benzer şekilde, yargıç (judge) artık harmanlanmış bir sayısal puana
    katkıda bulunmuyor (bkz. ``app.ai.verification.llm_judge.merge_verdicts``
    modülünün docstring'i) -- diğer her şey gibi kural bulguları katkıda
    bulunuyor, dolayısıyla burada yapılandırılacak bir "yargıç ağırlığı" da
    kalmadı.

    Attributes:
        min_automated_confidence: Bu değere eşit veya üzerindeyse bir taslak
            insan onayı olmadan gönderilebilir. İki insan onayı eşiğinden
            üst olanı.
        token_overlap_threshold: Toleranslı geri düşüşün (fallback) bir
            değeri kabul etmesi için, o değerin önemli token'larından
            kaynaklarda görünmesi gereken pay.
        judge_echo_overlap_threshold: Bir kararın kendi token'larının
            taslakta görünme payı bu değerin üzerindeyse, o karar bir yargı
            değil bir yankı (echo) sayılır ve atılır.
    """

    min_automated_confidence: float = 70.0
    token_overlap_threshold: float = 0.75
    judge_echo_overlap_threshold: float = 0.40


@dataclass(frozen=True)
class RoutingPolicy:
    """Altındaki hiçbir şeyin otomatik olarak yönlendirilemeyeceği puan.

    Birim listesinin kendisi artık bir politika değil -- birimler,
    ``units`` alanı (domain) aracılığıyla çalışma zamanında yönetilir
    (``POST/PATCH/DELETE /units``, yalnızca admin/manager) ve
    ``routing_graph`` tarafından her yönlendirme kararında
    ``app.domains.units.provider.get_active_units_for_routing`` üzerinden
    tazece okunur. Artık bir "İnsan Onayı Gerekli" sahte-birimi yok: yönlendirme
    gerçek bir birimi güvenle seçemediğinde (boş taslak, düşük puan, bir LLM
    hatası veya güncel listenin dışında bir birim adı), hiçbir birim atanmaz
    ve bunun yerine mevcut ``requires_human_approval`` bayrağı ayarlanır --
    özel bir birim değeri değil, taslak-kalitesi geçidinin zaten kullandığı
    aynı bayrak.

    Attributes:
        human_approval_score_threshold: Bunun altında bir taslak, bir insan
            dışında herhangi bir yere yönlendirilecek kadar güvenilir
            değildir. İki eşikten *düşük* olanı -- ilişkinin neden önemli
            olduğu için bkz. :func:`Policy.check_invariants`.
    """

    human_approval_score_threshold: float = 50.0


@dataclass(frozen=True)
class IntentPolicy:
    """Sözcüksel katman için marj eşikleri ve onun üzerine kurulu füzyon
    kararı için olasılık bantları.

    Attributes:
        presence_floor: Bunun altında bir niyet, sözcüksel katmanın kendi
            puanlamasında bir aday değil, gürültüdür. Bir taban olmadan,
            0.1 ve 0.0 puan alan iki kural, sırf kimse itiraz etmediği için
            kendinden emin bir karar gibi okunurdu. Üst düzey karar (aşağıdaki
            ``tau_high``/``tau_low``'a bakın) artık doğrudan buna
            dayanmasa bile, ``score_intents``'in çıktısının bir özelliği
            olarak hâlâ anlamlıdır.
        decisive_margin: Sözcüksel katmanın kendi marjı için referans fark;
            yukarıdaki ``presence_floor`` ile aynı statüde.
        compound_floor: Hem taslak hem de analiz sözcüksel olarak bağımsız
            biçimde iyi kanıtlanmış sayıldığında ve mesajın bileşik bir
            istek haline geldiği puan. Kasıtlı olarak, füzyon çalışmadan
            *önceki* ham toplamsal (additive) sözcüksel puanlar üzerinde
            kontrol edilir -- bir softmax'ın sınıfları yapısı gereği
            birbiriyle yarışır, bu yüzden "her iki okuma da bağımsız olarak
            güçlü" durumunu toplamsal bir puanın yapabildiği gibi temsil
            edemez (bkz. ``scripts/fit_router.py``'nin modül docstring'i).
        confidence_scale: Sözcüksel katmanın kendi güvenine [0, 1] aralığında
            eşlenen marj (``IntentScores.confidence``).
        tau_high: Yönlendiricinin bir niyete doğrudan bağlanması için gereken
            minimum füzyon olasılığı. Bunun altında merdiven tahmin yapmaz.
        tau_low: Bu füzyon olasılığının altında, tek başına füzyon sinyali
            bağlayıcı bir karar olarak *raporlanamayacak* kadar zayıftır,
            ama artık model çağrısını engellemez -- bir hızlı katman modeli
            mevcut olduğunda her zaman sorulur (bkz.
            ``app.ai.workflows.planner.resolve_plan``), çünkü düşük bir
            füzyon olasılığı tam olarak bir model çağrısının işe yaradığı
            durumdur, onu atlamak için bir sebep değil. ``tau_low`` yine de
            modelin kendi ``unclear`` kararına güvenmek yerine bir açıklayıcı
            soru sorulup sorulmayacağını sınırlar: yalnızca füzyon kanıtı bu
            kadar zayıfken *ve* model de en iyi iki seçeneği birbirinden
            ayıramamışsa (bkz. ``clarify_margin``).
        clarify_margin: En üstteki füzyon niyetinin, modelin ``unclear``
            kararının başka bir şeyle geçersiz kılınmak yerine gerçek bir
            berabere olarak kabul edilmesi için ikinciye karşı taşıması
            gereken minimum fark. Füzyon katmanının zaten net bir şekilde
            önde olduğu bir mesaj hakkında (sözcüksel kanıt yalnızca
            ``tau_high``'ın altında kaldığı için) modelin "emin değilim"
            demesi gereksiz bir soruya dönüşmemeli -- yalnızca gerçek bir
            fotobitirişte (photo finish) bu olmalı.
    """

    presence_floor: float = 1.4
    decisive_margin: float = 1.2
    compound_floor: float = 2.6
    confidence_scale: float = 4.0
    tau_high: float = 0.55
    tau_low: float = 0.35
    clarify_margin: float = 0.08


@dataclass(frozen=True)
class MemoryPolicy:
    """Konuşma geçmişi saklama sınırları.

    Attributes:
        history_window: Her turda prompt içinde harfiyen tutulan tur sayısı.
        history_raw_cap: Konsolidasyonun bunları özete katmış olması
            gerekmeden önce durumda tutulan ham tur sayısı. Konsolidasyonun
            her zaman elinde taşan (overflow) bir şey olması için
            ``history_window``'u aşmalıdır.
        consolidation_batch_size: Bir model çağrısına değecek minimum yeni
            taşan tur sayısı.
        qa_result_limit: Belge soru-cevabı için getirilen pasaj sayısı.
    """

    history_window: int = 12
    history_raw_cap: int = 40
    consolidation_batch_size: int = 4
    qa_result_limit: int = 4


@dataclass(frozen=True)
class SemanticPolicy:
    """Gömme (embedding) tabanlı prototip katmanı için eşikler.

    Bir anlamsal eşleşmenin işleme alınması için ikisinin de aşılması
    gerekir. Kısa Türkçe cümleler arasındaki kosinüs benzerliği sıkışıktır --
    ilgisiz resmi kayıt cümleleri rutin olarak 0.6 civarında oturur -- bu
    yüzden tek başına mutlak bir eşik sürekli tetiklenirken, tek başına bir
    marj da tesadüfen farklılaşan iki eşit derecede kötü eşleşmede tetiklenir.

    ``evaluation/datasets/intents.jsonl``'a karşı gerçek nomic-embed-text
    vektörleriyle kalibre edilmiştir. Ölçüm nettir: doğru kararlar 0.859 ve
    0.880 puan alırken, 0.747-0.758 bir yazı-tura gibidir (biri doğru, üçü
    yanlış) ve gerçekten eksik belirtilmiş her mesaj en fazla 0.740'a
    ulaşır. İlk 0.72 değeri gürültü bandının içinde kalıyordu ve üç doğru
    karara karşı üç yanlış karar üretiyordu -- rastgele karar veren bir
    katman, katman hiç olmamasından daha kötüdür, çünkü yanlış anladığı
    mesajlar daha önce doğru anlayabilecek bir modele yükseltiliyordu.

    0.80, güvenli bandın (0.758 -> 0.859) kenarı değil ortasıdır. Yalnızca
    son hatayı geçen noktayı seçmek, on beş vakalık bir örneklemde yalnızca
    0.002'lik bir pay bırakırdı.

    Attributes:
        decisive_similarity: Kazanan sınıfa minimum kosinüs benzerliği.
        decisive_margin: İkinciye karşı minimum fark. Kalibre edilmiş
            benzerlikte bağlayıcı değildir -- ayakta kalan her iki karar da
            bunu rahatça geçer (0.154, 0.098) -- ama iki eşit derecede iyi
            eşleşmenin yuvarlamayla ayrılmaması için korunur.
    """

    decisive_similarity: float = 0.80
    decisive_margin: float = 0.04


@dataclass(frozen=True)
class BudgetPolicy:
    """Dengeli akıl yürütme seviyesinde düğüm başına zaman bütçeleri.

    Attributes:
        node_seconds: Düğüm adı -> bütçe. Her anahtar bir yerde bir düğüm
            tarafından tüketilmelidir; kullanılmayan bir girdi, birinin
            uygulandığına inandığı ama aslında uygulanmayan bir bütçedir.
        workflow_ceiling_seconds: Ölçeklenmiş hiçbir düğüm bütçesinin
            aşamayacağı, tüm iş akışına ait zaman aşımı.
    """

    node_seconds: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType(
            {
                "analyze": 140.0,
                "retrieve_mevzuat": 25.0,
                "suggest_mevzuat": 70.0,
                "route": 45.0,
                "writer": 180.0,
                "assist": 70.0,
                # GUARDRAIL_JUDGE_TIMEOUT_SECONDS'ı (varsayılan 15.0s)
                # rahatça aşmalıdır: düğüm seviyesindeki zaman aşımı, yargıç
                # çağrısının kendi iç zaman aşımına karşı yarışı kaybetmelidir;
                # aksi halde tüm düğüm, yargıcın zarifçe None'a düşüp düğümün
                # yalnızca deterministik sonuçla bitirmesi yerine, yargılama
                # ortasında iptal edilir.
                "scan_sensitivity": 25.0,
                # retrieve_mevzuat ile aynı bütçe: aynı Qdrant/Ollama gidiş
                # dönüşü ve bir zaman aşımı, taslağı başarısız kılmak yerine
                # sıfır üslup örneğine düşer (bkz. retrieve_examples_node).
                "retrieve_examples": 25.0,
                # retrieve_examples ile aynı Qdrant/Ollama gidiş dönüşü, ama
                # bunun yerine document_qa koleksiyonuna karşı -- bir zaman
                # aşımı sıfır kaynak alıntısına düşer (yazar hâlâ analiz
                # adımının kendi özetine sahiptir), başarısız bir taslağa
                # değil (bkz. retrieve_source_chunks_node).
                "retrieve_source_chunks": 25.0,
                # "summarize" girdisi yok: ayrıntılı özetleme
                # (DocumentService.generate_detailed_summary) bir grafik
                # düğümü değil, isteğe bağlıdır (on-demand) ve kendini
                # bunun yerine settings.DETAILED_SUMMARY_TIMEOUT_SECONDS ile
                # sınırlar -- bu projenin 400s rakamının arkasında ölçtüğü
                # gerçek çağrı başına sayılar için o ayarın kendi
                # docstring'ine bakın.
            }
        )
    )
    workflow_ceiling_seconds: float = 480.0


@dataclass(frozen=True)
class GuardrailPolicy:
    """Girdi/çıktı koruma (guardrail) katmanı için eşikler ve rol eşlemesi.

    Attributes:
        sensitivity_block_levels: Bir belgeyi (veya ondan üretilen bir taslağı)
            otomatik olarak ilerlemek yerine ``NEEDS_HUMAN_APPROVAL``'a
            zorlayan ``gizlilik_derecesi`` dereceleri -- ayrı bir mekanizma
            değil, düşük güvenli bir taslağın zaten aldığı yönlendirmenin
            aynısı.
        output_groundedness_threshold: ``output_gate`` bir yardım
            (assist) yanıtını sansürsüz geçirmeden önce, o yanıttan
            çıkarılan iddiaların getirilen kaynak materyale kadar
            izlenebilmesi gereken minimum pay. ``VerificationPolicy.
            min_automated_confidence`` ile aynı kavram, ama 0-100 bir puan
            yerine bir paya ölçeklenmiş, çünkü assist yolunun yeniden
            kullanabileceği bir taslak-kalitesi puanı yok.
        pii_confidence_floor: Bu güvenin altında bir PII deseni eşleşmesi
            bir bulgu değil, gürültü olarak ele alınır (kaydedilir,
            işaretlenmez) -- rastlantısal 11 haneli bir sayının her kısmi
            eşleşmede TCKN işlemesini tetiklemesini engeller.
        judge_echo_overlap_threshold: Koruma yargıcı için
            ``VerificationPolicy.judge_echo_overlap_threshold``'un kavramını
            yeniden kullanır: yargılaması istenen içerikle bu token-örtüşme
            payının üzerinde, bir karar bir yargı değil bir yankıdır ve
            atılır.
        judge_promotion_confidence: Koruma yargıcının (hızlı katman, deseni
            görmeyen bir model çağrısı) "bu hassas okunuyor" kararının
            herhangi bir şey için güvenilmesi öncesinde geçmesi gereken
            minimum güven -- bir girdi belgesini ``requires_review``'a
            yükseltmek (``document_analysis_graph.scan_sensitivity_node``)
            ya da çıktı tarafında, hiç sızıntı olarak ele alınıp
            alınmayacağı (``output_gate.evaluate_response``'un
            ``semantic_leak``'i). Önceki 0.5'ten 0.75'e yükseltildi: düşük
            güvenli bir yargıç tahmini eskiden tek başına bir belgeyi
            insan incelemesine yükseltmeye ya da bir yanıtı doğrudan
            engellemeye yetiyordu; Görev'in hata raporunun adlandırdığı
            açıklanamayan "mesajda PII var, kısıldı" yanlış pozitiflerini
            üreten de buydu -- yargıç ikinci bir görüştür, ikinci bir
            deterministik dedektör değil, ve belirsizliği belirsizlik
            olarak okunmalıdır.
        role_clearance_map: Her ``UserRole``'ün okuyabileceği maksimum
            ``SensitivityLevel``. Her ``UserRole`` üyesinin bir girdisi
            olmalıdır -- atlanmış bir rol "erişim yok" demek değildir,
            ``require_clearance``'ın hiç değerlendiremediği bir roldür ki
            bu bir hatadır, kısıtlayıcı bir varsayılan değil. ADMIN ve
            MANAGER ikisi de tavana eşlenir (bir şirket yöneticisine tam
            erişim güvenilir, tıpkı bir admin gibi); buradaki EMPLOYEE
            girdisi yeni bir çalışanın başladığı *varsayılan* değerdir
            (``UserModel.clearance_level``'ın kendi sütun varsayılanı buna
            uyar) -- ``app.core.permissions.role_checker.clearance_for``,
            bir EMPLOYEE için bu harita girdisi yerine kullanıcı başına bu
            alanı okur, çünkü iki çalışanın meşru olarak farklı erişime
            ihtiyacı olabilir.
        default_sensitivity_level: Hiç gizlilik işareti taşımayan bir
            belgenin (``gizlilik_derecesi`` ``None`` olarak çıkarılmış,
            yani ``SensitivityLevel.UNMARKED``) her erişim kontrolü ve
            getirme-filtresi kararı için hangi seviyede ele alındığı.
            Yalnızca eksik bir dereceyi *doldurur* -- belgenin gerçekte
            taşıdığı bir dereceyi asla düşürmez ve ``UNMARKED``'ın kendisi
            ham çıkarma sonucu olarak asla üzerine yazılmaz (bkz.
            ``app.ai.guardrails.sensitivity.SensitivityAssessment.level``'a
            karşı ``effective_level``'ı): "hiç derece belirtilmedi" ile
            "olumlu olarak sınıflandırılmamış işaretlendi" arasındaki
            ayrım, ``effective_level``'ın alt akışındaki her tüketici
            "işaretsiz" yerine gerçek bir derece görse bile denetim
            izinde kalır.
    """

    sensitivity_block_levels: tuple[SensitivityLevel, ...] = (
        SensitivityLevel.GIZLI,
        SensitivityLevel.COK_GIZLI,
    )
    output_groundedness_threshold: float = 0.75
    pii_confidence_floor: float = 0.6
    judge_echo_overlap_threshold: float = 0.40
    judge_promotion_confidence: float = 0.75
    default_sensitivity_level: SensitivityLevel = SensitivityLevel.TASNIF_DISI
    role_clearance_map: Mapping[UserRole, SensitivityLevel] = field(
        default_factory=lambda: MappingProxyType(
            {
                UserRole.ROOT: SensitivityLevel.COK_GIZLI,
                UserRole.ADMIN: SensitivityLevel.COK_GIZLI,
                UserRole.MANAGER: SensitivityLevel.COK_GIZLI,
                UserRole.EMPLOYEE: SensitivityLevel.HIZMETE_OZEL,
            }
        )
    )


@dataclass(frozen=True)
class DraftPolicy:
    """Taslak yazarı için az-örnekli (few-shot) üslup örneği ve kaynak belge
    getirme.

    Attributes:
        style_examples_enabled: Ana anahtar. False, özellik-öncesi
            davranışı tam olarak yeniden üretir (``retrieve_examples_node``
            Qdrant'a hiç dokunmadan doğrudan boş bir listeye düşer) -- A/B
            ve acil geri alma (rollback) kolu.
        style_example_count: Taslak başına istenen üslup örneği sayısı.
            Bir değil iki: tek bir örnek kendi tuhaflıklarını sanki format
            buymuş gibi öğretir; iki örnek yazarın neyin değiştiğini
            (ifade, uzunluk) neyin yapısal olarak sabit olduğuna (alan
            sırası, kapanış yönü) karşı görmesini sağlar. Yeniden ölçüm
            yapmadan daha da yükseltilmemeli -- daha fazla örnek, aynı
            zamanda ``draft_verifier``'ın ``ornek_sizintisi`` kontrolünün
            yakalaması gereken daha fazla yüzey demektir.
        style_example_char_budget: Getirilen örnek metnin birleşik karakter
            uzunluğu için tavan; bunu aşan durumda önce en uzun örnek
            atılır. Brief + writer.md + örnekler toplamının, Türkçede bile
            ``OLLAMA_NUM_CTX`` (8192 token) içinde rahatça kalması için
            boyutlandırılmıştır; Türkçede ``CHARS_PER_TOKEN_TR`` (2.8)
            aynı metnin İngilizceye göre belirgin biçimde daha fazla token
            tutmasına neden olur.
        source_chunks_enabled: ``draft_graph.retrieve_source_chunks_node``
            için ana anahtar. False, özellik-öncesi davranışı tam olarak
            yeniden üretir (yazar yalnızca analiz adımının kendi özetini
            görür, belge alıntılarını asla görmez) --
            ``style_examples_enabled`` ile aynı A/B ve acil geri alma kolu.
        source_chunk_count: ``document_qa`` koleksiyonundan (assist
            adımının kendi ``search_document`` aracının zaten sorguladığı
            aynı indeks) taslak başına istenen belge alıntısı sayısı.
            ``style_example_count``'un iyice üzerinde boyutlandırılmıştır --
            kaynak belgenin kendisine dayanmak, Görev'in kendi "yalnızca
            özet kullanmak kritik detayların kaybolmasına neden olabilir"
            endişesinin adlandırdığı uydurmaya (fabrication) karşı birincil
            savunmadır; az-örnekli üslup örneği ikincil bir kalite
            artışıdır.
        source_chunk_char_budget: Getirilen alıntıların birleşik karakter
            uzunluğu için tavan, ``style_example_char_budget``'ın oynadığı
            aynı rol -- bunu aşan durumda cümle ortasından kırpmak yerine
            alıntının tamamı atılır (bkz. getirme düğümünün kendisi).
    """

    style_examples_enabled: bool = True
    style_example_count: int = 2
    style_example_char_budget: int = 4000
    source_chunks_enabled: bool = True
    source_chunk_count: int = 6
    source_chunk_char_budget: int = 6000


@dataclass(frozen=True)
class ChunkingPolicy:
    """Bu kod tabanının metni böldüğü iki şey için parça boyutu/örtüşme
    parametreleri: yükleme başına Belge Soru-Cevap indeksi ve çevrimdışı
    mevzuat külliyat indeksi.

    Her iki çift de eskiden dört çağrı noktasına
    (``app.domains.documents.service``, ``app.ai.retrieval.mcp_mevzuat``,
    ``scripts/index_mevzuat.py`` ve ikisinin de beslediği külliyat
    yükleyici) kopyala-yapıştır edilmiş aynı ``1000``/``200`` sabitiydi;
    üçünde "senkron kalmalı" yorumu vardı ama bunu zorlayan bir mekanizma
    yoktu. Bu sınıf o mekanizmadır -- dördü tarafından da okunan tek bir
    gerçek kaynak.

    Kasıtlı olarak parçalayıcılar arasında seçim yapan bir ``strategy``
    alanı yok. Tek üretim parçalayıcısı ``RecursiveChunker``
    (``app.ai.embeddings.chunking.recursive``)'dır; ``SemanticChunker``
    aynı paket içinde vardır ve birim testleri yazılmıştır, ama hiçbir
    üretim çağrı noktasına bağlanmamıştır ve önce yardımcı olduğu
    kanıtlanmadan bağlanmamalıdır -- bugün neden güvenli bir doğrudan
    değiştirme (drop-in) olmadığının somut nedenleri için o modülün kendi
    docstring'ine bakın (yaygın kısaltmaları ve büyük harfli sesli
    harfleri yanlış ele alan bir Türkçe cümle-sınırı regex'i, örtüşmesiz
    sınırsız bir parça boyutu ve ``_index_for_qa``'nın ondan oluşturduğu
    ``[s. N]`` sayfa alıntısını sessizce düşürecek olan, olmayan bir
    ``start_index`` meta verisi). Bu sorunun cevabı ``evaluation``'ın
    getirme (retrieval) paketinde bulunur; bu politika, kullanılmayan bir
    alanla bunu önceden yanıtlayacak yer değildir.

    Attributes:
        qa_chunk_size: Her bir ``document_qa`` parçasının (
            ``retrieve_source_chunks_node`` ve ``search_document`` aracı
            tarafından sorgulanan, yükleme başına Soru-Cevap indeksi)
            karakter uzunluğu. ``evaluation``'ın getirme paketi bunu resmi
            yazışma metni üzerinde gerçek Ollama gömmelerine karşı
            ölçtükten sonra 1000'den 1500'e yükseltildi: 1000/200'de taban
            çizgisi precision@6=0.84/nDCG@6=0.94 puan alırken, aynı altın
            veride 1500/300 1.00/1.00 puan aldı (bkz.
            ``evaluation/reports/retrieval-baseline.md``) -- daha az ve
            daha büyük parçalar, bir parça sınırına düşen daha az cevap
            anlamına geliyordu. Bu, eski değer altında zaten indekslenmiş
            belgeleri geriye dönük olarak yeniden parçalamaz;
            ``make reset-document-qa`` koleksiyonu temizler, böylece bir
            sonraki analiz onu yeni değer altında yeniden kurar.
        qa_chunk_overlap: Ardışık ``document_qa`` parçaları arasındaki
            karakter örtüşmesi -- bir parça sınırına yayılan bir cevabın
            kaybolmasını engeller.
        mevzuat_chunk_size: Her bir mevzuat külliyat parçasının karakter
            uzunluğu. Kasıtlı olarak ``qa_chunk_size`` ile paylaşılan tek
            bir çift yerine ayrı bir alan olarak tutulur: indeksleme
            işçisi (``app.workers.indexing.index_mevzuat_corpus``) ve BM25
            bağımlılık yolu (``app.ai.retrieval.mcp_mevzuat``,
            ``scripts/index_mevzuat.py``) aynı külliyat metni için bayt
            düzeyinde özdeş parçalar üretmelidir; aksi halde
            ``app.ai.retrieval.fusion.reciprocal_rank_fusion``'ın tam
            eşleşen ``page_content`` yinelenen giderme (dedup) işlemi, iki
            farklı şekilde bölünmüş bir parçayı iki kez sayar. Bu değeri
            değiştirmek, külliyatı işlenmiş (committed) ``mevzuat`` Qdrant
            koleksiyonunda ve ``sparse_vocab.json``'da halihazırda duran
            şeyden farklı bir şekilde yeniden parçalar -- yalnızca bir
            politika düzenlemesi değil, ``scripts/index_mevzuat.py``'nin
            yeniden çalıştırılmasını gerektirir.
        mevzuat_chunk_overlap: Mevzuat külliyat parçaları için karakter
            örtüşmesi; ``mevzuat_chunk_size`` ile aynı yeniden indeksleme
            uyarısı geçerlidir.
    """

    qa_chunk_size: int = 1500
    qa_chunk_overlap: int = 300
    mevzuat_chunk_size: int = 1000
    mevzuat_chunk_overlap: int = 200


@dataclass(frozen=True)
class Policy:
    """Deterministik karar katmanının tam parametre yüzeyi."""

    version: str
    verification: VerificationPolicy = field(default_factory=VerificationPolicy)
    routing: RoutingPolicy = field(default_factory=RoutingPolicy)
    intent: IntentPolicy = field(default_factory=IntentPolicy)
    memory: MemoryPolicy = field(default_factory=MemoryPolicy)
    semantic: SemanticPolicy = field(default_factory=SemanticPolicy)
    budget: BudgetPolicy = field(default_factory=BudgetPolicy)
    guardrail: GuardrailPolicy = field(default_factory=GuardrailPolicy)
    draft: DraftPolicy = field(default_factory=DraftPolicy)
    chunking: ChunkingPolicy = field(default_factory=ChunkingPolicy)

    def check_invariants(self) -> None:
        """Her zaman geçerli olması gereken parametreler arası ilişkileri doğrular.

        İçe aktarma (import) anında çağrılır; bu sayede kendisiyle çelişen
        bir politika, üretimde sessizce yanlış kararlar üretmek yerine
        süreci başarısız kılar.

        Raises:
            ValueError: Herhangi bir değişmez ihlal edildiğinde.
        """
        verification = self.verification
        routing = self.routing

        # İki insan-onayı eşiği, farklı ciddiyet seviyelerinde aynı
        # kavramdır: 70 "incelemeden gönderilebilir", 50 "hiçbir yere
        # yönlendirilemez" demektir. Bunları tersine çevirmek, bir taslağı
        # yönlendirilemeyecek kadar zayıf ve aynı anda gönderilebilecek
        # kadar iyi yapardı.
        if routing.human_approval_score_threshold >= verification.min_automated_confidence:
            raise ValueError(
                "routing.human_approval_score_threshold must stay below "
                "verification.min_automated_confidence"
            )

        for name, value in (
            ("token_overlap_threshold", verification.token_overlap_threshold),
            ("judge_echo_overlap_threshold", verification.judge_echo_overlap_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a share in [0, 1]")

        for name, value in (
            ("semantic.decisive_similarity", self.semantic.decisive_similarity),
            ("semantic.decisive_margin", self.semantic.decisive_margin),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a share in [0, 1]")

        if self.intent.compound_floor < self.intent.presence_floor:
            raise ValueError(
                "intent.compound_floor must be at least intent.presence_floor -- a "
                "compound reading cannot need less evidence than a single one"
            )

        for name, value in (
            ("intent.tau_high", self.intent.tau_high),
            ("intent.tau_low", self.intent.tau_low),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a probability in [0, 1]")

        if self.intent.tau_low >= self.intent.tau_high:
            raise ValueError(
                "intent.tau_low must stay below intent.tau_high -- otherwise the "
                "model-call band between them is empty or inverted"
            )

        if not 0.0 <= self.intent.clarify_margin <= 1.0:
            raise ValueError("intent.clarify_margin must be a probability gap in [0, 1]")

        if self.memory.history_raw_cap <= self.memory.history_window:
            raise ValueError(
                "memory.history_raw_cap must exceed memory.history_window so "
                "consolidation always has overflow to fold in"
            )

        ceiling = self.budget.workflow_ceiling_seconds
        for node, seconds in self.budget.node_seconds.items():
            if seconds <= 0:
                raise ValueError(f"budget for node {node!r} must be positive")
            if seconds > ceiling:
                raise ValueError(
                    f"budget for node {node!r} ({seconds}s) exceeds the workflow "
                    f"ceiling ({ceiling}s)"
                )

        guardrail = self.guardrail
        for name, value in (
            ("guardrail.output_groundedness_threshold", guardrail.output_groundedness_threshold),
            ("guardrail.pii_confidence_floor", guardrail.pii_confidence_floor),
            ("guardrail.judge_echo_overlap_threshold", guardrail.judge_echo_overlap_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a share in [0, 1]")

        missing_roles = set(UserRole) - set(guardrail.role_clearance_map)
        if missing_roles:
            raise ValueError(
                "guardrail.role_clearance_map is missing entries for: "
                f"{sorted(role.value for role in missing_roles)}"
            )

        if self.draft.style_example_count <= 0:
            raise ValueError("draft.style_example_count must be positive")
        if self.draft.style_example_char_budget <= 0:
            raise ValueError("draft.style_example_char_budget must be positive")
        if self.draft.source_chunk_count <= 0:
            raise ValueError("draft.source_chunk_count must be positive")
        if self.draft.source_chunk_char_budget <= 0:
            raise ValueError("draft.source_chunk_char_budget must be positive")

        chunking = self.chunking
        for size_name, overlap_name, size, overlap in (
            ("chunking.qa_chunk_size", "chunking.qa_chunk_overlap",
             chunking.qa_chunk_size, chunking.qa_chunk_overlap),
            ("chunking.mevzuat_chunk_size", "chunking.mevzuat_chunk_overlap",
             chunking.mevzuat_chunk_size, chunking.mevzuat_chunk_overlap),
        ):
            if size <= 0:
                raise ValueError(f"{size_name} must be positive")
            if overlap < 0:
                raise ValueError(f"{overlap_name} must not be negative")
            if overlap >= size:
                # Örtüşme, boyuta yetiştiğinde RecursiveCharacterTextSplitter
                # bozulur (neredeyse yinelenen ya da sonsuz örtüşen
                # parçalar) -- bu yalnızca verimsiz değil, geçersiz bir
                # yapılandırmadır.
                raise ValueError(
                    f"{overlap_name} ({overlap}) must be smaller than "
                    f"{size_name} ({size})"
                )
