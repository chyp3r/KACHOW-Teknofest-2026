from app.ai.agents.template_agent import TemplateAgent


class ComplianceAgent(TemplateAgent):
    """Belgeleri ilgili mevzuata dayandırmaktan sorumlu Uyum (Compliance) Ajanı."""

    TEMPLATE_NAME = "compliance"
    AGENT_NAME = "ComplianceAgent"
    DESCRIPTION = (
        "Gelen resmi belgeleri getirilen mevzuatla eşleştirir ve eksik her "
        "alanın hangi kurala ilişkin olduğunu açıklar."
    )
