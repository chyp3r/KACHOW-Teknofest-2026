"""Who is "us" and who is "them" -- a party model the draft/revision
pipeline had no notion of at all before this module existed.

Before this module, nothing in the pipeline ever asked "does this name
belong to us, or to whoever sent us this document?" Two concrete
consequences followed:

1. ``prompts/templates/writer.md``'s signature-block rule told the writer
   to use "Yazım Briefi'nde veya **gelen evrakın imza sahibi alanı**nda"
   varsa aynen kullan -- literally instructing it to sign OUR outgoing
   letter with the incoming document's own signatory, whenever the writing
   brief left the signer unspecified.
2. ``app.ai.verification.draft_verifier.verify_draft`` folds the *entire*
   classification (``_flatten_classification``, which includes
   ``imza_sahibi``, ``gonderen_kurum``, ``entities``, ...) into its trusted
   grounding haystack. So the exact identity swap (1) produces is not just
   unpunished -- it is *maximally grounded*: the counterparty's own name is
   "supported" by the very same classification it came from, and the draft
   scores as if nothing were wrong.

``app.ai.workflows.writing_brief``'s reply-direction heuristic compounds
this: ``_resolve_yazan_taraf``/``_resolve_muhatap`` unconditionally treat
the incoming document as "addressed to us" and reverse its
``gonderen_kurum``/``muhatap`` fields into our own sender/addressee slots,
with no verification that the document was actually addressed to us at all
-- a CV, an internship evaluation report, or any third-party document
reversed the same way, silently producing the wrong letterhead and the
wrong addressee.

This module is the fix: a small, deterministic (no model call) party model
resolved once per draft/revise turn and threaded through both the
writing-brief resolver and the verifier's grounding split (see
``app.ai.verification.draft_verifier``'s own ``own_facts``/
``counterparty_facts`` split). ``resolve_party_context`` decides
``DocumentRelation`` by checking whether the incoming document's own
``muhatap`` field actually names *us* -- reusing the exact same
token-overlap ladder (``TOKEN_OVERLAP_THRESHOLD``) ``draft_verifier``
already uses for institution-name paraphrase matching, not a new
similarity metric. When it does not match (or nothing about the document's
own addressee is known at all), the document is never treated as
"addressed to us", and no role reversal happens -- the counterparty's names
stay counterparty names, usable only as body-text facts, never as our own
identity.
"""

from dataclasses import dataclass
from typing import Any, Literal, Sequence

from app.ai.identity.company_profile import CompanyProfile
from app.ai.verification.draft_verifier import TOKEN_OVERLAP_THRESHOLD, _fold, _token_overlap

#: How the incoming document relates to us, decided once by
#: ``resolve_party_context`` and read everywhere a "was this addressed to
#: us" decision is needed (``app.ai.workflows.writing_brief``'s
#: role-reversal, the draft brief's own framing).
#:
#: - ``"reply_to_us"``: the document's own ``muhatap`` field names us (see
#:   :func:`resolve_party_context`) -- the classic "they wrote to us, we
#:   write back" cycle. Only this value ever licenses treating the
#:   document's ``gonderen_kurum`` as our reply's own addressee.
#: - ``"third_party"``: a document exists and named *someone*, but not us
#:   -- a CV, an internship report, a document genuinely addressed to a
#:   different institution, or one whose addressee we simply cannot
#:   confirm is us (no self-identity configured at all). Every name in it
#:   is counterparty material: usable as a body-text fact, never assigned
#:   to our own antet/imza/muhatap slots.
#: - ``"none"``: no document is attached, or it carries no
#:   sender/addressee fields at all -- there is nothing to reverse either
#:   way; whoever is writing must be resolved from the user's own message
#:   or our own configured identity instead.
DocumentRelation = Literal["reply_to_us", "third_party", "none"]


@dataclass(frozen=True)
class SelfParty:
    """Us: the company (and, loosely, the requesting user) actually
    writing this letter.

    Attributes:
        display_name: The company's full legal/official name (see
            ``CompanyProfile.display_name``).
        short_name: A shorter form, if configured.
        letterhead: The multi-line antet text a draft's header should use.
        default_signer_title: The signature block's default unvan.
        default_signer_name: The signature block's default ad soyad --
            never the incoming document's own signatory (see this module's
            docstring).
        aliases: Alternate ways this company's own name appears in a
            document or a user's message (see ``CompanyProfile.aliases``).
        unit_names: This company's own department/unit names (see
            ``app.domains.units.provider.get_active_units_for_routing``) --
            a user referring to "İnsan Kaynakları" as the sender means us,
            not a document's addressee, when that is one of our own units.
        requester_user_id: The id of the user who asked for this draft, for
            completeness/observability. Never rendered into a prompt --
            drafts are written on behalf of a company, not a named
            employee, unless the writing brief itself says otherwise.
    """

    display_name: str = ""
    short_name: str = ""
    letterhead: str = ""
    default_signer_title: str = ""
    default_signer_name: str = ""
    aliases: tuple[str, ...] = ()
    unit_names: tuple[str, ...] = ()
    requester_user_id: str = ""

    @property
    def names(self) -> tuple[str, ...]:
        """Every name variant that legitimately refers to us -- the
        matching surface :func:`resolve_party_context`/``belongs_to_us``
        compare candidate text against. Never rendered directly into a
        prompt; ``display_name``/``letterhead`` are for that."""
        return tuple(
            name
            for name in (self.display_name, self.short_name, *self.aliases, *self.unit_names)
            if name
        )

    @property
    def is_known(self) -> bool:
        """Whether there is any configured identity to match against at
        all. False for a company with no profile and no routable units --
        the state most companies are in until an admin fills the profile
        form in (see the seeder's minimal default, which keeps this True
        for any real, named company)."""
        return bool(self.names)


@dataclass(frozen=True)
class CounterParty:
    """Them: whoever the incoming document's own header/signature fields
    name -- material the writer may cite in the body, never assign to our
    own antet/imza/muhatap slots.

    Attributes:
        gonderen_kurum: The document's own sender institution.
        muhatap: The document's own addressee.
        imza_sahibi: The document's own signatory.
        basvuran_adi: The document's own applicant name, when it is a
            petition-shaped document.
        entities: Other names/institutions/dates the classifier noticed in
            the document body (see ``EvrakField.entities``) -- untyped and
            unprovenanced by construction, so treated the same as the
            fields above: counterparty material, cite-only.
    """

    gonderen_kurum: str = ""
    muhatap: str = ""
    imza_sahibi: str = ""
    basvuran_adi: str = ""
    entities: tuple[str, ...] = ()

    @classmethod
    def from_classification(cls, classification: dict[str, Any] | None) -> "CounterParty":
        """Build from a document-analysis ``classification`` dict (the
        same shape ``app.ai.workflows.draft_graph._build_brief`` renders
        from)."""
        classification = classification or {}
        fields: Any = classification.get("fields") or {}
        if hasattr(fields, "model_dump"):
            fields = fields.model_dump()
        entities = classification.get("entities") or []
        return cls(
            gonderen_kurum=str(fields.get("gonderen_kurum") or "").strip(),
            muhatap=str(fields.get("muhatap") or "").strip(),
            imza_sahibi=str(fields.get("imza_sahibi") or "").strip(),
            basvuran_adi=str(fields.get("basvuran_adi") or "").strip(),
            entities=tuple(str(entity) for entity in entities if entity),
        )

    @property
    def names(self) -> tuple[str, ...]:
        """Every name this counterparty is known by -- the matching
        surface ``belongs_to_them`` compares candidate text against."""
        return tuple(
            name
            for name in (
                self.gonderen_kurum,
                self.muhatap,
                self.imza_sahibi,
                self.basvuran_adi,
                *self.entities,
            )
            if name
        )

    @property
    def is_known(self) -> bool:
        return bool(self.gonderen_kurum or self.muhatap)


def _matches_any(value: str, names: Sequence[str]) -> bool:
    """Whether ``value`` refers to (one of) ``names``, tolerating
    paraphrase the same way ``draft_verifier._support_for`` does for
    institution names: an exact fold match, or a token-overlap ratio at or
    above the same ``TOKEN_OVERLAP_THRESHOLD`` the deterministic verifier
    already uses. Deliberately not a new similarity metric -- this is the
    one place outside ``draft_verifier`` itself that needs "is this
    paraphrase of that", and it should never drift from the verifier's own
    answer to the same question.
    """
    if not value:
        return False
    folded_value = _fold(value)
    if not folded_value:
        return False
    for name in names:
        if not name:
            continue
        folded_name = _fold(name)
        if not folded_name:
            continue
        if folded_name in folded_value or folded_value in folded_name:
            return True
        if _token_overlap(folded_name, folded_value) >= TOKEN_OVERLAP_THRESHOLD:
            return True
    return False


@dataclass(frozen=True)
class PartyContext:
    """The resolved party model for one draft/revise turn."""

    us: SelfParty
    them: CounterParty
    relation: DocumentRelation

    def belongs_to_us(self, value: str) -> bool:
        """Whether ``value`` (a name found somewhere in a draft or a slot
        resolution) refers to us."""
        return _matches_any(value, self.us.names)

    def belongs_to_them(self, value: str) -> bool:
        """Whether ``value`` refers to the counterparty named in the
        incoming document."""
        return _matches_any(value, self.them.names)


def resolve_party_context(
    profile: CompanyProfile,
    *,
    unit_names: Sequence[str] = (),
    classification: dict[str, Any] | None = None,
    requester_user_id: str = "",
) -> PartyContext:
    """Resolve this turn's party model.

    Args:
        profile: The requesting company's identity profile (see
            ``app.domains.companies.provider.get_company_profile``).
        unit_names: This company's own active routable unit names (see
            ``app.domains.units.provider.get_active_units_for_routing``).
        classification: The incoming document's analysis result, or
            ``None``/``{}`` for a document-less turn.
        requester_user_id: The id of the user who asked for this draft.

    Returns:
        The resolved context. ``relation`` is ``"reply_to_us"`` only when
        the document's own ``muhatap`` field is known AND matches one of
        ``us``'s own names -- never assumed by default the way the
        pre-existing ``app.ai.workflows.writing_brief`` reply-direction
        heuristic did. Everything else (a document with no party fields at
        all, a document whose addressee doesn't match us, or one we simply
        cannot verify because no self-identity is configured) resolves to
        ``"third_party"``/``"none"``, never to a blind role reversal.
    """
    us = SelfParty(
        display_name=profile.display_name,
        short_name=profile.short_name,
        letterhead=profile.letterhead,
        default_signer_title=profile.default_signer_title,
        default_signer_name=profile.default_signer_name,
        aliases=profile.aliases,
        unit_names=tuple(name for name in unit_names if name),
        requester_user_id=requester_user_id,
    )
    them = CounterParty.from_classification(classification)

    if not them.is_known:
        relation: DocumentRelation = "none"
    elif us.is_known and _matches_any(them.muhatap, us.names):
        relation = "reply_to_us"
    else:
        relation = "third_party"

    return PartyContext(us=us, them=them, relation=relation)
