from app.ai.agents.template_agent import TemplateAgent


class ConflictAuditorAgent(TemplateAgent):
    """Audits an already-applied revision for clashes with mevzuat/kaynak.

    Runs on the fast tier, after the rewrite is already merged into the
    draft -- it never runs before or instead of applying the user's
    instruction (see app.ai.revision.conflict's module docstring). Its only
    job is to report contradictions for a human to see, never to suppress
    or soften the edit.
    """

    TEMPLATE_NAME = "conflict_auditor"
    AGENT_NAME = "ConflictAuditorAgent"
    DESCRIPTION = (
        "Reports contradictions between an already-applied user revision "
        "instruction and the retrieved mevzuat/source document -- never "
        "reverts or softens the edit it is reviewing."
    )
