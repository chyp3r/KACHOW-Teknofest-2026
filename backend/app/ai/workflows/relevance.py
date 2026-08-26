"""Taslak akışı için belge-uygunluk (relevance) kabulü.

``app.ai.workflows.scope``, bir üretim isteğinin *bir şeye* -- bir belgeye,
açık bir taslağa ya da resmî yazışma kaydına -- bağlı olup olmadığını
yanıtlar. Ekli bir belge orada tek başına yeterli bir dayanak olarak
kabul edilir; bu, scope için doğru bir karardır (bir belge, turun *bir*
iş kalemiyle ilgili olduğuna kanıttır), ama özellikle taslak adımı için
fazla cömerttir: "Bu evraka çiğköfte kampanyası için bir metin yaz"
isteğinde ekli bir belge vardır ve ``scope.resolve_scope``'u dosdoğru
geçer, oysa istenen metnin o belgeyle hiçbir ilgisi yoktur.

Bu modül, tam olarak bu boşluğu yakalayan ikinci, daha dar bir kontroldür.
Scope "herhangi bir dayanak var mı" diye sorarken, bu modül "istek
gerçekten *bu* dayanakla mı ilgili" diye sorar -- ve yalnızca bir belge
eklendikten ve sınıflandırması (özellikle ``summary``) zaten mevcut
olduktan sonra çalışır; bu yüzden scope gibi plan-çözümleme anında değil,
``planning_graph._step_draft`` içinden çağrılır: karşılaştırılacak özet,
sınıflandırma adımı çalışana kadar mevcut değildir.

``scope`` ve ``app.ai.revision.conflict`` ile aynı iki katmanlı yapı:
ücretsiz bir deterministik geçiş turların ezici çoğunluğunu çözer (yalın
bir "taslak hazırla" kendine ait, ilgisiz olabilecek bir konu taşımaz;
resmî yazışma diliyle ifade edilmiş ya da belgenin kendi özetinde zaten
geçen bir şeyi adlandıran bir istek varsayılan olarak konuyla ilgilidir),
ve yalnızca her iki testi de geçemeyen bir istek hızlı katmandaki bir
modele yükseltilir; model yapılandırılmamışsa deterministik karar geçerli
kalır.
"""

import logging
from dataclasses import dataclass
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.intent_scorer import normalize
from app.ai.workflows.scope import DOMAIN_SURFACES
from app.ai.workflows.topic_words import content_words

logger = logging.getLogger(__name__)

__all__ = [
    "RelevanceVerdict",
    "assess_relevance_deterministic",
    "build_unrelated_reply",
    "classify_relevance_with_model",
    "resolve_relevance",
]

RelevanceReason = Literal[
    "bare_command",
    "domain_vocabulary",
    "deictic_reference",
    "document_overlap",
    "model_relevant",
    "model_unrelated",
    "unrelated",
    "degraded",
]

#: Ekli belgeye açıkça işaret eden bir mesaj ("bu belge", "bu kişinin",
#: "yukarıdaki") tanımı gereği ilgilidir -- kullanıcı kendi dayanağını
#: adlandırmıştır, sınıflandıracak bir şey kalmamıştır. Bu, CV yükleme
#: yanlış reddi için düzeltmedir: "Bu kişinin ekibe katılımı ile ilgili
#: bir bilgilendirme metni yaz" `DOMAIN_SURFACES`'ten hiçbir kelime taşımaz
#: ve CV'nin kendi özetiyle de hiç kelime paylaşmayabilir, ama "bu
#: kişinin" yüklenen belgeye yönelik belirsizliğe yer bırakmayan bir
#: işarettir.
_DEICTIC_SURFACES: tuple[str, ...] = (
    "bu belge", "bu evrak", "bu dokuman", "bu kisi", "bu kisinin",
    "bu kisiyle", "bu cv", "bu ozgecmis", "bu basvuru", "bu basvurunun",
    "buna", "bunun", "bununla", "yukarida", "yukarideki", "yukaridaki",
    "ekteki", "eklenen", "yukledigim", "yukledigin", "gonderdigim",
    "paylastigim", "yazdigim belge",
)


@dataclass(frozen=True)
class RelevanceVerdict:
    """Bir taslak talimatının ekli belgeyle gerçekten ilgili olup olmadığı.

    Attributes:
        relevant: Yalnızca taslak adımının çalışmayı reddetmesi gerektiğinde
            False.
        reason: Kararı hangi kuralın verdiği (bkz. ``RelevanceReason``).
        source: ``"deterministic"`` veya ``"model"``.
        detail: Türkçe denetim notu, kullanıcıya harfiyen gösterilmez.
    """

    relevant: bool
    reason: RelevanceReason
    source: Literal["deterministic", "model"] = "deterministic"
    detail: str = ""


class RelevanceOutput(BaseModel):
    """Hızlı katmandaki modelin, dayanaksız görünen bir taslak isteği hakkındaki kararı."""

    relevant: bool = Field(
        description=(
            "Kullanıcının isteği, verilen belge özetiyle aynı iş/konuyu mu "
            "ele alıyor? Emin değilsen (belirsizse) true döndür -- yalnızca "
            "belgeyle konu olarak açıkça ilgisizse (tamamen farklı bir konu "
            "-- ör. pazarlama, reklam, genel kültür) false döndür."
        )
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "0-1 arası güven skoru. relevant=false kararını yalnızca "
            "gerçekten eminsen yüksek ver; belirsiz durumlarda düşük bir "
            "güven skoru ver."
        ),
    )


def _coerce_fields(classification: dict[str, Any]) -> dict[str, Any]:
    """Çıkarılan başlık alanlarını sade bir dict olarak döndürür.

    ``draft_graph``/``writing_brief``'ten bilerek çoğaltıldı -- burada
    paylaşılan dört satırlık bir yardımcı fonksiyonun neden modüller
    arası bir bağımlılığa değmediğine dair ``writing_brief._coerce_fields``
    'in kendi docstring'ine bakın.
    """
    fields = (classification or {}).get("fields", {})
    if hasattr(fields, "model_dump"):
        return fields.model_dump()
    return fields if isinstance(fields, dict) else {}


def _document_text(classification: dict[str, Any]) -> str:
    """Bir isteğin muhtemelen *hakkında* olabileceği sınıflandırmanın her
    parçası.

    CV yanlış reddinin asıl kaynağı olan yalnızca özet/tür etiketinin
    ötesine genişletildi (belgenin kendi konusunu adlandıran bir istek --
    "bu kişinin ekibe katılımı" -- "Özgeçmiş belgesi." gibi bir belge-türü
    özetiyle hiçbir kelime paylaşmaz); artık çıkarılan başlık alanlarını
    (konu/muhatap/gönderen kurum/imza sahibi) ve analiz adımının bulduğu
    isimlendirilmiş varlıkları da kapsıyor -- *bu belirli belge* hakkındaki
    bir isteğin fiilen kullanma olasılığı en yüksek somut isimler bunlar.
    """
    fields = _coerce_fields(classification)
    entities = classification.get("entities") or []
    entity_text = " ".join(str(entity) for entity in entities if entity)
    return normalize(
        " ".join(
            part
            for part in (
                classification.get("summary", ""),
                classification.get("document_type_label", ""),
                fields.get("konu", ""),
                fields.get("muhatap", ""),
                fields.get("gonderen_kurum", ""),
                fields.get("imza_sahibi", ""),
                entity_text,
            )
            if part
        )
    )


def assess_relevance_deterministic(
    instruction: str, classification: dict[str, Any]
) -> RelevanceVerdict:
    """Uygunluğu talimat ve belgenin kendi özetinden karara bağlar.

    Args:
        instruction: Kullanıcının bu turdaki ham mesajı (zaten kalıp
            metinle sarılmış olan oluşturulmuş writer prompt'u değil).
        classification: Turun çözümlenmiş sınıflandırması,
            ``summary``/``document_type_label`` taşır.

    Returns:
        Bir karar. ``"unrelated"`` nedenli ``relevant=False``, bir modele
        yükseltmeye değer tek sonuçtur (bkz. ``resolve_relevance``); diğer
        tüm sonuçlar nihaidir.
    """
    normalized = normalize(instruction)
    words = content_words(instruction)

    if not words:
        return RelevanceVerdict(
            True, "bare_command", detail="İstek belgeden bağımsız bir konu içermiyor."
        )

    padded = f" {normalized} "
    if any(f" {surface}" in padded for surface in DOMAIN_SURFACES):
        return RelevanceVerdict(
            True, "domain_vocabulary", detail="İstek resmî yazışma terminolojisi içeriyor."
        )

    if any(surface in padded for surface in _DEICTIC_SURFACES):
        return RelevanceVerdict(
            True,
            "deictic_reference",
            detail="İstek yüklü belgeye doğrudan işaret ediyor (\"bu belge\", \"bu kişinin\" vb.).",
        )

    document_text = _document_text(classification)
    if document_text and any(word in document_text for word in words):
        return RelevanceVerdict(
            True, "document_overlap", detail="İstek belgenin kendi içeriğiyle örtüşüyor."
        )

    return RelevanceVerdict(
        False,
        "unrelated",
        detail=(
            "İstekteki konu ne belgenin özetiyle ne de resmî yazışma "
            "terminolojisiyle örtüşüyor."
        ),
    )


async def classify_relevance_with_model(
    llm_client: BaseLLMClient, instruction: str, classification: dict[str, Any]
) -> Optional[RelevanceOutput]:
    """Dayanaksız görünen bir isteğin belgeye uyup uymadığını hızlı katmana
    sorar.

    Args:
        llm_client: Hızlı katman istemcisi; router'ın kendi
            berabere-bozucusunun ve scope kapısının kullandığıyla aynı.
        instruction: Kullanıcının mesajı.
        classification: Turun çözümlenmiş sınıflandırması.

    Returns:
        Modelin yapılandırılmış kararı (relevance + confidence), ya da
        çağrı başarısız olduğunda ``None`` -- bir sağlayıcı kesintisinin
        asla bir ret gibi okunmaması için olumsuz karardan ayrı tutulur.
    """
    from app.ai.agents.base import BaseAgent

    agent = BaseAgent(
        llm_client=llm_client,
        name="RelevanceClassifier",
        description="Decides whether a draft request concerns the attached document.",
        system_prompt=(
            "Sana bir belge özeti ve bir kullanıcı isteği verilecek. İsteğin "
            "bu belgeyle aynı iş/konuyu ele alıp almadığına karar ver. Emin "
            "değilsen ilgili (relevant=true) say ve düşük bir güven skoru "
            "ver -- yalnızca gerçekten emin olduğunda ilgisiz say. Yalnızca "
            "yapılandırılmış JSON döndür."
        ),
    )

    prompt = (
        f"Belge türü: {classification.get('document_type_label', 'bilinmiyor')}\n"
        f"Belge özeti: {classification.get('summary', '(özet yok)')}\n\n"
        f'Kullanıcı isteği: "{instruction}"\n\n'
        "Bu istek belgeyle aynı konuyu mu ele alıyor? Emin değilsen ilgili say."
    )

    try:
        return await agent.run_structured(
            messages=prompt,
            response_model=RelevanceOutput,
            temperature=0.0,
            max_retries=1,
        )
    except Exception:
        logger.warning(
            "Relevance classification failed; falling back to deterministic verdict."
        )
        return None


#: Bu güven düzeyinin altında, modelin "unrelated" kararı "reddetmek için
#: yeterince emin değil" olarak ele alınır ve istek bunun yerine kabul
#: edilir. Meşru bir isteği reddetmek (bunun karşı önlem olduğu CV/"bu
#: kişinin ekibe katılımı" yanlış reddi), gerçekten ilgisiz bir istek için
#: ara sıra bir şey taslak haline getirmekten daha kötü bir hata modudur,
#: bu yüzden *olumsuz* bir karar için eşik, olumlu bir karar için olandan
#: bilerek daha yüksek tutulur.
_MODEL_REJECTION_CONFIDENCE_FLOOR = 0.7


async def resolve_relevance(
    instruction: str,
    classification: dict[str, Any],
    llm_client: Optional[BaseLLMClient] = None,
) -> RelevanceVerdict:
    """Uygunluğu çözer; yalnızca bir model çağrısının iyileştirebileceği
    durumu yükseltir.

    Args:
        instruction: Kullanıcının mesajı.
        classification: Turun çözümlenmiş sınıflandırması.
        llm_client: Hızlı katman istemcisi. Verilmemesi, deterministik
            kararın tek başına geçerli kalması demektir -- ``scope.
            resolve_scope``'un aynı model-yok davranışıyla eşleşerek daha
            katı, ama bozuk değil: dayanaksız görünen bir istek, bir modele
            kabul etme şansı verilmeden reddedilir.

    Returns:
        Nihai karar.
    """
    verdict = assess_relevance_deterministic(instruction, classification)
    if verdict.relevant or llm_client is None:
        return verdict

    result = await classify_relevance_with_model(llm_client, instruction, classification)
    if result is None:
        # Bozuk olan çağrı, bozuk olan istek değil -- "degraded" için
        # scope.resolve_scope'un aynı gerekçesine bakın.
        return RelevanceVerdict(
            True,
            "degraded",
            source="model",
            detail="Konu uygunluk modeli yanıt vermedi; istek kapsam içi sayıldı.",
        )
    if result.relevant:
        return RelevanceVerdict(
            True, "model_relevant", source="model", detail="Model belgeyle ilgili buldu."
        )
    if result.confidence < _MODEL_REJECTION_CONFIDENCE_FLOOR:
        # Reddetmek için yeterince emin değil -- eşiğin kendi açıklamasına bakın.
        return RelevanceVerdict(
            True,
            "model_relevant",
            source="model",
            detail=(
                f"Model belgeyle ilgisiz buldu ancak güven düşük "
                f"({result.confidence:.2f}); istek kapsam içi sayıldı."
            ),
        )
    return RelevanceVerdict(
        False,
        "model_unrelated",
        source="model",
        detail=f"Model belgeyle ilgisiz buldu (güven: {result.confidence:.2f}).",
    )


def build_unrelated_reply(document_summary: str, document_type_label: str = "") -> str:
    """"Bu istek bu belgeyle ilgili değil" yanıtını oluşturur. Asla modelden
    üretilmez, her zaman sabit metinden derlenir.

    Args:
        document_summary: Ekli belgenin özeti.
        document_type_label: Bilinen ise belgenin sınıflandırılmış türü.

    Returns:
        Türkçe yanıt.
    """
    type_note = f" ({document_type_label})" if document_type_label else ""
    lines = [
        f"Bu istek, şu anda yüklü olan belge{type_note} ile ilgili değil, bu "
        "yüzden bu isteğe uygun bir taslak hazırlamadım.",
        "",
        f"Yüklü belgenin özeti: {document_summary or 'Özet mevcut değil.'}",
        "",
        "Bu belgeyle ilgili bir taslak veya analiz isteyebilir, ya da farklı bir "
        "konu için yeni bir belge yükleyebilirsiniz.",
    ]
    return "\n".join(lines)
