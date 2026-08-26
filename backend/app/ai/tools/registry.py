"""Deklaratif araç spesifikasyonları ve bunların LangChain bağlaması.

:mod:`app.ai.workflows.step_graph`'taki ``STEP_SPECS``/``STEP_RUNNERS``
ayrımını yansıtır: bir ``ToolSpec``, işi fiilen yapan tek callable'ın yanında
veridir (ad, açıklama, argüman şeması); belirli bir LLM sağlayıcısının
araçları nasıl beyan etmek istediğinden ayrı tutulur.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

__all__ = ["ToolSpec", "to_langchain_tool"]


@dataclass(frozen=True)
class ToolSpec:
    """Asistan ajanının çağırabileceği bir araç.

    Attributes:
        name: Modelin bir araç çağrısında atıfta bulunacağı kararlı araç adı.
        description: Aracın ne yaptığı ve ne zaman çağrılacağı -- modelin
            aracın gerekli olup olmadığına karar vermek için gördüğü tek şey
            budur, bu yüzden uygulamayı değil *sonucu* tanımlamalıdır.
        args_schema: Aracın argümanlarını tanımlayan Pydantic modeli.
        handler: Aracın işini yapan ve modele geri beslenecek metni döndüren
            async callable. Doğrudan asistan ajanının kendi döngüsü
            tarafından çağrılır -- yalnızca :func:`to_langchain_tool`'un
            yalnızca-şema temsilcisini gören LangChain'in kendi araç
            yürütücüsü tarafından asla değil.
    """

    name: str
    description: str
    args_schema: type[BaseModel]
    handler: Callable[..., Awaitable[str]]


def to_langchain_tool(spec: ToolSpec) -> StructuredTool:
    """Bir sağlayıcının ``bind_tools``'unun ihtiyaç duyduğu, yalnızca-şema
    LangChain aracını inşa eder.

    Döndürülen araç LangChain'in kendisi tarafından asla yürütülmez --
    asistan ajanı, bağlanmış bir çağrıdan sonra ``AIMessage.tool_calls``'u
    inceler ve ``spec.handler``'ı ada göre eşleştirerek doğrudan çağırır. Bu
    temsilci yalnızca ``bind_tools``'un modele gönderilen araç şemasını (ad,
    açıklama, argümanlar için JSON şeması) türetmek için bağlanabilir
    *bir şeye* ihtiyaç duyduğu için var.

    Args:
        spec: Bağlanacak araç.

    Returns:
        ``spec``'in şemasını taşıyan bir ``StructuredTool``.
    """

    async def _unused(**_kwargs: Any) -> str:
        raise RuntimeError(
            f"'{spec.name}' must be invoked via ToolSpec.handler, not "
            "LangChain's own tool executor."
        )

    return StructuredTool.from_function(
        name=spec.name,
        description=spec.description,
        args_schema=spec.args_schema,
        coroutine=_unused,
    )
