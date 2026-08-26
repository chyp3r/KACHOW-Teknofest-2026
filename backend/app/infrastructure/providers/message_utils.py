import logging

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

logger = logging.getLogger(__name__)


def convert_messages(messages: list[dict]) -> list[BaseMessage]:
    """Standart mesaj dict'lerini LangChain Message nesnelerine dönüştürür.

    Bir LangChain chat modeliyle konuşan her ``BaseLLMClient``
    implementasyonu (``OllamaClient``, ``EvrenClient``) tarafından
    paylaşılır: eşleme sağlayıcıdan bağımsızdır, yalnızca bir
    dict -> ``BaseMessage`` çevirisidir.

    Orijinal üç rolün ötesinde iki rol daha vardır ve bunlar bir
    tool-calling döngüsünü ileri-geri taşımak için bulunur: bir
    ``assistant`` mesajı bir ``tool_calls`` anahtarı taşıyabilir (modelin
    kendi önceki turunun bir veya daha fazla tool istemesi), ve bir
    ``tool`` mesajı o turun sonucunu taşır (``tool_call_id``, ``name``,
    ``content``). İkisi de ham LangChain nesneleri yerine düz JSON-uyumlu
    dict'lerdir, böylece çağıranın mesaj listesi döngü turları arasında
    serileştirilebilir kalır (SSE debug loglaması için faydalı).
    """
    lc_messages: list[BaseMessage] = []
    for msg in messages:
        role = msg.get("role", "user").lower()
        content = msg.get("content", "")
        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                lc_messages.append(AIMessage(content=content, tool_calls=tool_calls))
            else:
                lc_messages.append(AIMessage(content=content))
        elif role == "tool":
            lc_messages.append(
                ToolMessage(
                    content=content,
                    tool_call_id=msg.get("tool_call_id", ""),
                    name=msg.get("name"),
                )
            )
        else:
            logger.warning(
                "Unknown message role: %s, defaulting to HumanMessage", role
            )
            lc_messages.append(HumanMessage(content=content))

    # Yalnızca bir sistem turu verilen bir chat modelinin yanıt vereceği bir
    # şey yoktur ve bazı sağlayıcılar boş bir tamamlama üretir. Bir
    # kullanıcı turu garanti et.
    if lc_messages and all(isinstance(m, SystemMessage) for m in lc_messages):
        lc_messages.append(HumanMessage(content="Yönergeye göre yanıt üret."))
    return lc_messages
