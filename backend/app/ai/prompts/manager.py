import hashlib
import logging
import os
import re
from typing import Any, Dict, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

#: Yer tutucular ``{{name}}`` biçimindedir, asla ``{name}`` değil. Şablonlar
#: tek küme parantezli literal JSON örnekleri gömer, bu yüzden onların
#: üzerinde :meth:`str.format` kullanılamaz -- JSON anahtarlarında ``KeyError``
#: fırlatır. Codebase'deki her renderer bu modülden geçmelidir, böylece iki
#: kural birbirinden tekrar sapamaz.
_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


#: Bu codebase'in ürettiği her şablon için beyan edilmiş ``{{placeholder}}``
#: kümesi. Burada karşılık gelen bir güncelleme olmadan yeni bir yer tutucu
#: kazanan bir şablon (veya beyan edilmiş birini sağlamayı bırakan bir agent),
#: tam olarak bu sözleşmenin yakaladığı sapmadır -- bkz.
#: ``tests/unit/ai/test_prompt_templates.py``.
TEMPLATE_CONTRACTS: Dict[str, frozenset] = {
    "assistant": frozenset(
        {
            "history_summary",
            "document_context",
            "security_boundary",
            "agent_identity",
            "user_display_name",
        }
    ),
    "classifier": frozenset(),
    "compliance": frozenset(),
    "router": frozenset(),
    "writer": frozenset(),
    "judge": frozenset(),
    "guardrail_judge": frozenset(),
    "reviser": frozenset(),
    "memory_summary": frozenset({"existing_summary", "new_turns"}),
    "conflict_auditor": frozenset(),
    "summarizer": frozenset(),
}


def declared_placeholders(template: str) -> set:
    """Bir şablonun metninin beyan ettiği ``{{name}}`` yer tutucularını döndürür.

    Args:
        template: Ham şablon metni (bir şablon adı değil -- yalnızca bir adı
            olan çağıranlar önce onu :meth:`PromptManager.get_template`
            aracılığıyla okumalıdır).

    Returns:
        Metinde bulunan farklı yer tutucu adlarının kümesi.
    """
    return set(_PLACEHOLDER_PATTERN.findall(template))


def render_placeholders(
    template: str, context: Mapping[str, Any], *, strict: bool = False
) -> str:
    """Bir şablondaki ``{{name}}`` yer tutucularını değiştirir.

    Args:
        template: Ham şablon metni.
        context: Yer tutucu adına göre anahtarlanmış, yerine konacak değerler.
        strict: True olduğunda, bir yer tutucunun sağlanan değeri yoksa
            loglamak yerine hata fırlatır. Üretim render'ı, eşleşmeyen bir
            yer tutucuyu her zaman olduğu gibi bırakır, böylece kısmen
            sağlanmış bir bağlam boş kalmak yerine okunabilir kalır;
            ``strict``, beyan edilen her yer tutucunun gerçekten
            sağlandığını doğrulamak isteyen testler için vardır.

    Returns:
        Render edilmiş metin.

    Raises:
        KeyError: ``strict`` True ise ve bir yer tutucunun eşleşen bir
            anahtarı yoksa.
    """

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            if strict:
                raise KeyError(f"Prompt placeholder '{{{{{key}}}}}' has no value.")
            logger.warning("Prompt placeholder '{{%s}}' has no value; left as-is.", key)
            return match.group(0)
        return str(context[key])

    return _PLACEHOLDER_PATTERN.sub(_replace, template)


class PromptManager:
    """Prompt şablonlarını diskten yükler, önbelleğe alır ve render eder.

    Prompt metnini uygulama kodundan ayırır ve şablonların içindeki JSON
    örneklerini küme parantezi tabanlı biçimlendirmeye karşı güvenli tutar.
    """

    def __init__(self, templates_dir: Optional[str] = None):
        """Prompt Manager'ı başlatır.

        Args:
            templates_dir: Şablonlar klasörüne isteğe bağlı yol. Varsayılan
                olarak bu dosyanın yanındaki ``templates`` klasörü kullanılır.
        """
        self.templates_dir = templates_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "templates"
        )
        #: ad -> (içerik, sürüm). ``version``, bir mtime değil kısa bir
        #: içerik hash'idir -- makineler/checkout'lar arasında deterministik
        #: ve bayt bayt aynı şablonlar için özdeştir; bu da
        #: ``GuardrailEventModel.prompt_template_version``'ın gerçekte bilmek
        #: istediği şeydir ("bu kararı hangi revizyon üretti").
        self._cache: Dict[str, Tuple[str, str]] = {}
        logger.info("Initialized PromptManager with templates_dir: %s", self.templates_dir)

    def _load(self, base_name: str) -> Tuple[str, str]:
        cached = self._cache.get(base_name)
        if cached is not None:
            return cached

        file_path = os.path.join(self.templates_dir, base_name)
        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f"Prompt template '{base_name}' not found at path: {file_path}"
            )

        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except Exception:
            logger.exception("Failed to read prompt template '%s'", base_name)
            raise

        version = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
        self._cache[base_name] = (content, version)
        logger.debug("Loaded and cached prompt template: %s (version %s)", base_name, version)
        return content, version

    def get_template(self, name: str) -> str:
        """Diskten bir prompt şablonu okur, ya da önbellekteki kopyayı döndürür.

        Args:
            name: ``.md`` uzantılı veya uzantısız şablon adı.

        Returns:
            Şablon metni.

        Raises:
            FileNotFoundError: Böyle bir şablon yoksa.
        """
        base_name = name if name.endswith(".md") else f"{name}.md"
        content, _ = self._load(base_name)
        return content

    def get_template_version(self, name: str) -> str:
        """Yüklenen şablonun içerik hash'i sürümünü döndürür.

        Args:
            name: ``.md`` uzantılı veya uzantısız şablon adı.

        Returns:
            Şablonun güncel içeriğinin kısa, deterministik bir hash'i --
            ``GuardrailEventModel.prompt_template_version``'ın bir guardrail
            kararının yanına kaydettiği değer.

        Raises:
            FileNotFoundError: Böyle bir şablon yoksa.
        """
        base_name = name if name.endswith(".md") else f"{name}.md"
        _, version = self._load(base_name)
        return version

    def render(self, name: str, *, strict: bool = False, **kwargs: Any) -> str:
        """Bir şablonu yükler ve ``{{variable}}`` yer tutucularını değiştirir.

        Args:
            name: Şablon adı.
            strict: Bkz. :func:`render_placeholders`.
            **kwargs: Yer tutucu değerleri.

        Returns:
            Render edilmiş prompt.
        """
        return render_placeholders(self.get_template(name), kwargs, strict=strict)

    def clear_cache(self) -> None:
        """Şablon önbelleğini temizler."""
        self._cache.clear()
        logger.debug("PromptManager cache cleared.")


#: Şablonlar çalışma zamanında salt okunurdur, bu yüzden süreç başına bir
#: yönetici yeterlidir ve her agent constructor'ının bir dizin stat çağrısı
#: yapmasını önler.
_default_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    """Süreç genelindeki PromptManager'ı döndürür."""
    global _default_manager
    if _default_manager is None:
        _default_manager = PromptManager()
    return _default_manager
