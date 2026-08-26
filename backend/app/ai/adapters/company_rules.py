"""Bir şirketin zorunlu yazım kuralları -- yazarın/revize edenin uyması ve
yargıcın karşısında not vermesi gereken, yönetici tarafından yazılmış
kısıtlar.

``app.ai.adapters.company_adapter.CompanyAdapter``'ın kardeşi (aynı paket,
aynı enjekte-edilen-callable deseni, aynı "AI Core asla app.domains import
etmez" kuralı -- okuyucu/yazıcı ``app.domains.companies.provider`` içinde
yaşar), ama ``CompanyAdapter.style_rules``'a katılmak yerine bilinçli olarak
kendi settings anahtarı altında saklanır: ``CompanyAdapter``, otomatik bir
eğitim çalıştırmasının (Faz C3) her başarılı çalıştırmada topluca yeniden
yazdığı şeydir (bkz. ``set_company_adapter``'ın "tüm listeyi değiştirir"
sözleşmesi); bir yöneticinin burada elle yazdığı bir kural bu yeniden
yazımdan değişmeden kurtulmalıdır, bu yüzden aynı listede yaşayamaz.

``CompanyAdapter``'dan farklı olarak, bir kural seti yalnızca güvene
dayanarak bir prompt'a iddia edilmez -- ``app.ai.verification.llm_judge.
judge_draft``'a aynı render edilmiş blok verilir ve taslağın onu gerçekten
takip edip etmediği sorulur (bkz. ``DraftJudgeVerdict.company_rules_ok``) ve
bir ihlal, mevcut doğrulama/revize onarım döngüsünün otomatik olarak
düzelttiği numaralandırılmış bir kusura dönüşür -- diğer her deterministik/
yargıç bulgusunun zaten geçtiği aynı döngü.
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Optional


@dataclass(frozen=True)
class CompanyRule:
    """Yönetici tarafından yazılmış bir yazım kuralı.

    Attributes:
        id: Kural oluşturulduğunda sunucu tarafında atanan kısa, sabit bir
            slug (örn. "K3") -- yargıcın kendi ``violated_rule_ids``'i
            tarafından referans alınır, böylece bir ihlal serbest metni
            yeniden eşleştirmeden tam olarak kurala geri izlenebilir. Aynı
            settaki *diğer* kurallara yapılan düzenlemelerde sabit kalır
            (bkz. ``app.domains.companies.provider.set_company_rules``), bu
            yüzden bir kuralın id'si, bir yöneticinin başka birini yeniden
            sıralaması veya kaldırması nedeniyle kaymaz.
        text: Kuralın kendisi, yöneticinin yazdığı şekilde Türkçe olarak
            (örn. "Kapanışta her zaman 'Arz ederim' kullan.").
        severity: "zorunlu" (bir ihlal, kritik bir yargıç bulgusuyla aynı
            şekilde otomatik onayı engeller) veya "onerilen" (yargıca ve
            yazara gösterilir, ama kendi başına asla insan incelemesi
            zorunlu kılmaz).
        enabled: False, bir kuralı uygulamadan saklı tutar -- bir yöneticinin
            metnini/id'sini kaybetmeden bir kuralı geçici olarak devre dışı
            bırakmasını sağlar.
    """

    id: str
    text: str
    severity: Literal["zorunlu", "onerilen"] = "zorunlu"
    enabled: bool = True


@dataclass(frozen=True)
class CompanyRuleSet:
    """Bir şirketin tam zorunlu/önerilen yazım kuralları seti.

    Attributes:
        company_id: Bu kural setinin ait olduğu kiracı.
        version: Her yazımda artırılır (bkz.
            ``app.domains.companies.provider.set_company_rules``).
        rules: Yönetici tarafından yazılmış sıradaki tam kural listesi.
        updated_at: Son yazımın ISO-8601 zaman damgası, veya bu kural seti
            hiç ayarlanmamışsa None (bkz. :meth:`empty`).
    """

    company_id: str
    version: int = 0
    rules: tuple[CompanyRule, ...] = field(default_factory=tuple)
    updated_at: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        """Bir prompt'a enjekte edilmeye veya yargıca verilmeye değer hiçbir
        şey yoksa True."""
        return not self.enabled_rules

    @property
    def enabled_rules(self) -> tuple[CompanyRule, ...]:
        """Şu anda açık olan kurallar -- her tüketicinin (prompt enjeksiyonu,
        yargıç) gerçekten okuduğu şey."""
        return tuple(rule for rule in self.rules if rule.enabled)

    @classmethod
    def empty(cls, company_id: str) -> "CompanyRuleSet":
        """Hiçbir şey yapılandırılmamış bir şirketin çözümlendiği kural seti.

        Asla ``None`` değil -- her çağıran, eksik bir kural setini ayrı bir
        durum olarak ele almak yerine koşulsuzca ``.is_empty``'i kontrol
        edebilir, ``CompanyAdapter.empty`` ile aynı kural.
        """
        return cls(company_id=company_id)

    def to_dict(self) -> dict[str, Any]:
        """JSON'a uygun gösterim -- ``CompanyModel.settings`` ve Redis
        önbellek değerine gerçekten yazılan şey."""
        return {
            "version": self.version,
            "rules": [
                {
                    "id": rule.id,
                    "text": rule.text,
                    "severity": rule.severity,
                    "enabled": rule.enabled,
                }
                for rule in self.rules
            ],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, company_id: str, value: Optional[dict[str, Any]]) -> "CompanyRuleSet":
        """``to_dict()`` biçimli bir eşlemeden (veya hiç ayarlanmamış bir
        şirket için ``None``'dan) yeniden oluşturur."""
        if not value:
            return cls.empty(company_id)
        rules = tuple(
            CompanyRule(
                id=str(item.get("id") or ""),
                text=str(item.get("text") or ""),
                severity=item.get("severity") or "zorunlu",
                enabled=bool(item.get("enabled", True)),
            )
            for item in (value.get("rules") or [])
            if item.get("text")
        )
        return cls(
            company_id=company_id,
            version=int(value.get("version") or 0),
            rules=rules,
            updated_at=value.get("updated_at"),
        )


#: Bir ``company_id`` alan ve o şirketin mevcut kural setini döndüren async
#: callable (asla hata fırlatmaz, asla None döndürmez -- bkz.
#: ``CompanyRuleSet.empty``) -- ``AdapterProvider`` ile aynı şekilde
#: ``create_draft_graph``/``create_revise_graph``'a enjekte edilir.
RulesProvider = Callable[[str], Awaitable[CompanyRuleSet]]
