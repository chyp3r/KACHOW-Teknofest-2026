from abc import ABC, abstractmethod
from typing import Dict, List


class BaseMemory(ABC):
    """Abstract Base Class for Chat and Agent Memory systems."""

    @abstractmethod
    async def get_messages(self, session_id: str, **kwargs) -> List[Dict[str, str]]:
        """Retrieve conversation history messages for a session.

        Args:
            session_id: Unique session identifier.
        """
        pass

    @abstractmethod
    async def add_message(
        self, session_id: str, role: str, content: str, **kwargs
    ) -> None:
        """Add a new message (user/assistant) to the session history.

        Args:
            session_id: Unique session identifier.
            role: The author role ('system', 'user', 'assistant').
            content: The text content of the message.
        """
        pass

    @abstractmethod
    async def clear(self, session_id: str) -> None:
        """Clear all stored messages/memory for a session.

        Args:
            session_id: Unique session identifier.
        """
        pass
