from dataclasses import dataclass


@dataclass(frozen=True)
class TokenBudget:
    """How many tokens a prompt may spend before the context window overflows.

    Attributes:
        total: The model's context window (``settings.OLLAMA_NUM_CTX``).
        reserved_for_completion: Tokens set aside for the model's own answer
            (typically the call's ``max_tokens``). Spending the whole window
            on the prompt would leave no room for the response.
    """

    total: int
    reserved_for_completion: int = 0

    @property
    def available(self) -> int:
        """Tokens the prompt itself may use."""
        return max(0, self.total - self.reserved_for_completion)
