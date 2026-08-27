"""Revize akışının genel giriş noktası: ``run_revise``.

``app.ai.workflows.revise_graph``'ın derlenmiş LangGraph iş akışı üzerine
ince bir cephe -- ayrıştırma (``app.ai.revision.instruction``), koşullu
yeniden getirme, hedefe yönelik yeniden yazım, doğrulama/onarım döngüsü ve
çelişki denetimi artık orada yaşıyor (tam topoloji için o modülün
docstring'ine bakın). Bu modül, ``app.ai.workflows.revise`` üzerinden
``parse_revision_instruction``, ``locate_target``, ``_merge`` veya
``run_revise`` içe aktaran her mevcut çağıran ve testin değişmeden
çalışmaya devam etmesi için var.
"""

import logging
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.ai.adapters.company_adapter import AdapterProvider
from app.ai.adapters.company_rules import RulesProvider
from app.ai.identity.company_profile import ProfileProvider
from app.ai.llms.base import BaseLLMClient
from app.ai.reasoning_levels import get_reasoning_level_preset
from app.ai.revision.instruction import (
    EditDirective,
    Operation,
    RevisionInstruction,
    Scope,
    TargetSpan,
    _merge,
    decompose_instruction,
    locate_target,
    needs_reretrieval,
    parse_revision_instruction,
)
from app.ai.session.focus import DraftVersion
from app.ai.workflows.events import child_config
from app.ai.workflows.revise_graph import create_revise_graph
from app.core.enums.step_status import StepStatus

logger = logging.getLogger(__name__)

#: Ayrıştırma app.ai.revision.instruction'a taşınmadan ve akışın kendisi
#: derlenmiş bir alt grafiğe taşınmadan önce bunları bu modülden içe aktaran
#: çağıranlar (ve testler) için yeniden dışa aktarılmıştır.
__all__ = [
    "EditDirective",
    "Operation",
    "RevisionInstruction",
    "Scope",
    "TargetSpan",
    "decompose_instruction",
    "locate_target",
    "needs_reretrieval",
    "parse_revision_instruction",
    "run_revise",
]


async def run_revise(
    *,
    active_draft: DraftVersion,
    instructions: str,
    correspondence_type: str,
    llm_client: BaseLLMClient,
    fast_llm_client: Optional[BaseLLMClient],
    reasoning_level: str,
    config: Optional[RunnableConfig] = None,
    emit_token_fn=None,
    mevzuat_retriever: Optional[Any] = None,
    revise_graph: Optional[Any] = None,
    instruction_origin: str = "user_turn",
    company_id: Optional[str] = None,
    adapter_provider: Optional[AdapterProvider] = None,
    rules_provider: Optional[RulesProvider] = None,
    profile_provider: Optional[ProfileProvider] = None,
    today: str = "",
    resolved_placeholder_answers: Optional[dict[str, Any]] = None,
    instruction_haystack: str = "",
) -> dict[str, Any]:
    """Aktif taslağın hedefe yönelik bir revizyonunu üretir.

    ``draft_graph``'ın kendi çıktısıyla aynı şekilde bir sözlük döndürür
    (``status``, ``draft``, ``correspondence_type``, ``confidence_score``,
    ``combined_score``, ``verification``, ``judge``, ``missing_information``,
    ``requires_human_approval``, ``classification``, ``context``,
    ``source_document``), böylece alt akıştaki kod -- ``human_gate_node``,
    ``_step_routing`` ve ``focus_node``'un sürümlemesi -- revize edilmiş bir
    taslağı yeni üretilmiş biriyle aynı şekilde ele alır. Ayrıca bu akışın
    alt grafik sürümünde yeni olan ``conflicts``, ``conflict_notes``,
    ``changelog``, ``pii_findings``, ``repair_items``, ``attempt_history``,
    ``retrieval_meta`` ve ``instruction_origin`` alanlarını da taşır.

    Args:
        active_draft: Revize edilen taslak sürümü; yazıldığı andan itibaren
            kendi zemin bilgisini (``classification``/``context``/
            ``source_document``/``style_examples``/
            ``correspondence_type_source``) taşır.
        instructions: Kullanıcının ayrıştırılmamış revizyon isteği.
        correspondence_type: Çağıranın daha spesifik bir şey vermediği
            durumlarda ``active_draft``'ın kendi tipine düşer (burada yeniden
            çözümlenecek bir şey yok -- revize asla yeniden sınıflandırma
            yapmaz).
        llm_client: Kalite katmanı istemcisi.
        fast_llm_client: İsteğe bağlı hakem ve çelişki denetleyicisi için
            kullanılan hızlı katman istemcisi. Belirtilmezse draft_graph ile
            aynı şekilde ``llm_client``'a düşer.
        reasoning_level: draft_graph'ın reflexion döngüsüyle aynı şekilde
            hakemin açık/kapalı varsayılanını seçer.
        config: Alt grafiğe iletilen çalıştırılabilir yapılandırma; böylece
            düğümlerin kendi ``emit_token``/``emit_node_*`` çağrıları SSE
            kuyruğuna ulaşır (bkz. ``app.ai.workflows.events.child_config``).
        emit_token_fn: Kullanılmıyor -- yalnızca hâlâ
            ``emit_token_fn=emit_token`` geçen mevcut çağıranların
            değişmemesi için tutuluyor. Token akışı artık ``config``
            üzerinden alt grafiğin kendi içinde gerçekleşiyor.
        mevzuat_retriever: Koşullu mevzuat yeniden getirme için isteğe bağlı
            getirici (bkz. ``app.ai.revision.retrieval``).
        revise_graph: ``llm_client``/``fast_llm_client``/``mevzuat_retriever``
            üzerinden bir tane inşa etmek yerine çağrılacak önceden derlenmiş
            bir grafik -- birçok revizyon inşa eden bir çağıranın (veya bir
            testin) bir kez derlemesine olanak tanır.
        instruction_origin: Sıradan bir revize turu için ``"user_turn"``,
            bu çağrı onay kapısının kendi "revizyon iste" eylemine
            (bkz. ``planning_graph.gate_revise_node``) yanıt verdiğinde
            ``"human_gate"``. ``SessionFocus.compute_focus_update``'in
            bunları ayırt edebilmesi için doğrudan sonuca taşınır.
        company_id: Bu revizyonun hangi kiracı için olduğu -- bu şirketin
            çalışma zamanı stil adaptörünü çözer (Faz C2). None,
            ``adapter_provider``'ı atlamakla aynı şekilde adaptör çözümünü
            tamamen atlar.
        adapter_provider: Bir şirketin adaptörünü çözen asenkron çağrılabilir
            (bkz. ``app.domains.companies.provider.get_company_adapter``);
            bu çağrı kendi grafiğini inşa ettiğinde ``create_revise_graph``'a
            iletilir. ``revise_graph`` önceden inşa edilmiş olarak
            verildiğinde göz ardı edilir -- o grafiğin kendi
            adapter_provider'ı (veya yokluğu) zaten geçerlidir.
        rules_provider: Bir şirketin zorunlu yazım kurallarını çözen asenkron
            çağrılabilir (bkz.
            ``app.domains.companies.provider.get_company_rules``);
            ``adapter_provider`` ile aynı şekilde ``create_revise_graph``'a
            iletilir (C27) -- bu olmadan, bu geri düşüş yoluyla kendi
            grafiğini inşa eden bir çağıran (önceden inşa edilmiş bir
            ``revise_graph`` geçirmek yerine -- bu kod tabanındaki her
            çağıranın bugün yaptığı gibi), her revizyonda şirketin zorunlu
            kurallarını sessizce kaybederdi, oysa orijinal taslak bunları
            uygulamıştı. ``revise_graph`` önceden inşa edilmiş olarak
            verildiğinde göz ardı edilir -- o grafiğin kendi rules_provider'ı
            zaten geçerlidir.
        profile_provider: Bir şirketin kimlik profilini çözen asenkron
            çağrılabilir (bkz.
            ``app.domains.companies.provider.get_company_profile``); aynı
            şekilde iletilir (Faz 6). ``revise_graph`` önceden inşa edilmiş
            olarak verildiğinde göz ardı edilir.
        today: Bu revizyonun gerçekleştiği tarih (bkz.
            app.ai.workflows.dates.today_tr); revise_graph.verify_node'un
            kendi tarih-yer tutucu yedeği, yeniden yazım geçişi bir tane
            yeniden getirirse "Tarih:" yer tutucusunu doldurabilsin diye
            iletilir -- sıradan bir revizyon orijinal taslağın tarihini
            değiştirmeden korur (bkz. revise_graph'ın kendi tarih değiştirme
            karşıtı kuralı) ve buna asla ihtiyaç duymaz, ancak başlığı meşru
            şekilde yeniden üreten bir yeniden yazım yine de kullanıcıya
            sorulan bir soruya dönüşmemelidir.
        resolved_placeholder_answers: Taslak turundaki eksik-bilgi gate'inde
            çözülmüş / "Sen karar ver" ile ertelenmiş yer tutucu cevapları
            (`InfoQuestion.key` -> değer veya `AUTO_ANSWER`). None verilirse
            `active_draft.resolved_placeholder_answers`'a düşer. verify_node
            bunları kullanıp kullanıcının zaten cevapladığı bir yer tutucuyu
            tekrar sormaz.
        instruction_haystack: draft_graph'ın `instruction_haystack`'inin
            revizyon karşılığı (bu turun talimatı + önceki kullanıcı turları +
            yerleşmiş brief cevapları). Boşsa `instructions`'a düşer.
            verify_node bunu `verify_draft`'a `instructions=` olarak geçirir.

    Returns:
        Revizyon sonucu.
    """
    del emit_token_fn  # kullanılmıyor; docstring'e bakın

    preset = get_reasoning_level_preset(reasoning_level)
    resolved_correspondence_type = correspondence_type or active_draft.correspondence_type
    graph = revise_graph or create_revise_graph(
        llm_client, fast_llm_client, mevzuat_retriever, adapter_provider, rules_provider,
        profile_provider,
    )

    try:
        final_state = await graph.ainvoke(
            {
                "active_draft": active_draft,
                "instructions": instructions,
                "reasoning_level": preset.level.value,
                "company_id": company_id or "",
                "today": today,
                "resolved_placeholder_answers": (
                    resolved_placeholder_answers
                    if resolved_placeholder_answers is not None
                    else active_draft.resolved_placeholder_answers
                ),
                "instruction_haystack": instruction_haystack or instructions,
            },
            config=child_config(config),
        )
    except Exception as exc:
        logger.exception("Revise sub-graph invocation failed")
        return {
            "draft": active_draft.text,
            "correspondence_type": resolved_correspondence_type,
            "correspondence_sub_genre": active_draft.correspondence_sub_genre,
            "confidence_score": 0.0,
            "combined_score": 0.0,
            "requires_human_approval": True,
            "status": StepStatus.FAILED,
            "error": f"Revizyon üretilemedi: {exc}",
            "classification": active_draft.classification,
            "context": active_draft.context,
            "source_document": active_draft.source_document,
            "writing_brief": active_draft.writing_brief,
            "resolved_placeholder_answers": active_draft.resolved_placeholder_answers,
        }

    status = final_state.get("status", StepStatus.FAILED)
    if status == StepStatus.FAILED:
        return {
            "draft": final_state.get("draft", active_draft.text),
            "correspondence_type": resolved_correspondence_type,
            "correspondence_sub_genre": active_draft.correspondence_sub_genre,
            "confidence_score": 0.0,
            "combined_score": 0.0,
            "requires_human_approval": True,
            "status": StepStatus.FAILED,
            "error": final_state.get("error", "Revizyon üretilemedi."),
            "classification": active_draft.classification,
            "context": active_draft.context,
            "source_document": active_draft.source_document,
            "writing_brief": active_draft.writing_brief,
            "resolved_placeholder_answers": active_draft.resolved_placeholder_answers,
        }

    return {
        "draft": final_state.get("draft", active_draft.text),
        "correspondence_type": final_state.get("correspondence_type") or resolved_correspondence_type,
        "confidence_score": final_state.get("confidence_score", 0.0),
        "combined_score": final_state.get("combined_score", 0.0),
        "requires_human_approval": final_state.get("requires_human_approval", True),
        "evaluation_notes": final_state.get("evaluation_notes", ""),
        "verification": final_state.get("verification", {}),
        "judge": final_state.get("judge", {}),
        "judge_available": final_state.get("judge_available", False),
        "repair_items": final_state.get("repair_items", []),
        "pii_findings": final_state.get("pii_findings", []),
        "missing_information": final_state.get("missing_information", []),
        "attempt_history": final_state.get("attempt_history", []),
        # C29: bu ikisi eskiden alt grafik sonucundan burada eksik kalıyordu --
        # revise_graph.verify_node ikisini de hesaplayıp döndürür (draft_graph'ın
        # kendi sonucunun taşıdığıyla aynı denetlenebilir kural dökümü ve
        # deneme sayısı), ancak bu cephe bunları hiç yüzeye çıkarmıyordu; bu
        # yüzden alt grafiğin gerçekte ne yaptığından bağımsız olarak her
        # revize edilmiş taslak boş applied_rules ve deneme sayısı olmadan
        # kalıcı hale geliyordu.
        "applied_rules": final_state.get("applied_rules", []),
        "attempts": final_state.get("attempts", 0),
        "conflicts": final_state.get("conflicts", []),
        "conflict_notes": final_state.get("conflict_notes", ""),
        "changelog": final_state.get("changelog", {}),
        "retrieval_meta": final_state.get("retrieval_meta", {}),
        "status": status,
        "classification": active_draft.classification,
        "context": final_state.get("context") or active_draft.context,
        "source_document": active_draft.source_document,
        # Revize edilen sürümden değiştirilmeden taşınır, yeniden türetilmez
        # -- bir revizyon ne yeni stil örnekleri getirir ne de yazışma tipini
        # yeniden çözer (bkz. bu modülün docstring'i). Bu, bu sözlükten kendi
        # DraftVersion'ını inşa eden *ikinci* bir gate_revise turunun (bkz.
        # planning_graph.gate_revise_node) bunlara hâlâ sahip olması için
        # gerekli; aksi halde revise_graph'ın verify_node'unun bağlı olduğu
        # PII/geri düşüş tipi kapı eşliği ve sızıntı tespiti sessizce
        # kaybolur.
        "style_examples": [{"text": text} for text in active_draft.style_examples],
        "correspondence_type_source": active_draft.correspondence_type_source,
        "correspondence_sub_genre": final_state.get("correspondence_sub_genre")
        or active_draft.correspondence_sub_genre,
        "writing_brief": active_draft.writing_brief,
        "resolved_placeholder_answers": active_draft.resolved_placeholder_answers,
        "reasoning_level": preset.level.value,
        "instruction_origin": instruction_origin,
    }
