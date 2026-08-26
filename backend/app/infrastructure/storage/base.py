from abc import ABC, abstractmethod


class BaseStorage(ABC):
    """Tüm nesne/dosya depolama istemcileri için soyut temel sınıf."""

    @abstractmethod
    async def put_file(self, file_path: str, content: bytes) -> str:
        """Bir dosyanın ikili içeriğini depoya kaydet.

        Args:
            file_path: Depodaki hedef yol/anahtar.
            content: Byte cinsinden dosya içeriği.

        Returns:
            Kaydedilen dosyanın referans yolunu veya URI'sini içeren bir dize.
        """
        pass

    @abstractmethod
    async def get_file(self, file_path: str) -> bytes:
        """Depodan bir dosyanın içeriğini al.

        Args:
            file_path: Dosyanın yolu/anahtarı.

        Returns:
            Byte cinsinden dosya içeriği.
        """
        pass

    @abstractmethod
    async def delete_file(self, file_path: str) -> bool:
        """Depodan bir dosya sil.

        Args:
            file_path: Dosyanın yolu/anahtarı.

        Returns:
            Silme başarılıysa True, aksi halde False.
        """
        pass
