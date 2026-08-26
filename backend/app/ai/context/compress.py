"""Genel ``ContextBlock`` sıkıştırıcıları.

Her fonksiyon ``app.ai.context.builder``'daki ``Compressor`` biçimine
(``(text, budget_tokens) -> text``) sahiptir ve sağlayıcıdan bağımsızdır:
blok, aktif istemcinin tam tahmin edicisine erişemediğinden, bir token
bütçesini karakter bütçesine çevirmek için ``CHARS_PER_TOKEN_TR`` kullanarak
karakterler üzerinde çalışır.
"""

from app.ai.llms.base import CHARS_PER_TOKEN_TR

#: Ayakta kalan baş ve son kısım arasına eklenen işaretçi;
#: `document_analysis_graph._trim_for_extraction`'ın aynı amaçla zaten
#: kullandığı işaretçiyle aynıdır -- bir okuyucu (insan ya da model) onu
#: bir kez gördüğünde ne anlama geldiğini zaten bilir.
ELISION_MARKER = "\n\n[... içeriğin orta kısmı kısaltıldı ...]\n\n"


def truncate_with_marker(text: str, budget_tokens: int) -> str:
    """`text`'in baş ve son kısmını korur, ortasını çıkarır.

    Bir belgenin başlığı ve imza/kapanış bloğu çoğu prompt'un ihtiyaç
    duyduğu alanları taşır; bir şeyden fedakarlık edilmesi gerektiğinde
    kaybedilmesi en güvenli kısım ortadır. Mevcut karakterleri baş ve son
    kısımlar arasında eşit olarak böler.

    Args:
        text: Küçültülecek metin.
        budget_tokens: İçine sığdırılacak token bütçesi.

    Returns:
        Zaten sığıyorsa `text` değişmeden; aksi halde yaklaşık
        `budget_tokens`'a sığacak şekilde baş+son korunmuş, ortası
        çıkarılmış hali.
    """
    budget_chars = max(0, int(budget_tokens * CHARS_PER_TOKEN_TR))
    marker_chars = len(ELISION_MARKER)

    if len(text) <= budget_chars:
        return text
    if budget_chars <= marker_chars:
        return text[:budget_chars]

    remaining = budget_chars - marker_chars
    head_chars = remaining // 2
    tail_chars = remaining - head_chars
    return f"{text[:head_chars]}{ELISION_MARKER}{text[-tail_chars:] if tail_chars else ''}"
