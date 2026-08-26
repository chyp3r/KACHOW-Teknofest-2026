"""Ucuz, LLM kullanmayan bir sayfa listesi.

"3. sayfayı açıkla" sorusunu yanıtlamak için modelin, sayfa 3'ün var
olduğunu ve kabaca ne içerdiğini okumaya karar vermeden önce bilmesi
gerekir -- bu, bunu üretim çağrısı yapmadan doğrudan çıkarılmış metinden
inşa eder, böylece belgenin kaba şeklini elde etmek hiçbir şeye mal olmaz.
"""

import dataclasses

#: Bir sayfanın önizleme satırının kesilmeden önce izin verilen en uzun hali.
PREVIEW_CHAR_LIMIT = 80


@dataclasses.dataclass(frozen=True)
class PageSummary:
    """Tek bir taslak girdisi: bir sayfa numarası ve ilk boş olmayan satırı."""

    page: int
    preview: str


def build_outline(
    pages: list[str], preview_chars: int = PREVIEW_CHAR_LIMIT
) -> list[PageSummary]:
    """Bir belgenin sayfa metinlerinden, sayfa başına tek satırlık bir taslak inşa eder.

    Args:
        pages: Belge sırasına göre sayfa başına çıkarılmış metin.
        preview_chars: Her sayfanın önizleme satırının maksimum uzunluğu.

    Returns:
        Sırayla, sayfa başına bir `PageSummary`.
    """
    summaries: list[PageSummary] = []
    for index, page_text in enumerate(pages, start=1):
        first_line = next(
            (line.strip() for line in page_text.splitlines() if line.strip()), ""
        )
        summaries.append(PageSummary(page=index, preview=first_line[:preview_chars]))
    return summaries


def format_outline(outline: list[PageSummary]) -> str:
    """Bir taslağı, bir model veya kullanıcının doğrudan okuyabileceği metin olarak render eder.

    Args:
        outline: `build_outline` tarafından inşa edilen taslak.

    Returns:
        Sayfa başına bir satır, ya da hiç sayfa yoksa yedek bir mesaj.
    """
    if not outline:
        return "Bu belge için sayfa bilgisi bulunmuyor."
    return "\n".join(
        f"s.{summary.page}: {summary.preview or '(boş sayfa)'}" for summary in outline
    )
