"""Transfer'e özgü politika kapısı -- PDP'nin zaten izin verdiğini daraltır.

`app.core.authz.engine`'in kendi şeklini yansıtır (fırlatma yapmayan, saf
bir karar nesnesi) ancak bilinçli olarak ayrı, daha küçük bir katmandır:
`TransferPolicy` yalnızca PDP'nin zaten verdiği izni *kaldırır* (kendine
gönderim, aktif olmayan/silinmiş bir alıcı, yetersiz yetki, AI kanalında
eksik bir favori) -- PDP'nin reddettiği hiçbir şeye asla izin vermez ve
ikisinin "evet" sahipliği konusunda anlaşmazlığa düşmesine asla izin
verilmez. Bunun çağrı sırasında nereye oturduğu için (önce PDP, sonra bu)
`ArtifactTransferService.execute`'un kendi docstring'ine bakın.

Kiracı (tenant) eşleşmesi bilinçli olarak bu politikanın kendi
kontrollerinden biri *değildir*: `evaluate` çalıştığında, `recipient` zaten
`UserRepository.get_by_id_in_company(recipient_id, company_id)` üzerinden
yüklenmiştir -- kiracılar arası bir id orada `None`'a çözümlenir ve çağıran,
politika hiç danışılmadan önce `NotFoundException` fırlatır; bu,
`PoolService`/`DraftShareService`'in zaten kullandığı "iş kuralı değil,
RLS/şirket kapsamlı arama" örüntüsünün aynısıdır.
"""

from dataclasses import dataclass
from typing import Optional

from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.permissions.role_checker import clearance_for
from app.domains.units.repository import UnitMembershipRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserFavoriteRepository


@dataclass(frozen=True)
class TransferPolicyDecision:
    """`ArtifactTransferService.execute`'un üzerine hareket ettiği karar.

    Attributes:
        permit: Transferin devam edip edemeyeceği.
        reason_code: İlk başarısız kontrol için kısa bir makine etiketi
            (`"self_transfer"`, `"recipient_inactive"`, `"clearance"`,
            `"favorite_required"`), ya da `permit` True olduğunda `None`.
        message_tr: Doğrudan gösterilmeye hazır Türkçe bir açıklama, ya da
            `permit` True olduğunda `None`.
        cross_unit: Alıcının birincil biriminin belgenin kendi hedef
            biriminden farklı olup olmadığı -- bir çağıranın bir onay
            istemi (Faz 4) oluşturması, transfer hakkındaki her şey yolunda
            olsa bile buna ihtiyaç duyduğundan, `permit`'ten bağımsız
            olarak hesaplanır.
    """

    permit: bool
    reason_code: Optional[str]
    message_tr: Optional[str]
    cross_unit: bool


class TransferPolicy:
    def __init__(
        self,
        unit_membership_repository: UnitMembershipRepository,
        favorite_repository: UserFavoriteRepository,
    ):
        self.unit_membership_repository = unit_membership_repository
        self.favorite_repository = favorite_repository

    async def evaluate(
        self,
        *,
        sender: UserModel,
        recipient: UserModel,
        company_id: str,
        channel: str,
        artifact_sensitivity: Optional[SensitivityLevel] = None,
        artifact_destination_unit_id: Optional[str] = None,
    ) -> TransferPolicyDecision:
        """Her reddetme kuralını sırayla değerlendirir, ilk isabette kısa devre yapar.

        Args:
            sender: Bu belirli belgeyi transfer etmek için zaten
                PDP-yetkili, kimliği doğrulanmış çağıran.
            recipient: `company_id` içinde zaten çözümlenmiş hedef kullanıcı
                (bkz. bu modülün kendi docstring'i).
            company_id: Cross-unit/favori aramaları için kiracı kapsamı.
            channel: `"chat"` | `"ai"` | `"rest"` -- yalnızca `"ai"`,
                alıcının zaten bir favori olmasını gerektirir (bkz. planın
                §2.3'ü: AI kanalı, kullanıcının açıkça favorilemeye
                güvenmediği birine gönderim yapamamalıdır; manuel
                chat/REST gönderimlerinde böyle bir gereklilik yoktur,
                çünkü alıcıyı doğrudan elle seçen insandır).
            artifact_sensitivity: Evrakın gizlilik derecesi. Bir taslak
                için `None` -- taslaklar bugün bu sistemde yetki kavramı
                taşımaz, dolayısıyla kontrol uydurma bir varsayılanla
                karşılaştırılmak yerine tamamen atlanır.
            artifact_destination_unit_id: Belgenin cross-unit hesaplaması
                için, varsa kendi yönlendirilmiş birimi
                (`drafts.destination_unit_id`). Bir evrak için `None`
                (`DocumentModel`de bugün eşdeğer bir kavram yok) veya
                yönlendirilmemiş bir taslak için -- bu durumda
                `cross_unit` `False` kalır, bir tahmin yerine dürüst bir
                "hesaplanamıyor" durumu.

        Returns:
            Bir `TransferPolicyDecision`. `cross_unit`, `permit=False`
            bir kararda bile her zaman hesaplanır.
        """
        cross_unit = await self._compute_cross_unit(
            recipient.id, company_id, artifact_destination_unit_id
        )

        if recipient.id == sender.id:
            return TransferPolicyDecision(
                permit=False,
                reason_code="self_transfer",
                message_tr="Kendinize transfer yapamazsınız.",
                cross_unit=cross_unit,
            )

        if not recipient.is_active or recipient.is_deleted:
            return TransferPolicyDecision(
                permit=False,
                reason_code="recipient_inactive",
                message_tr="Alıcı artık aktif değil.",
                cross_unit=cross_unit,
            )

        if artifact_sensitivity is not None:
            recipient_clearance = clearance_for(recipient)
            if recipient_clearance is None or recipient_clearance < artifact_sensitivity:
                return TransferPolicyDecision(
                    permit=False,
                    reason_code="clearance",
                    message_tr="Alıcının gizlilik yetkisi bu evrak için yeterli değil.",
                    cross_unit=cross_unit,
                )

        if channel == "ai":
            is_favorite = await self.favorite_repository.is_favorite(
                sender.id, recipient.id, company_id
            )
            if not is_favorite:
                return TransferPolicyDecision(
                    permit=False,
                    reason_code="favorite_required",
                    message_tr=(
                        "AI üzerinden yalnızca favorilerinizdeki kişilere gönderim "
                        "yapılabilir. Önce bu kişiyi favorilerinize ekleyin."
                    ),
                    cross_unit=cross_unit,
                )

        return TransferPolicyDecision(permit=True, reason_code=None, message_tr=None, cross_unit=cross_unit)

    async def _compute_cross_unit(
        self, recipient_id: str, company_id: str, artifact_destination_unit_id: Optional[str]
    ) -> bool:
        if not artifact_destination_unit_id:
            return False
        primary = await self.unit_membership_repository.get_primary_for_user(recipient_id, company_id)
        if primary is None:
            return False
        return primary.unit_id != artifact_destination_unit_id
