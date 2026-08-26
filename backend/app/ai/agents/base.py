import logging
import time
from abc import ABC
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

from pydantic import BaseModel

from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import render_placeholders
from app.observability.ai_metrics import LLM_DURATION, LLM_TOKENS, STRUCT_RETRIES

logger = logging.getLogger(__name__)

#: İki deneme, üç değil. Her tekrar deneme yerelde tam bir üretimi baştan
#: çalıştırır; tüketici donanımda üçüncü deneme, çağıranın toplam gecikme
#: bütçesinden daha fazla duvar-saati harcar ve ikincisinin başarısız olduğu
#: yerde neredeyse hiçbir zaman başarılı olmaz.
DEFAULT_MAX_RETRIES = 2


class BaseAgent(ABC):
    """Çoklu ajan sistemindeki uzmanlaşmış ajanlar için temel sınıf.

    Sorumluluklar:

    1. **Birleşik mesajlaşma** -- tek bir prompt veya bir mesaj geçmişi kabul eder.
    2. **Prompt render etme** -- ``{{variable}}`` yer tutucularını yerine koyar.
       Bu, bilinçli olarak :meth:`str.format` KULLANMAZ: prompt şablonları tek
       süslü parantezli literal JSON örnekleri içerir, bu yüzden ``format`` bunlar
       üzerinde ``KeyError`` fırlatır ve önceki uygulama bu hatayı yutup sessizce
       render edilmemiş bir prompt'u gönderiyordu.
    3. **Guardrail'ler** -- üretim sonrası opsiyonel doğrulayıcılar.
    4. **Gözlemlenebilirlik** -- çağrı başına gecikme loglaması.
    5. **Kendi kendini düzeltme** -- yapılandırılmış çıktı şema doğrulamasında
       başarısız olduğunda hata geri bildirimiyle sınırlı tekrar deneme.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        name: str,
        description: str,
        system_prompt: str,
        validators: Optional[List[Callable[[str], None]]] = None,
    ):
        """Temel Ajan'ı başlatır.

        Args:
            llm_client: BaseLLMClient'a uyan LLM sağlayıcı istemcisi.
            name: Ajanın insan tarafından okunabilir adı (örn. "ClassifierAgent").
            description: Bu ajanın ne yaptığına dair kısa özet.
            system_prompt: İsteğe bağlı ``{{placeholders}}`` içeren temel talimatlar.
            validators: Opsiyonel üretim sonrası doğrulayıcı fonksiyonlar.
        """
        self.llm_client = llm_client
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.validators = validators or []
        logger.info("Initialized Agent [%s]: %s", self.name, self.description)

    def _render_system_prompt(self, context: Optional[Dict[str, Any]] = None) -> str:
        """Sistem prompt'undaki ``{{variable}}`` yer tutucularını yerine koyar.

        Args:
            context: Enjekte edilecek değerler. ``None`` şablonu değiştirmeden döndürür.

        Returns:
            Render edilmiş prompt. Bilinmeyen yer tutucular hata fırlatmak yerine
            olduğu gibi bırakılır; böylece kısmen sağlanmış bir bağlam bile
            sessizce boş bir prompt yerine kullanılabilir bir prompt üretir.
        """
        if not context:
            return self.system_prompt
        return render_placeholders(self.system_prompt, context)

    def _prepare_messages(
        self,
        messages: Union[str, List[Dict[str, str]]],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        """Render edilmiş sistem prompt'unu başa ekleyerek mesaj listesini oluşturur.

        Args:
            messages: Prompt string'i veya mesaj geçmişi listesi.
            context: Sistem prompt şablonuna enjekte edilecek değişkenler.

        Returns:
            Tam olarak bir sistem mesajıyla başlayan bir mesaj listesi.
        """
        prepared = [{"role": "system", "content": self._render_system_prompt(context)}]

        if isinstance(messages, str):
            prepared.append({"role": "user", "content": messages})
        else:
            # Çağıranın sağladığı sistem turlarını at; bu slot ajana aittir.
            prepared.extend(
                msg for msg in messages if msg.get("role") != "system"
            )

        return prepared

    def _record_tokens(self, prepared: List[Dict[str, str]], output: str) -> None:
        """Tamamlanan bir çağrı için ``LLM_TOKENS``'ı artırır.

        Args:
            prepared: Sağlayıcıya gönderilen tam mesaj listesi (bu çağrıda
                prompt'un ulaştığı en büyük boyut -- bir bağlam taşması
                riskinin karşılaştırılması gereken değer).
            output: Üretilen metin.
        """
        prompt_text = "\n".join(msg.get("content", "") for msg in prepared)
        LLM_TOKENS.labels(agent=self.name, kind="prompt").inc(
            self.llm_client.count_tokens(prompt_text)
        )
        LLM_TOKENS.labels(agent=self.name, kind="completion").inc(
            self.llm_client.count_tokens(output)
        )

    async def run(
        self,
        messages: Union[str, List[Dict[str, str]]],
        context: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Ajan çalıştırmasını gerçekleştirir ve metin yanıtını döndürür.

        Args:
            messages: Prompt string'i veya mesaj geçmişi listesi.
            context: Sistem prompt şablonuna enjekte edilecek değişkenler.
            temperature: Üretim sıcaklığı.
            max_tokens: Maksimum token sınırı.
            **kwargs: Ek model/sağlayıcı yapılandırmaları.

        Returns:
            Üretilen metin.

        Raises:
            Exception: Sağlayıcının veya bir doğrulayıcının fırlattığı her ne ise.
        """
        start_time = time.perf_counter()
        prepared = self._prepare_messages(messages, context)

        try:
            response = await self.llm_client.generate(
                messages=prepared,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            for validator in self.validators:
                validator(response)

            self._record_tokens(prepared, response)
            logger.info(
                "Agent [%s] generated %d chars in %.2fs",
                self.name,
                len(response),
                time.perf_counter() - start_time,
            )
            return response
        except Exception:
            logger.exception("Agent [%s] execution failed", self.name)
            raise
        finally:
            LLM_DURATION.labels(agent=self.name, method="run").observe(
                time.perf_counter() - start_time
            )

    async def run_structured(
        self,
        messages: Union[str, List[Dict[str, str]]],
        response_model: type[BaseModel],
        context: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        **kwargs: Any,
    ) -> Any:
        """Ajanı çalıştırır ve çıktıyı bir Pydantic modeline karşı doğrular.

        Başarısızlıkta ajan, eklenen bir düzeltme notuyla tekrar dener. Not, üst
        üste yığılmak yerine bir öncekinin yerine geçer: orijinal uygulama her
        turda aynı listeye ekleme yapıyordu, bu yüzden üçüncü denemeye
        gelindiğinde (potansiyel olarak binlerce token'lık) kaynak belge üç kez
        yeniden gönderiliyordu.

        Args:
            messages: Prompt string'i veya mesaj geçmişi listesi.
            response_model: Çıktının doğrulanacağı Pydantic model sınıfı.
            context: Sistem prompt şablonuna enjekte edilecek değişkenler.
            temperature: Üretim sıcaklığı.
            max_retries: İlki dahil toplam deneme sayısı.
            **kwargs: Ek model/sağlayıcı yapılandırmaları.

        Returns:
            Doğrulanmış bir ``response_model`` örneği.

        Raises:
            Exception: Her deneme başarısız olduysa, sağlayıcının veya
                doğrulamanın verdiği son hata.
        """
        start_time = time.perf_counter()
        base_messages = self._prepare_messages(messages, context)
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            attempt_messages = list(base_messages)
            if last_error is not None:
                attempt_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Önceki yanıtın geçersizdi ve "
                            f"{response_model.__name__} şemasına uymadı. "
                            f"Hata: {last_error}. "
                            "Yalnızca şemaya birebir uyan geçerli bir JSON nesnesi "
                            "üret; açıklama, markdown veya ek metin ekleme."
                        ),
                    }
                )

            try:
                result = await self.llm_client.generate_structured(
                    messages=attempt_messages,
                    response_model=response_model,
                    temperature=temperature,
                    **kwargs,
                )

                for validator in self.validators:
                    validator(result.model_dump_json())

                self._record_tokens(attempt_messages, result.model_dump_json())
                logger.info(
                    "Agent [%s] structured %s ok on attempt %d/%d in %.2fs",
                    self.name,
                    response_model.__name__,
                    attempt,
                    max_retries,
                    time.perf_counter() - start_time,
                )
                if attempt > 1:
                    STRUCT_RETRIES.labels(agent=self.name).inc(attempt - 1)
                LLM_DURATION.labels(agent=self.name, method="run_structured").observe(
                    time.perf_counter() - start_time
                )
                return result
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Agent [%s] structured output invalid on attempt %d/%d: %s",
                    self.name,
                    attempt,
                    max_retries,
                    exc,
                )

        logger.error(
            "Agent [%s] failed structured generation of %s after %d attempts.",
            self.name,
            response_model.__name__,
            max_retries,
        )
        STRUCT_RETRIES.labels(agent=self.name).inc(max_retries)
        LLM_DURATION.labels(agent=self.name, method="run_structured").observe(
            time.perf_counter() - start_time
        )
        raise last_error  # type: ignore[misc]

    def stream(
        self,
        messages: Union[str, List[Dict[str, str]]],
        context: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Ajan yanıtını parça parça (chunk-by-chunk) stream eder.

        Args:
            messages: Prompt string'i veya mesaj geçmişi listesi.
            context: Sistem prompt şablonuna enjekte edilecek değişkenler.
            temperature: Üretim sıcaklığı.
            max_tokens: Maksimum token sınırı.
            **kwargs: Ek model/sağlayıcı yapılandırmaları.

        Returns:
            Metin parçalarının async iterator'ü.
        """
        prepared = self._prepare_messages(messages, context)
        return self.llm_client.stream(
            messages=prepared,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
