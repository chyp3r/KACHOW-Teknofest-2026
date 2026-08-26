"""Bir revizyon için deterministik, LLM kullanmayan bir değişiklik günlüğü.

Kullanıcı, önceki/sonraki taslağın tamamını yan yana okumadan *gerçekte
neyin değiştiğini* görebilmelidir. Bu, revizyon öncesi ve sonrası taslak
arasında düz bir paragraf düzeyinde diff'tir (``difflib.SequenceMatcher``)
-- model çağrısı yok, yorumlama yok, sadece neyin taşındığı, neyin
eklendiği ve neyin kaldırıldığı. Talimatın kendi direktiflerine (bkz.
``app.ai.revision.instruction``) atıf, en iyi çaba pozisyonel eşleştirmedir;
bir ipucu olarak gösterilir, kesinlik iddiası taşımaz.
"""

import difflib
from typing import Optional, Sequence

from pydantic import BaseModel, Field

from app.ai.revision.instruction import EditDirective

#: Önceki/sonraki kesitler bu uzunlukta kırpılır -- bir changelog girdisi
#: "bu paragraf değişti" demek içindir, paragrafın tamamını ikinci kez
#: yeniden üretmek için değil.
_SNIPPET_LIMIT = 400

#: `ChangeEntry.directive`'in kendi `max_length` değeri -- (`_SNIPPET_LIMIT`'i
#: yeniden kullanmak yerine) ayrı bir sabit olarak tutulur ki oluşturmadan
#: önce uygulanan kırpma ile alanın kendi doğrulama sınırı sessizce
#: birbirinden uzaklaşamasın. `EditDirective.raw` (tüm-taslak yedek yolunda
#: bu değerin kaynağı -- bkz. `instruction.decompose_instruction`) kendisi
#: sınırsızdır: `_parse_one`'ın kısa, kapalı kelime dağarcıklarından türettiği
#: diğer tüm `EditDirective` alanlarının aksine, kullanıcının tüm revizyon
#: talimatını olduğu gibi taşır. Bundan daha uzun bir talimat eskiden
#: kırpılmadan `ChangeEntry(...)`'e ulaşır ve `audit_node`'un hiç yakalamadığı
#: bir `pydantic.ValidationError` fırlatırdı -- bu, bir changelog atıf
#: hatası yüzünden zaten başarılı olmuş bir revizyonun elden çıkarılması
#: demekti (bu düzeltmenin diğer yarısı için `revise_graph.audit_node`'un
#: kendi sağlamlaştırmasına bakın).
_DIRECTIVE_LIMIT = 200


class ChangeEntry(BaseModel):
    """İki taslak sürümü arasındaki paragraf düzeyinde tek bir değişiklik."""

    directive: str = Field(
        default="", max_length=_DIRECTIVE_LIMIT,
        description="En yakın eşleşen kullanıcı direktifi (varsa), en iyi çaba eşleştirmesi.",
    )
    scope: str = Field(default="", description="Direktifin kapsamı (paragraph/section/whole).")
    before: str = Field(default="", max_length=_SNIPPET_LIMIT)
    after: str = Field(default="", max_length=_SNIPPET_LIMIT)
    char_delta: int = Field(description="after uzunluğu eksi before uzunluğu.")


class RevisionChangelog(BaseModel):
    """Bir revizyon için tam değişiklik günlüğü, en eski değişiklik önce."""

    entries: list[ChangeEntry] = Field(default_factory=list)
    summary: str = Field(default="")


def _truncate(text: str, limit: int = _SNIPPET_LIMIT) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _summarize(entries: list[ChangeEntry]) -> str:
    if not entries:
        return "Taslakta gözle görülür bir değişiklik tespit edilmedi."
    added = sum(1 for e in entries if not e.before and e.after)
    removed = sum(1 for e in entries if e.before and not e.after)
    changed = len(entries) - added - removed
    parts = []
    if changed:
        parts.append(f"{changed} bölüm değiştirildi")
    if added:
        parts.append(f"{added} bölüm eklendi")
    if removed:
        parts.append(f"{removed} bölüm kaldırıldı")
    return ", ".join(parts) + "."


def build_changelog(
    before: str,
    after: str,
    directives: Optional[Sequence[EditDirective]] = None,
) -> RevisionChangelog:
    """İki taslak sürümünü paragraf ayrıntı düzeyinde karşılaştırır (diff).

    Args:
        before: Bu revizyondan önceki taslak metni.
        after: Bu revizyondan sonraki taslak metni.
        directives: En iyi çaba atfı için talimatın kendi direktifleri,
            sırasıyla -- ``i``-inci değişen paragraf grubu, varsa ``i``-inci
            direktifin ``raw`` metniyle etiketlenir; bu yalnızca okuyucu
            için bir ipucudur, hangi direktifin gerçekte hangi değişikliğe
            neden olduğu konusunda bir doğruluk iddiası taşımaz (tek bir
            direktif birden fazla paragrafa dokunabilir veya hiçbirine
            dokunmayabilir).

    Returns:
        En eski değişiklik önce olacak şekilde değişiklik günlüğü.
    """
    before_paragraphs = _split_paragraphs(before)
    after_paragraphs = _split_paragraphs(after)
    directive_texts = [d.raw for d in (directives or [])]
    directive_scopes = [d.scope for d in (directives or [])]

    matcher = difflib.SequenceMatcher(None, before_paragraphs, after_paragraphs, autojunk=False)
    entries: list[ChangeEntry] = []
    directive_index = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        before_text = "\n\n".join(before_paragraphs[i1:i2])
        after_text = "\n\n".join(after_paragraphs[j1:j2])
        directive = directive_texts[directive_index] if directive_index < len(directive_texts) else ""
        scope = directive_scopes[directive_index] if directive_index < len(directive_scopes) else ""
        directive_index += 1

        entries.append(
            ChangeEntry(
                directive=_truncate(directive, _DIRECTIVE_LIMIT),
                scope=scope,
                before=_truncate(before_text),
                after=_truncate(after_text),
                char_delta=len(after_text) - len(before_text),
            )
        )

    return RevisionChangelog(entries=entries, summary=_summarize(entries))
