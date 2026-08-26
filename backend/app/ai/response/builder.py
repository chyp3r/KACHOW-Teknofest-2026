"""Output gate üzerinde geriye dönük uyumlu bir sarmalayıcı (wrapper).

``evaluate_response`` (``app.ai.guardrails.output_gate``) artık gerçek
kapıdır: enjeksiyon-yankı kontrolü, dayanaklılık ve PII sızıntısı, tek bir
yerde. Bu modülün ``build_response``/``FALLBACK_REPLY``'si yalnızca var olan
her çağıranın ve testin zaten kullandığı genel yüzey olduğu için tutuluyor --
``planning_graph._run_assist`` artık doğrudan ``evaluate_response``'u çağırıyor
ve ona bu iki değerli sarmalayıcının yer bulamadığı gerçek kaynak
materyallerini ve hassasiyet bağlamını geçiriyor.
"""

import logging

from app.ai.guardrails.output_gate import FALLBACK_REPLY, evaluate_response

logger = logging.getLogger(__name__)

__all__ = ["FALLBACK_REPLY", "build_response"]


def build_response(reply: str) -> tuple[str, bool]:
    """Kaynak/hassasiyet bağlamı olmadan bir yanıtı doğrular ve sonlandırır.

    Args:
        reply: Ham, zaten üretilmiş yanıt.

    Returns:
        Bir ``(text, flagged)`` çifti. Her kontrolü geçtiğinde ``text``,
        ``reply`` ile değişmeden aynıdır, aksi halde kapının düzenlenmiş/yer
        değiştirmiş metnidir. ``flagged``, kapının eylemi ``"pass"`` olmadığında True'dur.
    """
    verdict = evaluate_response(reply)
    if verdict.action != "pass":
        logger.warning("Reply flagged by the output gate (%s); replaced.", verdict.action)
    return verdict.text, verdict.action != "pass"
