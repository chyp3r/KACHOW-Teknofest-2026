from app.ai.agents.template_agent import TemplateAgent


class ComplianceAgent(TemplateAgent):
    """Compliance Agent responsible for grounding documents in relevant legislation."""

    TEMPLATE_NAME = "compliance"
    AGENT_NAME = "ComplianceAgent"
    DESCRIPTION = (
        "Matches incoming official documents against retrieved legislation "
        "and explains which rule each missing field relates to."
    )
