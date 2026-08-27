import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_openai import ChatOpenAI

from app.ai.llms.base import BaseLLMClient, ToolCallResponse
from app.core.config import settings
from app.infrastructure.providers.message_utils import convert_messages

logger = logging.getLogger(__name__)

#: ``with_structured_output`` yolları. Tercih edilen ilki; ikincisi araç
#: çağırma sunmayan bir model için yedektir (bkz.
#: ``EvrenClient.generate_structured``).
_FUNCTION_CALLING = "function_calling"
_JSON_SCHEMA = "json_schema"

#: vLLM'in araç çağırma ayrıştırıcısı olmayan bir modelde ``tool_choice``
#: gördüğünde döndürdüğü reddin imzası. Durum kodu değil metin üzerinden
#: eşleştirilir: aynı 400, LiteLLM'in sarmalayıcı mesajının içinden geçerek
#: ulaşır ve ayırt edici olan tek şey bu ifadedir.
_NO_TOOL_PARSER_MARKERS = ("tool-call-parser", "tool_call_parser")


def _lacks_tool_calling(error: Exception) -> bool:
    """Hata, modelin araç çağırmayı hiç sunmadığını mı söylüyor."""
    message = str(error).lower()
    return any(marker in message for marker in _NO_TOOL_PARSER_MARKERS)


class EvrenClient(BaseLLMClient):
    """TEKNOFEST tarafından sağlanan barındırılan çıkarım API'si Evren için istemci.

    OpenAI uyumlu (bearer token, ``/v1/chat/completions``), paylaşılan H200
    donanımında sunulur -- ``OllamaClient``'ın çevrimiçi karşılığı. Aynı
    metod yüzeyi, aynı parametre-seti-başına önbellekleme şekli,
    yapılandırılmış/araç çıktısı için aynı ``method="function_calling"``
    sabitlemesi (Evren'in kendi sorun giderme dokümanları, altta yatan vLLM
    motorunun yerel araç çağırmasının güvenilir yapılandırılmış çıktı yolu
    olduğunu doğrular; Ollama'nın özel-render modellerinin ihtiyaç duyduğu
    aynı takas).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.7,
        reasoning: bool = False,
        max_tokens: int = 4096,
        request_timeout: float | None = None,
    ):
        """Evren istemcisini başlat.

        Args:
            base_url: Evren'in OpenAI uyumlu API kökü, örn.
                ``https://evren-llmapi.ssyz.org.tr/v1``.
            model: Evren'in model takma adlarından biri (örn. "llm-fast",
                "llm-large", "guard", "router").
            api_key: Takım bearer token'ı. Pratikte gereklidir -- Evren
                kimliği doğrulanmamış istekleri reddeder -- ama burada
                doğrulanmaz, bu yüzden eksik bir anahtar istemci
                oluşturulurken değil, ilk gerçek çağrıda Evren'in kendi
                401'iyle başarısız olur.
            temperature: Varsayılan örnekleme sıcaklığı.
            reasoning: Düşünme modunun (``enable_thinking``) istenip
                istenmeyeceği. Evren'in kendi dokümanları bunu caydırır ve
                yeterli ``max_tokens`` payı olmadan etkinleştirildiğinde bir
                başarısızlık modu (boş yanıt, ``finish_reason="length"``)
                belgeler -- buna katılan çağıranlar (DEEP reasoning-level
                ön ayarı) bunun için zaten bütçe ayırır.
            max_tokens: Varsayılan maksimum üretilen token sayısı.
            request_timeout: İstek başına saniye cinsinden zaman aşımı.
                Varsayılan ``settings.EVREN_REQUEST_TIMEOUT_SECONDS`` --
                Evren'in kendi belgelenmiş önerisi (paylaşılan donanımda
                1800s'ye kadar).
        """
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model
        self.temperature = temperature
        self.reasoning = reasoning
        self.max_tokens = max_tokens
        self.request_timeout = (
            request_timeout
            if request_timeout is not None
            else settings.EVREN_REQUEST_TIMEOUT_SECONDS
        )
        self._client_cache: dict[tuple, ChatOpenAI] = {}
        #: Bu modelin desteklediği yapılandırılmış çıktı yolu. İlk reddedilmede
        #: bir kez ``json_schema``'ya düşer (bkz. ``generate_structured``).
        self._structured_method = _FUNCTION_CALLING
        logger.info(
            "Initialized EvrenClient base_url=%s model=%s temperature=%s "
            "reasoning=%s max_tokens=%s timeout=%s",
            base_url,
            model,
            temperature,
            reasoning,
            max_tokens,
            self.request_timeout,
        )

    @property
    def context_window(self) -> int:
        """Evren'in bağlam penceresi (``settings.EVREN_NUM_CTX``, varsayılan 262144)."""
        return settings.EVREN_NUM_CTX

    def _build_client(
        self,
        temperature: float,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ChatOpenAI:
        """Yapılandırılmış bir Evren istemcisi döndür, parametre seti başına bir tane yeniden kullanarak.

        Args:
            temperature: Bu çağrı için örnekleme sıcaklığı.
            max_tokens: Üretim bütçesi; istemci varsayılanına düşer.
            **kwargs: Ekstra seçenekler. ``reasoning`` burada tüketilir ve
                ``enable_thinking``'e çevrilir; geri kalan her şey
                ``ChatOpenAI``'a iletilir.

        Returns:
            Önbelleklenmiş veya yeni oluşturulmuş bir ``ChatOpenAI``.
        """
        reasoning = kwargs.pop("reasoning", self.reasoning)
        num_predict = max_tokens if max_tokens is not None else self.max_tokens

        try:
            extra_key = tuple(sorted(kwargs.items()))
            cacheable = True
        except TypeError:
            extra_key = ()
            cacheable = False

        cache_key = (temperature, num_predict, reasoning, extra_key)
        if cacheable and cache_key in self._client_cache:
            return self._client_cache[cache_key]

        # enable_thinking her çağrıda açıkça gönderilmeli, asla atlanmamalı.
        # Gerçek API'ye karşı canlı doğrulandı: llm-large, bu anahtar
        # tamamen yokken bile yeterince karmaşık bir prompt için
        # düşünme-modunu varsayılan olarak AÇIK bırakır -- üretim writer
        # prompt'uyla (9.7k karakter sistem + 5.3k karakter kullanıcı
        # mesajı) doğrudan tekrarlandı, bu da tüm 2048-token bütçesini
        # gizli reasoning_content'te tüketti ve sıfır gerçek içerikle
        # finish_reason="length" döndürdü. Bu anahtarı atlamak, reasoning'i
        # devre dışı bırakmakla aynı şey değildir, bu yüzden önceki sürüm
        # (yalnızca reasoning=True olduğunda gönderiyordu) varsayılan
        # olarak boş taslaklar üretiyordu. Hem üst düzey hem de vLLM'nin
        # chat_template_kwargs iç içe yazımı gönderilir çünkü Evren'in
        # dokümanları dağıtılan motorun hangisini okuduğunu netleştirmiyor
        # -- canlı doğrulandı ki her ikisi de onurlandırılıyor.
        extra_body: dict[str, Any] = {
            "enable_thinking": reasoning,
            "chat_template_kwargs": {"enable_thinking": reasoning},
        }

        client = ChatOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.model_name,
            temperature=temperature,
            max_tokens=num_predict,
            timeout=self.request_timeout,
            extra_body=extra_body,
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
        """Evren kullanarak bir mesaj listesinden yanıt üret."""
        temp = temperature if temperature is not None else self.temperature

        client = self._build_client(temp, max_tokens, **kwargs)
        lc_messages = convert_messages(messages)

        started = time.perf_counter()
        try:
            response = await client.ainvoke(lc_messages)
        except Exception:
            logger.exception("Error generating response from Evren")
            raise

        logger.info(
            "Evren generate model=%s took=%.2fs",
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
        """Evren kullanarak yanıtı parça parça akıt."""
        temp = temperature if temperature is not None else self.temperature

        client = self._build_client(temp, max_tokens, **kwargs)
        lc_messages = convert_messages(messages)

        try:
            async for chunk in client.astream(lc_messages):
                text = str(chunk.content)
                if text:
                    yield text
        except Exception:
            logger.exception("Error streaming response from Evren")
            raise

    @staticmethod
    async def _invoke_structured(
        client: ChatOpenAI, response_model: Any, lc_messages: Any, method: str
    ) -> Any:
        """Tek bir yapılandırılmış çıktı denemesi, verilen yolla."""
        return await client.with_structured_output(response_model, method=method).ainvoke(
            lc_messages
        )

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        response_model: Any,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Bir Pydantic modeline karşı doğrulanmış yapılandırılmış çıktı üret.

        Düşünme modu, ``OllamaClient`` ile aynı nedenle zorla kapatılır:
        reasoning token'ları JSON gövdesinden önce gelir, token bütçesini
        tüketir, ve Evren'in kendi sorun giderme dokümanları
        yapılandırılmış/kısa çıktılar için tam olarak bu başarısızlık
        modunu (boş içerik, ``finish_reason="length"``) belgeler.

        Tercih edilen yol ``method="function_calling"``'dir
        (``OllamaClient.generate_structured``'ı yansıtarak): yerel araç
        çağırma, vLLM-sunulan Qwen modellerine karşı güvenilir çalıştığı
        doğrulanan yapılandırılmış çıktı yoludur. Ancak Evren'in her modeli
        bunu sunmaz -- ``guard`` dağıtımı araç çağırma ayrıştırıcısı
        olmadan çalışır ve her ``tool_choice`` isteğini 400 ile reddeder
        ("requires --tool-call-parser to be set"). O modelde ısrar etmek,
        guardrail hakemlerinin tamamının sessizce ölü kalması demekti
        (çağıranlar açık başarısız olur, bkz. ``llm_nuance``): PII/sızıntı
        değerlendirmesi hiç çalışmıyordu. Bu yüzden reddedilme
        yakalanır ve istemci, ömrü boyunca ``json_schema``'ya geçer --
        model başına bir kez öğrenilir, her çağrıda tekrar denenmez.
        """
        temp = temperature if temperature is not None else self.temperature
        max_tokens = kwargs.pop("max_tokens", None)
        kwargs.setdefault("reasoning", False)
        client = self._build_client(temp, max_tokens, **kwargs)

        lc_messages = convert_messages(messages)

        started = time.perf_counter()
        try:
            result = await self._invoke_structured(
                client, response_model, lc_messages, self._structured_method
            )
        except Exception as exc:
            if self._structured_method != _FUNCTION_CALLING or not _lacks_tool_calling(exc):
                logger.exception("Error generating structured response from Evren")
                raise
            logger.warning(
                "Evren model '%s' does not support tool calling for structured "
                "output; switching this client to %s for the rest of its life.",
                self.model_name,
                _JSON_SCHEMA,
            )
            self._structured_method = _JSON_SCHEMA
            try:
                result = await self._invoke_structured(
                    client, response_model, lc_messages, _JSON_SCHEMA
                )
            except Exception:
                logger.exception("Error generating structured response from Evren")
                raise

        logger.info(
            "Evren structured model=%s schema=%s took=%.2fs",
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

        Düşünme modu, `generate_structured`'ın kapattığı aynı nedenle
        zorla kapatılır: reasoning token'ları araç çağrısı yükünden önce
        gelir ve ondan önce üretim bütçesini tüketebilir.
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
            logger.exception("Error generating tool-call response from Evren")
            raise

        logger.info(
            "Evren generate_with_tools model=%s tool_calls=%d took=%.2fs",
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
        """No-op: Evren uzak, paylaşılan donanımlı bir servistir.

        Yerel bir Ollama örneğinin aksine, süreç belleğine yüklenecek bir
        model yoktur, ve başlangıçta spekülatif bir istek göndermek,
        hiçbir faydası olmadan hız sınırlı takım kotasının bir kısmını
        harcardı.

        Returns:
            Her zaman True.
        """
        logger.info(
            "Skipping warm-up for Evren model '%s' (remote provider).",
            self.model_name,
        )
        return True
