import json
import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import AliasChoices, BaseModel, Field
from langchain_core.runnables import RunnableConfig

from app.ai.agents.editor import EditorAgent
from app.ai.agents.writer import WriterAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.correspondence import (
    format_correspondence_profile,
    resolve_correspondence_type,
)

logger = logging.getLogger(__name__)

MIN_AUTOMATED_CONFIDENCE_SCORE = 70.0


class DraftState(TypedDict, total=False):
    """LangGraph State representing the document drafting/writing workflow context."""

    source_document: str
    classification: dict[str, Any]
    correspondence_type: str
    correspondence_type_source: str
    context: str
    instructions: str
    draft: str
    edit_feedback: str
    needs_revision: bool
    confidence_score: float
    requires_human_approval: bool
    evaluation_notes: str
    status: str
    error: str
    attempts: int
    brief: str


class EditorOutput(BaseModel):
    """Pydantic schema for editor review, edit, and final evaluation."""

    final_draft: str = Field(
        validation_alias=AliasChoices("final_draft", "corrected_draft", "corrected-draft"),
        description="Editör tarafından denetlenmiş, düzeltilmiş ve parlatılmış nihai resmi yazı taslağı metni. "
                    "Eğer herhangi bir düzeltme gerekmiyorsa, gelen taslak metnini aynen koru. "
                    "Hatalar varsa (yazım kuralları, resmi dil, brief dışı uydurulan bilgileri temizleme) bunları doğrudan bu metinde düzelt."
    )
    confidence_score: float = Field(
        ge=0.0,
        le=100.0,
        validation_alias=AliasChoices("confidence_score", "quality_trust_score", "quality-trust-score"),
        description="Yazının doğruluğu ve kalitesine verilen güven skoru (0.0 ile 100.0 arasında)."
    )
    requires_human_approval: bool = Field(
        default=False,
        validation_alias=AliasChoices("requires_human_approval", "human_approval_required", "human-approval-required"),
        description="Eksik veya doğrulanamayan bilgi nedeniyle insan onayı gerekip gerekmediği."
    )
    evaluation_notes: str = Field(
        default="",
        validation_alias=AliasChoices("evaluation_notes", "explanation", "evaluation-notes"),
        description="Güven skorunun, yapılan düzeltmelerin ve insan onayı kararının kısa Türkçe gerekçesi."
    )


def _format_classification(classification: dict[str, Any]) -> str:
    """Serialize document analysis data for grounded agent prompts."""
    if not classification:
        return "Sınıflandırma bilgisi sağlanmadı."
    
    # Pre-process classification dict to handle non-serializable Document objects and other types
    cleaned = {}
    for k, v in classification.items():
        if isinstance(v, list):
            cleaned_list = []
            for item in v:
                if hasattr(item, "page_content") and hasattr(item, "metadata"):  # LangChain Document
                    cleaned_list.append({
                        "page_content": item.page_content,
                        "metadata": item.metadata
                    })
                elif hasattr(item, "model_dump"):  # Pydantic v2
                    cleaned_list.append(item.model_dump())
                elif hasattr(item, "dict"):  # Pydantic v1
                    cleaned_list.append(item.dict())
                else:
                    cleaned_list.append(item)
            cleaned[k] = cleaned_list
        elif hasattr(v, "page_content") and hasattr(v, "metadata"):  # LangChain Document
            cleaned[k] = {
                "page_content": v.page_content,
                "metadata": v.metadata
            }
        elif hasattr(v, "model_dump"):  # Pydantic v2
            cleaned[k] = v.model_dump()
        elif hasattr(v, "dict"):  # Pydantic v1
            cleaned[k] = v.dict()
        else:
            cleaned[k] = v

    try:
        return json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        return str(cleaned)


def create_draft_graph(llm_client: BaseLLMClient):
    """Create and compile the LangGraph document drafting/generation workflow
    utilizing Writer and Editor agent roles in a streamlined pipeline.

    Flow: START -> validate_input -> Writer -> Editor -> END
    """
    writer_agent = WriterAgent(llm_client)
    editor_agent = EditorAgent(llm_client)

    # 1. Input Validation Node
    async def validate_input_node(state: DraftState) -> dict[str, Any]:
        classification = state.get("classification", {})
        instructions = (
            state.get("instructions", "").strip()
            or "Gelen evraka uygun resmî ve kurumsal bir yazışma taslağı oluştur."
        )
        correspondence_type, type_source = resolve_correspondence_type(
            state.get("correspondence_type"),
            instructions,
            classification,
        )
        source_document = state.get("source_document", "").strip()
        if not source_document:
            error = "Gelen evrak içeriği sağlanmadığı için taslak oluşturulamadı."
            logger.error(error)
            return {
                "correspondence_type": correspondence_type.value,
                "correspondence_type_source": type_source,
                "draft": "",
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "FAILED",
                "error": error,
                "attempts": state.get("attempts", 0),
                "brief": "",
            }

        context = state.get("context", "").strip()
        
        # Compile Brief (Briefing Agent / Context Builder Pattern)
        fields = classification.get("fields", {})
        if hasattr(fields, "model_dump"):
            fields = fields.model_dump()
        elif hasattr(fields, "dict"):
            fields = fields.dict()
        elif not isinstance(fields, dict):
            fields = {}

        # Trim source_document for brief (head + tail) to avoid exceeding context
        _src = source_document
        _HEAD = 4000
        _TAIL = 1000
        if len(_src) > _HEAD + _TAIL:
            _src = (
                _src[:_HEAD]
                + "\n\n[... belgenin orta kısmı kısaltıldı ...]\n\n"
                + _src[-_TAIL:]
            )

        brief = (
            f"1. Belge Türü: {classification.get('document_type_label') or classification.get('document_type') or 'Belirtilmedi'}\n"
            f"2. Belge Özeti: {classification.get('summary') or 'Özet çıkarılamadı.'}\n"
            f"3. Çıkarılan Kritik Bilgiler:\n"
            f"   - Tarih: {fields.get('tarih') or 'Bulunamadı'}\n"
            f"   - Sayı: {fields.get('sayi') or 'Bulunamadı'}\n"
            f"   - Konu: {fields.get('konu') or 'Bulunamadı'}\n"
            f"   - Muhatap: {fields.get('muhatap') or 'Bulunamadı'}\n"
            f"4. Gelen Evrak Metni:\n\"\"\"\n{_src}\n\"\"\"\n"
            f"5. Doğrulanmış Mevzuat Bağlamı:\n\"\"\"\n{context or 'İlgili mevzuat bağlamı bulunamadı.'}\n\"\"\"\n"
            f"6. Kullanıcı Talebi ve Talimatlar: {instructions}\n"
        )

        return {
            "source_document": source_document,
            "classification": classification,
            "correspondence_type": correspondence_type.value,
            "correspondence_type_source": type_source,
            "context": context,
            "instructions": instructions,
            "brief": brief,
            "requires_human_approval": not bool(context) or type_source == "fallback",
            "status": "IN_PROGRESS",
            "error": "",
            "attempts": state.get("attempts", 0),
        }

    def route_after_validation(state: DraftState) -> str:
        return "end" if state.get("status") == "FAILED" else "writer"

    # 2. Writer Node
    async def writer_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        logger.info("Running Writer Node...")
        status_queue = config.get("configurable", {}).get("status_queue")
        attempts = state.get("attempts", 0)
        if status_queue:
            await status_queue.put({
                "event": "node_start",
                "node": "draft",
                "label": "Taslak Oluşturma",
                "message": f"[Yazar Ajanı] Taslak yazılıyor..."
            })
        brief = state["brief"]
        correspondence_profile = format_correspondence_profile(
            state["correspondence_type"]
        )

        is_other = state["correspondence_type"] == "other_official"

        if is_other:
            rules_instruction = (
                "- Yazışma türü 'Diğer resmî yazışma' (alternatif tür) olduğu için, brief belgesinde bulunmayan eksik veya tamamlayıcı bilgileri kendi genel bilgilerini/bilgi dağarcığını kullanarak tamamlayabilirsin.\n"
                "- Resmi yazı standartlarına uygunluğu sağlamak için makul ve tutarlı tamamlamalar yapabilirsin."
            )
        else:
            rules_instruction = (
                "- Yalnızca brief içindeki bilgilere ve mevzuat bağlamına sadık kal.\n"
                "- Gelen evrak veya mevzuatta yer almayan hiçbir kişi, kurum, sayı, tarih veya olay uydurma.\n"
                "- Cevap yazısı için zorunlu olan ancak brief içinde bulunmayan eksik bilgiler varsa bunu taslak metin içinde açıkça belirt (örn. '[Tarih Eksik - Lütfen Doldurun]')."
            )

        prompt = (
            f"### GÖREV:\n"
            f"Aşağıdaki 'Brief' (özet, kritik bilgiler ve mevzuat) doğrultusunda resmi ve kurumsal bir Türkçe cevap taslağı yaz.\n\n"
            f"### BRIEF BELGESİ:\n"
            f"{brief}\n\n"
            f"### YAZIŞMA TÜRÜ PROFILI:\n"
            f"{correspondence_profile}\n\n"
            f"### KURALLAR:\n"
            f"{rules_instruction}"
        )

        try:
            draft = await writer_agent.run(messages=prompt, temperature=0.7)
            if not draft.strip():
                raise ValueError("WriterAgent boş taslak döndürdü.")
            return {
                "draft": draft,
                "attempts": attempts + 1,
                "status": "IN_PROGRESS",
            }
        except Exception as e:
            logger.exception("Writer Node failed")
            return {
                "draft": "",
                "attempts": attempts + 1,
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "FAILED",
                "error": f"WriterAgent taslak üretemedi: {e}",
            }

    def route_after_writer(state: DraftState) -> str:
        return "end" if state.get("status") == "FAILED" else "editor"

    # 3. Editor Node
    async def editor_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        logger.info("Running Editor Node...")
        status_queue = config.get("configurable", {}).get("status_queue")
        if status_queue:
            await status_queue.put({
                "event": "node_start",
                "node": "draft",
                "label": "Taslak Denetleme ve Düzeltme",
                "message": "[Editör Ajanı] Taslak resmi yazışma kuralları ve kaynak doğruluğu açısından denetleniyor ve düzeltiliyor..."
            })
        brief = state["brief"]
        correspondence_profile = format_correspondence_profile(
            state["correspondence_type"]
        )

        is_other = state["correspondence_type"] == "other_official"

        if is_other:
            rules_instruction = (
                "Yazışma türü 'Diğer resmî yazışma' (alternatif tür) olduğu için, brief dışındaki tamamlayıcı genel veya kurumsal bilgilerin kullanımı serbesttir. "
                "Hataları ve üslubu düzelt, ancak uydurulmuş gibi görünen genel/kurumsal tamamlayıcı bilgileri silmek yerine koru ve resmi yazışma normlarına uyarla."
            )
        else:
            rules_instruction = (
                "Yazışma türü ('Üst yazı', 'Cevap yazısı' veya 'Bilgilendirme metni') olduğu için, kaynağa bağlılık kuralı mutlaktır. "
                "Brief dışından uydurulmuş bilgi, kişi, kurum, sayı veya mevzuat varsa bunları nihai metinden tamamen temizle veya yer tutuculara (örn. '[Bilgi Eksik]') dönüştür."
            )

        prompt = (
            f"### BRIEF BELGESİ:\n"
            f"{brief}\n\n"
            f"### YAZIŞMA TÜRÜ PROFILI:\n"
            f"{correspondence_profile}\n\n"
            f"### DENETLENECEK VE DÜZELTİLECEK TASLAK METİN:\n"
            f"\"\"\"\n{state['draft']}\n\"\"\"\n\n"
            f"### DENETLEME VE DÜZELTME TALİMATI:\n"
            "Taslağı brief belgesine uygunluk, kaynaklara sadakat, kurumsal dil, Türkçe yazım kuralları, noktalama ve akıcılık yönünden incele.\n"
            f"{rules_instruction}\n"
            "İnceleme sonucuna göre kalite güven skorunu (0-100), düzeltilmiş nihai metni ve insan onayı gereksinimini yapılandırılmış JSON olarak döndür."
        )
        try:
            res: EditorOutput = await editor_agent.run_structured(
                messages=prompt,
                response_model=EditorOutput,
                temperature=0.2,
            )
            requires_human_approval = (
                state.get("requires_human_approval", False)
                or res.requires_human_approval
                or res.confidence_score < MIN_AUTOMATED_CONFIDENCE_SCORE
            )
            return {
                "draft": res.final_draft,
                "confidence_score": res.confidence_score,
                "requires_human_approval": requires_human_approval,
                "evaluation_notes": res.evaluation_notes,
                "status": (
                    "NEEDS_HUMAN_APPROVAL" if requires_human_approval else "COMPLETED"
                ),
            }
        except Exception as e:
            logger.exception("Editor Node failed")
            return {
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "NEEDS_HUMAN_APPROVAL",
                "error": f"EditorAgent taslağı doğrulayamadı ve düzeltemedi: {e}",
            }

    # Define Graph
    builder = StateGraph(DraftState)
    builder.add_node("validate_input", validate_input_node)
    builder.add_node("writer", writer_node)
    builder.add_node("editor", editor_node)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges(
        "validate_input",
        route_after_validation,
        {
            "writer": "writer",
            "end": END,
        },
    )
    builder.add_conditional_edges(
        "writer",
        route_after_writer,
        {
            "editor": "editor",
            "end": END,
        },
    )
    builder.add_edge("editor", END)

    return builder.compile()
