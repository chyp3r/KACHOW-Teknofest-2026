"""Bir şirketin çalışma zamanı üslup adaptörü -- Faz C2, RLHF katmanının
anında-etkili yarısı (bir prompt'a nasıl ulaştığı için bkz.
[[app.ai.adapters.injection]], ve #185'in kendi çerçevesi).

Bilinçli olarak I/O içermeyen ve bu modülün hiçbir yerinde ``app.domains``
import etmeyen düz, değişmez (immutable) bir dataclass: bu kod tabanının AI
Core'u domains katmanını asla import etmez (bkz. ``docs/architecture/
backend.md``, "Backend yalnızca AI Core'u çağırır" -- bağımlılık yalnızca
diğer yöne işaret eder). Bunlardan birini üreten gerçek Redis/Postgres
destekli okuyucu/yazıcı bunun yerine ``app.domains.companies.provider``
içinde yaşar ve oluşturma sırasında draft/revise grafiklerine düz bir async
callable olarak enjekte edilir -- routing grafiğinin ``units_provider``'ı
için ``app.domains.units.provider.get_active_units_for_routing``'in zaten
kurduğu tam olarak aynı desen.
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional


@dataclass(frozen=True)
class CompanyAdapter:
    """Bir şirketin birikmiş üslup tercihleri.

    YALNIZCA üslup ve biçimi taşır, asla gerçekleri taşımaz -- bu sadece bir
    sözleşme değil, yapısal olarak zorunlu kılınır: bu sınıfta dünya
    hakkında bir iddiaya (bir gerçek, bir isim, bir tarih) benzeyen hiçbir
    şey yoktur, yalnızca *nasıl* yazılacağına dair tercihler vardır.
    ``preferred_examples`` gerçek üretilmiş metindir, bu yüzden
    ``style_examples``'ın zaten geçtiği aynı ``ornek_sizintisi``
    (örnek-sızıntısı) deterministik kontrolüne beslenir (bkz.
    ``draft_verifier.verify_draft``'ın ``style_examples`` parametresi) --
    tercih edilen bir örnekten sızan bir şirket adı veya tarih, getirilen bir
    few-shot örneğinden sızan biriyle tıpatıp aynı şekilde yakalanır, ayrı
    bir kontrole gerek yoktur.

    Attributes:
        company_id: Bu adaptörün ait olduğu kiracı (tenant).
        version: Her yazımda artırılır (bkz. ``app.domains.companies.
            provider.set_company_adapter``) -- bir eğitim çalıştırmasının
            (Faz C3) veya bir yöneticinin manuel düzenlemesinin denetim
            izinde ve ``GET .../adapter`` yanıtında birbirinden
            ayırt edilmesini sağlar.
        style_rules: Bir yazım tercihini açıklayan kısa Türkçe cümleler
            (örn. "Kapanışta her zaman 'Arz ederim' kullan"). Madde
            işaretli liste olarak render edilir, rehberlik olarak uygulanır,
            asla bir gerçek kaynağı olarak değil.
        preferred_examples: Şirketin tercih ettiği üslubu temsil ettiğini
            onayladığı tam örnek metinler. ``style_examples`` ile aynı güven
            sınırı: yalnızca üslup referansı, aynı sızıntı kontrolüne tabi.
        avoided_patterns: ``style_rules``'ın aynası -- bu şirketin
            taslaklarının KULLANMAMASI gereken bir kalıbın kısa açıklamaları
            (örn. "Edilgen çatı kullanma").
        trained_at: Son yazımın ISO-8601 zaman damgası, veya bu adaptör hiç
            ayarlanmamışsa None (bkz. :meth:`empty`).
        sample_count: Bu sürümü kaç geri bildirim/eğitim örneğinin
            bilgilendirdiği -- elle yazılmış bir adaptör için 0 (Faz C3'ün
            otomatik madenciliği var olmadan önce, bir yöneticinin
            doğrudan kural yazması). Yalnızca bilgilendirme amaçlıdır,
            adaptörün uygulanıp uygulanmayacağını belirlemek için asla
            kullanılmaz.
    """

    company_id: str
    version: int = 0
    style_rules: tuple[str, ...] = field(default_factory=tuple)
    preferred_examples: tuple[str, ...] = field(default_factory=tuple)
    avoided_patterns: tuple[str, ...] = field(default_factory=tuple)
    trained_at: Optional[str] = None
    sample_count: int = 0

    @property
    def is_empty(self) -> bool:
        """Bir prompt'a enjekte edilmeye değer hiçbir şey yoksa True."""
        return not (self.style_rules or self.preferred_examples or self.avoided_patterns)

    @classmethod
    def empty(cls, company_id: str) -> "CompanyAdapter":
        """Yapılandırılmış tercihi olmayan bir şirketin çözümlendiği adaptör.

        Asla ``None`` değil -- her çağıran (``writer_node``, ``rewrite_node``,
        ...) eksik bir adaptörü ayrı bir durum olarak ele almak yerine
        koşulsuzca ``.is_empty``'i kontrol edebilir.
        """
        return cls(company_id=company_id)

    def to_dict(self) -> dict[str, Any]:
        """JSON'a uygun gösterim -- ``CompanyModel.settings`` ve Redis önbellek
        değerine gerçekten yazılan şey.

        ``company_id`` bilinçli olarak hariç tutulur: settings blob'u zaten
        o şirketin kendi satırının *içinde* yaşar, orada id'yi tekrar
        belirtmek, satırın gerçek id'sinden sapabilecek gereksiz veri olurdu.
        """
        return {
            "version": self.version,
            "style_rules": list(self.style_rules),
            "preferred_examples": list(self.preferred_examples),
            "avoided_patterns": list(self.avoided_patterns),
            "trained_at": self.trained_at,
            "sample_count": self.sample_count,
        }

    @classmethod
    def from_dict(cls, company_id: str, value: Optional[dict[str, Any]]) -> "CompanyAdapter":
        """``to_dict()`` biçimli bir eşlemeden (veya hiç ayarlanmamış bir
        şirket için ``None``'dan) yeniden oluşturur."""
        if not value:
            return cls.empty(company_id)
        return cls(
            company_id=company_id,
            version=int(value.get("version") or 0),
            style_rules=tuple(value.get("style_rules") or ()),
            preferred_examples=tuple(value.get("preferred_examples") or ()),
            avoided_patterns=tuple(value.get("avoided_patterns") or ()),
            trained_at=value.get("trained_at"),
            sample_count=int(value.get("sample_count") or 0),
        )


#: Bir ``company_id`` alan ve o şirketin mevcut adaptörünü döndüren async
#: callable (asla hata fırlatmaz, asla None döndürmez -- bkz.
#: ``CompanyAdapter.empty``) -- ``routing_graph.UnitsProvider`` ile aynı
#: şekilde ``create_draft_graph``/``create_revise_graph``'a enjekte edilir,
#: böylece bu modül (ve her grafik modülü) asla ``app.domains`` import etmez.
AdapterProvider = Callable[[str], Awaitable[CompanyAdapter]]
