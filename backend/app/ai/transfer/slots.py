"""Fast-tier structured extraction for the `transfer` plan's `transfer_resolve`
step -- the only LLM call anywhere in the transfer flow.

This is parsing, never a decision: the output is a name string and an
optional artifact reference, nothing here is authorization, policy, or
recipient identity. `RecipientResolutionService`/`ArtifactResolutionService`
(both deterministic, both in `app.domains.transfers`) turn these slots into
real candidates; `TransferPolicy` and the mandatory `transfer_gate`
confirmation are what actually decide whether anything moves. A bad
extraction here produces, at worst, a wrong disambiguation list or an
"couldn't find that" reply -- never a wrong transfer, since nothing executes
without a human confirming the *resolved* recipient/artifact the confirmation
card shows, not the raw slot text.
"""

import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.ai.llms.base import BaseLLMClient

logger = logging.getLogger(__name__)


class TransferSlots(BaseModel):
    """What the user's message says about who/what to send, verbatim.

    Every field is `None` when the message doesn't say -- the caller must
    treat an unpopulated slot as "ask" or "fall back to the resolution
    ladder", never as a default.
    """

    recipient_name: Optional[str] = Field(
        default=None,
        description=(
            "Alıcının mesajda geçen adı/kullanıcı adı (örn. 'Ahmet', 'ahmet.yilmaz'). "
            "Mesajda bir kişi belirtilmemişse null."
        ),
    )
    artifact_kind: Optional[str] = Field(
        default=None,
        description=(
            "'draft': mesaj bir taslaktan bahsediyor. 'document': mesaj bir evrak/belgeden "
            "bahsediyor. Belirsizse null -- tahmin etme."
        ),
    )
    artifact_reference: Optional[str] = Field(
        default=None,
        description=(
            "Kullanıcının belirttiği açık bir referans varsa (bir başlık, bir sürüm numarası, "
            "'az önce yazdığım' gibi bir işaret) o metin aynen buraya; hiçbir şey "
            "belirtilmemişse null. Bu bir kimlik değil, sadece ne dediğinin kaydı -- "
            "gerçek eşleşme ArtifactResolutionService'te yapılır."
        ),
    )


async def extract_transfer_slots(llm_client: BaseLLMClient, message: str) -> TransferSlots:
    """Parse `message` into `TransferSlots` with a single fast-tier call.

    Never raises: a failed or malformed call returns an all-`None`
    `TransferSlots`, which `_step_transfer_resolve` treats exactly like a
    message that named nobody and nothing -- it falls through to
    `RecipientResolutionService`/`ArtifactResolutionService`'s own ladders
    (which, for the artifact side, works even with a totally empty
    `artifact_reference`: it just resolves the thread's/user's most recent
    one instead of a named one).
    """
    from app.ai.agents.base import BaseAgent

    agent = BaseAgent(
        llm_client=llm_client,
        name="TransferSlotExtractor",
        description="Bir gönderme isteğinden alıcı adını ve artifact referansını çıkarır.",
        system_prompt=(
            "Kullanıcı bir taslak veya evrakı birine göndermek istiyor. Mesajdan şunları "
            "çıkar: alıcının adı (varsa), gönderilecek şeyin türü (taslak/evrak, belirtilmişse) "
            "ve kullanıcının verdiği açık bir referans (başlık, sürüm, vb.). Hiçbir şeyi tahmin "
            "etme -- mesajda açıkça geçmeyen bir alanı null bırak. Yalnızca yapılandırılmış JSON "
            "döndür, açıklama yazma."
        ),
    )
    try:
        return await agent.run_structured(
            messages=message,
            response_model=TransferSlots,
            temperature=0.0,
            max_retries=1,
        )
    except Exception:
        logger.warning("Transfer slot extraction failed; falling back to empty slots.")
        return TransferSlots()
