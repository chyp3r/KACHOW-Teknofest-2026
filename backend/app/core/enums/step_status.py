from enum import StrEnum


class StepStatus(StrEnum):
    """SSE üzerinden raporlandığı şekliyle tek bir plan adımı veya taslak revizyonunun sonucu.

    Bir `StrEnum` üyesi, yerine geçtiği düz dize literali ile tam olarak
    aynı şekilde karşılaştırılır ve serileştirilir, bu yüzden hâlâ düz
    dizeler döndüren bir alt grafik (örn. draft_graph), burada eşit
    karşılaştırmak için hiçbir değişikliğe ihtiyaç duymaz.
    """

    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    NEEDS_HUMAN_APPROVAL = "NEEDS_HUMAN_APPROVAL"
    NEEDS_INPUT = "NEEDS_INPUT"
    REVISE_REQUESTED = "REVISE_REQUESTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
