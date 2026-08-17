from app.ai.agents.template_agent import TemplateAgent


class SummarizerAgent(TemplateAgent):
    """Produces a detailed, unbounded-length Turkish summary of a document or chunk.

    Deliberately its own agent rather than a reuse of ``ClassifierAgent``:
    ``classifier.md`` (ClassifierAgent's own template) hard-codes "Özet en
    fazla 3 cümle olsun" ("the summary must be at most 3 sentences") in its
    system prompt -- the second, independent source of the three-sentence cap
    alongside ``analyze_node``'s merged-schema Field description (see
    ``document_analysis_graph.SummaryOutput``). Reusing ``classifier_agent``
    here would keep that constraint in force via the system prompt even after
    removing it from the schema, so this needs a template of its own that
    never states a length cap.
    """

    TEMPLATE_NAME = "summarizer"
    AGENT_NAME = "SummarizerAgent"
    DESCRIPTION = "Produces a detailed Turkish summary of an official document, unabridged."
