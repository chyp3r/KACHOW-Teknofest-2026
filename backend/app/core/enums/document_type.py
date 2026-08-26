from enum import StrEnum


class DocumentType(StrEnum):
    """Girişte tanınan gelen resmi belge (evrak) türleri.

    Bu taksonomi kurumun *aldığı* belgeyi tanımlar. Kurumun *ürettiği*
    resmi yanıtı tanımlayan `CorrespondenceType`'ın karşılığıdır. İkisini
    ayrı tutmak, giriş boru hattının gelen bir dilekçeyi sınıflandırmasına
    izin verirken taslak boru hattının bağımsız olarak yanıtın bir yanıt
    mektubu olması gerektiğine karar vermesini sağlar.
    """

    OFFICIAL_LETTER = "official_letter"
    PETITION = "petition"
    INFORMATION_REQUEST = "information_request"
    COMPLAINT = "complaint"
    CIRCULAR = "circular"
    DIRECTIVE = "directive"
    REPORT = "report"
    MINUTES = "minutes"
    LEAVE_REQUEST = "leave_request"
    OTHER = "other"
