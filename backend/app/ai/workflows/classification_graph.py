import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.agents.classifier import ClassifierAgent
from app.ai.agents.metadata import MetadataAgent
from app.ai.agents.ner import NERAgent
from app.ai.llms.base import BaseLLMClient

logger = logging.getLogger(__name__)


class ClassificationState(TypedDict):
    """LangGraph State representing the classification workflow context."""

    input_text: str
    doc_type: str
    summary: str
    entities: dict[str, list[str]]  # people, organizations, dates
    metadata: dict[str, Any]
    next_workflow_state: str


class ClassificationOutput(BaseModel):
    """Pydantic schema for structured document classification."""

    doc_type: str = Field(
        description="Belgenin türü (örn. 'Dilekçe', 'Sözleşme', 'Resmi Yazı', 'Genelge', 'Soru')."
    )
    summary: str = Field(description="Belgenin kısa, net Türkçe özeti.")


class NEROutput(BaseModel):
    """Pydantic schema for structured named entity extraction."""

    people: list[str] = Field(
        default_factory=list,
        description="Metinde geçen kişi adları (örn. 'Ahmet Yılmaz').",
    )
    organizations: list[str] = Field(
        default_factory=list,
        description="Metinde geçen kurum, şirket veya organizasyon adları (örn. 'ASELSAN').",
    )
    dates: list[str] = Field(
        default_factory=list,
        description="Metinde geçen tarih veya zaman ifadeleri (örn. '29 Temmuz 2026').",
    )


class MetadataOutput(BaseModel):
    """Pydantic schema for dynamic metadata extraction."""

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Konu, referans no, dil, ton vb. içeren dinamik metadata tablosu.",
    )


def create_classification_graph(llm_client: BaseLLMClient):
    """Create and compile the LangGraph document classification workflow.

    Flow: START -> Classify & Summarize -> Extract Entities (NER) -> Extract Metadata -> END
    """
    # Instantiate agents
    classifier_agent = ClassifierAgent(llm_client)
    ner_agent = NERAgent(llm_client)
    metadata_agent = MetadataAgent(llm_client)

    # 1. Classification Node
    async def classify_node(state: ClassificationState) -> dict[str, Any]:
        logger.info("Running Classification Node...")
        prompt = (
            "Aşağıdaki belgenin/isteğin türünü ve özetini çıkart.\n\n"
            f"İÇERİK:\n\"\"\"\n{state['input_text']}\n\"\"\""
        )
        try:
            res: ClassificationOutput = await classifier_agent.run_structured(
                messages=prompt, response_model=ClassificationOutput
            )
            return {"doc_type": res.doc_type, "summary": res.summary}
        except Exception:
            logger.exception("Classification Node failed")
            return {"doc_type": "Bilinmeyen", "summary": "Özet çıkarılamadı."}

    # 2. NER Node
    async def ner_node(state: ClassificationState) -> dict[str, Any]:
        logger.info("Running NER Node...")
        prompt = (
            "Aşağıdaki metinden kişi adlarını, kurumları ve tarihleri ayıkla.\n\n"
            f"İÇERİK:\n\"\"\"\n{state['input_text']}\n\"\"\""
        )
        try:
            res: NEROutput = await ner_agent.run_structured(
                messages=prompt, response_model=NEROutput
            )
            return {
                "entities": {
                    "people": res.people,
                    "organizations": res.organizations,
                    "dates": res.dates,
                }
            }
        except Exception:
            logger.exception("NER Node failed")
            return {"entities": {"people": [], "organizations": [], "dates": []}}

    # 3. Metadata Node
    async def metadata_node(state: ClassificationState) -> dict[str, Any]:
        logger.info("Running Metadata Node...")
        prompt = (
            "Aşağıdaki metinden konu, önem derecesi, referans no ve dil gibi öznitelikleri çıkartarak "
            "anahtar-değer şeklinde bir metadata nesnesi oluştur.\n\n"
            "Kullanıcı belirli bir çıktı yazışma türü istiyorsa `correspondence_type` alanını "
            "yalnızca şu değerlerden biriyle ekle: `cover_letter`, `response_letter`, "
            "`information_notice`, `other_official`. Açık bir talep yoksa bu alanı ekleme.\n\n"
            f"İÇERİK:\n\"\"\"\n{state['input_text']}\n\"\"\""
        )
        try:
            res: MetadataOutput = await metadata_agent.run_structured(
                messages=prompt, response_model=MetadataOutput
            )
            # Decide the initial workflow state (e.g. if it is a general question, route to RAG)
            next_state = "RAG" if state.get("doc_type") != "Gereksiz" else "Routing"
            return {"metadata": res.metadata, "next_workflow_state": next_state}
        except Exception:
            logger.exception("Metadata Node failed")
            return {"metadata": {}, "next_workflow_state": "RAG"}

    # Define Graph
    builder = StateGraph(ClassificationState)
    builder.add_node("classify", classify_node)
    builder.add_node("ner", ner_node)
    builder.add_node("metadata", metadata_node)

    builder.add_edge(START, "classify")
    builder.add_edge("classify", "ner")
    builder.add_edge("ner", "metadata")
    builder.add_edge("metadata", END)

    return builder.compile()
