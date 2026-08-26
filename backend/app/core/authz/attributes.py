"""PDP'nin akıl yürüttüğü öznitelik türleri: Subject, Resource, Environment, Action.

Bilinçli olarak yalın. ``Subject``/``Resource`` gizlilik yetkisi taşımaz --
bu, ``app.core.permissions.role_checker``'ın kendi, alt akış ilgisi olarak
kalır (ikisinin neden birlikte katlanmaması gerektiği için
``engine.py``'nin modül docstring'ine bakın).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.core.enums.user_role import UserRole


@dataclass(frozen=True)
class Subject:
    """Hakkında bir karar verilen kimliği doğrulanmış çağıran.

    Attributes:
        user_id: Çağıranın ``UserModel.id``'si.
        role: Çağıranın ``UserRole``'ü.
        company_id: Çağıranın tenant'ı, veya ``UserRole.ROOT`` için ``None``
            (bkz. ``UserModel.company_id``'nin docstring'i).
    """

    user_id: str
    role: UserRole
    company_id: Optional[str]


@dataclass(frozen=True)
class Resource:
    """Bir eylemin karşısında denendiği şey.

    Attributes:
        type: Kısa bir etiket ("document", "draft", "unit", "user", ...) --
            ``permission_grants.resource_type``'a ve kural eylemlerinin
            namespace önekine karşı eşleştirilir, burada kapalı bir küme
            olarak zorlanmaz.
        id: Zaten var olduğunda kaynağın birincil anahtarı (henüz
            oluşturulmamış bir kaynak için yoktur, örn. ``POST /units``'ten
            önceki bir ``unit:manage`` kontrolü).
        company_id: Kaynağın tenant'ı. Yalnızca tenant'sız kaynaklar için
            (bir ``companies`` satırının kendisi, veya tek bir şirket
            hedefi olmayan bir ``system:*`` eylemi) ``None``.
        owner_id: Sahiplik bu kaynak türü için anlamlı bir kavram
            olduğunda (belgeler, taslaklar) kaynağın sahibi. Aksi halde
            ``None``.
    """

    type: str
    id: Optional[str] = None
    company_id: Optional[str] = None
    owner_id: Optional[str] = None


@dataclass(frozen=True)
class Environment:
    """Özne/kaynak/eylem dışındaki istek zamanı bağlamı.

    Attributes:
        now: ``permission_grants.valid_from``/``valid_until`` pencereleri
            için değerlendirme zamanı. Zaman sınırlı izinleri
            umursamayan çağrı yerlerinin bunu atlayabilmesi için
            varsayılan olarak mevcut UTC zamanına ayarlanır.
        company_scope: Bir ``UserRole.ROOT`` öznesinin varsa açıkça
            içine geçtiği şirket (``X-Company-Scope`` başlığı). Diğer
            her rol için yok sayılır.
    """

    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    company_scope: Optional[str] = None


class Action:
    """Namespace'lenmiş eylem tanımlayıcıları, ``"<resource_type>:<verb>"``.

    Bilinçli olarak bir enum değil düz bir dize namespace'i:
    ``permission_grants.action``, kod değişikliği olmadan gelecekteki bir
    kaynak türüne izin verilebilmesi için serbest metin bir DB sütunudur,
    ve wildcard ``"*"`` (root'un yerleşik kuralı, ve devredilen bir iznin
    kendi kaçış kapağı), her somut eylemle aynı uzayda geçerli bir değer
    olmak zorundadır.
    """

    DOCUMENT_READ = "document:read"
    DOCUMENT_UPDATE = "document:update"
    DOCUMENT_DELETE = "document:delete"
    DRAFT_READ = "draft:read"
    #: Bugün yalnızca bir taslağın kendi yönlendirilmiş birimi (bkz.
    #: `drafts/router.py`'nin `PATCH /{draft_id}/destination`'ı) -- içeriğin
    #: kendisi yalnızca-ekleme'dir (yeni bir sürüm, asla yerinde-düzenleme
    #: değil), bu yüzden bunun o tek değiştirilebilir alanın ötesine
    #: genişlemesi asla gerekmez.
    DRAFT_UPDATE = "draft:update"
    DRAFT_DELETE = "draft:delete"
    DRAFT_SEND = "draft:send"
    #: `ArtifactTransferService.execute`'u *her iki* artifact türü için de
    #: kapılar (taslak veya belge) -- `draft:transfer`/`document:transfer`
    #: olarak bölünmüş değil, tek bir eylem, çünkü kararın kendisi ("bu
    #: özne bu artifact'i başka birine taşıyabilir mi") artifact'in hangi
    #: tabloda yaşadığına bağlı değildir. `DRAFT_SEND`, birleştirilmek
    #: yerine kendi, daha eski eylemi olarak tutulur (hâlâ yeni hiçbir şeyi
    #: kapılamaz -- `DraftShareService.send` artık bunun yerine buna
    #: devrediyor), çünkü var olan `permission_grants` satırlarının zaten
    #: referans verdiği bir `Action` değerini kaldırmak onları sessizce
    #: geçersiz kılardı.
    ARTIFACT_TRANSFER = "artifact:transfer"
    UNIT_MANAGE = "unit:manage"
    USER_MANAGE = "user:manage"
    PERMISSION_GRANT = "permission:grant"
    PERMISSION_REVOKE = "permission:revoke"

    ALL: tuple[str, ...] = (
        DOCUMENT_READ,
        DOCUMENT_UPDATE,
        DOCUMENT_DELETE,
        DRAFT_READ,
        DRAFT_UPDATE,
        DRAFT_DELETE,
        DRAFT_SEND,
        ARTIFACT_TRANSFER,
        UNIT_MANAGE,
        USER_MANAGE,
        PERMISSION_GRANT,
        PERMISSION_REVOKE,
    )
