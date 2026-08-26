import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama

from app.ai.llms.base import BaseLLMClient, ToolCallResponse
from app.core.config import settings
from app.infrastructure.providers.message_utils import convert_messages

logger = logging.getLogger(__name__)


class OllamaClient(BaseLLMClient):
    """LangChain kullanarak yerel bir Ollama örneğiyle etkileşim kuran istemci.

    Yerel çıkarım için iki özellik önemlidir ve ikisi de daha önce eksikti:

    1. ``num_ctx`` her çağrıda ayarlanır. Ollama'nın varsayılan bağlam
       penceresi 2048 token'dır ve uyarı vermeden *baştan itibaren* kırpar --
       bu da sistem prompt'unu veya belge başlığını sessizce siler. Bunu
       düğüm başına ayarlamak (kodun eskiden yaptığı gibi), diğer her
       düğümü bozuk bırakır.
    2. ``ChatOllama`` örnekleri önbelleklenir. Çağrı başına bir tane
       oluşturmak, her istekte altta yatan HTTP bağlantı havuzunu atardı.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.7,
        reasoning: bool = False,
        max_tokens: int = 4096,
        num_ctx: int | None = None,
        keep_alive: str | None = None,
    ):
        """Ollama istemcisini başlat.

        Args:
            base_url: Yerel Ollama örneğinin çalıştığı URL.
            model: Kullanılacak modelin adı.
            temperature: Üretim için varsayılan sıcaklık.
            reasoning: Modelin düşünme modunu kullanıp kullanmayacağı.
            max_tokens: Varsayılan maksimum üretilen token sayısı.
            num_ctx: Bağlam penceresi boyutu. Varsayılan ``settings.OLLAMA_NUM_CTX``.
            keep_alive: Ollama'nın modeli çağrılar arasında bellekte ne kadar süre tuttuğu.
        """
        self.base_url = base_url
        self.model_name = model
        self.temperature = temperature
        self.reasoning = reasoning
        self.max_tokens = max_tokens
        self.num_ctx = num_ctx if num_ctx is not None else settings.OLLAMA_NUM_CTX
        self.keep_alive = (
            keep_alive if keep_alive is not None else settings.OLLAMA_KEEP_ALIVE
        )
        self._client_cache: dict[tuple, ChatOllama] = {}
        logger.info(
            "Initialized OllamaClient base_url=%s model=%s temperature=%s "
            "reasoning=%s max_tokens=%s num_ctx=%s keep_alive=%s",
            base_url,
            model,
            temperature,
            reasoning,
            max_tokens,
            self.num_ctx,
            self.keep_alive,
        )

    def _build_client(
        self,
        temperature: float,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ChatOllama:
        """Yapılandırılmış bir Ollama istemcisi döndür, parametre seti başına bir tane yeniden kullanarak.

        Args:
            temperature: Bu çağrı için örnekleme sıcaklığı.
            max_tokens: Üretim bütçesi; istemci varsayılanına düşer.
            **kwargs: Ekstra ChatOllama seçenekleri. ``reasoning``,
                ``num_predict`` ve ``num_ctx`` burada tüketilir; geri kalan
                her şey iletilir.

        Returns:
            Önbelleklenmiş veya yeni oluşturulmuş bir ``ChatOllama``.
        """
        reasoning = kwargs.pop("reasoning", self.reasoning)
        num_predict = kwargs.pop(
            "num_predict",
            max_tokens if max_tokens is not None else self.max_tokens,
        )
        num_ctx = kwargs.pop("num_ctx", self.num_ctx)

        # Yalnızca hashlenebilir ekstralar önbellek anahtarına katılabilir;
        # diğer her şey, yanlış yapılandırmayı sessizce paylaşmak yerine
        # yeni bir istemci zorlar.
        try:
            extra_key = tuple(sorted(kwargs.items()))
            cacheable = True
        except TypeError:
            extra_key = ()
            cacheable = False

        cache_key = (temperature, num_predict, num_ctx, reasoning, extra_key)
        if cacheable and cache_key in self._client_cache:
            return self._client_cache[cache_key]

        client = ChatOllama(
            base_url=self.base_url,
            model=self.model_name,
            temperature=temperature,
            reasoning=reasoning,
            num_predict=num_predict,
            num_ctx=num_ctx,
            keep_alive=self.keep_alive,
            **kwargs,
        )
        if cacheable:
            self._client_cache[cache_key] = client
        return client

    async def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Yerel Ollama kullanarak bir mesaj listesinden yanıt üret."""
        temp = temperature if temperature is not None else self.temperature

        client = self._build_client(temp, max_tokens, **kwargs)
        lc_messages = convert_messages(messages)

        started = time.perf_counter()
        try:
            response = await client.ainvoke(lc_messages)
        except Exception:
            logger.exception("Error generating response from Ollama")
            raise

        logger.info(
            "Ollama generate model=%s took=%.2fs",
            self.model_name,
            time.perf_counter() - started,
        )
        return str(response.content)

    async def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yerel Ollama kullanarak yanıtı parça parça akıt."""
        temp = temperature if temperature is not None else self.temperature

        client = self._build_client(temp, max_tokens, **kwargs)
        lc_messages = convert_messages(messages)

        try:
            async for chunk in client.astream(lc_messages):
                text = str(chunk.content)
                if text:
                    yield text
        except Exception:
            logger.exception("Error streaming response from Ollama")
            raise

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        response_model: Any,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Bir Pydantic modeline karşı doğrulanmış yapılandırılmış çıktı üret.

        Düşünme modu zorla kapatılır: reasoning token'ları JSON gövdesinden
        önce yayılır, ``num_predict`` bütçesini tüketir ve doğrulanan
        nesneyi rutin olarak kırpar.

        Kütüphanenin ``"json_schema"`` varsayılanı yerine
        ``method="function_calling"`` sabitlenir. İkincisi Ollama'nın yerel
        ``format=<schema>`` gramer-kısıtlı çözümlemesine eşlenir -- ama bu
        yol, özel bir Ollama render/ayrıştırıcı motoru üzerinde çalışan
        modeller için (örn. ``ollama show`` şablonu düz bir ``{{ .Prompt }}``
        geçişi olan ``qwen3.5``) sessizce hiçbir etki yapmaz: Ollama API'sine
        karşı doğrudan doğrulandı ki ``format`` (hem düz ``"json"`` dizesi
        hem de tam bir JSON-schema nesnesi) tamamen görmezden gelindi, aynı
        modellerin ``tools`` dizisiyle oluşturulan bir istek ise iç
        içe/isteğe bağlı alanlar ve enum değerleri dahil tam olarak
        onurlandırıldı. Yerel araç çağırma, bu motorun gerçekten
        uyguladığı yapılandırılmış çıktı yoludur.
        """
        temp = temperature if temperature is not None else self.temperature
        max_tokens = kwargs.pop("max_tokens", None)
        kwargs.setdefault("reasoning", False)
        client = self._build_client(temp, max_tokens, **kwargs)

        lc_messages = convert_messages(messages)

        started = time.perf_counter()
        try:
            structured_llm = client.with_structured_output(
                response_model, method="function_calling"
            )
            result = await structured_llm.ainvoke(lc_messages)
        except Exception:
            logger.exception("Error generating structured response from Ollama")
            raise

        logger.info(
            "Ollama structured model=%s schema=%s took=%.2fs",
            self.model_name,
            getattr(response_model, "__name__", response_model),
            time.perf_counter() - started,
        )
        return result

    async def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ToolCallResponse:
        """``bind_tools`` aracılığıyla bir araç çağırma alışverişinin bir turunu üret.

        `generate_structured`'ın ``method="function_calling"`` ile
        sabitlediği aynı yerel araç çağırma yolunu kullanır -- Ollama
        API'sine karşı doğrudan doğrulandı ki ``format=<schema>``'nin
        sessizce hiçbir etki yapmadığı özel-render'lı modellerde (örn.
        qwen3.5) tam olarak onurlandırılıyor. Düşünme modu, orada olduğu
        aynı nedenle zorla kapatılır: reasoning token'ları araç çağrısı
        yükünden önce gelir ve ondan önce üretim bütçesini tüketebilir.
        """
        temp = temperature if temperature is not None else self.temperature
        kwargs.setdefault("reasoning", False)
        client = self._build_client(temp, max_tokens, **kwargs)
        lc_messages = convert_messages(messages)

        started = time.perf_counter()
        try:
            bound = client.bind_tools(tools)
            response = await bound.ainvoke(lc_messages)
        except Exception:
            logger.exception("Error generating tool-call response from Ollama")
            raise

        logger.info(
            "Ollama generate_with_tools model=%s tool_calls=%d took=%.2fs",
            self.model_name,
            len(response.tool_calls or []),
            time.perf_counter() - started,
        )
        return ToolCallResponse(
            content=str(response.content or ""),
            tool_calls=[
                {
                    "id": call.get("id") or "",
                    "name": call.get("name", ""),
                    "args": call.get("args") or {},
                }
                for call in (response.tool_calls or [])
            ],
        )

    async def warm_up(self) -> bool:
        """Modeli belleğe yükle, böylece ilk gerçek istek soğuk olmaz.

        Returns:
            Model yanıt verdiyse True, Ollama'ya ulaşılamadıysa False.
        """
        try:
            await self._build_client(0.0, 1).ainvoke(
                [HumanMessage(content="ping")]
            )
            logger.info("Warmed up Ollama model '%s'.", self.model_name)
            return True
        except Exception as exc:
            logger.warning(
                "Could not warm up Ollama model '%s': %s", self.model_name, exc
            )
            return False
