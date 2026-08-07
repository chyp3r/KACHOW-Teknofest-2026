"""Reference phrasings each decision class is matched against semantically.

The lexical rules in ``intent_rules`` match surfaces literally, so they are
blind to paraphrase by construction: every new way of saying "prepare a reply"
has to be added by hand, and the measured baseline showed whole categories
failing on phrasings nobody had thought to list. These prototypes are the
semantic counterpart -- a handful of *examples* per class, compared by meaning
rather than by substring.

They are examples, not rules. The matcher never decides on a prototype alone
(see ``semantic.prototype_matcher``): a hit needs both a high similarity and a
clear gap to the runner-up, because "embedding similarity said so" is a much
weaker warrant than "the user literally wrote 'taslak hazırla'". The lexical
layer stays the fast path; this only runs where that layer abstained.

Prototype *vectors* are precomputed into ``datasets/prototypes/`` by
``scripts/build_prototypes.py``. Nothing here is embedded at request time
except the user's own message.
"""

from typing import Mapping

__all__ = ["PROTOTYPES", "FAMILIES", "prototype_texts"]

#: Family -> label -> example phrasings.
#:
#: Phrasings are chosen to be *different from* the lexical surfaces rather than
#: to duplicate them. A prototype that repeats a phrase the rule table already
#: matches adds nothing: that message never reaches this layer.
PROTOTYPES: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "intent": {
        "draft": (
            "Bu evraka resmî bir cevap metni hazırla.",
            "Gelen yazıya karşılık verecek bir yazışma kaleme al.",
            "Kuruma iletilecek bir tebligat metni düzenle.",
            "Vatandaşa dönüş yapacak resmî bir metin kurgula.",
            "Bu başvuruya mukabelede bulunacak yazıyı oluştur.",
        ),
        "analyze": (
            "Bu evrakı inceleyip bulgularını raporla.",
            "Belgenin usule uygunluğunu değerlendir.",
            "Evraktaki eksik unsurları tespit et.",
            "Bu belgenin hangi türe girdiğini belirle.",
            "Evrakı gözden geçirip özetini çıkar.",
        ),
        "assist": (
            "Bu belgede hangi bilgi geçiyor?",
            "Evrakın içeriğinde ne yazıyor?",
            "Belgede adı geçen kurum hangisi?",
            "Yazıda belirtilen süre ne kadar?",
            "Bu evrakta kimin imzası var?",
            "Merhaba, nasılsın?",
            "Bu sistem ne işe yarıyor?",
            "Resmî yazışma kuralları hakkında genel bilgi verir misin?",
            "Teşekkür ederim, çok yardımcı oldun.",
            "Daha önce ne konuşmuştuk, hatırlıyor musun?",
        ),
        #: Added alongside the `revise` intent's lexical rules (see
        #: `intent_rules.REVISE_RULES`, all gated on an active draft). Chosen to
        #: be different phrasings from those surfaces, not restatements of
        #: them -- a prototype that repeats a matched surface never reaches
        #: this layer at all (see this module's own docstring).
        "revise": (
            "Bu taslağın tonunu biraz yumuşatır mısın?",
            "Son paragrafı tekrar ele alalım.",
            "Yazıyı biraz daha resmî bir üsluba çevir.",
            "Az önceki metni gözden geçirip düzelt.",
            "Bu bölümü farklı bir şekilde ifade edelim.",
        ),
    },
    "correspondence_type": {
        "cover_letter": (
            "Ekteki belgeyi ilgili makama gönderen bir üst yazı.",
            "İletilen dayanak belgeyi ve beklenen işlemi bildiren yazı.",
        ),
        "response_letter": (
            "Gelen talebe doğrudan cevap veren resmî yazı.",
            "Başvuruda sorulan hususu karşılayan mukabele yazısı.",
        ),
        "information_notice": (
            "Bir konuda tarafsız bilgi aktaran duyuru metni.",
            "Personeli veya vatandaşı bilgilendiren açıklama yazısı.",
        ),
        "other_official": (
            "Türü net olmayan genel bir resmî yazışma.",
            "Kurum içi serbest formatlı resmî metin.",
        ),
    },
}

#: The families the matcher knows about.
FAMILIES: tuple[str, ...] = tuple(PROTOTYPES)


def prototype_texts(family: str) -> list[tuple[str, str]]:
    """Flatten a family into ``(label, text)`` pairs in a stable order.

    Args:
        family: The family name.

    Returns:
        Every prototype phrasing with the label it stands for, ordered so the
        precomputed vector file is reproducible.

    Raises:
        KeyError: For an unknown family.
    """
    labels = PROTOTYPES[family]
    return [
        (label, text)
        for label in sorted(labels)
        for text in labels[label]
    ]
