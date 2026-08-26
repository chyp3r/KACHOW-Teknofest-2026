"""Bir taslağın asla sormaması gereken tek alan için sunucu tarafından çözülen "bugün".

Üretilen bir taslağın kendi "Tarih:" satırı, bir belgeden çıkarılan veya
kullanıcı tarafından sağlanan bir bilgi değil, yazıldığı tarihtir --
kullanıcıya bunu sormak (bkz. Görev'in hata raporu 3. maddesi), ona hangi gün
olduğunu sormak kadar anlamsızdır. Bu modül, bu tarihin geldiği tek yerdir;
böylece her çağıran (yazarın brief'i, deterministik yer tutucu güvence
mekanizması, doğrulayıcının dayanaklandırma kontrolü) aynı tur için aynı
değer üzerinde anlaşır.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def today_tr() -> str:
    """Uygulamanın yapılandırılmış saat diliminde güncel tarih, Türkçe format.

    Returns:
        ``"GG.AA.YYYY"``, gerçek Türkçe resmi yazışmaların ve bu kod
        tabanının kendi örneklerinin zaten kullandığı formatla eşleşir
        (bkz. ``datasets/resmi_yazisma``).
    """
    return datetime.now(ZoneInfo(settings.APP_TIMEZONE)).strftime("%d.%m.%Y")
