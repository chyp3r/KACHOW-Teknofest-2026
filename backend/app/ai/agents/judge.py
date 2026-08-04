from app.ai.agents.template_agent import TemplateAgent


class JudgeAgent(TemplateAgent):
    """Judges a draft on criteria the deterministic verifier cannot check.

    Runs on the fast tier: it emits a small structured verdict, never the
    draft text itself, so its cost is a label-sized generation rather than a
    second full draft.
    """

    TEMPLATE_NAME = "judge"
    AGENT_NAME = "JudgeAgent"
    DESCRIPTION = (
        "Judges a draft's request-fit, register, closing direction and "
        "muhatap consistency -- the parts of quality a regex cannot see."
    )
