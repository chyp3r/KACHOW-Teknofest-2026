"""Bir ADMIN, bir MANAGER ve bir EMPLOYEE hesabının best-effort önyükleme (bootstrap) işlemi.

Aksi takdirde taze bir dağıtımın (yeni bir ortam, bir demo, CI) hiç
kullanıcısı olmaz -- bir tane oluşturmanın tek yolu, davet çıkarmak için
zaten var olan bir hesap gerektiren davet kısıtlı kayıt akışıdır
(`UserService.register_user`). Bu, o geçidi tamamen atlayarak
(bir bootstrap'ın kendini davet edecek hiçbir şeyi yoktur) `UserRepository`
üzerinden doğrudan rol başına bir hesap oluşturur.

Tasarım gereği idempotent: her hesap oluşturulmadan önce e-postaya göre
(ve o kullanıcı adı bağımsız olarak farklı bir e-posta tarafından
alınmışsa bir IntegrityError'dan kaçınmak için kullanıcı adına göre de)
kontrol edilir, bu yüzden her başlatmada tekrar çalıştırmak var olan bir
satırı asla çoğaltmaz veya üzerine yazmaz. Her hesap kendi kısa ömürlü
oturumunu alır -- `app.observability.run_recorder`'ın örüntüsünü yansıtır,
çünkü `app.lifespan`'ın istek kapsamlı bir `Depends(get_db)`'si yoktur --
bu yüzden bir hesabın çakışması diğer ikisinin seed edilmesini asla
engellemez.

Her fonksiyon kendi istisnalarını yutar ve sadece loglar -- seed işlemi
API'nin ayağa kalkmama sebebi olmamalıdır.
"""

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from app.core.config import settings
from app.core.enums.user_role import UserRole
from app.core.security import hash_password
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.infrastructure.database.session import OwnerAsyncSessionLocal, tenant_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SeedAccount:
    username: str
    email: str
    password: str
    role: str
    #: Sadece root için None -- bkz. UserModel.company_id'nin CHECK constraint'i.
    company_id: Optional[str]


def _seed_accounts(company_id: Optional[str]) -> list[_SeedAccount]:
    accounts = [
        _SeedAccount(
            username="root",
            email=settings.SEED_ROOT_EMAIL,
            password=settings.SEED_ROOT_PASSWORD,
            role=UserRole.ROOT.value,
            company_id=None,
        ),
    ]
    if company_id is not None:
        accounts.extend(
            [
                _SeedAccount(
                    username="admin",
                    email=settings.SEED_ADMIN_EMAIL,
                    password=settings.SEED_ADMIN_PASSWORD,
                    role=UserRole.ADMIN.value,
                    company_id=company_id,
                ),
                _SeedAccount(
                    username="manager",
                    email=settings.SEED_MANAGER_EMAIL,
                    password=settings.SEED_MANAGER_PASSWORD,
                    role=UserRole.MANAGER.value,
                    company_id=company_id,
                ),
                _SeedAccount(
                    username="employee",
                    email=settings.SEED_EMPLOYEE_EMAIL,
                    password=settings.SEED_EMPLOYEE_PASSWORD,
                    role=UserRole.EMPLOYEE.value,
                    company_id=company_id,
                ),
            ]
        )
    return accounts


async def _seed_one(account: _SeedAccount) -> bool:
    """Henüz yoksa bir hesap oluşturur.

    Varlık kontrolü, kiracı kapsamlı bir bağlantı yerine şema-sahibi
    bağlantısı (`OwnerAsyncSessionLocal`) üzerinde çalışır: `username`/
    `email`, şirket başına değil *sistem genelinde* benzersizdir
    (`UserModel`'in kendi `unique=True` kolonları), bu yüzden "bu zaten var
    mı" sorusu her şirketi görebilmelidir, `app.infrastructure.database.
    session.get_owner_db` ile aynı gerekçe. Bunun yerine tek bir şirketin
    row-level-security kapsamı altında kontrol etmek önce denendi ve tam
    olarak şöyle bozuldu: iki farklı şirket de "admin" adlı bir kullanıcıyla
    seed edilebilir, şirket başına kapsamlı kontrol diğerini göremez, ve
    insert işlemi yine de *global* benzersizlik kısıtına takılır -- sadece
    daha geç, ve temiz bir "zaten var, atla" yerine ele alınmamış bir
    `IntegrityError` olarak.

    Insert işleminin kendisi `tenant_session` kullanır -- `users` row-level
    security altındadır (migration `0013_rls`) ve bu yazma işleminin
    okuyacağı bir istek kapsamlı `ContextVar`'ı yoktur, bu yüzden hedef
    company_id'yi (veya hiç şirketi olmayan root hesabı için
    `is_root=True`'yu) açıkça sağlamalıdır.

    Returns:
        Yeni bir satır oluşturulduysa True; (e-posta veya kullanıcı adına
        göre) zaten varsa ve hiçbir şey yapılmadıysa False.
    """
    async with OwnerAsyncSessionLocal() as check_session:
        check_repository = UserRepository(check_session)
        if await check_repository.get_by_email(account.email) is not None:
            return False
        if await check_repository.get_by_username(account.username) is not None:
            logger.warning(
                "Seed account username '%s' is already taken by a different "
                "email; skipping.",
                account.username,
            )
            return False

    is_root = account.role == UserRole.ROOT.value
    async with tenant_session(account.company_id, is_root=is_root) as session:
        repository = UserRepository(session)
        user = UserModel(
            id=str(uuid4()),
            company_id=account.company_id,
            username=account.username,
            email=account.email,
            hashed_password=hash_password(account.password),
            role=account.role,
            is_active=True,
            is_deleted=False,
        )
        await repository.create(user)
        await session.commit()
        return True


async def seed_default_users(company_id: Optional[str]) -> None:
    """Varsayılan ROOT/ADMIN/MANAGER/EMPLOYEE hesaplarını oluşturur, zaten
    var olanları atlar.

    `settings.SEED_DEFAULT_USERS` kapalıyken hiçbir şey yapmaz. Her
    başlatmada çağrılması güvenlidir.

    Args:
        company_id: ADMIN/MANAGER/EMPLOYEE'nin bağlanacağı demo şirket
            (önce çalışması gereken `app.domains.companies.seeder.
            seed_demo_company`'ye bakınız). ROOT'un şirketi olmadığından
            her durumda seed edilir. `None` olduğunda (demo şirket seed
            işlemi kapalı ve henüz hiçbiri yoksa), sadece ROOT seed edilir.
    """
    if not settings.SEED_DEFAULT_USERS:
        return

    created = []
    for account in _seed_accounts(company_id):
        try:
            if await _seed_one(account):
                created.append(f"{account.email} ({account.role})")
        except Exception:
            logger.exception("Failed to seed default account %s", account.email)

    if created:
        logger.info("Seeded default accounts: %s", ", ".join(created))
