"""Kim "biz"iz, kim "onlar" -- bu modül var olmadan önce draft/revize
pipeline'ının hiç bir kavramı olmadığı bir taraf modeli.

Bu modülden önce, pipeline içinde hiçbir şey "bu ad bize mi ait, yoksa bu
belgeyi bize gönderen kişiye mi?" diye sormuyordu. Bunun iki somut sonucu vardı:

1. ``prompts/templates/writer.md``'nin imza bloğu kuralı yazarı "Yazım
   Briefi'nde veya **gelen evrakın imza sahibi alanı**nda" varsa aynen
   kullanmasını söylüyordu -- yazım briefi imzalayanı belirtilmemiş
   bıraktığında BİZİM giden mektubumuzu gelen belgenin kendi imzalayanıyla
   imzalamasını doğrudan söylüyordu.
2. ``app.ai.verification.draft_verifier.verify_draft``, *tüm*
   sınıflandırmayı (``imza_sahibi``, ``gonderen_kurum``, ``entities``, ...
   dahil olan ``_flatten_classification``) kendi güvenilen dayanak
   yığınına katlıyor. Yani (1)'in ürettiği kimlik değişimi yalnızca
   cezasız kalmakla kalmıyor -- *maksimum düzeyde dayanaklı* hale
   geliyor: karşı tarafın kendi adı, geldiği aynı sınıflandırma tarafından
   "destekleniyor" ve taslak sanki hiçbir sorun yokmuş gibi puanlanıyor.

``app.ai.workflows.writing_brief``'in yanıt yönü sezgiseli bunu daha da
kötüleştiriyor: ``_resolve_yazan_taraf``/``_resolve_muhatap``, gelen belgeyi
koşulsuz olarak "bize hitaben" olarak ele alıyor ve ``gonderen_kurum``/
``muhatap`` alanlarını bizim kendi gönderen/muhatap alanlarımıza ters
çeviriyor; belgenin gerçekten bize hitaben olup olmadığına dair hiçbir
doğrulama yapmadan -- bir özgeçmiş, bir staj değerlendirme raporu veya
başka herhangi bir üçüncü taraf belgesi aynı şekilde ters çevriliyor,
sessizce yanlış antet ve yanlış muhatap üretiyordu.

Bu modül bunun düzeltmesidir: her draft/revize turunda bir kez çözümlenen
ve hem yazım briefi çözümleyicisi hem de doğrulayıcının dayanak ayrımı
(bkz. ``app.ai.verification.draft_verifier``'ın kendi ``own_facts``/
``counterparty_facts`` ayrımı) boyunca aktarılan küçük, deterministik
(model çağrısı olmayan) bir taraf modeli. ``resolve_party_context``,
gelen belgenin kendi ``muhatap`` alanının gerçekten *bizi* adlandırıp
adlandırmadığını kontrol ederek ``DocumentRelation``'a karar verir -- yeni
bir benzerlik metriği değil, ``draft_verifier``'ın kurum adı parafraz
eşleştirmesi için zaten kullandığı aynı token-overlap merdivenini
(``TOKEN_OVERLAP_THRESHOLD``) yeniden kullanarak. Eşleşme yoksa (veya
belgenin kendi muhatabı hakkında hiçbir şey bilinmiyorsa), belge asla
"bize hitaben" olarak ele alınmaz ve hiçbir rol ters çevirmesi yapılmaz --
karşı tarafın adları karşı taraf adları olarak kalır, yalnızca gövde
metni gerçeği olarak kullanılabilir, asla bizim kendi kimliğimiz olarak değil.
"""

from dataclasses import dataclass
from typing import Any, Literal, Sequence

from app.ai.identity.company_profile import CompanyProfile
from app.ai.verification.draft_verifier import TOKEN_OVERLAP_THRESHOLD, _fold, _token_overlap

#: Gelen belgenin bizimle nasıl ilişkili olduğu, ``resolve_party_context``
#: tarafından bir kez karar verilir ve "bu bize mi hitaben" kararının
#: gerektiği her yerde okunur (``app.ai.workflows.writing_brief``'in rol
#: ters çevirmesi, taslak briefinin kendi çerçevelemesi).
#:
#: - ``"reply_to_us"``: belgenin kendi ``muhatap`` alanı bizi adlandırıyor
#:   (bkz. :func:`resolve_party_context`) -- klasik "bize yazdılar, biz de
#:   geri yazıyoruz" döngüsü. Yalnızca bu değer, belgenin ``gonderen_kurum``'unu
#:   yanıtımızın kendi muhatabı olarak ele almaya izin verir.
#: - ``"third_party"``: bir belge var ve *birini* adlandırıyor, ama bizi
#:   değil -- bir özgeçmiş, bir staj raporu, gerçekten farklı bir kuruma
#:   hitaben olan bir belge veya muhatabının biz olduğunu doğrulayamadığımız
#:   bir belge (hiç kimlik yapılandırılmamış). İçindeki her ad karşı taraf
#:   materyalidir: gövde metni gerçeği olarak kullanılabilir, asla bizim
#:   kendi antet/imza/muhatap alanlarımıza atanamaz.
#: - ``"none"``: hiçbir belge eklenmemiş, veya hiç gönderen/muhatap alanı
#:   taşımıyor -- ters çevrilecek hiçbir şey yok; kim yazıyor, kullanıcının
#:   kendi mesajından veya bizim kendi yapılandırılmış kimliğimizden
#:   çözümlenmelidir.
DocumentRelation = Literal["reply_to_us", "third_party", "none"]


@dataclass(frozen=True)
class SelfParty:
    """Biz: bu mektubu fiilen yazan şirket (ve gevşek biçimde, istek yapan kullanıcı).

    Attributes:
        display_name: Şirketin tam yasal/resmî adı (bkz.
            ``CompanyProfile.display_name``).
        short_name: Yapılandırılmışsa daha kısa bir biçim.
        letterhead: Bir taslağın başlığının kullanması gereken çok satırlı antet metni.
        default_signer_title: İmza bloğunun varsayılan unvanı.
        default_signer_name: İmza bloğunun varsayılan ad soyadı --
            asla gelen belgenin kendi imzalayanı değil (bkz. bu modülün docstring'i).
        aliases: Bu şirketin kendi adının bir belgede veya kullanıcının
            mesajında görünme biçimleri (bkz. ``CompanyProfile.aliases``).
        unit_names: Bu şirketin kendi departman/birim adları (bkz.
            ``app.domains.units.provider.get_active_units_for_routing``) --
            bir kullanıcının gönderen olarak "İnsan Kaynakları"na atıfta
            bulunması, o bizim kendi birimlerimizden biriyse bir belgenin
            muhatabı değil, bizi ifade eder.
        requester_user_id: Bu taslağı isteyen kullanıcının id'si, tamlık/
            gözlemlenebilirlik içindir. Asla bir promptun içine render
            edilmez -- taslaklar, yazım briefinin kendisi aksini söylemedikçe
            adlandırılmış bir çalışan adına değil, bir şirket adına yazılır.
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
        """Meşru olarak bize atıfta bulunan her ad varyantı --
        :func:`resolve_party_context`/``belongs_to_us``'un aday metni
        karşılaştırdığı eşleştirme yüzeyi. Asla doğrudan bir promptun
        içine render edilmez; bunun için ``display_name``/``letterhead`` vardır."""
        return tuple(
            name
            for name in (self.display_name, self.short_name, *self.aliases, *self.unit_names)
            if name
        )

    @property
    def is_known(self) -> bool:
        """Karşılaştırılacak hiç yapılandırılmış bir kimlik olup olmadığı.
        Ne profili ne de yönlendirilebilir birimi olan bir şirket için
        False -- bir yöneticinin profil formunu doldurmasına kadar çoğu
        şirketin içinde bulunduğu durum (bu, herhangi bir gerçek,
        adlandırılmış şirket için bunu True tutan seeder'ın minimal
        varsayılanıdır)."""
        return bool(self.names)


@dataclass(frozen=True)
class CounterParty:
    """Onlar: gelen belgenin kendi başlık/imza alanlarının adlandırdığı kişi --
    yazarın gövdede alıntılayabileceği ama asla kendi antet/imza/muhatap
    alanlarımıza atayamayacağı materyal.

    Attributes:
        gonderen_kurum: Belgenin kendi gönderen kurumu.
        muhatap: Belgenin kendi muhatabı.
        imza_sahibi: Belgenin kendi imzalayanı.
        basvuran_adi: Belge bir dilekçe şeklindeyse, belgenin kendi başvuran adı.
        entities: Sınıflandırıcının belge gövdesinde fark ettiği diğer
            ad/kurum/tarihler (bkz. ``EvrakField.entities``) -- yapı gereği
            türsüz ve kaynaksız, bu yüzden yukarıdaki alanlarla aynı şekilde
            ele alınır: karşı taraf materyali, yalnızca alıntılanabilir.
    """

    gonderen_kurum: str = ""
    muhatap: str = ""
    imza_sahibi: str = ""
    basvuran_adi: str = ""
    entities: tuple[str, ...] = ()

    @classmethod
    def from_classification(cls, classification: dict[str, Any] | None) -> "CounterParty":
        """Bir belge analizi ``classification`` dict'inden inşa eder (
        ``app.ai.workflows.draft_graph._build_brief``'in render ettiği
        aynı şekil)."""
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
        """Bu karşı tarafın bilindiği her ad -- ``belongs_to_them``'in
        aday metni karşılaştırdığı eşleştirme yüzeyi."""
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
    """``value``'nun ``names``'ten (birine) atıfta bulunup bulunmadığı;
    ``draft_verifier._support_for``'un kurum adları için yaptığı gibi
    parafrazı tolere eder: tam bir katlama eşleşmesi, veya deterministik
    doğrulayıcının kurum adı parafraz eşleştirmesi için zaten kullandığı
    aynı ``TOKEN_OVERLAP_THRESHOLD``'a eşit ya da üzerinde bir
    token-overlap oranı. Bilinçli olarak yeni bir benzerlik metriği değil --
    burası ``draft_verifier``'ın dışında "bu, şunun parafrazı mı" sorusuna
    ihtiyaç duyan tek yer ve verifier'ın aynı soruya verdiği yanıttan asla
    sapmamalıdır.
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
    """Bir draft/revize turu için çözümlenmiş taraf modeli."""

    us: SelfParty
    them: CounterParty
    relation: DocumentRelation

    def belongs_to_us(self, value: str) -> bool:
        """``value``'nun (bir taslakta veya bir alan çözümlemesinde
        bulunan bir ad) bize atıfta bulunup bulunmadığı."""
        return _matches_any(value, self.us.names)

    def belongs_to_them(self, value: str) -> bool:
        """``value``'nun gelen belgede adlandırılan karşı tarafa atıfta
        bulunup bulunmadığı."""
        return _matches_any(value, self.them.names)


def resolve_party_context(
    profile: CompanyProfile,
    *,
    unit_names: Sequence[str] = (),
    classification: dict[str, Any] | None = None,
    requester_user_id: str = "",
) -> PartyContext:
    """Bu turun taraf modelini çözümler.

    Args:
        profile: İstek yapan şirketin kimlik profili (bkz.
            ``app.domains.companies.provider.get_company_profile``).
        unit_names: Bu şirketin kendi aktif, yönlendirilebilir birim adları
            (bkz. ``app.domains.units.provider.get_active_units_for_routing``).
        classification: Gelen belgenin analiz sonucu, veya belgesiz bir tur
            için ``None``/``{}``.
        requester_user_id: Bu taslağı isteyen kullanıcının id'si.

    Returns:
        Çözümlenmiş bağlam. ``relation``, yalnızca belgenin kendi
        ``muhatap`` alanı bilinip ``us``'un kendi adlarından biriyle
        eşleştiğinde ``"reply_to_us"`` olur -- var olan
        ``app.ai.workflows.writing_brief`` yanıt yönü sezgiselinin yaptığı
        gibi asla varsayılan olarak varsayılmaz. Geri kalan her şey (hiç
        taraf alanı olmayan bir belge, muhatabı bizimle eşleşmeyen bir
        belge, veya hiç kendi kimliğimiz yapılandırılmadığı için basitçe
        doğrulayamadığımız bir belge) ``"third_party"``/``"none"``'a
        çözümlenir, asla kör bir rol ters çevirmesine değil.
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
