import logging
import re
from typing import Any, AsyncIterator, Optional

from langchain_core.runnables import RunnableConfig

from app.ai.agents.base import BaseAgent
from app.ai.identity.company_profile import CompanyProfile
from app.ai.identity.injection import format_agent_identity, format_user_address
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager
from app.ai.tools.registry import ToolSpec, to_langchain_tool
from app.core.config import settings
from app.observability.ai_metrics import LLM_TOKENS

logger = logging.getLogger(__name__)

#: Yerel (Ollama) modda iki araç turu, daha fazla değil. Her tur tam bir
#: yerel üretimdir; iki tur sonunda hâlâ bir yanıta yakınsamamış bir istek,
#: üçüncü bir veri noktasına ihtiyaç duyan bir modelden çok tekrar tekrar
#: sorgulayan bir model olma ihtimali daha yüksektir ve üçüncü bir deneme,
#: bundan nadiren fayda gören bir vaka için "assist" node'unun zaman
#: bütçesini patlatır.
MAX_TOOL_TURNS_LOCAL = 2

#: Evren'e (çevrimiçi, TEKNOFEST barındırmalı API) bağlıyken daha yüksek bir
#: tavan. Uzak çıkarım yerel bir turdan belirgin biçimde daha hızlıdır, bu
#: yüzden "assist" node'unun zaman bütçesi birkaç araç turunu rahatça
#: kaldırır; bu da modele, yanıt için gereken bilgiye ulaşana kadar farklı
#: araçları (belge erişimi, mevzuat, birim yönlendirme, ...) sırayla deneme
#: alanı verir.
MAX_TOOL_TURNS_EVREN = 5


def _max_tool_turns() -> int:
    """Aktif sağlayıcıya göre araç turu tavanı.

    ``settings.LOCAL_MODE`` yerel Ollama ile Evren arasında seçim yapan aynı
    anahtardır (bkz. ``app.ai.llms._default_provider``); burada onu doğrudan
    okumak, tavanı ``run_stream``'in çağrı imzasını değiştirmeden sağlayıcıya
    bağlar.
    """
    return MAX_TOOL_TURNS_LOCAL if settings.LOCAL_MODE else MAX_TOOL_TURNS_EVREN


#: Düzeltme mesajlarının rolü. ``system`` OLAMAZ, iki bağımsız sebeple:
#:
#: 1. Evren'in vLLM sunucusu konuşmanın ortasındaki bir sistem turunu 400 ile
#:    reddeder ("System message must be at the beginning") -- turun tamamı
#:    "Yanıt üretilemedi" ile düşer.
#: 2. ``BaseAgent._prepare_messages`` zaten tam olarak bir sistem mesajı
#:    garanti eder ve çağıranın gönderdiği sistem turlarını atar: o slot
#:    ajanın kendisine aittir.
#:
#: Dolayısıyla bir ``user`` turu, ama içeriği :data:`_NUDGE_PREFIX` ile
#: kullanıcıdan gelmediğini söyleyerek başlar -- bu işaret olmadan model
#: düzeltmeyi kullanıcının gerçek isteği sanıp konuşma diliyle cevaplıyor,
#: yani "Şimdi de ... kontrol edelim:" gibi bir arama planı yazıyordu. Plan
#: metninin kullanıcıya ulaşmasına karşı asıl koruma yine de rol değil,
#: aşağıdaki :data:`_NARRATION_PATTERN`'dir.
_NUDGE_ROLE = "user"

#: Her düzeltme mesajının başına konan, mesajın kaynağını açıklayan işaret.
_NUDGE_PREFIX = (
    "[SİSTEM UYARISI -- bu mesaj kullanıcıdan gelmedi ve kullanıcıya "
    "gösterilmeyecek] "
)

#: Hiç araç çağırmadan cevap yazmaya çalışan modele verilen düzeltme.
#:
#: Erken pes etme (`_GIVEUP_PATTERN`) korumasının kaçırdığı, daha sık ve daha
#: zararlı olan durum: model evrakta HİÇ arama yapmadan, sistem prompt'undaki
#: analiz özetine dayanarak kendinden emin bir cevap uyduruyor. Bu bir
#: "bulamadım" itirafı gibi okunmadığı için kalıp eşleşmesi onu yakalamaz --
#: yakalanan tek sinyal, araç çağrısı sayısının sıfır olmasıdır.
#:
#: Son cümle bilerek var: yüklü evrakla ilgisi olmayan meta sorular ("bu
#: sistemde neler yapabilirim", "az önce ne sordum") da bu düzeltmeyi görür ve
#: bu izin olmadan model onları da evrakta aramaya çalışırdı.
_NO_RETRIEVAL_NUDGE = (
    _NUDGE_PREFIX
    + "Yazmak üzere olduğun yanıt iptal edildi ve kullanıcıya "
    "gösterilmedi: yüklü evrakta hiç arama yapmadan yazılmıştı. Sistem "
    "yönergesindeki özet bir cevap kaynağı değildir. Soruya en uygun arama "
    "aracını şimdi çağır ve cevabı evraktan getir. Araç çağrısının yanına "
    "açıklama, plan veya 'şimdi şunu kontrol edelim' türü bir metin YAZMA. "
    "Kullanıcının sorusu evrakla ilgili değilse -- sistemin yetenekleri, "
    "konuşmanın geçmişi veya sıradan bir nezaket ifadesiyse -- araç "
    "çağırmadan doğrudan yanıtla."
)

#: Model, cevap yerine bir arama planı yazdığında verilen düzeltme.
#:
#: Bildirilen bozulmanın doğrudan biçimi: model araç çağırmak yerine (ya da
#: çağırmadan önce) "Şimdi de şu kelimeleri kontrol edelim:" diye bir sonraki
#: adımını anlatan bir metin döndürüyor, hiç araç çağrısı olmadığı için döngü
#: bunu nihai yanıt sanıp kullanıcıya gönderiyordu.
_NARRATION_NUDGE = (
    _NUDGE_PREFIX
    + "Bu metin kullanıcıya gösterilmedi. Sıradaki adımını anlatan "
    "cümleler ('şimdi şunu kontrol edelim', 'şu terimleri arayalım', 'bir de "
    "buna bakalım') kullanıcıya gitmez. İki seçeneğin var: aramayı yapacaksan "
    "ilgili aracı yanına hiçbir açıklama yazmadan doğrudan çağır; arama "
    "bittiyse nihai yanıtı yaz -- yalnızca sonuç, varsa sayfa atfıyla, süreç "
    "anlatımı olmadan."
)

#: Bir sonraki adımı duyuran, cevap değil plan olan bir yanıt. Türkçe'nin
#: istek kipi ("kontrol edelim", "bakalım", "arayalım") bu bozulmanın en
#: güvenilir işareti; ``\w{0,3}`` araya giren kaynaştırma harfini
#: ("araYalım", "inceleYelim") soğurur.
_NARRATION_PATTERN = re.compile(
    r"\b(?:kontrol\s+ed|gözden\s+geçir|karşılaştır|araştır|incele|doğrula|"
    r"tara|dene|bak|ara)\w{0,3}(?:elim|alım|eyim|ayım)\b"
    r"|^\s*şimdi\s+de\b"
    r"|\bbir\s+sonraki\s+adım",
    re.IGNORECASE | re.MULTILINE,
)


def _looks_like_narration(text: Optional[str]) -> bool:
    """Yanıt, bir cevap değil bir sonraki arama adımının duyurusu gibi mi okunuyor."""
    return bool(text) and _NARRATION_PATTERN.search(text) is not None


#: Yanıtın sonundaki KAYNAKLAR bloğu (bkz. ``assistant.md``). Bu bloktaki
#: satırlar evraktan BİREBİR alıntılardır, modelin kendi ifadesi değildir --
#: aşağıdaki kalıp kontrollerinden önce çıkarılır, yoksa "...bahsedilmemektedir"
#: diyen bir kaynak cümlesi modelin pes ettiği sanılıp gereksiz bir düzeltme
#: turu tetiklerdi.
_SOURCES_BLOCK_PATTERN = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?[ \t]*KAYNAKLAR[ \t]*(?:\*\*)?[ \t]*:?[ \t]*$.*",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def _without_sources_block(text: Optional[str]) -> str:
    """Modelin kendi yazdığı kısım -- alıntıladığı kaynak satırları hariç."""
    return _SOURCES_BLOCK_PATTERN.sub("", text or "")


#: Düzeltme verilmiş bir turda, nihai yanıtı üreten son ``stream()`` çağrısına
#: eklenen kapanış yönergesi (bkz. ``run_stream``).
_FINAL_ANSWER_INSTRUCTION = (
    _NUDGE_PREFIX
    + "Şimdi kullanıcıya nihai yanıtı yaz. Doğrudan bilginin kendisiyle "
    "başla; 'Belgede ... bilgisi bulunmaktadır/mevcuttur' gibi bir ön duyuru "
    "cümlesi EKLEME -- cevabı vermen bilginin bulunduğunu zaten gösterir. "
    "Bilgi gerçekten yoksa tek cümleyle 'yüklü evrakta bu bilgiye "
    "ulaşılamadı' de. Evraktan gelen her bilgiyi `[1]`, `[2]` gibi numaralı atıfla "
    "işaretle ve yanıtın sonuna KAYNAKLAR bloğunu ekle; her satırda o "
    "bilginin evraktaki BİREBİR cümlesi ve varsa `(s. N)` sayfası olsun "
    "(sistem yönergesindeki biçim). Hangi aramaları yaptığını, hangi "
    "terimleri denediğini veya sırada ne yapacağını ANLATMA; kullanıcı arama "
    "sürecini görmemeli."
)

#: Bir belge ekliyken, model araç çağırmayı bırakıp bu kalıplardan birini
#: içeren bir "bulamadım / bilmiyorum" yanıtıyla turu bitirmeye çalışıyorsa ve
#: henüz erişim (retrieval) bütçesini tüketmemişse, yanıtı kabul etme;
#: denemediği araç/sorguları denemesi için döngüyü sürdür (bkz.
#: ``run_stream``). Bir kaç yanlış pozitif yalnızca bir ekstra tur maliyeti
#: getirir -- kabul edilebilir takas.
_GIVEUP_PATTERN = re.compile(
    "|".join(
        (
            r"bilmiyor",
            r"bulamad",
            r"ulaşamad",
            r"erişemed",
            r"rastlan[ıa]mad",
            r"tespit\s+edemed",
            r"yer\s+alm[ıi]yor",
            r"yer\s+almamakta",
            r"geçmiyor",
            r"geçmemekte",
            r"bulunmuyor",
            r"bulunmamakta",
            r"mevcut\s+değil",
            r"belirtilm(?:emiş|emekte)",
            r"içermiyor",
            r"içermemekte",
            r"söz\s+edilm",
            r"bahsedilm",
            r"herhangi\s+bir\s+bilgi\w*\s+(?:yok|bulun)",
            r"belge\w*\s+\w*\s*yer\s+alm",
            r"evrak\w*\s+\w*\s*(?:yok|bulun\w*may)",
        )
    ),
    re.IGNORECASE,
)

#: "Bulamadım"la turu erken kapatan modele, denemediği yolları hatırlatan ve
#: en az bir arama aracı daha çağırmasını isteyen düzeltme mesajı.
_GIVEUP_RETRY_NUDGE = (
    _NUDGE_PREFIX
    + "Yazmak üzere olduğun 'bulunamadı' yanıtı iptal edildi ve "
    "kullanıcıya gösterilmedi: erişim bütçen dolmadan pes ettin. Henüz "
    "denemediğin bir arama yolunu şimdi dene -- farklı ifadelerle anlamsal "
    "arama, farklı metin kalıpları, üst veri/özet, sayfa dökümü veya ilgili "
    "sayfanın tam metni. İlgili aracı yanına açıklama veya plan yazmadan "
    "doğrudan çağır. Bu da sonuç vermezse nihai yanıtın tek cümle olsun: "
    "'yüklü evrakta bu bilgiye ulaşamadım'. Hangi aramaları veya terimleri "
    "denediğini ANLATMA."
)


def _looks_like_giveup(text: Optional[str]) -> bool:
    """Yanıt, bir arama sonucu değil bir "bulamadım/bilmiyorum" itirafı gibi mi okunuyor."""
    return bool(text) and _GIVEUP_PATTERN.search(text) is not None


def _final_answer_nudge(
    *,
    content: Optional[str],
    require_retrieval: bool,
    has_tools: bool,
    tool_calls_made: int,
    max_tool_turns: int,
) -> Optional[str]:
    """Modelin bitirmek istediği turu reddedip reddetmeyeceğimize karar verir.

    Model araç çağırmayı bırakıp nihai yanıtını yazdığında çağrılır. Üç
    reddetme sebebi var, en güçlüsü önce:

    1. **Cevap değil, plan.** Model bir sonraki arama adımını anlatıyor
       ("şimdi de şu kelimeleri kontrol edelim:") -- bu bir yanıt değildir ve
       araç çağrısı taşımadığı için döngü onu nihai yanıt sanardı. Araç
       çağrısı sayısından bağımsız olarak reddedilir.
    2. **Hiç arama yapılmadı.** Bir belge ekli, gerçek bir soru soruldu ve
       model sıfır araç çağrısıyla cevap yazıyor -- cevabın kaynağı olsa olsa
       sistem yönergesindeki özet ya da modelin kendi uydurması olabilir.
    3. **Erken pes etme.** Model "bulamadım/bilmiyorum" diyor ama erişim
       bütçesini (``max_tool_turns``) henüz tüketmedi.

    Args:
        content: Modelin yazdığı nihai yanıt metni.
        require_retrieval: Bu turda bir belge ekli ve tur, evrakla ilgili
            olabilecek gerçek bir soru mu (bkz. ``run_stream``'in aynı adlı
            parametresi). False ise hiçbir reddetme yapılmaz.
        has_tools: Bu tura bağlanmış en az bir araç var mı -- yoksa modelden
            arama yapmasını istemek anlamsızdır.
        tool_calls_made: Bu turda şimdiye kadar yürütülen araç çağrısı sayısı.
        max_tool_turns: Sağlayıcıya göre erişim bütçesi (bkz.
            ``_max_tool_turns``).

    Returns:
        Modele iletilecek düzeltme mesajı, ya da yanıt kabul edilecekse
        ``None``.
    """
    if not require_retrieval or not has_tools:
        return None
    # Yalnızca modelin kendi yazdığı kısma bakılır; KAYNAKLAR bloğu evraktan
    # birebir alıntıdır ve modelin ne yaptığı hakkında hiçbir şey söylemez.
    prose = _without_sources_block(content)
    if _looks_like_narration(prose):
        return _NARRATION_NUDGE
    if tool_calls_made == 0:
        return _NO_RETRIEVAL_NUDGE
    if tool_calls_made < max_tool_turns and _looks_like_giveup(prose):
        return _GIVEUP_RETRY_NUDGE
    return None


class AssistantAgent(BaseAgent):
    """Sohbet şeklinde yanıt verir, gerektiğinde erişim (retrieval) araçlarına başvurur.

    Önceki ``ChatAgent`` (yalnızca sohbet) ile ``DocumentQAAgent`` (erişim
    temelli, yalnızca belge) ayrımının yerini alır: router daha önce bir
    mesajın ikisinden hangisine ihtiyaç duyduğuna önceden karar vermek zorunda
    kalıyordu, ki bu tam olarak ``intent_rules.py``/``intent_scorer.py``'nin
    bir kısmının hakemlik etmesi için var olduğu karardı. Burada aynı ajan her
    ikisini de ele alır ve modelin kendisi, tur bazında bir yanıtın araç
    çağrısına ihtiyaç duyup duymadığına karar verir -- bkz. ``run_stream``.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        """Asistan ajanını başlatır.

        Args:
            llm_client: LLM sağlayıcı istemcisi. Herhangi bir araç bağlandığında
                ``generate_with_tools``'u desteklemelidir.
            prompt_manager: Opsiyonel prompt yöneticisi override'ı.
        """
        manager = prompt_manager or get_prompt_manager()
        super().__init__(
            llm_client=llm_client,
            name="AssistantAgent",
            description="Sohbet şeklinde yanıt verir, belge/mevzuat sorguları için araçları çağırır.",
            system_prompt=manager.get_template("assistant"),
        )

    async def run_stream(
        self,
        *,
        query: str,
        history: list[dict[str, str]],
        history_summary: Optional[str] = None,
        document_context: Optional[str] = None,
        security_boundary: Optional[str] = None,
        agent_identity: Optional[str] = None,
        user_display_name: Optional[str] = None,
        tools: list[ToolSpec],
        require_retrieval: bool = False,
        config: Optional[RunnableConfig] = None,
        node: str = "assist",
    ) -> AsyncIterator[str]:
        """Araç döngüsünü çalıştırır, ardından nihai yanıtı token token stream eder.

        Args:
            query: Kullanıcının mevcut mesajı.
            history: Önceki konuşma turları (çağıran tarafından zaten pencerelenmiş).
            history_summary: Pencereden daha eski turların kayan özeti.
            document_context: Eklenmiş belgenin kısa açıklaması (başlık/özet),
                sistem prompt'una render edilir; böylece model bir araç
                çağırmadan önce bile bir belgenin ekli olduğunu bilir. Derinliği
                araçların kendisi sağlar; bu yalnızca onlara başvurup
                başvurmayacağına karar vermek için yeterlidir.
            security_boundary: İsteği yapanın yetki seviyesini ve ekli belgenin
                gizlilik düzeyini açıklayan kısa bir Türkçe not (bkz.
                ``app.ai.workflows.planning_graph._build_security_boundary_note``).
                Yalnızca ikincil, prompt seviyesinde bir katman -- sınırı asıl
                uygulayan deterministik kontrollerdir (``document_tools.py``'nin
                erişimde reddi, ``output_gate.py``); bu, bir regex'in
                yakalayamayacağı parafraz durumunu yakalamak için vardır.
            agent_identity: Render edilmiş ``{{agent_identity}}`` metni -- isteği
                yapan şirketin kendi kimliği (bkz.
                ``app.ai.identity.injection.format_agent_identity``) veya
                yapılandırılmış bir şirket profili yoksa sistem varsayılanı.
            user_display_name: Render edilmiş ``{{user_display_name}}`` metni --
                çağırana ismiyle hitap etme talimatı (bkz.
                ``app.ai.identity.injection.format_user_address``) veya isim
                bilinmiyorsa nötr bir yedek.
            tools: Bu tur için bağlanabilir araçlar. Hiçbir şey ekli değilse
                (belge yok, mevzuat erişimcisi yok) boştur -- bu durumda döngü
                tamamen atlanır ve bu düz bir sohbet gibi davranır.
            require_retrieval: Bu turda bir belge ekli ve tur, evrakla ilgili
                olabilecek gerçek bir soru mu (yani bir selamlama/nezaket
                ifadesi değil). True ise modelin nihai yanıtı iki durumda
                reddedilir ve döngü bir düzeltme mesajıyla sürdürülür (bkz.
                ``_final_answer_nudge``): hiç araç çağırmadan cevap yazması,
                ya da erişim bütçesini tüketmeden "bulamadım" demesi.
            config: Bir alt grafiği tetikleyen araç işleyicilerine iletilen ve
                ``tool_call`` ilerleme olaylarını yayınlamak için kullanılan
                çalıştırılabilir yapılandırma.
            node: Bu olayların yayınlandığı SSE node id'si.

        Yields:
            Nihai yanıtın metin parçaları.
        """
        # Ertelenmiş import: app.ai.workflows.events, __init__'i eagerly
        # planning_graph'ı import eden app.ai.workflows paketinin altında
        # yaşar; planning_graph de AssistantAgent'ı import eder -- burada
        # modül seviyesinde bir import, bu modülün kendi sınıf gövdesi
        # tamamlanmadan önce buraya döngüsel olarak geri döner. planner.py'nin
        # BaseAgent'ı modül kapsamında değil bir fonksiyon içinde import
        # etmesinin nedeni de aynıdır.
        from app.ai.workflows.events import emit_tool_call

        context = {
            "history_summary": history_summary
            or "(Bu konuşmada henüz özetlenecek eski mesaj yok.)",
            "document_context": document_context
            or "(Bu turda yüklenmiş bir belge yok.)",
            "security_boundary": security_boundary
            or "Bu oturum için bilinen bir yetki kısıtlaması yok.",
            "agent_identity": agent_identity or format_agent_identity(CompanyProfile.empty("")),
            "user_display_name": user_display_name or format_user_address(None),
        }
        messages = self._prepare_messages(
            [*history, {"role": "user", "content": query}], context=context
        )

        tools_by_name = {tool.name: tool for tool in tools}
        lc_tools = [to_langchain_tool(tool) for tool in tools]

        # Yalnızca bir generate_with_tools turu, elde zaten boş olmayan bir
        # yanıt varken döngüyü temiz bir şekilde (başka araç çağrısı olmadan)
        # bitirdiğinde set edilir -- yakınsamış bir araç turunun yaygın
        # biçimi. Diğer her çıkışta (bir turun kendi çağrısı hata fırlattı,
        # tur tavanı bir araç çağrısı beklerken tükendi ya da hiç araç
        # bağlanmadı) None bırakılır; böylece bunlar tam olarak eskisi gibi
        # aşağıdaki gerçek stream() çağrısına düşmeye devam eder.
        final_response_content: Optional[str] = None
        max_tool_turns = _max_tool_turns()
        tool_calls_made = 0
        nudges = 0
        for _ in range(max_tool_turns if lc_tools else 0):
            try:
                response = await self.llm_client.generate_with_tools(
                    messages=messages, tools=lc_tools, temperature=0.2
                )
            except Exception:
                logger.exception("AssistantAgent tool-call turn failed")
                break

            if not response.tool_calls:
                # Model turu bitirmek istiyor. Cevabı, arama yapmadan ya da
                # erişim bütçesini tüketmeden yazılmışsa kabul etme: atladığı
                # yolları denemesi için bir düzeltme mesajı ekleyip döngüyü
                # sürdür (bkz. _final_answer_nudge). Düzeltme sayısı da
                # tavanla sınırlı, yani en kötü ihtimalle döngü yine
                # max_tool_turns çağrıdan sonra biter.
                nudge = (
                    _final_answer_nudge(
                        content=response.content,
                        require_retrieval=require_retrieval,
                        has_tools=bool(lc_tools),
                        tool_calls_made=tool_calls_made,
                        max_tool_turns=max_tool_turns,
                    )
                    if nudges < max_tool_turns
                    else None
                )
                if nudge is not None:
                    nudges += 1
                    logger.info(
                        "AssistantAgent rejected a final answer written after %d tool "
                        "call(s); nudging the model to use its tools (nudge %d).",
                        tool_calls_made,
                        nudges,
                    )
                    # Reddedilen metin bilerek bağlama EKLENMEZ. Eklendiğinde
                    # iki zararı oluyordu: uydurulmuş cevap ya da arama planı
                    # bağlamda kalıp nihai yanıta sızıyor, ve model o anlatım
                    # üslubunu ("şimdi de şuna bakalım") sürdürüyordu.
                    messages.append({"role": _NUDGE_ROLE, "content": nudge})
                    continue
                final_response_content = response.content
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": response.tool_calls,
                }
            )
            for call in response.tool_calls:
                tool_calls_made += 1
                spec = tools_by_name.get(call["name"])
                await emit_tool_call(config, node, call["name"], call.get("args") or {})
                if spec is None:
                    result = f"Bilinmeyen araç: {call['name']}"
                else:
                    try:
                        result = await spec.handler(**(call.get("args") or {}))
                    except Exception as exc:
                        logger.exception("Assistant tool '%s' failed", call["name"])
                        result = f"Araç çalıştırılırken hata oluştu: {exc}"
                messages.append(
                    {
                        "role": "tool",
                        "content": str(result),
                        "tool_call_id": call.get("id", ""),
                        "name": call["name"],
                    }
                )

        # Araç döngüsünün kendi yanıtı zaten yakınsadığında, aynı şeyi tekrar
        # söylemek için ikinci bir tam üretim geçişine ödeme yapmak yerine onu
        # yeniden kullan: gerçek bir istekte bu, iki Ollama çağrısı ile üç
        # arasındaki farktı ve üçüncüsü, "assist" node'unu node_budget
        # tavanının (app/ai/policy/schema.py) üzerine, önemli olacak sıklıkta
        # itiyordu. Böyle bir yanıt henüz yoksa (bkz. final_response_content'in
        # kendi yorumu) orijinal koşulsuz stream() çağrısına düşer.
        final_chunks: list[str] = []
        if final_response_content:
            final_chunks.append(final_response_content)
            yield final_response_content
        else:
            # Bir düzeltme verildiyse konuşmanın son turları araç sonuçları ve
            # sistem uyarılarıdır; buradan devam eden bir stream, cevabı değil
            # süreci anlatmaya meyleder. Nihai yanıtın ne olması gerektiğini
            # son bir kez söyle -- yalnızca bu durumda, sıradan (düzeltmesiz)
            # yolun davranışı değişmesin.
            if nudges:
                messages.append(
                    {"role": _NUDGE_ROLE, "content": _FINAL_ANSWER_INSTRUCTION}
                )
            async for chunk in self.llm_client.stream(messages=messages, temperature=0.2):
                final_chunks.append(chunk)
                yield chunk

        # Nihai çağrıdan hemen önceki haliyle `messages`e göre ölçülür -- bu
        # turda prompt'un ulaştığı en büyük boyut (araç turları zaten
        # katlanmış), ki bu tam olarak bağlam taşması riski anıdır.
        prompt_text = "\n".join(msg.get("content", "") or "" for msg in messages)
        LLM_TOKENS.labels(agent=self.name, kind="prompt").inc(
            self.llm_client.count_tokens(prompt_text)
        )
        LLM_TOKENS.labels(agent=self.name, kind="completion").inc(
            self.llm_client.count_tokens("".join(final_chunks))
        )
