import logging
from typing import Any, AsyncIterator, Optional

from langchain_core.runnables import RunnableConfig

from app.ai.agents.base import BaseAgent
from app.ai.identity.company_profile import CompanyProfile
from app.ai.identity.injection import format_agent_identity, format_user_address
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager
from app.ai.tools.registry import ToolSpec, to_langchain_tool
from app.observability.ai_metrics import LLM_TOKENS

logger = logging.getLogger(__name__)

#: İki araç turu, daha fazla değil. Her tur tam bir yerel üretimdir; iki tur
#: sonunda hâlâ bir yanıta yakınsamamış bir istek, üçüncü bir veri noktasına
#: ihtiyaç duyan bir modelden çok tekrar tekrar sorgulayan bir model olma
#: ihtimali daha yüksektir ve üçüncü bir deneme, bundan nadiren fayda gören
#: bir vaka için "assist" node'unun zaman bütçesini patlatır.
MAX_TOOL_TURNS = 2


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
        # MAX_TOOL_TURNS bir araç çağrısı beklerken tükendi ya da hiç araç
        # bağlanmadı) None bırakılır; böylece bunlar tam olarak eskisi gibi
        # aşağıdaki gerçek stream() çağrısına düşmeye devam eder.
        final_response_content: Optional[str] = None
        for _ in range(MAX_TOOL_TURNS if lc_tools else 0):
            try:
                response = await self.llm_client.generate_with_tools(
                    messages=messages, tools=lc_tools, temperature=0.2
                )
            except Exception:
                logger.exception("AssistantAgent tool-call turn failed")
                break

            if not response.tool_calls:
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
