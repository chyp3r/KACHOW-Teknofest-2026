"""Bu uygulamanın bildiği harici MCP sunucuları.

`MCPManager` herhangi bir sunucuyla konuşabilir; bu modül hangilerinin var
olduğuna karar verir. Kayıt işlemi, başlangıçta gömülü bir çağrı yerine küçük,
grep'lenebilir bir liste olsun ve bir sunucu koda dokunmadan yapılandırma ile
devre dışı bırakılabilsin diye ayrı tutuldu.

Bugün itibarıyla tek bir sunucu var: mevzuat.gov.tr ve bedesten.adalet.gov.tr'yi
sorgulayan `mevzuat-mcp` (github.com/saidsurucu/mevzuat-mcp, MIT). Bunu iki
bağımsız ayar tarafından kontrol edilen iki çalışma zamanı çağıranı paylaşıyor
(tam gerekçe için `core.config.Settings`'e bakın):

* `app.ai.retrieval.mcp_mevzuat` -- doküman analizinin mevzuat getirme
  bileşeni, varsayılan olarak canlıdır (`MEVZUAT_SOURCE="mcp"`), başarısızlık
  durumunda depoya gömülü derlem'e geri döner. `check_required_fields`'a asla
  dokunmaz: o, sabit kodlanmış madde numaralarına sahip bir kural tablosu
  üzerinde küme çıkarmasıdır, bu yüzden uyumluluk kararı, alıntıları hangi
  kaynağın sağladığından bağımsız olarak deterministik kalır.
* `app.ai.tools.mevzuat_tools` -- asistanın canlı arama aracı, varsayılan
  olarak kapalıdır (`MEVZUAT_MCP_ENABLED`), yerel derlem aracı hiçbir şey
  bulamadığında bir üst kademe olarak sunulur.

Aşağıdaki `register_servers()`, *iki ayardan herhangi biri* isteyince
sunucuyu kaydeder; böylece iki ayarın varsayılanları birbiriyle
çelişse bile (`MEVZUAT_SOURCE="mcp"` ama `MEVZUAT_MCP_ENABLED=False`)
belgelenen varsayılan davranış çalışmaya devam eder.

Aynı sunucu, yukarıdaki "local" kaynağın ve asistanın yerel derlem aracının
okuduğu, depoya gömülü derlemi oluşturmak için `scripts/fetch_mevzuat_corpus.py`
tarafından çevrimdışı olarak da kullanılır.
"""

import logging

from app.core.config import settings
from app.mcp.manager import mcp_manager

logger = logging.getLogger(__name__)

#: Mevzuat sunucusu için kayıtlı ad, tüm çağrı noktalarında kullanılır.
MEVZUAT_SERVER = "mevzuat"


def register_servers() -> list[str]:
    """Yapılandırılmış her MCP sunucusunu paylaşılan yönetici ile kaydet.

    İdempotenttir: yeniden kayıt, kopyalar biriktirmek yerine istemciyi
    değiştirir; bu yüzden bunu hem başlangıçtan hem de bir test fixture'ından
    çağırmak güvenlidir.

    Returns:
        Şu anda kayıtlı olan sunucuların adları.
    """
    registered: list[str] = []

    if settings.MEVZUAT_MCP_ENABLED or settings.MEVZUAT_SOURCE == "mcp":
        mcp_manager.register_server(
            name=MEVZUAT_SERVER,
            command=settings.MEVZUAT_MCP_COMMAND,
            args=settings.mevzuat_mcp_args,
        )
        registered.append(MEVZUAT_SERVER)
        logger.info(
            "Registered MCP server '%s' (command: %s). MEVZUAT_MCP_ENABLED=%s, "
            "MEVZUAT_SOURCE=%s.",
            MEVZUAT_SERVER,
            settings.MEVZUAT_MCP_COMMAND,
            settings.MEVZUAT_MCP_ENABLED,
            settings.MEVZUAT_SOURCE,
        )
    else:
        logger.debug(
            "Neither MEVZUAT_MCP_ENABLED nor MEVZUAT_SOURCE=mcp is set; nothing "
            "reaches mevzuat-mcp and legislation stays fully local."
        )

    return registered


def is_registered(name: str) -> bool:
    """Bir sunucunun çağrılabilir durumda olup olmadığını bildir.

    Args:
        name: Kayıtlı sunucu adı.

    Returns:
        Sunucu kayıtlıysa True.
    """
    return name in mcp_manager.clients
