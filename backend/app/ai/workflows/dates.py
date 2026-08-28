"""Bir taslağın "Tarih:" satırı için sunucu tarafından çözülen değerin geldiği tek yer.

Üretilen bir taslağın kendi "Tarih:" satırı, bir belgeden çıkarılan veya
kullanıcı tarafından sağlanan bir bilgi değil, yazıldığı tarihtir --
kullanıcıya bunu sormak (bkz. Görev'in hata raporu 3. maddesi), ona hangi gün
olduğunu sormak kadar anlamsızdır. Bu modül, bu tarihin geldiği tek yerdir;
böylece her çağıran (yazarın brief'i, deterministik yer tutucu güvence
mekanizması, doğrulayıcının dayanaklandırma kontrolü) aynı tur için aynı
değer üzerinde anlaşır.

İki farklı bağlamda iki farklı doğru değer vardır: **ilk taslak** yazılırken
doğru değer ``today_tr()``'dir (taslak o an yazılıyor). Bir **revizyon**
sırasındaki deterministik yer tutucu yedek mekanizması içinse (bkz.
``app.ai.verification.placeholders.fill_date_placeholders``) doğru değer
``today_tr()`` DEĞİL, ``extract_draft_date()`` ile revize edilen taslağın
kendi hâlihazırdaki "Tarih:" satırından çıkarılan değerdir -- bir revizyon,
yapısı gereği orijinal taslağın tarihini asla değiştirmez (bkz.
``app.ai.workflows.revise_graph.ReviseState.today``'in kendi notu); revizyon
sırasında bugünün tarihini kullanmak, kullanıcının hiç değiştirmediği bir
alanı sessizce bozar.
"""

import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.core.config import settings


def today_tr() -> str:
    """Uygulamanın yapılandırılmış saat diliminde güncel tarih, Türkçe format.

    Yalnızca **ilk taslak** yazılırken doğrudan kullanılır. Bir revizyon
    sırasındaki tarih yer tutucu yedek mekanizması için ``extract_draft_date``
    tercih edilir -- bkz. bu modülün kendi docstring'i.

    Returns:
        ``"GG.AA.YYYY"``, gerçek Türkçe resmi yazışmaların ve bu kod
        tabanının kendi örneklerinin zaten kullandığı formatla eşleşir
        (bkz. ``datasets/resmi_yazisma``).
    """
    return datetime.now(ZoneInfo(settings.APP_TIMEZONE)).strftime("%d.%m.%Y")


#: Taslağın kendi doldurulmuş "Tarih:" satırı -- `app.ai.verification.
#: placeholders._DATE_LINE_PATTERN`'in tersi: köşeli parantezli bir yer
#: tutucu değil, gerçek bir değer arar. `[` ile başlamayan herhangi bir
#: değeri kabul eder (`today_tr()`'nin ürettiği "GG.AA.YYYY" formatına
#: sabitlenmez) -- yazarın verbatim kopyalaması istenen değer zaten bu
#: formatta olsa da, çıkarılan değeri olduğu gibi geri vermek, onu yeniden
#: ayrıştırıp normalize etmekten (ve olası bir format uyuşmazlığında
#: sessizce yanlış bir değer üretmekten) daha güvenlidir.
_FILLED_DATE_LINE_PATTERN = re.compile(
    r"^[ \t]*Tarih[ \t]*:[ \t]*(?!\[)(\S.*?)[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)


def extract_draft_date(text: str) -> Optional[str]:
    """Taslak metninin kendi "Tarih:" satırındaki dolu değeri çıkarır.

    Bir revizyonun tarih yer tutucu yedek mekanizması için: model,
    revize ederken orijinal "Tarih:" satırını verbatim korumak yerine bir
    yer tutucuyla ("Tarih: [Tarih]") değiştirirse, deterministik yedek
    mekanizma bunu ``today_tr()`` (revizyon anının tarihi) ile değil, bu
    fonksiyonun revize edilmekte olan taslağın *kendi* metninden çıkardığı
    değerle doldurmalıdır -- aksi hâlde kullanıcı hiç dokunmadığı bir alanı
    revizyonun sessizce değiştirdiğini görür (bkz. bu modülün docstring'i).

    Args:
        text: İçinde aranacak taslak metni (tipik olarak revize edilmekte
            olan ``DraftVersion.text``).

    Returns:
        Bulunan tarih değeri (satırın kendi biçimiyle, yeniden
        biçimlendirilmeden), ya da satır hiç yoksa veya kendisi de
        doldurulmamış bir yer tutucuysa ``None``.
    """
    match = _FILLED_DATE_LINE_PATTERN.search(text or "")
    return match.group(1) if match else None
