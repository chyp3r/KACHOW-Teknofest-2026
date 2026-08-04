from app.ai.agents.template_agent import TemplateAgent
from app.ai.guardrails.injection import assert_no_prompt_leak


class ClassifierAgent(TemplateAgent):
    """Classifier Agent responsible for classifying texts, categorizing requests, and analyzing sentiment."""

    TEMPLATE_NAME = "classifier"
    AGENT_NAME = "ClassifierAgent"
    DESCRIPTION = "Categorizes text into predefined categories, labels, and performs sentiment analysis."
    VALIDATORS = (assert_no_prompt_leak,)
