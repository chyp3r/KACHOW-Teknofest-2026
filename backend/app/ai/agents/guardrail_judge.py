from app.ai.agents.template_agent import TemplateAgent


class GuardrailJudgeAgent(TemplateAgent):
    """Judges meaning-level sensitivity/leakage the deterministic patterns can't see.

    Runs on the fast tier, same shape as ``JudgeAgent``: it emits a small
    structured verdict, never the judged content itself, so its cost is a
    label-sized generation. Used for two tasks (input document sensitivity,
    output reply leakage) selected by the calling prompt -- see
    ``app.ai.guardrails.llm_nuance``.
    """

    TEMPLATE_NAME = "guardrail_judge"
    AGENT_NAME = "GuardrailJudgeAgent"
    DESCRIPTION = (
        "Judges whether a document or reply is sensitive/leaky in meaning "
        "rather than pattern -- the nuance a regex cannot see."
    )
