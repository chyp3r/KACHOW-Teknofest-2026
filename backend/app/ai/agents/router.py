from app.ai.agents.template_agent import TemplateAgent


class RouterAgent(TemplateAgent):
    """Router Agent responsible for deciding the best agent, tool, or workflow path to handle a given request."""

    TEMPLATE_NAME = "router"
    AGENT_NAME = "RouterAgent"
    DESCRIPTION = "Analyzes input requests and routes them to the most suitable specialized agent or workflow."
