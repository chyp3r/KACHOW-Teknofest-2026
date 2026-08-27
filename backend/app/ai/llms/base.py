from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Dict, Any, Optional

#: Türkçe için kalibre edilmiş, token başına karakter sayısı. Sondan eklemeli
#: (aglütinatif) biçimbilim, karakter başına İngilizce'den (~4 karakter/tok)
#: daha fazla alt kelime token'ına bölünür, bu yüzden ödünç alınmış bir
#: İngilizce oran burada sistematik olarak eksik sayım yapardı. Sağlayıcının
#: kesin sayısı değil -- Ollama, keyfi modeller için bir tokenize endpoint'i
#: sunmaz -- ama gerçek, tutarlı bir ölçüm; metnin ``settings.OLLAMA_NUM_CTX``'e
#: göre boyutlandırılması gerektiği her yerde, önceden bir promptun modelin
#: bağlam penceresini taşmaya ne kadar yakın olduğuna dair hiçbir görünürlük
#: sunmayan karakter sayısı/tur sayısı sezgisellerinin yerine kullanılır.
CHARS_PER_TOKEN_TR = 2.8


@dataclass
class ToolCallResponse:
    """Bir araç çağırma alışverişinin akışsız (non-streaming) tek bir turu.

    Attributes:
        content: Modelin araç çağrılarıyla birlikte (veya onların yerine)
            ürettiği metin. Bazı sağlayıcılar bir araç istediğinde bile
            kısa bir yorum üretir; çoğu yalnızca boş içerikli araç
            çağrıları üretir.
        tool_calls: İstenen çağrılar, her biri ``{"id", "name", "args"}``.
            Boş olması, modelin bir araç çağırmak yerine doğrudan yanıt
            vermeyi seçtiği anlamına gelir.
    """

    content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


class BaseLLMClient(ABC):
    """Tüm LLM sağlayıcıları için birleşik bir arayüzü temsil eden soyut temel sınıf."""

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> str:
        """Bir mesaj listesinden yanıt üretir.

        Args:
            messages: Mesaj dict'lerinin listesi (örn. [{"role": "user", "content": "hi"}])
            temperature: Örnekleme sıcaklığı
            max_tokens: Üretilecek maksimum token sayısı
            **kwargs: Sağlayıcıya özel ek parametreler
        """
        pass

    @abstractmethod
    def stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncIterator[str]:
        """Üretilen yanıtı parça parça akıtır (stream).

        Args:
            messages: Mesaj dict'lerinin listesi
            temperature: Örnekleme sıcaklığı
            max_tokens: Üretilecek maksimum token sayısı
            **kwargs: Sağlayıcıya özel ek parametreler
        """
        pass

    @abstractmethod
    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        response_model: Any,
        temperature: Optional[float] = None,
        **kwargs: Any
    ) -> Any:
        """Bir Pydantic modeline karşı doğrulanmış yapılandırılmış çıktı üretir.

        Args:
            messages: Mesaj dict'lerinin listesi
            response_model: Çıktının doğrulanacağı Pydantic model sınıfı
            temperature: Örnekleme sıcaklığı
            **kwargs: Sağlayıcıya özel ek parametreler
        """
        pass

    @abstractmethod
    async def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Any],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> ToolCallResponse:
        """Bir araç çağırma alışverişinin tek bir turunu üretir.

        Akışsız (non-streaming): bir araç çağrısı, aşağı akıştaki herhangi bir
        şey kullanıcıya gösterilmeden önce incelenip yürütülmesi gerektiğinden,
        yalnızca bir araç isteği olabilecek bir turda akıtılacak yararlı
        hiçbir şey yoktur.

        Args:
            messages: Mesaj dict'leri. Olağan ``system``/``user``/
                ``assistant`` rollerinin ötesinde, bir araç döngüsünü devam
                ettiren bir çağıran, bir ``tool_calls`` anahtarı taşıyan bir
                ``assistant`` mesajı (modelin önceki turu) ve
                ``tool_call_id``/``name``/``content`` taşıyan ``tool``
                mesajları (o turun sonuçları) içerebilir.
            tools: Bu sağlayıcının yerel bağlanabilir biçimindeki araç
                şemaları (örn. LangChain destekli bir istemci için
                LangChain ``BaseTool`` örnekleri).
            temperature: Örnekleme sıcaklığı.
            max_tokens: Üretilecek maksimum token sayısı.
            **kwargs: Sağlayıcıya özel ek parametreler.

        Returns:
            Modelin metni (varsa) ve istediği araç çağrıları.
        """
        pass

    @property
    def context_window(self) -> int:
        """Bu sağlayıcının bağlam penceresi (token).

        Bağlam bütçesinin (``TokenBudget.total``) ve sohbetteki bağlam
        doluluk göstergesinin boyutlandığı değer. Varsayılan olarak yerel
        Ollama sınırını (``settings.OLLAMA_NUM_CTX``) döndürür; barındırılan
        sağlayıcılar (Evren) çok daha geniş bir pencere için bunu geçersiz
        kılar.
        """
        from app.core.config import settings

        return settings.OLLAMA_NUM_CTX

    def count_tokens(self, text: str) -> int:
        """``text``'in bağlam penceresine karşı kaç token'a mal olacağını tahmin eder.

        Bir karakter oranı tahmini (bkz. ``CHARS_PER_TOKEN_TR``), sağlayıcının
        kesin sayısı değil. Bir promptun ``settings.OLLAMA_NUM_CTX``'e
        yaklaştığını -- Ollama'nın onu baştan sessizce kırpmasından önce --
        yakalamak için yeterince iyi; daha önce hiç görünürlük yoktu, yalnızca
        karakter sayısı ve tur sayısı vekilleri vardı. Gerçek bir
        tokenizer'a sahip bir sağlayıcı, bunu kesin bir sayımla geçersiz kılabilir.

        Args:
            text: Boyutlandırılacak metin.

        Returns:
            Tahmini token sayısı. Boş/yalnızca boşluk içeren metin için 0.
        """
        stripped = text.strip() if text else ""
        if not stripped:
            return 0
        return max(1, round(len(stripped) / CHARS_PER_TOKEN_TR))

    def _format_prompt(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """Basit bir prompt ve system prompt'u standart bir mesaj listesine biçimlendirmeye yarayan yardımcı."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> str:
        """Bir prompt string'inden doğrudan metin üretmek için kolaylık metodu."""
        messages = self._format_prompt(prompt, system_prompt)
        return await self.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

    def stream_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncIterator[str]:
        """Bir prompt string'inden doğrudan yanıt akıtmak için kolaylık metodu."""
        messages = self._format_prompt(prompt, system_prompt)
        return self.stream(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
