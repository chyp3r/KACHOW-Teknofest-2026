import asyncio
import logging
import os

from app.infrastructure.storage.base import BaseStorage

logger = logging.getLogger(__name__)


class LocalStorage(BaseStorage):
    """Yol güvenliğiyle yerel dosya sistemini kullanan LocalStorage implementasyonu."""

    def __init__(self, base_dir: str):
        """Yerel depoyu başlat.

        Args:
            base_dir: Dosyaların kaydedileceği kök dizin.
        """
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)
        logger.info(f"Initialized LocalStorage at root: {self.base_dir}")

    def _get_abs_path(self, file_path: str) -> str:
        """Mutlak yolu çözümle ve dizin geçişi saldırılarına karşı koru."""
        abs_path = os.path.abspath(os.path.join(self.base_dir, file_path))
        if not abs_path.startswith(self.base_dir):
            raise ValueError(
                f"Directory traversal detected: path '{file_path}' resolves outside root."
            )
        return abs_path

    async def put_file(self, file_path: str, content: bytes) -> str:
        """Byte'ları eşzamansız olarak yerel dosyaya kaydet."""
        abs_path = self._get_abs_path(file_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        def _write():
            with open(abs_path, "wb") as f:
                f.write(content)

        await asyncio.to_thread(_write)
        logger.debug(f"Saved file locally: {file_path}")
        return file_path

    async def get_file(self, file_path: str) -> bytes:
        """Yerel dosyadan byte'ları eşzamansız olarak oku."""
        abs_path = self._get_abs_path(file_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Local file not found at: {file_path}")

        def _read():
            with open(abs_path, "rb") as f:
                return f.read()

        return await asyncio.to_thread(_read)

    async def delete_file(self, file_path: str) -> bool:
        """Dosyayı yerel dosya sisteminden eşzamansız olarak sil."""
        abs_path = self._get_abs_path(file_path)
        if not os.path.exists(abs_path):
            return False

        def _delete():
            os.remove(abs_path)

        await asyncio.to_thread(_delete)
        logger.debug(f"Deleted file locally: {file_path}")
        return True
