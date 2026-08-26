"""Çıkarılan belgeler için sayfa düzeyinde adresleme.

Çıkarma işlemi zaten sayfa başına metin üretiyor (`ExtractedDocument.pages`),
ama şimdiye kadar bu, tek bir string'e düzleştirilip atılıyordu. `PageMap`,
düzleştirilmiş metindeki bir karakter ofsetinden geldiği sayfaya geri
haritalamayı tutar; böylece bir parçanın `start_index`'i (bkz.
`app.ai.embeddings.chunking.recursive.RecursiveChunker`) anonim bir aralık
yerine gerçek bir sayfa numarasıyla etiketlenebilir.
"""

import dataclasses

#: Her çıkarıcının `ExtractedDocument.pages`'i `.text`'e birleştirme şekliyle
#: (bkz. `app/infrastructure/extractors/*.py`) ve
#: `app/domains/documents/service.py`'nin temizlenmiş sayfaları yeniden
#: birleştirme şekliyle eşleşir.
PAGE_SEPARATOR = "\n\n"


@dataclasses.dataclass(frozen=True)
class PageMap:
    """Birleştirilmiş belge metnindeki karakter ofsetlerini sayfa numaralarına eşler."""

    #: Her sayfanın birleştirilmiş metinde başladığı karakter ofseti;
    #: boundaries[i], (i + 1)-inci (1'den başlayarak) sayfanın başladığı yerdir.
    boundaries: tuple[int, ...]

    @property
    def page_count(self) -> int:
        return len(self.boundaries)

    def page_for_offset(self, offset: int) -> int:
        """Birleştirilmiş metindeki bir karakter ofsetinin düştüğü, 1'den başlayan sayfa.

        Args:
            offset: Birleştirilmiş belge metnine göre karakter ofseti.

        Returns:
            1'den başlayan sayfa numarası. Hiç sayfa bilgisi yoksa 1. sayfaya
            varsayılan olarak döner; haritalanmış metnin sonunu aşan bir
            ofset için de bilinen son sayfaya sabitlenir.
        """
        if not self.boundaries:
            return 1
        page = 1
        for index, start in enumerate(self.boundaries):
            if offset < start:
                break
            page = index + 1
        return page


def build_page_map(pages: list[str], separator: str = PAGE_SEPARATOR) -> PageMap:
    """`.text` ile aynı sayfalardan, aynı şekilde birleştirilerek bir `PageMap` inşa eder.

    Args:
        pages: Belge sırasına göre sayfa başına çıkarılmış metin.
        separator: Sayfaların birleştirildiği string -- birleştirilmiş metni
            üreten şeyle eşleşmezse ofsetler kayar.

    Returns:
        Her sayfayı kapsayan bir `PageMap`.
    """
    boundaries: list[int] = []
    cursor = 0
    for page in pages:
        boundaries.append(cursor)
        cursor += len(page) + len(separator)
    return PageMap(boundaries=tuple(boundaries))


def format_anchor(page: int) -> str:
    """Bir sayfa numarasını modele ve kullanıcıya gösterilen atıf biçiminde render eder."""
    return f"[s. {page}]"
