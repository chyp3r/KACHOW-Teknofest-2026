"""Bir şirketin kimliği -- ajanın kendini kim olarak tanıttığı ve yazım
briefi o alanı boş bıraktığında bir taslağın kendi antet/imza bloğunun
kime çözümleneceği.

``app.ai.adapters.company_adapter.CompanyAdapter``'a birkaç alan daha eklemek
yerine bilinçli olarak ayrı bir yapı: ``CompanyAdapter``'ın tüm sözleşmesi
"asla bir gerçek kaynağı değil, yalnızca bir stil tercihi"dir (bkz. kendi
docstring'i); bir şirketin gerçek adı, anteti ve varsayılan imzalayan unvanı
stil değil, gerçektir. İkisini karıştırmak ya bu sözleşmeyi zayıflatmak ya da
her adapter tüketicisine alanları elle geri ayırmayı öğretmek anlamına
gelirdi. ``company_adapter.py``'deki aynı "AI Core asla ``app.domains``'i
import etmez" kuralı burada da geçerli -- okuyucu/yazıcı bunun yerine
``app.domains.companies.provider``'da yaşar ve construction zamanında
assistant/draft/revise graph'larına düz bir async callable olarak enjekte
edilir, aynı ``adapter_provider``/``units_provider`` deseni.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


@dataclass(frozen=True)
class CompanyProfile:
    """Bir şirketin kimliği, AI katmanının bilmesi gerektiği kadarıyla.

    Attributes:
        company_id: Bu profilin hangi kiracıya ait olduğu.
        version: Her yazımda artırılır (bkz. ``app.domains.companies.
            provider.set_company_profile``) -- ``CompanyAdapter.version``
            ile aynı denetim izi amacı.
        display_name: Şirketin tam yasal/resmî adı (örn.
            "Ankara Büyükşehir Belediyesi Fen İşleri Dairesi Başkanlığı").
        short_name: ``display_name``'den farklıysa, gündelik referans için
            daha kısa bir biçim.
        agent_name: Asistanın kendini tanıtırken kullandığı ad (örn.
            "Fen İşleri Karar Destek Asistanı"). Boş ise sistem varsayılan
            kimliği uygulanır (bkz. ``format_agent_identity``).
        letterhead: Yazım briefi henüz bir gönderen kimliği sağlamamışsa
            bir taslağın kendi başlık bölümünün kullanması gereken
            çok satırlı "T.C. ..." kurumsal başlığı.
        default_signer_title: Ne yazım briefi ne de kaynak belge bir unvan
            sağlamadığında, bir taslağın imza bloğunda varsayılan olarak
            kullanılacak unvan (örn. "Daire Başkanı").
        default_signer_name: ``default_signer_title`` ile aynı koşullar
            altında, bir taslağın imza bloğunda varsayılan olarak
            kullanılacak ad (ad soyad). Bilinçli olarak asla gelen belgenin
            kendi ``imza_sahibi``'si değildir -- o ad *karşı tarafa* aittir
            (bkz. ``app.ai.identity.parties.CounterParty``), bize asla
            değil. ``default_signer_title``'dan ayrı tutulur (tek bir
            "varsayılan imzalayan" string'inde birleştirilmez), çünkü bir
            şirket birini diğeri olmadan yapılandırabilir -- dönüşümlü
            imzalayan adıyla sabit bir imza unvanı yaygındır, tersi de
            mümkündür.
        aliases: Bu şirketin kendi adının bir belgede veya kullanıcının
            kendi mesajında görünme biçimleri (kısaltmalar, bir birimin
            kendi kısa formu, eski bir ad) -- bağlamda bulunan bir adın
            *bize* ait olup olmadığına karar verirken ``display_name``/
            ``short_name`` ile aynı şekilde başvurulur (bkz.
            ``app.ai.identity.parties.resolve_party_context``). Hiçbir şeyi
            render etmek için kullanılmaz; yalnızca bir eşleştirme yardımcısıdır.
        updated_at: Son yazımın ISO-8601 zaman damgası, veya bu profil hiç
            ayarlanmamışsa None (bkz. :meth:`empty`).
    """

    company_id: str
    version: int = 0
    display_name: str = ""
    short_name: str = ""
    agent_name: str = ""
    letterhead: str = ""
    default_signer_title: str = ""
    default_signer_name: str = ""
    aliases: tuple[str, ...] = ()
    updated_at: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        """Sistem varsayılan kimliğinin veya bir taslağın varsayılan
        başlık/imzasının üzerine yazmaya değer hiçbir şey olmadığında True."""
        return not (
            self.display_name
            or self.short_name
            or self.agent_name
            or self.letterhead
            or self.default_signer_title
            or self.default_signer_name
            or self.aliases
        )

    @classmethod
    def empty(cls, company_id: str) -> "CompanyProfile":
        """Hiçbir şey yapılandırılmamış bir şirketin çözümlendiği profil.

        Asla ``None`` değildir -- her çağıran, eksik bir profili ayrı bir
        durum olarak ele almak yerine koşulsuz olarak ``.is_empty``'yi
        kontrol edebilir; ``CompanyAdapter.empty`` ile aynı kural.
        """
        return cls(company_id=company_id)

    def to_dict(self) -> dict[str, Any]:
        """JSON güvenli temsil -- ``CompanyModel.settings``'e ve Redis önbellek
        değerine fiilen yazılan şey.

        ``company_id`` bilinçli olarak hariç tutulur, ``CompanyAdapter.to_dict``
        ile aynı gerekçeyle: settings blob'u zaten o şirketin kendi satırının
        içinde yaşar.
        """
        return {
            "version": self.version,
            "display_name": self.display_name,
            "short_name": self.short_name,
            "agent_name": self.agent_name,
            "letterhead": self.letterhead,
            "default_signer_title": self.default_signer_title,
            "default_signer_name": self.default_signer_name,
            "aliases": list(self.aliases),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, company_id: str, value: Optional[dict[str, Any]]) -> "CompanyProfile":
        """``to_dict()`` şeklindeki bir mapping'den (veya hiç ayarlanmamış bir
        şirket için ``None``'dan) yeniden inşa eder."""
        if not value:
            return cls.empty(company_id)
        return cls(
            company_id=company_id,
            version=int(value.get("version") or 0),
            display_name=str(value.get("display_name") or ""),
            short_name=str(value.get("short_name") or ""),
            agent_name=str(value.get("agent_name") or ""),
            letterhead=str(value.get("letterhead") or ""),
            default_signer_title=str(value.get("default_signer_title") or ""),
            default_signer_name=str(value.get("default_signer_name") or ""),
            aliases=tuple(str(a) for a in (value.get("aliases") or []) if str(a).strip()),
            updated_at=value.get("updated_at"),
        )


#: Bir ``company_id`` alan ve o şirketin güncel profilini döndüren async
#: callable (asla hata fırlatmaz, asla None döndürmez -- bkz.
#: ``CompanyProfile.empty``) -- ``AdapterProvider``'ın enjekte edildiği
#: şekilde planning/draft/revise graph'larına enjekte edilir.
ProfileProvider = Callable[[str], Awaitable[CompanyProfile]]
