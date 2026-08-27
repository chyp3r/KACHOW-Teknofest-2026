"""Asistan ajanının bir tur için çağırabileceği transfer aracı (Faz 4, #201).

:mod:`app.ai.tools.document_tools` içindeki diğer her aracın aksine, bunu
çağırmak yalnızca metin döndürmek yerine duraklatılmış, insan tarafından
onaylanan bir eyleme yol açabilir. Bu duraklama bilinçli olarak bu aracın
``interrupt()``'ı kendisinin çağırmasıyla **uygulanmaz**: bir araç handler'ı
assist adımının kendi düğümünün içinde çalışır (bkz.
``planning_graph._step_assist``/``_run_assist``) ve ``interrupt()``, devam
ettiğinde sahibi olan *bütün* düğümü baştan tekrar oynatır -- assist adımı
için bu, modelin bütün akışlı yanıtını ve aynı turdaki her önceki araç
çağrısını ikinci kez yeniden çalıştırmak anlamına gelirdi; ``brief_gate``/
``human_gate``'in ödememek için kendi düğümlerine ayrıldığı tam maliyet
(kendi docstring'lerine bakın).

Bu yüzden bu araç yalnızca *önerir*: artefaktı ve alıcıyı deterministik
olarak çözümler ve (``transfer_provider`` aracılığıyla ulaşılan
``TransferIntentService`` üzerinden -- bu modül ``app.ai.*`` altındadır ve
diğer her enjekte edilmiş sağlayıcı çağrı noktası gibi asla doğrudan
``app.domains.*``'ı import etmez) bir ``artifact_transfer_intents`` satırı
açar, sonra sonucu ``on_transfer_proposed`` aracılığıyla ``_step_assist``'e
geri verir -- ``on_anchor_referenced``/``on_tool_result``'ın zaten kullandığı
aynı yan kanal geri çağırım deseni. Turu zorunlu, sunucu tarafından
zorlanan onay için (interrupt için güvenli, ayrı bir düğüm olan)
``transfer_gate_node``'a fiilen yönlendiren şey ``_step_assist``'tir. Bu
handler'ın modele döndürdüğü metin tamamen açıklayıcıdır -- model kendi
yanıtında bu konuda ne söylerse söylesin, transfer yalnızca bir insan
gerçek onay kartında "Onayla"ya tıkladıktan sonra yürütülür ve
``TransferIntentService.execute``, herhangi bir çağıranın (bu araç, model,
graph) ne olduğuna inandığından bağımsız olarak ``CONFIRMED`` olarak
kalıcı hale getirilmemiş hiçbir şeyi reddeder.
"""

from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolSpec


class ProposeTransferArgs(BaseModel):
    """Arguments for the ``propose_transfer`` tool."""

    recipient_name: str = Field(
        description="Kullanıcının belirttiği alıcının adı veya kullanıcı adı."
    )
    artifact_kind: Optional[Literal["draft", "document"]] = Field(
        default=None,
        description=(
            "Gönderilecek şeyin türü: 'draft' (taslak) veya 'document' (evrak). "
            "Kullanıcı açıkça belirtmemişse null bırak -- en son taslak varsayılan olarak kullanılır."
        ),
    )


#: Aracın çözümlediği ve düz metinle yanıtladığı terminal sonuçlar --
#: onaylanacak hiçbir şey yok, bu yüzden `_step_assist` bunlar için asla
#: `transfer_gate`'e yönlendirmez (şimdi kaldırılmış deterministik
#: `transfer_resolve` adımındaki `_settle`'ı, hâlâ bir insana ihtiyaç duyan
#: iki sonuç dışında yansıtır: bkz. `_GATED_OUTCOMES`).
_TERMINAL_REPLIES = {
    "unresolved": "Gönderilecek bir {noun} bulamadım.",
    "recipient_not_found": "'{recipient_name}' adında bir kullanıcı bulamadım.",
    "artifact_ambiguous": "Birden fazla {noun} buldum; hangisini kastettiğinizi belirtir misiniz?",
}

#: Bir insan için duraklaması gereken sonuçlar -- `_step_assist`, tam olarak
#: bu ikisi için `transfer_gate_node`'a yönlendirir, yukarıdakilerin hiçbiri için değil.
_GATED_OUTCOMES = {"needs_disambiguation", "needs_confirmation"}


def build_transfer_tools(
    *,
    company_id: Optional[str],
    user_id: Optional[str],
    thread_id: str,
    run_id: Optional[str],
    active_draft_id: Optional[str],
    active_document_id: Optional[str],
    transfer_provider: Any,
    on_transfer_proposed: Callable[[dict], None],
) -> list[ToolSpec]:
    """``propose_transfer`` aracını, gerçekten kullanılabilir olduğunda inşa eder.

    ``transfer_provider`` ayarlanmadığında (özellik bu dağıtım için
    bağlanmamış) veya çağıran kimliği eksik olduğunda (``company_id``/
    ``user_id``, ``REQUIRE_AUTH`` kapalıyken açık demo/dev yolu) boş bir
    liste döndürür -- modele araç hiç sunulmaz bile: kimliği doğrulanmış
    bir göndereni olmayan bir transferin karşı yetkilendirilecek hiçbir şeyi
    yoktur. ``settings.AI_TRANSFER_ENABLED`` kapısının kendisi bir seviye
    yukarıda, ``_run_assist``'te yaşar -- bu codebase'deki her diğer özellik
    bayrağının, kilitlediği her araca/sağlayıcıya çoğaltılmak yerine çağrı
    noktasında bir kez kontrol edilmesiyle tutarlı.
    """
    if transfer_provider is None or not company_id or not user_id:
        return []

    async def _propose_transfer(recipient_name: str, artifact_kind: Optional[str] = None) -> str:
        kind = artifact_kind if artifact_kind in ("draft", "document") else "draft"
        noun = "taslak" if kind == "draft" else "evrak"

        if kind == "draft":
            resolution = await transfer_provider.resolve_draft(
                company_id=company_id, user_id=user_id, thread_id=thread_id, explicit_draft_id=active_draft_id
            )
        else:
            resolution = await transfer_provider.resolve_document(
                company_id=company_id, user_id=user_id, focus_document_id=active_document_id
            )

        if resolution.status == "unresolved":
            return _TERMINAL_REPLIES["unresolved"].format(noun=noun)
        if resolution.status == "ambiguous":
            candidates = resolution.draft_candidates or resolution.document_candidates
            listing = "; ".join(
                (f"v{c.version} ({c.correspondence_type or 'taslak'})" if kind == "draft" else c.file_name)
                for c in candidates
            )
            return _TERMINAL_REPLIES["artifact_ambiguous"].format(noun=noun) + f" ({listing})"

        artifact = (resolution.draft_candidates or resolution.document_candidates)[0]
        source_artifact_id = artifact.id
        source_version = artifact.version if kind == "draft" else None

        status, candidates = await transfer_provider.resolve_recipient(
            company_id=company_id, name=recipient_name, requester_id=user_id
        )
        if status == "not_found":
            return _TERMINAL_REPLIES["recipient_not_found"].format(recipient_name=recipient_name)

        recipient_candidates = [
            {"user_id": c.user_id, "username": c.username, "unit_name": c.unit_name, "source": "name_match"}
            for c in candidates
        ]
        resolved_recipient_id = recipient_candidates[0]["user_id"] if status == "resolved" else None

        intent = await transfer_provider.open_intent(
            company_id=company_id,
            thread_id=thread_id,
            run_id=run_id,
            requester_id=user_id,
            artifact_kind=kind,
            source_artifact_id=source_artifact_id,
            source_version=source_version,
            resolved_recipient_id=resolved_recipient_id,
            candidate_recipients=tuple(recipient_candidates) if status == "ambiguous" else (),
        )

        if intent.error_reason:
            return intent.error_message or "Transfer başlatılamadı."
        if intent.state == "POLICY_DENIED":
            return (intent.policy_snapshot or {}).get("message_tr") or "Bu transfer şu anda gerçekleştirilemiyor."

        outcome = "needs_confirmation" if intent.state == "AWAITING_CONFIRMATION" else "needs_disambiguation"
        on_transfer_proposed(
            {
                "status": "COMPLETED",
                "outcome": outcome,
                "intent_id": intent.id,
                "artifact_kind": kind,
                "source_artifact_id": source_artifact_id,
                "source_version": source_version,
                "candidate_recipients": intent.candidate_recipients,
                "cross_unit": intent.cross_unit,
                "policy_snapshot": intent.policy_snapshot,
            }
        )
        if outcome == "needs_disambiguation":
            return (
                f"Aynı isimde birden fazla kullanıcı buldum; hangisini kastettiğinizi "
                f"onay ekranından seçebilirsiniz."
            )
        return (
            f"{noun.capitalize()}ı göndermeye hazır -- onayınızı bekliyorum."
        )

    return [
        ToolSpec(
            name="propose_transfer",
            description=(
                "Kullanıcının bir taslağı veya evrakı belirli bir kişiye göndermesini "
                "önerir. Kullanıcı 'şunu ona gönder', 'taslağı Ahmet'le paylaş' gibi "
                "birine bir şey göndermek istediğini açıkça belirttiğinde çağır -- "
                "asla kendiliğinden, taslak üretiminin bir devamı olarak çağırma. "
                "Bu çağrı transferi hemen gerçekleştirmez; kullanıcıya ayrı bir onay "
                "ekranı gösterilir, gönderim yalnızca kullanıcı orada onaylarsa olur. "
                "Bu aracı çağırmadan, bir gönderim önerildiğini veya bir onay ekranı "
                "açılacağını asla söyleme -- bu vaat yalnızca bu aracı gerçekten "
                "çağırdıktan ve onaylayan bir sonuç aldıktan sonra geçerlidir."
            ),
            args_schema=ProposeTransferArgs,
            handler=_propose_transfer,
        )
    ]
