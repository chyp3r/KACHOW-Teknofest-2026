from dataclasses import dataclass


@dataclass(frozen=True)
class TokenBudget:
    """Bağlam penceresi taşmadan önce bir prompt'un harcayabileceği token sayısı.

    Attributes:
        total: Aktif sağlayıcının bağlam penceresi
            (``BaseLLMClient.context_window`` -- Ollama'da ``OLLAMA_NUM_CTX``,
            Evren'de ``EVREN_NUM_CTX``).
        reserved_for_completion: Modelin kendi cevabı için ayrılan token
            sayısı (genelde çağrının ``max_tokens`` değeri). Tüm pencereyi
            prompt'a harcamak cevaba yer bırakmaz.
    """

    total: int
    reserved_for_completion: int = 0

    @property
    def available(self) -> int:
        """Prompt'un kendisinin kullanabileceği token sayısı."""
        return max(0, self.total - self.reserved_for_completion)
