"""Guardrail nüans katmanı: kalıp için değil, anlam için bir LLM hakemi.

``app.ai.verification.llm_judge``'ın ``draft_verifier.verify_draft`` ile
olan ilişkisiyle aynı: deterministik guardrail katmanı (``pii.py``'nin
regex+checksum'ı, ``sensitivity.py``'nin ``gizlilik_derecesi`` eşlemesi,
``output_gate.py``'nin iddia çıkarımı dayanaklılık kontrolü) yapısal bir
şekli olan her şeyi yakalar. Ancak yalnızca anlam olarak hassas okunan bir
belgeyi (bir izin talebinin metnindeki tıbbi bir detay, bir şikayette
bağlamdan anlaşılan bir muhbirin kimliği) veya hiç harfiyen bir PII
string'i üretmeden gizli bir gerçeği sızdıran bir yanıtı yakalayamaz.
Bunlar string eşleştirme değil, muhakeme gerektirir; bu yüzden bu modül
bunlar için fast-tier modele küçük, tek bir yapılandırılmış çağrı ekler --
bu kod tabanının taslak kalitesi için zaten bir kez yaptığı takasla aynısı.

Hakemin, yargıladığı içeriği yeniden üretmesine bilerek izin verilmez:
``GuardrailJudgeVerdict.reason`` uzunluk sınırlıdır ve doğrulama sonrası bir
koruma, metni yargılanan içerikle güçlü şekilde örtüşen bir verdikti
reddeder (``llm_judge._reject_draft_echo`` ile aynı teknik). İçeriği geri
yansıtan bir model onu yargılamıyor demektir ve tekrar denemesini istemek
sadece ikinci bir yansımayla sonuçlanır -- bu yüzden bir yansıma, yeniden
deneme değil, bozulmuş bir çağrı olarak ele alınır.

Buradaki her giriş noktası açık başarısız olur (fail open): bir zaman
aşımı, bir şema hatası, bir sağlayıcı hatası veya tespit edilen bir yansıma
hepsi ``None`` döner ve çağıran, yavaş veya kullanılamayan bir Ollama
örneği yüzünden isteği engellemek yerine yalnızca-deterministik verdikte
geri döner (çözümlenmiş politika kararı -- kapsamlı olmaktan önce
kullanılabilir olmak gelir).
"""

import asyncio
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.ai.agents.guardrail_judge import GuardrailJudgeAgent
from app.ai.policy import get_policy
from app.ai.verification.draft_verifier import _fold
from app.core.config import settings
from app.observability.ai_metrics import GUARDRAIL_JUDGE_FAILURES

logger = logging.getLogger(__name__)

#: Bir verdiktin kendi token'larının bu orandan fazlası yargılanan içerikte
#: görünüyorsa, verdikti bir yargı değil, bir yansıma olarak ele al.
_ECHO_OVERLAP_THRESHOLD = get_policy().guardrail.judge_echo_overlap_threshold

#: Bundan daha uzun metin, prompt'a ulaşmadan önce kısaltılır -- hakemin
#: üzerinde muhakeme yapacak kadarına ihtiyacı vardır, tüm belgenin/yanıtın
#: birebir aynısına değil (bu ayrıca bir yansımanın korumadan sıyrılmasını
#: da çok daha olası kılardı).
_MAX_JUDGED_TEXT_CHARS = 4000


class GuardrailJudgeVerdict(BaseModel):
    """Guardrail hakeminin yapılandırılmış verdikti. Hiçbir alan yargılanan içeriği taşıyamaz."""

    sensitive: bool = Field(
        description="İçerik anlam olarak hassas/sızıntı riski taşıyor mu."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=300, description="Kısa gerekçe; içerik metnini tekrar üretme.")


def _reject_echo(verdict: GuardrailJudgeVerdict, judged_text: str) -> bool:
    """Yargılamak yerine yargılanan içeriği yansıtan bir verdikti tespit et.

    Args:
        verdict: Aday verdikt.
        judged_text: Değerlendirmesi gereken belge veya yanıt metni.

    Returns:
        Verdiktin gerekçesi, yargılanan metinle güvenilemeyecek kadar
        güçlü örtüşüyorsa True.
    """
    content_tokens = set(_fold(judged_text).split())
    if not content_tokens:
        return False

    reason_tokens = [token for token in _fold(verdict.reason).split() if len(token) > 2]
    if len(reason_tokens) < 6:
        return False

    overlap = sum(1 for token in reason_tokens if token in content_tokens) / len(reason_tokens)
    return overlap > _ECHO_OVERLAP_THRESHOLD


async def _run_judge(
    agent: GuardrailJudgeAgent,
    *,
    prompt: str,
    judged_text: str,
    timeout_s: Optional[float],
) -> Optional[GuardrailJudgeVerdict]:
    """Her iki yargılama görevi için paylaşılan çağrı/bozulma yolu. Asla fırlatmaz.

    Args:
        agent: Oluşturulmuş bir :class:`GuardrailJudgeAgent` (fast-tier istemci).
        prompt: Göreve özgü tam prompt (aşağıdaki iki genel fonksiyona bakın).
        judged_text: Yargılanan ham metin, yalnızca anti-yansıma kontrolü
            için kullanılır -- verdiktte asla geri gönderilmez.
        timeout_s: Kesin zaman aşımı; varsayılan
            ``settings.GUARDRAIL_JUDGE_TIMEOUT_SECONDS``.

    Returns:
        Verdikt, veya zaman aşımı, şema hatası, sağlayıcı hatası ya da
        tespit edilen bir yansıma durumunda ``None``.
    """
    if not settings.GUARDRAIL_JUDGE_ENABLED:
        return None

    timeout = timeout_s if timeout_s is not None else settings.GUARDRAIL_JUDGE_TIMEOUT_SECONDS

    try:
        verdict: GuardrailJudgeVerdict = await asyncio.wait_for(
            agent.run_structured(
                messages=prompt,
                response_model=GuardrailJudgeVerdict,
                temperature=0.0,
                max_retries=1,
            ),
            timeout=timeout,
        )
        # Sadece çağrının kendisini değil, yansıma kontrolünü de kapsar --
        # bu fonksiyon asla fırlatmayacağını taahhüt eder ve hatalı
        # biçimlendirilmiş/mocklanmış bir verdikt (eksik alanlar, yanlış
        # türler) bir zaman aşımı veya sağlayıcı hatasıyla aynı şekilde
        # bozulmalı, dışarı yayılıp çağıran düğümü de birlikte
        # çökertmemelidir.
        if _reject_echo(verdict, judged_text):
            logger.warning(
                "Guardrail judge verdict echoed the judged content; treating as degraded."
            )
            GUARDRAIL_JUDGE_FAILURES.labels(reason="echo").inc()
            return None
    except asyncio.TimeoutError:
        logger.warning("Guardrail judge timed out after %.0fs; degrading.", timeout)
        GUARDRAIL_JUDGE_FAILURES.labels(reason="timeout").inc()
        return None
    except Exception:
        logger.exception("Guardrail judge call failed; degrading.")
        GUARDRAIL_JUDGE_FAILURES.labels(reason="exception").inc()
        return None

    return verdict


async def judge_input_sensitivity(
    agent: GuardrailJudgeAgent,
    *,
    text: str,
    timeout_s: Optional[float] = None,
) -> Optional[GuardrailJudgeVerdict]:
    """Bir belgenin, kalıp olmasa bile anlam olarak hassas okunup okunmadığını sor.

    Args:
        agent: Oluşturulmuş bir :class:`GuardrailJudgeAgent`.
        text: Değerlendirilecek belge metni.
        timeout_s: Kesin zaman aşımı geçersiz kılması.

    Returns:
        Verdikt, veya çağrı bozulduysa ``None`` -- çağıranlar yalnızca
        deterministik ``SensitivityAssessment``'e geri döner.
    """
    if not text.strip():
        return None

    truncated = text[:_MAX_JUDGED_TEXT_CHARS]
    prompt = (
        "GÖREV: GİRDİ HASSASİYET DEĞERLENDİRMESİ\n\n"
        "### DEĞERLENDİRİLECEK BELGE METNİ:\n"
        f"{truncated}"
    )
    return await _run_judge(agent, prompt=prompt, judged_text=truncated, timeout_s=timeout_s)


async def judge_output_leakage(
    agent: GuardrailJudgeAgent,
    *,
    reply: str,
    source_summary: str,
    timeout_s: Optional[float] = None,
) -> Optional[GuardrailJudgeVerdict]:
    """Bir yanıtın, harfiyen bir PII string'i olmadan bir kaynağın anlamını
    sızdırıp sızdırmadığını sor.

    Args:
        agent: Oluşturulmuş bir :class:`GuardrailJudgeAgent`.
        reply: Değerlendirilecek üretilmiş yanıt.
        source_summary: Kaynak materyalin gerçekte açıklanmasına izin
            verdiği şeyin kısa bir açıklaması (örn. belgenin kendi özeti) --
            neredeyse her parafrazı bir eşleşme gibi gösterecek olan tam
            kaynak metni değil.
        timeout_s: Kesin zaman aşımı geçersiz kılması.

    Returns:
        Verdikt, veya çağrı bozulduysa ``None`` -- çağıranlar yalnızca
        deterministik sızıntı kontrolüne geri döner.
    """
    if not reply.strip():
        return None

    truncated = reply[:_MAX_JUDGED_TEXT_CHARS]
    prompt = (
        "GÖREV: ÇIKTI SIZINTI DEĞERLENDİRMESİ\n\n"
        "### KAYNAĞIN İZİN VERDİĞİ BİLGİ ÖZETİ:\n"
        f"{source_summary or '(özet yok)'}\n\n"
        "### DEĞERLENDİRİLECEK YANIT:\n"
        f"{truncated}"
    )
    return await _run_judge(agent, prompt=prompt, judged_text=truncated, timeout_s=timeout_s)
