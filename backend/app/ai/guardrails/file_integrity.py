"""Magic-byte file validation and resource-exhaustion safeguards for uploads.

``DocumentService._validate_upload`` (before this module) only checked file
extension and the client-declared ``Content-Type`` header -- both are strings
the uploader controls and neither says anything about what the bytes actually
are. A file renamed from ``.docx`` to ``.doc`` (Word's old OLE2 format is not
even in ``ALLOWED_DOCUMENT_EXTENSIONS`` -- only the modern zip-based formats
carry archive-bomb risk) sails through unexamined. This module reads the
actual bytes: does the content's signature match what the extension claims,
and if it is an archive, does it expand to something a single upload has no
business becoming.

Built entirely on dependencies already in ``requirements.txt``
(``pypdfium2``, ``Pillow``, the standard library's ``zipfile``) -- no new
dependency for a check that runs on every upload.
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

#: Ceilings chosen to comfortably exceed any real official document while
#: still bounding worst-case memory/CPU a single upload can force -- not
#: measured against a specific attack sample, just generous enough that no
#: legitimate resmi yazışma or ek ever approaches them.
MAX_PDF_PAGES = 500
MAX_IMAGE_PIXELS = 60_000_000  # ~60 megapixels
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MB
MAX_ARCHIVE_COMPRESSION_RATIO = 100
MAX_ARCHIVE_ENTRIES = 2000

_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "tif", "tiff"})
#: Old binary Word format's file signature (m.10's letterhead has no bearing
#: on this -- this is the container format, not the document content).
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
#: Shared by zip, and every zip-based Office format (docx/xlsx/pptx) --
#: relevant here because none of those extensions are in
#: ALLOWED_DOCUMENT_EXTENSIONS, so a zip-based file can only have arrived by
#: being renamed to one of the extensions that is (".doc").
_ZIP_MAGIC = b"PK\x03\x04"
#: Archive member extensions that indicate a nested archive -- a docx/xlsx
#: member is always plain XML, never another archive, so one appearing here
#: is exactly the nesting escalation a decompression bomb relies on.
_NESTED_ARCHIVE_SUFFIXES = (".zip", ".docx", ".xlsx", ".pptx", ".rar", ".7z", ".gz")


def _is_image_bytes(content: bytes) -> bool:
    return (
        content[:8] == b"\x89PNG\r\n\x1a\n"
        or content[:3] == b"\xff\xd8\xff"
        or content[:4] == b"II*\x00"
        or content[:4] == b"MM\x00*"
    )


class FileIntegrityResult(BaseModel):
    """Outcome of a magic-byte / resource-exhaustion check on one upload."""

    ok: bool
    reason: str = Field(default="")


def _check_pdf(content: bytes) -> FileIntegrityResult:
    if pdfium is None:  # pragma: no cover - depends on optional dependency
        # No parser available to check with -- the extraction chain will
        # fail identically downstream with its own, already-good error
        # message, so let it through to that rather than duplicating it here.
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
        # verify() leaves the file object unusable for further decoding per
        # Pillow's own docs; reopen to read dimensions safely.
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
    """Reject a zip-based upload that would decompress to something absurd.

    Args:
        content: Raw bytes already confirmed to start with the zip signature.

    Returns:
        ``ok=False`` on too many entries, an oversized decompressed payload,
        a suspicious compression ratio, or a nested archive member -- the
        four classic decompression-bomb shapes.
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
    """Validate that an upload's bytes actually match its claimed type.

    Runs before the existing extension/MIME allow-list check in
    ``DocumentService._validate_upload`` closes the gap that check leaves
    open: extension and ``Content-Type`` are both strings the uploader
    supplies and neither is verified against the actual bytes.

    Args:
        content: Raw uploaded bytes.
        file_name: Original file name, used only for its extension.
        content_type: Declared MIME type (currently unused here -- the
            allow-list check already accepts either a matching extension or
            a matching MIME type, so this check only needs the extension to
            know which signature to expect).

    Returns:
        ``ok=True`` when the content is consistent with its claimed type and
        within the resource-exhaustion ceilings; ``ok=False`` with a Turkish
        ``reason`` otherwise.
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
        # Genuine old-format .doc is OLE2. A zip-based file under this
        # extension is only explicable as a renamed docx/xlsx/pptx -- accept
        # it structurally, but archive-bomb check it exactly as if its real
        # extension had been declared.
        if content[:8] == _OLE2_MAGIC:
            return FileIntegrityResult(ok=True)
        if content[:4] == _ZIP_MAGIC:
            return _check_archive(content)
        return FileIntegrityResult(
            ok=False,
            reason="Dosya uzantısı DOC ancak içerik tanınan bir belge imzası taşımıyor.",
        )

    if extension == "txt":
        # A text upload whose bytes are actually a disguised binary format
        # is exactly the spoofing gap this module exists to close.
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

    # Any other extension is already rejected by the allow-list check this
    # runs alongside; nothing further to validate here.
    return FileIntegrityResult(ok=True)
