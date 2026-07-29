from abc import ABC, abstractmethod


class BaseStorage(ABC):
    """Abstract Base Class for all object/file storage clients."""

    @abstractmethod
    async def put_file(self, file_path: str, content: bytes) -> str:
        """Save a file's binary content to storage.

        Args:
            file_path: The destination path/key in the storage.
            content: The file content in bytes.

        Returns:
            A string containing the reference path or URI of the saved file.
        """
        pass

    @abstractmethod
    async def get_file(self, file_path: str) -> bytes:
        """Retrieve a file's content from storage.

        Args:
            file_path: The path/key of the file.

        Returns:
            The file content in bytes.
        """
        pass

    @abstractmethod
    async def delete_file(self, file_path: str) -> bool:
        """Delete a file from storage.

        Args:
            file_path: The path/key of the file.

        Returns:
            True if deletion was successful, False otherwise.
        """
        pass
