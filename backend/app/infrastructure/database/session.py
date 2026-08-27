import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.context import get_current_tenant

logger = logging.getLogger(__name__)

def _pool_kwargs() -> dict:
    """Her iki engine'in paylaştığı havuz ayarları (bkz. ``settings.DB_POOL_*``).

    Ayarlanmadan bırakıldığında SQLAlchemy varsayılanları yalnızca 5 + 10
    bağlantı verir; birkaç dakikalarca süren istek bunu tüketip diğer her
    şeyi zaman aşımına uğratıyordu (bkz. #288).
    """
    return dict(
        echo=False,  # Debug SQL sorgu loglaması için True yapın
        future=True,
        pool_pre_ping=True,  # Kullanmadan önce bağlantıları test et
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    )


def _app_connect_args() -> dict:
    """asyncpg ``server_settings`` -- yalnızca uygulamanın çalışma zamanı bağlantısına.

    ``idle_in_transaction_session_timeout``, sızan bir bağlantının (bir
    istek transaction'ı açık bırakıp dakikalarca AI işi yapması) 30 dakika
    yerine ~1 dakikada Postgres tarafından koparılmasını sağlar. Owner
    bağlantısına bilinçli olarak uygulanmaz: onun tüketicileri (giriş/
    token yenileme/kayıt) kısa ve DDL'e yakın yollardır.
    """
    ms = settings.DB_IDLE_IN_TXN_TIMEOUT_MS
    if ms and ms > 0:
        return {"server_settings": {"idle_in_transaction_session_timeout": str(ms)}}
    return {}


# PostgreSQL bağlantısı için eşzamansız motor oluştur -- Faz 3'ten (Postgres
# RLS) itibaren uygulamanın kısıtlı, owner olmayan rolü. Bunun neden bir
# tablo-sahibi/superuser bağlantısı olmaması gerektiği için
# settings.DATABASE_URL'in kendi docstring'ine bakın.
engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args=_app_connect_args(),
    **_pool_kwargs(),
)

# Eşzamansız oturum oluşturucu
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

#: Şema sahibi bağlantısı -- bkz. settings.ALEMBIC_DATABASE_URL'in
#: docstring'i. Yalnızca aşağıdaki get_owner_db tarafından, satır düzeyi
#: güvenliği zorunlu olarak atlaması gereken dar bir tenant-öncesi kimlik
#: arama seti için kullanılır (bkz. o fonksiyonun kendi docstring'i), asla
#: genel bir kaçış kapağı olarak değil.
owner_engine = create_async_engine(
    settings.effective_alembic_database_url,
    **_pool_kwargs(),
)

OwnerAsyncSessionLocal = async_sessionmaker(
    bind=owner_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def _apply_tenant_guc(session: AsyncSession, company_id: Optional[str], is_root: bool) -> None:
    """RLS politikalarının (migration 0013_rls) anahtarladığı Postgres GUC'larını ayarla.

    ``session`` üzerinde çalıştırılan *ilk* ifade olmalıdır. ``AsyncSession``
    işlemine tembel biçimde, ilk kullanımda başlar, ve ``set_config(..., true)``
    (== ``SET LOCAL``) yalnızca verildiği işlem boyunca sürer -- çağıran
    başka bir şey çalıştırmadan önce bunu çağırmak, onu işlemi başlatan
    ifade yapar, bu yüzden ayar bu oturumdaki her sonraki ifade için,
    nihai commit/rollback'e kadar hayatta kalır. Bunu daha sonra çağırmak,
    daha önceki, GUC'suz bir ifadenin önce kendi işlemini başlatmasına (ve
    istek yolunda, muhtemelen bitirmesine) izin verirdi, ve ayar o işlem
    commit olduğu anda buharlaşırdı.

    Args:
        session: Yeni açılmış bir oturum, üzerinde henüz hiçbir şey çalıştırılmadı.
        company_id: ``app.current_company_id``'yi kapsar. ``None``/falsy,
            gerçek hiçbir satırın ``company_id``'siyle eşleşmeyen (hepsi
            NOT NULL, boş değil) boş dizeye dönüşür -- güvenli-başarısız
            "tanımlanmış tenant yok" durumu.
        is_root: RLS politikalarının ``company_id`` karşılaştırmalarına OR
            ile eklediği ``app.is_root``'u ayarlar, böylece kapsama alınmış
            bir root öznesi şirketler arasında okuyabilir.
    """
    await session.execute(
        text("SELECT set_config('app.current_company_id', :cid, true)"),
        {"cid": company_id or ""},
    )
    await session.execute(
        text("SELECT set_config('app.is_root', :v, true)"),
        {"v": "on" if is_root else "off"},
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Eşzamansız bir SQLAlchemy veritabanı oturumu veren FastAPI bağımlılığı.

    Vermeden önce mevcut isteğin tenant GUC'larını uygular (bkz.
    ``_apply_tenant_guc``) -- herhangi bir bağımlılık çalışmadan önce
    ``app.api.middleware.tenant.TenantContextMiddleware``'in isteğin
    JWT'sinden doldurduğu ``app.core.context.get_current_tenant``'tan
    çözülür. Tenant bağlamı yoksa (anonim bir istek, veya auth bağımlılığı
    henüz reddetmemiş biri) boş bir şirket kapsamına ve ``is_root=False``'a
    çözülür: satır düzeyi güvenlik daha sonra her RLS'li tabloda sıfır satır
    döndürür, güvenli-başarısız varsayılan -- ``app.core.permissions.
    role_checker.clearance_for``'un "bilinmeyen yetki hiçbir şeyi
    açmaz" için zaten belgelediği aynı şekil.

    Kaynakları temizler ve başarısızlıkta otomatik olarak geri alır.
    """
    async with AsyncSessionLocal() as session:
        try:
            tenant = get_current_tenant()
            await _apply_tenant_guc(
                session,
                tenant.company_id if tenant else None,
                tenant.is_root if tenant else False,
            )
            yield session
            await session.commit()
        except Exception as e:
            logger.error(
                f"Database transaction error: {e}. Rolling back.",
                exc_info=True,
            )
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_owner_db() -> AsyncGenerator[AsyncSession, None]:
    """Şema sahibi bağlantısında bir oturum veren FastAPI bağımlılığı.

    Bir satır düzeyi güvenlik politikasının kapsayacağı herhangi bir şirket
    bağlamı var olmadan *önce* ``users``/``invited_emails``'i küresel
    olarak benzersiz bir ``username``/``email`` ile aramak zorunda olan
    dar tenant-öncesi kimlik arama seti için: ``POST /auth/login``,
    ``POST /auth/refresh``, ``POST /users`` (davet ile kapılı kayıt).
    ``settings.ALEMBIC_DATABASE_URL``'in docstring'ine bakın.

    Bilinçli olarak satır düzeyi güvenliği tamamen atlar -- owner bağlantısı
    herhangi bir politikadan bağımsız olarak her zaman yapabilir (bunun
    uygulamanın normal bağlantısının neden YAPAMAMASI gerektiği için
    migration ``0013_rls``'in kendi modül docstring'ine bakın). Burada
    yalnızca *bu üç rotanın çalıştırdığı her sorgu tanımı gereği doğal
    olarak şirketler arası olduğu için* güvenlidir -- bir username/email
    sistem genelinde benzersizdir, şirket başına değil -- asla çağıranın
    bundan fazlasıyla güvenildiği için değil. Diğer her rota ``get_db``'yi
    kullanmaya devam eder.
    """
    async with OwnerAsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            logger.error(
                f"Database transaction error (owner connection): {e}. Rolling back.",
                exc_info=True,
            )
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def tenant_session(
    company_id: Optional[str], is_root: bool = False
) -> AsyncGenerator[AsyncSession, None]:
    """Tenant bağlamını okuyacak bir isteği olmayan kod için ``get_db``-eşdeğeri bir oturum.

    Zaten hangi şirket için hareket ettiklerini bilen istek-dışı
    yazarlar/okuyucular için: ``app.domains.units.provider.
    get_active_units_for_routing``, kullanıcı/birim seeder'ları
    (``app.domains.users.seeder``, ``app.domains.units.seeder``), dört
    en iyi çaba kaydedicisi (``app.domains.drafts.draft_recorder``,
    ``app.observability.run_recorder``/``guardrail_recorder``,
    ``app.domains.chat.chat_recorder`` -- migration ``0016_recorder_
    tables_rls``'ten beri, bkz. ``RunModel.company_id``'nin docstring'i),
    ve ``app.events.subscribers``'in bildirim yazan dinleyicileri.
    ``get_db``'nin yaptığı aynı GUC'ları (bkz. ``_apply_tenant_guc``),
    ``app.core.context.get_current_tenant`` yerine açık argümanlardan
    uygular -- bunu doldurmuş uçan bir istek yoktur.
    """
    async with AsyncSessionLocal() as session:
        try:
            await _apply_tenant_guc(session, company_id, is_root)
            yield session
            await session.commit()
        except Exception as e:
            logger.error(
                f"Database transaction error (tenant_session): {e}. Rolling back.",
                exc_info=True,
            )
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def request_tenant_session() -> AsyncGenerator[AsyncSession, None]:
    """``get_db`` ile aynı oturum, ama bir FastAPI bağımlılığı *değil*.

    ``get_db`` bir ``yield``-bağımlılığı olduğu için, tuttuğu bağlantı
    ancak HTTP yanıtı tümüyle gönderildikten sonra iade edilir -- bir
    ``StreamingResponse`` akarken veya handler dakikalarca süren bir AI
    çağrısı yaparken bu, bağlantının tüm o süre boyunca ``idle in
    transaction`` beklemesi demektir (bkz. #288).

    Bu yardımcı, ``get_db`` ile aynı tenant GUC'larını
    (``app.core.context.get_current_tenant``'tan -- ``TenantContextMiddleware``
    her bağımlılıktan önce doldurur) uygular, ama ``async with`` bloğu
    biter bitmez bağlantıyı bırakır. Handler'ın *kısa* DB işini (auth
    araması, sahiplik/erişim kontrolleri) uzun işten önce yapıp bağlantıyı
    geri vermesi için kullanılır.
    """
    tenant = get_current_tenant()
    async with tenant_session(
        tenant.company_id if tenant else None,
        tenant.is_root if tenant else False,
    ) as session:
        yield session


def pool_status() -> dict[str, int]:
    """Uygulama engine'inin havuz sayaçlarının anlık görüntüsü.

    ``app.lifespan``'in periyodik doygunluk logu ve ``/health`` tarafından
    kullanılır. ``QueuePool`` kullanılmadığında (örn. testlerde
    ``NullPool``) sayaçlar eksik olabilir, bu yüzden her biri savunmacı
    biçimde okunur.
    """
    pool = engine.pool
    out: dict[str, int] = {}
    for name in ("size", "checkedin", "checkedout", "overflow"):
        getter = getattr(pool, name, None)
        try:
            out[name] = int(getter()) if callable(getter) else 0
        except Exception:
            out[name] = 0
    out["capacity"] = settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW
    return out


async def verify_db_connection() -> bool:
    """PostgreSQL veritabanına bağlantı kurabildiğimizi doğrula."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            val = result.scalar()
            if val == 1:
                logger.info("PostgreSQL database connection verified successfully.")
                return True
            return False
    except Exception as e:
        logger.error(
            f"PostgreSQL database connection verification failed: {e}",
            exc_info=True,
        )
        return False
