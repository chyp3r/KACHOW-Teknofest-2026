"""Üretilen bir taslağın kendi "bulunamadı" işaretleri için deterministik
yedek mekanizma.

Brief, yazara eksik olan her şey için bir ``[...]`` yer tutucusu bırakmasını
talimat verir (bkz. ``app.ai.workflows.draft_graph._build_brief``), ama bir
prompt talimatı bir garanti değildir -- daha küçük bir yerel model, kendisine
söylenen yer tutucu yerine bir başlık alanının satırına düz "bulunamadı" /
"belirtilmemiş" / "yok" değerini yazabilir. Düz metin olarak bırakıldığında,
bu sessizce tüm eksik-bilgi kapısını atlar: ``PLACEHOLDER_PATTERN`` buna asla
eşleşmez, bu yüzden ``build_missing_info_request`` insana o alanın değerini
asla sormaz ve taslak, alan sanki gerçekten -- kısaca da olsa -- doldurulmuş
gibi gönderilir -- ki bu tam olarak bu modülün kapatmak için var olduğu "hiç
soru sorulmuyor" hatasıdır.
"""

import re
from typing import NamedTuple

from app.ai.verification.draft_verifier import PLACEHOLDER_PATTERN, _fold

#: Bu yedek mekanizmanın tanıdığı başlık satırı etiketleri, değeri
#: doldurulmamış bir işaret olduğunda alanın dönüştüğü köşeli parantez
#: adına eşlenmiş. ``writer.md``'nin bu alanlar için zaten kullandığı yer
#: tutucu adlarıyla eşleşir (``[Belge Sayısı]``, ``[Tarih]``, ``[Konu]``,
#: ``[Muhatap]``), böylece buradaki bir ikame ile yazarın kendi başına
#: bıraktığı bir ikame, akış aşağısındaki her şey için (``build_missing_info_request``,
#: insan kapısı) ayırt edilemez.
_FIELD_PLACEHOLDERS: dict[str, str] = {
    "sayı": "Belge Sayısı",
    "sayi": "Belge Sayısı",
    "tarih": "Tarih",
    "konu": "Konu",
    "muhatap": "Muhatap",
}

#: "Bu alan aslında doldurulmadı" anlamına gelen katlanmış (ASCII, küçük
#: harf) değerler -- bir modelin bunlardan birini bir `[...]` yer tutucusu
#: yerine bir başlık satırının değeri olarak yazması, aynı bilgi boşluğunu
#: bırakır, sadece `PLACEHOLDER_PATTERN`'in yazılı olarak göremeyeceği bir
#: biçimde. Boş dize kasıtlı olarak eklenmiştir: katlama tüm noktalama
#: işaretlerini kaldırır, bu yüzden "---", "___" veya "N/A" (ki "n a"ya
#: katlanır) gibi bir değer zaten buna veya aşağıdaki açık bir girdiye
#: çöker -- ve kırpıldıktan sonra çıplak boşluk olan bir değer, yapı gereği
#: aynı "burada hiçbir şey yok" boşluğudur.
_UNFILLED_MARKERS = frozenset(
    {
        "", "bulunamadi", "bulunamamistir", "belirtilmemis", "belirtilmemistir",
        "bilinmiyor", "mevcut degil", "yok", "n a", "na", "belirtilmedi",
        "bos",
    }
)

#: Bir satırın başında tanınan bir alan etiketi, iki nokta üst üste, sonra
#: değeri. ``STRUCTURE_CHECKS``'in kendi alan kalıplarının yaptığı gibi
#: satır başına sabitlenmiştir, böylece bu sadece taslağın o alan için
#: kendi başlık satırıyla eşleşir -- asla, mesela, kendi etiketi olan başka
#: bir belgenin numarasını alıntılayan bir "İlgi:" satırıyla değil.
_HEADER_LINE_PATTERN = re.compile(
    r"^([ \t]*)(Sayı|Sayi|Tarih|Konu|Muhatap)([ \t]*:[ \t]*)(.+)$",
    re.MULTILINE | re.IGNORECASE,
)


class NormalizedDraft(NamedTuple):
    text: str
    substitutions: int


def normalize_unfilled_markers(draft: str) -> NormalizedDraft:
    """Tanınan bir başlık satırının "bulunamadı" değerini bir yer tutucuya çevir.

    Args:
        draft: Üretilen taslak metni.

    Returns:
        (Muhtemelen yeniden yazılmış) taslak ve kaç satırın ikame edildiği
        -- sadece metinle ilgilenen çağıranlar sayıyı görmezden gelebilir,
        ama bu, bir çağıranın modelin bu yedek mekanizmaya gerçekte ne
        sıklıkla ihtiyaç duyduğunu loglamasına/gözlemlemesine olanak tanır.
    """
    count = 0

    def _replace(match: "re.Match[str]") -> str:
        nonlocal count
        indent, label, separator, value = match.groups()
        if _fold(value) not in _UNFILLED_MARKERS:
            return match.group(0)
        placeholder = _FIELD_PLACEHOLDERS.get(label.lower(), label)
        count += 1
        return f"{indent}{label}{separator}[{placeholder}]"

    normalized = _HEADER_LINE_PATTERN.sub(_replace, draft)
    return NormalizedDraft(text=normalized, substitutions=count)


#: Taslağın kendi "Tarih:" başlık satırı, değeri olarak köşeli parantezli
#: bir yer tutucuyla -- örn. "Tarih: [Tarih]" veya "Tarih: [Tarih Eksik -
#: Lütfen Doldurun]" (bkz. writer.md ve draft_graph.writer_node'un kendi
#: kuralı). Taslakta herhangi bir yerde tarihten bahseden herhangi bir
#: `[...]` aralığına değil, özellikle "Tarih" etiketiyle başlayan bir
#: satıra sabitlenmiştir -- gelen belgenin kendi tarihi, hiç referans
#: verildiğinde, "İlgi:" satırında oturur, asla bu etiketin arkasında
#: değil, bu yüzden bu, onu asla yanıtın kendi alanıyla karıştırıp bugünün
#: tarihiyle üzerine yazamaz.
_DATE_LINE_PATTERN = re.compile(
    r"^([ \t]*)(Tarih)([ \t]*:[ \t]*)\[[^\]]*\][ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)


def fill_date_placeholders(draft: str, today: str) -> NormalizedDraft:
    """Taslağın kendi "Tarih:" yer tutucusunu sunucu tarafında çözülen
    tarihle doldur.

    Üretilen bir taslak, kendi tarihini insanın sağlaması için asla
    bırakmamalıdır (bkz. app.ai.workflows.dates.today_tr ve bunun kapattığı
    hata raporu kalemi) -- yazara `today`'i olduğu gibi bu satıra kopyalaması
    söylenir (bkz. draft_graph._build_brief'in 0. bölümü), ama bir prompt
    talimatı bir garanti değildir, bu yüzden bu deterministik yedek
    mekanizmadır; "belirtilmemiş" yazan bir modelin önce yakalanması ve
    bunun hâlâ doldurulacak bir yer tutucu bulması için
    ``normalize_unfilled_markers``'dan hemen sonra çalıştırılır.

    Args:
        draft: Üretilen taslak metni.
        today: İkame edilecek tarih (bkz. app.ai.workflows.dates.today_tr).

    Returns:
        (Muhtemelen yeniden yazılmış) taslak ve kaç "Tarih:" satırının
        dolduruldu. ``today`` boşsa, taslak değiştirilmeden döndürülür --
        doldurulacak bir şey yoktur ve yer tutucuyu olduğu gibi bırakmak,
        içine boş bir değer yazmaktan daha güvenlidir.
    """
    if not today:
        return NormalizedDraft(text=draft, substitutions=0)

    count = 0

    def _replace(match: "re.Match[str]") -> str:
        nonlocal count
        indent, label, separator = match.groups()
        count += 1
        return f"{indent}{label}{separator}{today}"

    filled = _DATE_LINE_PATTERN.sub(_replace, draft)
    return NormalizedDraft(text=filled, substitutions=count)


#: Yazarın bıraktığı çıplak, rolsüz bir yer tutucu, kime ait olduğunu
#: belirten sürüme eşlenmiş -- olağan (kurumsal) taslak için. Katlanmış
#: ("ünvan"/"Ünvan"/"UNVAN" hepsi "unvan"a çöker) biçim üzerinden
#: anahtarlanmıştır, böylece bu, modelin yayabileceği her büyük/küçük
#: harf/aksan varyantını yakalar; `writer.md`'nin bu alanları artık nasıl
#: adlandırdığıyla eşleşir (bkz. kendi "İmza Bloğu" kuralı) -- bu, tek
#: başına bir prompt talimatının yetmediği durumlar için deterministik
#: yedek mekanizmadır; `normalize_unfilled_markers`'ın başlık bloğunun
#: kendi alanları için oynadığı rolün aynısı.
_SIGNATURE_PLACEHOLDERS: dict[str, str] = {
    _fold("Ad Soyad"): "İmzalayacak yetkilinin adı ve soyadı",
    _fold("Ad, Soyad"): "İmzalayacak yetkilinin adı ve soyadı",
    _fold("Adı Soyadı"): "İmzalayacak yetkilinin adı ve soyadı",
    _fold("Soyad"): "İmzalayacak yetkilinin adı ve soyadı",
    _fold("Unvan"): "İmzalayacak yetkilinin unvanı",
    _fold("İmza"): "İmzalayacak yetkilinin adı ve soyadı",
    # Korpüsten türetilen anonimleştirme yer tutucuları (bkz.
    # datasets/resmi_yazisma/anonimlestirme-manifesti.jsonl) -- bunlardan
    # birini kelimesi kelimesine taşıyan bir üslup örneği, eskiden
    # atıfsız ve sorulmadan geçiyordu (ne bu harita ne de
    # _INSTITUTION_PLACEHOLDERS bunları tanıyordu); bu, bu modülün
    # kapatmak için var olduğu tam olarak atıfsız-soru hatasıdır, sadece
    # model tarafından yazılan yerine korpüs-şekilli bir yer tutucu için.
    _fold("İmza Sahibi"): "İmzalayacak yetkilinin adı ve soyadı",
    _fold("Kişi Adı"): "İmzalayacak yetkilinin adı ve soyadı",
}

#: Aynı yer tutucular, bireysel bir dilekçe için (bkz. `writer.md`'nin
#: kendi "Yapı İstisnaları" bölümü) -- bir kurum adına imzalayan bir
#: "yetkili" yoktur, sadece dilekçe sahibinin kendisi vardır.
_SIGNATURE_PLACEHOLDERS_PETITION: dict[str, str] = {
    _fold("Ad Soyad"): "Dilekçe sahibinin adı ve soyadı",
    _fold("Ad, Soyad"): "Dilekçe sahibinin adı ve soyadı",
    _fold("Adı Soyadı"): "Dilekçe sahibinin adı ve soyadı",
    _fold("Soyad"): "Dilekçe sahibinin adı ve soyadı",
    _fold("Unvan"): "Dilekçe sahibinin unvanı",
    _fold("İmza"): "Dilekçe sahibinin adı ve soyadı",
    _fold("İmza Sahibi"): "Dilekçe sahibinin adı ve soyadı",
    _fold("Kişi Adı"): "Dilekçe sahibinin adı ve soyadı",
}

#: Çıplak bir kurum yer tutucusu -- her zaman gönderenin kendi kurumu
#: (bkz. `writer.md`'nin "1. Başlık / Kurum Adı" kuralı): bir taslağın
#: kendi antetinin atıfta bulunduğu tek "Kurum Adı" onu gönderen kim ise
#: odur, asla muhatap değil (o ad "Muhatap"ın arkasında oturur, bu
#: etiketin değil).
_INSTITUTION_PLACEHOLDERS: dict[str, str] = {
    _fold("Kurum Adı"): "Gönderen kurumun adı",
}


def normalize_role_placeholders(
    draft: str, *, is_individual_petition: bool = False
) -> NormalizedDraft:
    """Belirsiz, rolsüz bir yer tutucuyu, kime ait olduğunu belirten bir
    yer tutucuya çevir.

    Bunun kapattığı hata: çıplak bir ``[Ad Soyad]``/``[Unvan]`` yer
    tutucusu, insan kapısına *hakkında* soracak hiçbir şey vermez --
    ``missing_info.InfoQuestion.to_prompt_question``, köşeli parantezler
    içindeki her ne metin varsa onu olduğu gibi sorunun kendi etiketi
    olarak render eder, bu yüzden atıfsız bir yer tutucu atıfsız bir soru
    haline gelir ("'Ad Soyad' bilgisi nedir?" -- kimin?).

    Kasıtlı olarak konumdan bağımsızdır (mesela, özellikle taslağın kendi
    "Tarih:" satırına sabitlenen ``_DATE_LINE_PATTERN``'in aksine): çıplak
    bir "Ad Soyad"/"Unvan"/"İmza" yer tutucusu, bu alanda her zaman kimin
    imzaladığıyla ilgilidir ve çıplak bir "Kurum Adı" her zaman kimin
    gönderdiğiyle ilgilidir, yazarın taslağın neresinde bıraktığından
    bağımsız olarak -- burada her iki ifadenin de makul olarak anlamına
    gelebileceği ikinci, farklı bir şey yoktur.

    Args:
        draft: Üretilen taslak metni.
        is_individual_petition: Kişisel dilekçe-şeklindeki bir alt-tür için
            True (bkz. ``draft_verifier.verify_draft``'ın aynı adlı kendi
            parametresi) -- "İmzalayacak yetkilinin..." yerine "Dilekçe
            sahibinin..."i seçer.

    Returns:
        (Muhtemelen yeniden yazılmış) taslak ve kaç yer tutucunun yeniden
        adlandırıldığı.
    """
    signature_map = _SIGNATURE_PLACEHOLDERS_PETITION if is_individual_petition else _SIGNATURE_PLACEHOLDERS
    count = 0

    def _replace(match: "re.Match[str]") -> str:
        nonlocal count
        inner = match.group(0)[1:-1].strip()
        folded = _fold(inner)
        replacement = signature_map.get(folded) or _INSTITUTION_PLACEHOLDERS.get(folded)
        if replacement is None:
            return match.group(0)
        count += 1
        return f"[{replacement}]"

    normalized = PLACEHOLDER_PATTERN.sub(_replace, draft)
    return NormalizedDraft(text=normalized, substitutions=count)
