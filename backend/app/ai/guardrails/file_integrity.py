"""Yüklenen dosyalar için magic-byte doğrulaması ve kaynak tükenmesi önlemleri.

``DocumentService._validate_upload`` (bu modülden önce) yalnızca dosya
uzantısını ve istemcinin bildirdiği ``Content-Type`` başlığını kontrol
ediyordu -- ikisi de yükleyicinin kontrol ettiği string'lerdir ve hiçbiri
baytların gerçekte ne olduğu hakkında bir şey söylemez. ``.docx``'ten
``.doc``'a yeniden adlandırılmış bir dosya (Word'ün eski OLE2 formatı
``ALLOWED_DOCUMENT_EXTENSIONS`` içinde bile değildir -- yalnızca modern
zip tabanlı formatlar arşiv bombası riski taşır) incelenmeden geçer. Bu
modül gerçek baytları okur: içeriğin imzası uzantının iddia ettiğiyle
eşleşiyor mu, ve bir arşivse, tek bir yüklemenin dönüşmesi makul olmayan
bir şeye mi genişliyor.

Tamamen ``requirements.txt``'te zaten bulunan bağımlılıklar üzerine kurulu
(``pypdfium2``, ``Pillow``, standart kütüphanenin ``zipfile``'ı) -- her
yüklemede çalışan bir kontrol için yeni bir bağımlılık eklenmedi.
"""

import io
import logging
import os
import zipfile
from typing import Optional

from pydantic import BaseModel, Field

from app.infrastructure.extractors.base import has_pdf_magic_bytes

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised via patching in tests
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None

try:  # pragma: no cover - exercised via patching in tests
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

#: Gerçek herhangi bir resmi belgeyi rahatça aşacak, ama yine de tek bir
#: yüklemenin zorlayabileceği en kötü durum bellek/CPU'sunu sınırlayacak
#: şekilde seçilmiş üst sınırlar -- belirli bir saldırı örneğine göre
#: ölçülmedi, sadece hiçbir meşru resmi yazışma veya ekin bunlara
#: yaklaşmayacağı kadar cömert.
MAX_PDF_PAGES = 500
MAX_IMAGE_PIXELS = 60_000_000  # ~60 megapixels
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MB
MAX_ARCHIVE_COMPRESSION_RATIO = 100
MAX_ARCHIVE_ENTRIES = 2000

_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "tif", "tiff"})
#: Eski ikili Word formatının dosya imzası (bunun m.10'un antetli kağıdıyla
#: bir ilgisi yok -- bu, belge içeriği değil, konteyner formatıdır).
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
#: Zip ve tüm zip tabanlı Office formatları (docx/xlsx/pptx) tarafından
#: paylaşılır -- burada önemlidir çünkü bu uzantıların hiçbiri
#: ALLOWED_DOCUMENT_EXTENSIONS içinde değildir, dolayısıyla zip tabanlı bir
#: dosya ancak izin verilen uzantılardan birine (".doc") yeniden
#: adlandırılarak gelmiş olabilir.
_ZIP_MAGIC = b"PK\x03\x04"
#: İç içe geçmiş bir arşivi işaret eden arşiv üyesi uzantıları -- bir
#: docx/xlsx üyesi her zaman düz XML'dir, asla başka bir arşiv değildir,
#: dolayısıyla burada biri görünmesi tam olarak bir dekompresyon bombasının
#: dayandığı iç içe geçme eskalasyonudur.
_NESTED_ARCHIVE_SUFFIXES = (".zip", ".docx", ".xlsx", ".pptx", ".rar", ".7z", ".gz")


def _is_image_bytes(content: bytes) -> bool:
    return (
        content[:8] == b"\x89PNG\r\n\x1a\n"
        or content[:3] == b"\xff\xd8\xff"
        or content[:4] == b"II*\x00"
        or content[:4] == b"MM\x00*"
    )


class FileIntegrityResult(BaseModel):
    """Tek bir yükleme üzerindeki magic-byte / kaynak tükenmesi kontrolünün sonucu."""

    ok: bool
    reason: str = Field(default="")


def _check_pdf(content: bytes) -> FileIntegrityResult:
    if pdfium is None:  # pragma: no cover - depends on optional dependency
        # Kontrol edecek bir ayrıştırıcı yok -- çıkarma zinciri zaten kendi
        # iyi hata mesajıyla aşağı akışta aynı şekilde başarısız olacak,
        # bunu burada tekrarlamak yerine oraya geçmesine izin ver.
        return FileIntegrityResult(ok=True)
    try:
        document = pdfium.PdfDocument(content)
        try:
            page_count = len(document)
        finally:
            document.close()
    except Exception as exc:
        return FileIntegrityResult(
            ok=False, reason=f"PDF içeriği ayrıştırılamadı: {exc}"
        )
    if page_count > MAX_PDF_PAGES:
        return FileIntegrityResult(
            ok=False,
            reason=(
                f"PDF sayfa sayısı izin verilen sınırı aşıyor "
                f"({page_count} > {MAX_PDF_PAGES})."
            ),
        )
    return FileIntegrityResult(ok=True)


def _check_image(content: bytes) -> FileIntegrityResult:
    if Image is None:  # pragma: no cover - depends on optional dependency
        return FileIntegrityResult(ok=True)
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        # Pillow'un kendi dokümantasyonuna göre verify() dosya nesnesini
        # başka bir çözümleme için kullanılamaz hale getirir; boyutları
        # güvenle okumak için yeniden aç.
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
    except Exception as exc:
        return FileIntegrityResult(
            ok=False, reason=f"Görsel içeriği ayrıştırılamadı: {exc}"
        )
    pixels = width * height
    if pixels > MAX_IMAGE_PIXELS:
        return FileIntegrityResult(
            ok=False,
            reason=(
                f"Görsel piksel sayısı izin verilen sınırı aşıyor "
                f"({pixels} > {MAX_IMAGE_PIXELS})."
            ),
        )
    return FileIntegrityResult(ok=True)


def _check_archive(content: bytes) -> FileIntegrityResult:
    """Açıldığında saçma bir boyuta ulaşacak zip tabanlı bir yüklemeyi reddet.

    Args:
        content: Zip imzasıyla başladığı zaten doğrulanmış ham baytlar.

    Returns:
        Çok fazla girdi, aşırı büyük açılmış içerik, şüpheli bir sıkıştırma
        oranı veya iç içe geçmiş bir arşiv üyesi durumunda ``ok=False`` --
        dekompresyon bombasının dört klasik biçimi.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                return FileIntegrityResult(
                    ok=False,
                    reason=(
                        f"Arşiv girdi sayısı izin verilen sınırı aşıyor "
                        f"({len(infos)} > {MAX_ARCHIVE_ENTRIES})."
                    ),
                )
            for info in infos:
                if info.filename.lower().endswith(_NESTED_ARCHIVE_SUFFIXES):
                    return FileIntegrityResult(
                        ok=False,
                        reason="Arşiv içinde iç içe geçmiş başka bir arşiv bulundu.",
                    )
            total_uncompressed = sum(info.file_size for info in infos)
            total_compressed = sum(info.compress_size for info in infos) or 1
            if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                return FileIntegrityResult(
                    ok=False,
                    reason=(
                        "Arşivin açılmış boyutu izin verilen sınırı aşıyor "
                        f"({total_uncompressed} > {MAX_ARCHIVE_UNCOMPRESSED_BYTES} bayt)."
                    ),
                )
            ratio = total_uncompressed / total_compressed
            if ratio > MAX_ARCHIVE_COMPRESSION_RATIO:
                return FileIntegrityResult(
                    ok=False,
                    reason=(
                        f"Arşiv sıkıştırma oranı şüpheli derecede yüksek "
                        f"({ratio:.0f}x > {MAX_ARCHIVE_COMPRESSION_RATIO}x)."
                    ),
                )
    except zipfile.BadZipFile as exc:
        return FileIntegrityResult(ok=False, reason=f"Arşiv içeriği bozuk: {exc}")
    return FileIntegrityResult(ok=True)


def check_file_integrity(
    content: bytes, *, file_name: str, content_type: Optional[str] = None
) -> FileIntegrityResult:
    """Bir yüklemenin baytlarının gerçekten iddia ettiği türle eşleştiğini doğrula.

    ``DocumentService._validate_upload`` içindeki mevcut uzantı/MIME
    izin-listesi kontrolünden önce çalışır ve o kontrolün bıraktığı boşluğu
    kapatır: uzantı ve ``Content-Type`` ikisi de yükleyicinin sağladığı
    string'lerdir ve hiçbiri gerçek baytlara karşı doğrulanmaz.

    Args:
        content: Ham yüklenen baytlar.
        file_name: Yalnızca uzantısı için kullanılan orijinal dosya adı.
        content_type: Bildirilen MIME türü (şu anda burada kullanılmıyor --
            izin-listesi kontrolü zaten eşleşen bir uzantıyı veya eşleşen bir
            MIME türünü kabul ediyor, dolayısıyla bu kontrol hangi imzanın
            beklendiğini bilmek için yalnızca uzantıya ihtiyaç duyar).

    Returns:
        İçerik iddia ettiği türle tutarlıysa ve kaynak tükenmesi üst
        sınırları içindeyse ``ok=True``; aksi halde Türkçe bir ``reason``
        ile ``ok=False``.
    """
    extension = os.path.splitext(file_name)[1].lower().lstrip(".")

    if extension == "pdf":
        if not has_pdf_magic_bytes(content):
            return FileIntegrityResult(
                ok=False,
                reason="Dosya uzantısı PDF ancak içerik PDF imzası taşımıyor.",
            )
        return _check_pdf(content)

    if extension in _IMAGE_EXTENSIONS:
        if not _is_image_bytes(content):
            return FileIntegrityResult(
                ok=False,
                reason="Dosya uzantısı görsel ancak içerik geçerli bir görsel imzası taşımıyor.",
            )
        return _check_image(content)

    if extension == "doc":
        # Gerçek eski formattaki .doc, OLE2'dir. Bu uzantı altındaki zip
        # tabanlı bir dosya yalnızca yeniden adlandırılmış bir
        # docx/xlsx/pptx olarak açıklanabilir -- yapısal olarak kabul et,
        # ama gerçek uzantısı bildirilmiş gibi arşiv bombası kontrolünden
        # aynen geçir.
        if content[:8] == _OLE2_MAGIC:
            return FileIntegrityResult(ok=True)
        if content[:4] == _ZIP_MAGIC:
            return _check_archive(content)
        return FileIntegrityResult(
            ok=False,
            reason="Dosya uzantısı DOC ancak içerik tanınan bir belge imzası taşımıyor.",
        )

    if extension == "txt":
        # Baytları aslında gizlenmiş bir ikili format olan bir metin
        # yüklemesi, tam olarak bu modülün var olma nedeni olan sahtecilik
        # boşluğudur.
        if (
            has_pdf_magic_bytes(content)
            or content[:8] == _OLE2_MAGIC
            or content[:4] == _ZIP_MAGIC
            or _is_image_bytes(content)
        ):
            return FileIntegrityResult(
                ok=False,
                reason="Dosya uzantısı TXT ancak içerik ikili bir dosya imzası taşıyor.",
            )
        return FileIntegrityResult(ok=True)

    # Diğer tüm uzantılar, bunun yanında çalıştığı izin-listesi kontrolü
    # tarafından zaten reddedilir; burada doğrulanacak başka bir şey yok.
    return FileIntegrityResult(ok=True)
