from enum import StrEnum


class CorrespondenceType(StrEnum):
    """Taslak iş akışının ürettiği desteklenen resmi yazışma çıktıları.

    Spesifikasyona göre bu dört tanede sabittir. Bunlardan biri olmayan
    belirli bir tür için kullanıcı isteği (bir itiraz dilekçesi, bir
    muvafakatname, ...) yine de buraya -- OTHER_OFFICIAL'a -- çözülür, ama
    türün kendisini tür ile birlikte ayrı bir serbest metin alt-tür olarak
    taşır (bkz.
    ``app.ai.workflows.correspondence.resolve_correspondence_type``), bu
    yüzden writer prompt'u gerçekte ne üretileceğini yine de bilir.
    """

    COVER_LETTER = "cover_letter"
    RESPONSE_LETTER = "response_letter"
    INFORMATION_NOTICE = "information_notice"
    OTHER_OFFICIAL = "other_official"
