"""Resmi bir belgenin etiketli başlık alanlarının deterministik olarak çıkarılması.

Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik başlık
düzenini *belirler*: "Sayı:" bir yan başlıktır (m.11), "Tarih:" aynı satırda sağ
kenarda yer alır (m.12), "Konu:" bir satır aşağıda gelir (m.13), "İlgi:" atıf
yapılan belgeleri listeler (m.15) ve "Ek:" imzadan sonra gelir (m.18). Format
serbest değil önceden belirlenmiş olduğu için, bu değerler düzenli ifadelerle
küçük bir dil modelinin ulaştığından çok daha yüksek doğrulukla okunabilir.

Bunun ne kadar önemli olduğu modele bağlıdır ve her iki uç da 12 belgelik örnek
külliyat üzerinde ölçüldü:

- `qwen3:8b`, şema genişledikçe kötü bozuluyor. Tek bir alan sorulduğunda
  `sayi`yi doğru döndürüyor; aynı anda üç alan sorulduğunda `sayi`yi null olarak
  döndürüyor ve başka bir alanı, üretim bütçesi tükenene kadar tekrar eden bir
  token döngüsüne sokabiliyor. Genel çıkarım doğruluğu tek başına %28,4, bu
  ayrıştırıcıyla birlikte %98,5.
- `qwen3.5:9b` (projenin varsayılanı) tüm şemayı iyi idare ediyor: tek başına
  %94,0, bu ayrıştırıcıyla birlikte %97,0. Burada ayrıştırıcı artık kritik
  önemde değil, ama yine de `muhatap`'ı düzeltiyor (%60 -> %100), yanlış
  değerlerin üçte ikisini kaldırıyor ve model daha az alan ürettiği için
  çıkarım süresini kabaca üçte bir azaltıyor.

Yani ayrıştırıcı her iki durumda da yerini hak ediyor: küçük modelde bir
doğruluk tabanı, büyük modelde ise bir hassasiyet ve gecikme kazancı olarak.
Burada ayrıştırılan değerler, aynı alan için model çıktısına önceliklidir.
"""

import re
from typing import Any, Optional

from app.ai.compliance.checker import is_blank, normalize_value
from app.ai.verification.draft_verifier import INSTITUTION_PATTERN, TOKEN_OVERLAP_THRESHOLD
from app.core.constants import SIGNATURE_WINDOW_LINES

# Aynı satırda önceki bir değeri sonlandırabilecek her etiket. Yönetmelik
# "Tarih"i "Sayı"nın sağına aynı satıra yerleştirir, bu yüzden bir değer satır
# sonunda değil bir sonraki etikette durmalıdır.
_LABEL_ALTERNATION = (
    r"Sayı|Sayi|Tarih|Konu|İlgi|Ilgi|Ek|Ekler|Dağıtım|Dagitim|"
    r"Gizlilik\s+Derecesi|İvedilik|Ivedilik|Adres|Telefon|E-?posta"
)

#: "Etiket : değer" kalıbıyla eşleşir, satır sonunda veya bir sonraki bilinen
#: etikette durur. İki nokta üst üstenin etrafında sadece boşluk ve sekme
#: olabilir -- asla satır sonlarıyla da eşleşen `\s` değil; aksi halde boş bir
#: "Konu :" satırı bir sonraki satırın metnini yakalardı. Bu önemliydi: belgenin
#: boş bıraktığı bir alan için sessizce bir değer uyduruyordu.
#:
#: İki nokta üst üsteden önceki `\S{0,3}`, etiket ile iki nokta üst üste arasında
#: kısa, sapkın bir token'a tolerans gösterir: gerçek taranmış külliyat OCR'ı
#: (datasets/resmi_yazisma/ altındaki 45 gerçek CY-*.pdf'e karşı yapılan
#: field_recovery kalibrasyonuna bakın) tekrarlayan bir şablonda tutarlı biçimde
#: bir form onay kutusu glifini "Sayı (o :..." olarak yanlış okuyor -- bu tek
#: kalıp, o külliyattaki eksik `sayi` değerlerinin çoğunu oluşturuyordu. Format
#: zaten normal bir "Etiket : değer" olduğunda gerçek bir değerin içine
#: sızmaması için 3 karakterle sınırlandırıldı.
_VALUE_TAIL = (
    rf"[ \t]*\S{{0,3}}[ \t]*[:：][ \t]*(.+?)"
    rf"(?=[ \t]+(?:{_LABEL_ALTERNATION})[ \t]*[:：]|[ \t]*$)"
)

#: Bir tarih, ya rakamla ("16.04.2026") ya da yazıyla ("16 Nisan 2026").
_DATE = (
    r"\d{1,2}[./]\d{1,2}[./]\d{4}"
    r"|\d{1,2}\s+(?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s+\d{4}"
)
#: RYUEHY m.12 bir "Tarih:" etiketi öngörür, ama gerçek resmi yazışmalar
#: genellikle tarihi etiketsiz olarak Sayı satırının sağına yerleştirir
#: (datasets/resmi_yazisma/ altındaki 45 gerçek taranmış CY-*.pdf'e karşı
#: doğrulandı: bu, o külliyatta eksik `tarih`in tek en büyük nedeniydi).
#: Yalnızca etiketli SINGLE_VALUE_PATTERN girişi hiçbir şey bulamadığında bir
#: yedek olarak denenir -- parse_labelled_fields içindeki kullanımına bakın.
_UNLABELLED_DATE_ON_SAYI_LINE = re.compile(
    rf"(?:^|\n)\s*Say[ıi][^\n]*?({_DATE})\s*$", re.MULTILINE
)
#: Aynı gerçek dünya sorunu için ikinci, daha dar bir yedek: bazı görsel model
#: transkripsiyonları tarihi Sayı satırına yapıştırılmış tutmak yerine kendi
#: satırına bölüyor (CY-010'un glm-ocr:latest başlık onarımına karşı
#: doğrulandı: "Sayı : Z-43452547-120.07.03-1841896\n20.04.2026\nKonu : ..." --
#: yukarıdaki etiketli ve aynı satır kalıplarının ikisi de orada hiçbir şey
#: bulamıyor). Yalnızca ikisi de hiçbir şey bulamadığında denenir ve tarihin
#: sadece Sayı'dan sonra bir yerde bulunması değil, bir sonraki satırın
#: *tamamı* olması şartı aranır -- böylece gövdede ilgisiz içerikle ayrılmış,
#: daha sonra geçen bir tarih asla başlık tarihiyle karıştırılmaz.
_UNLABELLED_DATE_ON_LINE_AFTER_SAYI = re.compile(
    rf"(?:^|\n)\s*Say[ıi][^\n]*\n[ \t]*({_DATE})[ \t]*(?:\n|$)", re.MULTILINE
)

SINGLE_VALUE_PATTERN: dict[str, re.Pattern[str]] = {
    "sayi": re.compile(rf"(?:^|\n)\s*Say[ıi]{_VALUE_TAIL}", re.MULTILINE),
    "tarih": re.compile(rf"(?:^|\n|\s)Tarih{_VALUE_TAIL}", re.MULTILINE),
    "konu": re.compile(rf"(?:^|\n)\s*Konu{_VALUE_TAIL}", re.MULTILINE),
    "gizlilik_derecesi": re.compile(
        rf"(?:^|\n)\s*Gizlilik\s+Derecesi{_VALUE_TAIL}", re.MULTILINE | re.IGNORECASE
    ),
    "ivedilik": re.compile(
        rf"(?:^|\n)\s*[İI]vedilik{_VALUE_TAIL}", re.MULTILINE | re.IGNORECASE
    ),
    "adres": re.compile(rf"(?:^|\n)\s*Adres{_VALUE_TAIL}", re.MULTILINE),
}

LIST_VALUE_PATTERN: dict[str, re.Pattern[str]] = {
    "ilgi": re.compile(rf"(?:^|\n)\s*[İI]lgi{_VALUE_TAIL}", re.MULTILINE),
    "ekler": re.compile(rf"(?:^|\n)\s*Ek(?:ler)?{_VALUE_TAIL}", re.MULTILINE),
}

#: Birden fazla öğeyi numaralandıran ("a) ... b) ...") bir "İlgi:" veya "Ek:"
#: değerini böler. İşaretten sonra boşluk gelmesi şarttır, aksi halde
#: "01.01.2026" gibi bir tarihin başındaki "01." bir numaralandırıcı sanılır ve
#: tarih gün kısmını kaybeder.
_LIST_ITEM_SEPARATOR = re.compile(
    r"(?:^|\s)(?:[a-zçğıöşü]\)|\d{1,2}[\.\)])[ \t]+", re.IGNORECASE
)


def _clean(value: str) -> str:
    """Yakalanan bir değerdeki boşlukları normalleştirir.

    Args:
        value: Ham regex yakalaması.

    Returns:
        Boşlukları sadeleştirilmiş, sondaki gereksiz noktalama olmadan değer.
    """
    return re.sub(r"\s+", " ", value).strip().strip(",;")


def _split_list(value: str) -> list[str]:
    """Numaralandırılmış bir İlgi/Ek değerini öğelerine böler.

    Args:
        value: Ham yakalanan değer.

    Returns:
        Temizlenmiş öğeler, veya numaralandırma yoksa tek öğeli bir liste.
    """
    parts = [part for part in _LIST_ITEM_SEPARATOR.split(value) if part.strip()]
    if len(parts) > 1:
        return [_clean(part) for part in parts]
    cleaned = _clean(value)
    return [cleaned] if cleaned else []


#: Serbest içerik yerine etiketli yan başlık olan satırlar.
_ANY_LABEL_LINE = re.compile(rf"^\s*(?:{_LABEL_ALTERNATION})[ \t]*[:：]", re.IGNORECASE)
#: "T.C." başlık satırı (m.10). Baştan en fazla 3 alfanümerik olmayan
#: karaktere tolerans gösterir: gerçek OCR (taranmış külliyatta
#: CY-023/027/028/030) "T.C." ile aynı satıra tutarlı biçimde dekoratif bir
#: çerçeve/amblem glifi yapıştırıyor ("* T.C.", ", T.C."); tam eşleşme
#: gerektiren bir anchor bunu doğrudan reddediyor ve antet-kurum taramasını
#: tamamen kaybettiriyordu (aşağıdaki _parse_sender_institution hiç
#: başlamıyordu bile).
_TC_LINE = re.compile(r"^[^A-Za-zÇĞİÖŞÜçğıöşü]{0,3}\s*T\s*\.?\s*C\s*\.?\s*$", re.IGNORECASE)
#: Bir muhatap satırı: Türkçe bir yönelme hâli ekiyle biter (m.14), örn.
#: "ÖRNEK VALİLİĞİNE", "İLGİLİ MAKAMA", "DAĞITIM YERLERİNE".
#:
#: Ekin kendisi, öncesindeki dizinin aksine sadece büyük harf olarak kalır --
#: bunu güvenli kılan şey de budur. `.{6,40}?` (herhangi karakterler, tüm bir
#: cümleyi kapsayamasın diye uzunluğu sınırlı) genelde büyük harfli bir
#: muhatap satırı içinde tek bir sapkın küçük harfli OCR eserine tolerans
#: gösterir (taranmış külliyattaki gerçek OCR bazı muhatapları arada bir
#: yanlış büyük/küçük harfli bir harfle işleniyor), ama yine de satırın büyük
#: harfle *bitmesini* şart koşar; ki sıradan bir isim veya küçük harfli bir
#: cümle parçası bunu asla yapmaz. Önce tamamen büyük/küçük harf duyarsız bir
#: sürüm denendi ve reddedildi: "Zeynep Kaya" -- sıradan bir kişi adı -- buna
#: eşleşiyordu, çünkü "Kaya" da binlerce sıradan Türkçe kelime gibi "ya" ile
#: bitiyor; sadece sonda büyük harf şartı koymak bunu eliyor. Bkz.
#: test_addressee_pattern_does_not_match_a_capitalised_name ve
#: test_addressee_pattern_does_not_match_an_ordinary_body_sentence.
_ADDRESSEE_SUFFIX = r"(?:NA|NE|YA|YE|MAKAMA|YERLERİNE|BAŞKANLIĞINA)"
#: Sondaki `\s+[0-9/]{1,12}`, ekten sonra tam olarak bir kısa *rakam ve eğik
#: çizgiden oluşan* notasyona tolerans gösterir -- taranmış külliyattaki
#: gerçek görsel model OCR'ı (CY-012) el yazısı bir referans numarasını
#: ('7/4/2413') doğru okuduğunda bunu muhatapla aynı satıra koyuyor ve daha
#: katı bir `$` anchor'ı o yüzden tüm satırı reddediyordu.
#:
#: `\S` yerine `[0-9/]` ile sınırlandırıldı: herhangi kısa bir token'a izin
#: veren ilk deneme, çıkarılan metni sabit tutup eski ve yeni ayrıştırıcı
#: çıktısını karşılaştıran, 45 gerçek taramaya karşı yapılan A/B çalışmasında
#: bulunan gerçek bir regresyona yol açtı. "HAZİNE VE MALİYE BAKANLIĞI" --
#: bir kurumun kendi antet satırı, muhatap değil -- "MALİYE" "YE" ile bittiği
#: ve "BAKANLIĞI" kısa bir token olduğu için yanlışlıkla eşleşti; çünkü
#: _parse_addressee *ilk* eşleşen satırı döndürüyor, bu yanlış eşleşme hem
#: belgenin aşağısındaki gerçek muhatabı geçersiz kıldı hem de (
#: _parse_sender_institution'ın paylaşılan durdurma koşulu üzerinden) aynı
#: antete sahip her belgede gonderen_kurum tespitini sıfırladı. Aşağıdaki
#: "Zeynep Kaya" durumuyla aynı hata ailesi, sadece bir kişi adı yerine bir
#: kurum adına çarpıyor -- notasyonu bir referans-numarası şekliyle
#: sınırlamak, külliyatta ölçülen her gerçek el yazısı referans durumuyla
#: eşleşmeye devam ederken bunu kapatıyor.
_ADDRESSEE_LINE = re.compile(rf"^.{{6,40}}?{_ADDRESSEE_SUFFIX}(?:\s+[0-9/]{{1,12}})?\s*$")
#: İsim şeklinde bir kelime: Baş harfi büyük ("Ahmet") veya TAMAMEN BÜYÜK
#: harfli bir Türkçe soyisim ("GÜLER"). Resmi yazışmalar geleneksel olarak
#: soyismi (ve bazen bir unvan kısaltmasını, "Prof. Dr.") tamamen büyük
#: harfle yazar -- yalnızca baş harfi büyük kalıp "Yaşar GÜLER"i doğrudan
#: reddediyordu. 23 elle etiketlenmiş gerçek belgenin `clean_text`'ine karşı
#: ölçüldü (yapısı gereği OCR hatasız): yalnızca-baş-harf-büyük kalıp
#: bunların 17/23'ünde `imza_sahibi`/`imza_unvani`'yi kaybetti; hepsi
#: datasets/sample/'ın tekdüze "Ahmet Yılmaz" tarzı sentetik külliyatının
#: hiç sınamadığı, tamamen büyük harfli soyisimli belgelerdi.
_NAME_WORD = r"(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+|[A-ZÇĞİÖŞÜ]{2,})"
#: İmza bloğundaki kişisel bir isim satırı: 2-4 isim şeklinde kelime, rakam
#: yok. Baştaki lookahead, satırda bir yerde en az bir küçük harf şart koşar,
#: bu yüzden tamamen BÜYÜK harfli kelimelerden oluşan bir satır -- "TÜRKİYE
#: BÜYÜK MİLLET MECLİSİ BAŞKANLIĞI" gibi bir kurum/antet satırı -- tek
#: başına asla eşleşemez; gerçek bir imza her zaman en az bir baş harfi
#: büyük ad taşır. Bu, her kurum-adı yanlış pozitifini tek başına
#: yakalamaz (koşan metinde kullanılan "Türkiye Büyük Millet Meclisi" gibi
#: *baş harfleri büyük kelimeli* bir kurum ifadesi hâlâ bu kalıpla eşleşir)
#: -- aşağıdaki `_parse_signature`, `INSTITUTION_PATTERN` aracılığıyla kurum
#: adına benzeyen bir adayı ek olarak reddeder ve geri kalanı için birincil
#: savunma olarak adayları belge sırasıyla denemeye güvenir (gerçek isim
#: satırı önce gelir).
_PERSON_NAME_LINE = re.compile(
    rf"^(?=.*[a-zçğıöşü])(?:{_NAME_WORD}\.?\s+){{1,3}}{_NAME_WORD}$"
)
#: `INSTITUTION_PATTERN`'in (draft_verifier.py) kapsamadığı kurum-adı ekleri.
#: O kalıp *taslak* metninden (`drafts` paketinin kendi altın seti) bir kurum
#: iddiası çıkarmak için ayarlanmıştır, o yüzden oraya eklenecek yeni bir ek
#: bu modülün hiç ilgilenmemesi gereken rakamları oynatabilir -- bunun yerine
#: burada, aynı şekilde (1-5 baş harfi büyük kelime + ek) yerel olarak
#: tutuldu. Özellikle "Meclisi", aşağıdaki `_parse_signature`'da "Türkiye
#: Büyük Millet Meclisi"nin bir imza adayı olarak geçmesine izin veren
#: şeydi: gerçek külliyatta ölçüldü, aynı TBMM antet şablonu altındaki dört
#: belgenin (CY-010/011/033/050) hepsinde aksi halde bir imza satırının
#: beklendiği yerde tam olarak bu kurum satırı oturuyor.
_LOCAL_INSTITUTION_SUFFIX_PATTERN = re.compile(
    r"\b(?:[A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ]*\s+){1,5}(?:Meclisi|Kurulu|Komisyonu)\b"
)
#: Bir satırı isim değil unvan olarak işaretleyen kelimeler.
_TITLE_HINT = re.compile(
    r"(Müdür|Başkan|Bakan|Vali|Kaymakam|Rektör|Dekan|Müsteşar|Amir|Şef|"
    r"Koordinatör|Uzman|Memur|İşletmen|Mühendis|Sekreter|Yardımcısı|a\.)",
    re.IGNORECASE,
)
#: Gövdeyi bitiren kapanış formülleri; imza bloğu bunları izler.
_CLOSING_FORMULA = re.compile(
    r"(arz ederim|rica ederim|arz olunur|bilgilerinize|düzenlenmiştir)",
    re.IGNORECASE,
)


def _content_lines(text: str) -> list[str]:
    """Boş olmayan, etiket olmayan satırları belge sırasıyla döndürür.

    Args:
        text: Çıkarılan belge metni.

    Returns:
        Kırpılmış içerik satırları.
    """
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_sender_institution(lines: list[str]) -> Optional[str]:
    """Anteti okur: "T.C." ile ilk yan başlık arasındaki satırlar.

    Args:
        lines: Belge sırasıyla içerik satırları.

    Returns:
        Kurum adı, veya antet yoksa None.
    """
    try:
        start = next(i for i, line in enumerate(lines) if _TC_LINE.match(line))
    except StopIteration:
        return None

    collected = []
    for line in lines[start + 1 :]:
        if _ANY_LABEL_LINE.match(line) or _ADDRESSEE_LINE.match(line):
            break
        collected.append(line)
        if len(collected) >= 3:
            break
    return " ".join(collected) if collected else None


def _parse_addressee(lines: list[str]) -> Optional[str]:
    """Muhatap satırını bulur (m.14): yönelme ekiyle biten büyük harfli satır.

    Args:
        lines: Belge sırasıyla içerik satırları.

    Returns:
        Muhatap, veya hiçbir satır eşleşmezse None.
    """
    for index, line in enumerate(lines):
        if _ANY_LABEL_LINE.match(line) or _TC_LINE.match(line):
            continue
        if _ADDRESSEE_LINE.match(line):
            # Parantez içinde bir birim adı bir sonraki satırda gelebilir.
            suffix = ""
            if index + 1 < len(lines) and lines[index + 1].startswith("("):
                suffix = " " + lines[index + 1]
            return (line + suffix).strip()
    return None


def _parse_signature(lines: list[str]) -> dict[str, str]:
    """İmza bloğunu okur (m.17): üstte isim, altta unvan.

    Args:
        lines: Belge sırasıyla içerik satırları.

    Returns:
        `imza_sahibi` ve `imza_unvani` içerebilecek eşleme.
    """
    # İmza bloğu kapanış formülünü izleyen kısımdır. Belgenin kendi sonundan
    # geriye doğru değil, oradan *ileri* doğru arama yapılır: gerçek antet
    # şablonları imzadan sonra bir antet altbilgisi (adres, santral, faks,
    # web) taşır, bu yüzden sayfa sonundan geriye doğru bir pencere altbilgiye
    # düşer ve imzayı tamamen kaçırır -- eski geriye dönük pencereyle gerçek
    # taranmış külliyatta 0/23, bununla 21/23 ölçüldü (bkz.
    # SIGNATURE_WINDOW_LINES'ın kendi kalibrasyon yorumu). Formül yoksa
    # (ör. bir tutanak) belgenin kendi sonuna düşer; burada eski geriye
    # dönük davranış doğrudur.
    #
    # Sonuncusu değil *ilk* eşleşme kazanır: `lines` her zaman tek bir sayfa
    # değildir. Üretimde buraya çıkarılan belgenin tamamı -- tüm sayfalar
    # birleştirilmiş olarak -- verilir ve ekli bir belge (mektubun ilettiği
    # bir "Ek:" yanıt, veya İlgi'de alıntılanan önceki bir yazı) genellikle
    # daha aşağıda kendi kapanış formülünü taşır. Son geçtiği yeri almak,
    # aramayı mevcut belgenin kendi kapanışı yerine o ekin kapanışına
    # bağlar ve gerçek imzayı tamamen kaçırır -- iki gerçek çok sayfalı
    # belgede (CY-002, CY-034) ölçüldü, her biri bir ekin kendi
    # "Bilgilerinize/arz ederim"i tarafından çekilmişti. Bunun asıl önemli
    # olduğu tek sayfalı durum için güvenli olduğu doğrulandı: 23 elle
    # etiketlenmiş gerçek belgenin kendi `clean_text`'i (yalnızca 1. sayfa)
    # hiçbiri bu kalıpla birden fazla eşleşmiyor, yani `first` ve `last`
    # her birinde tek tek aynı sonucu veriyor -- fark yalnızca sonraki
    # sayfalar metne girdiğinde ortaya çıkıyor.
    start = 0
    closing_formula_found = False
    for index, line in enumerate(lines):
        if _CLOSING_FORMULA.search(line):
            start = index + 1
            closing_formula_found = True
            break
    window = (
        lines[start : start + SIGNATURE_WINDOW_LINES]
        if closing_formula_found
        else lines[start:][-4:]
    )
    tail = [
        line
        for line in window
        if not _ANY_LABEL_LINE.match(line) and line.lower() != "imza"
    ]

    # Sondaki tek başına bir isim imza değildir. İmzasız bir dilekçede son
    # satır sadece başvuranın adıdır, ve bunu `imza_sahibi` olarak iddia etmek
    # gerçek bir 3071 m.4 eksikliğini gizler. Doğrulama şart koşulur: isimden
    # sonra bir unvan satırı, açık bir "İmza" işareti, veya kurumsal bir antet
    # -- resmi bir yazı tanımı gereği imzalıdır (m.17).
    # Türkçe büyük/küçük harf dönüşümü burada önemlidir: "İmza".lower() "imza"
    # değil, noktalı bir i artı birleşen bir nokta olan "i̇mza"yı üretir.
    has_signature_marker = any(
        normalize_value(line).rstrip(":") == "imza" for line in lines[start:]
    )
    has_letterhead = any(_TC_LINE.match(line) for line in lines)

    parsed: dict[str, str] = {}
    for index, line in enumerate(tail):
        if (
            not _PERSON_NAME_LINE.match(line)
            or _TITLE_HINT.search(line)
            # Baş harfleri büyük kelimelerden oluşan bir kurum ifadesi
            # ("Türkiye Büyük Millet Meclisi") hâlâ _PERSON_NAME_LINE ile
            # eşleşir -- o kalıbın kendi docstring'ine bakın. Kurum adına
            # benzeyen bir adayı bir kişi olarak kabul etmek yerine doğrudan
            # reddet -- hem paylaşılan kalıba hem de onun kapsamadığı eklere
            # karşı kontrol edilir (bkz. _LOCAL_INSTITUTION_SUFFIX_PATTERN'in
            # kendi docstring'i).
            or INSTITUTION_PATTERN.search(line)
            or _LOCAL_INSTITUTION_SUFFIX_PATTERN.search(line)
        ):
            continue
        title = next(
            (
                candidate
                for candidate in tail[index + 1 :]
                if _TITLE_HINT.search(candidate)
            ),
            None,
        )
        if title is None and not has_signature_marker and not has_letterhead:
            break
        parsed["imza_sahibi"] = line
        if title is not None:
            parsed["imza_unvani"] = title
        break
    return parsed


def parse_positional_fields(text: str) -> dict[str, Any]:
    """Yönetmeliğin etiketle değil konumla yerleştirdiği alanları çıkarır.

    Başlık (m.10), muhatap (m.14) ve imza bloğu (m.17) hiçbir yan başlık
    taşımaz, bu yüzden yapısal olarak bulunurlar. Bunlar öngörülen etiketler
    değil sezgisel yöntemlerdir, bu yüzden her kalıp kasıtlı olarak katıdır:
    hiçbir şey raporlamamak, gerçek bir eksikliği gizleyecek bir değer
    uydurmaktan çok daha iyidir.

    Args:
        text: Çıkarılan belge metni.

    Returns:
        `EvrakField` adlarının ayrıştırılmış değerlere eşlemesi; yalnızca
        güvenle bulunanları içerir.
    """
    lines = _content_lines(text)
    parsed: dict[str, Any] = {}

    institution = _parse_sender_institution(lines)
    if institution:
        parsed["gonderen_kurum"] = institution

    addressee = _parse_addressee(lines)
    if addressee:
        parsed["muhatap"] = addressee

    parsed.update(_parse_signature(lines))
    return parsed


def parse_labelled_fields(text: str) -> dict[str, Any]:
    """Yönetmeliğin etiketli yan başlık olarak öngördüğü alanları çıkarır.

    Args:
        text: Çıkarılan belge metni.

    Returns:
        `EvrakField` adlarının ayrıştırılmış değerlere eşlemesi; yalnızca
        gerçekten bulunan alanları içerir. Asla tahmin etmez: bulunmayan bir
        etiket hiçbir giriş üretmez.
    """
    parsed: dict[str, Any] = {}

    for name, pattern in SINGLE_VALUE_PATTERN.items():
        match = pattern.search(text)
        if match:
            value = _clean(match.group(1))
            if value:
                parsed[name] = value

    for name, pattern in LIST_VALUE_PATTERN.items():
        match = pattern.search(text)
        if match:
            items = _split_list(match.group(1))
            if items:
                parsed[name] = items

    # Gerçek yazışmaların genellikle Sayı satırının sağına koyduğu etiketsiz
    # tarih için yedek (bkz. _UNLABELLED_DATE_ON_SAYI_LINE) -- yalnızca
    # yukarıdaki etiketli "Tarih:" formu hiçbir şey bulamadığında denenir, bu
    # yüzden tarihi etiketleyen bir belge bundan etkilenmez.
    if "tarih" not in parsed:
        match = _UNLABELLED_DATE_ON_SAYI_LINE.search(text)
        if match:
            value = _clean(match.group(1))
            if value:
                parsed["tarih"] = value

    # İkinci yedek, yalnızca yukarıdaki aynı satır formu da hiçbir şey
    # bulamadığında denenir -- bkz. _UNLABELLED_DATE_ON_LINE_AFTER_SAYI'nin
    # kendi docstring'i.
    if "tarih" not in parsed:
        match = _UNLABELLED_DATE_ON_LINE_AFTER_SAYI.search(text)
        if match:
            value = _clean(match.group(1))
            if value:
                parsed["tarih"] = value

    # Konumsal alanlar yalnızca etiketli bir değer zaten bulunmadıysa doldurur.
    for name, value in parse_positional_fields(text).items():
        parsed.setdefault(name, value)

    return parsed


#: Ayrıştırıcının HER İKİ yönde de yetkili olduğu alanlar: yönetmelik alanın
#: nasıl göründüğünü öngörüyorsa ve ayrıştırıcı onu bulamıyorsa, alan
#: gerçekten yoktur ve o alan için model değeri atılır.
#:
#: Sunumu öngörülmemiş ve bu yüzden ayrıştırıcının dışlayamadığı alanları
#: kasıtlı olarak dışlar:
#:   - `adres` / `iletisim`: bir dilekçe bunları çoğunlukla etiketsiz yazar.
#:   - `gizlilik_derecesi` / `ivedilik`: yan başlık yerine tek başına damga
#:     olarak görünür ("HİZMETE ÖZEL", "ACELE").
#:   - `basvuran_adi`: hiç ayrıştırıcı desteği yok.
#: Bunlar için, bulunamayan bir ayrıştırma "yok" değil "bilinmiyor" anlamına
#: gelir, bu yüzden modele hâlâ güvenilir.
AUTHORITATIVE_FIELD: frozenset[str] = frozenset(
    {
        "sayi",
        "tarih",
        "konu",
        "ilgi",
        "ekler",
        "muhatap",
        "gonderen_kurum",
        "imza_sahibi",
        "imza_unvani",
    }
)

#: Boş değeri None yerine liste olan alanlar.
_LIST_FIELD: frozenset[str] = frozenset({"ilgi", "ekler"})

#: RYUEHY uygunluk kontrolünün okuduğu ve bu projenin çıkarım-kabul kapısının
#: (bkz. FallbackDocumentExtractor'ın `header_field_probe`'u) bir çıkarımın
#: güvenilir olup olmadığına karar vermek için kullandığı beş başlık alanı.
#: Belge geneli bir düzyazı okunabilirlik skoru (`ExtractedDocument.quality_ratio`)
#: başlık bloğunun sağ salim kalıp kalmadığını göremez -- aksi halde temiz bir
#: sayfadaki bozuk bir `sayi` yine de genel olarak düzgün Türkçe düzyazı gibi
#: okunur. Bunun yerine bu beşini saymak, uygunluk denetçisinin önemsediği
#: gerçek başarısızlığın doğrudan bir ölçümüdür.
HEADER_FIELD: tuple[str, ...] = ("sayi", "tarih", "konu", "muhatap", "gonderen_kurum")


def count_header_fields(text: str) -> int:
    """`HEADER_FIELD`'in kaçının `text`'ten kurtarılabildiğini sayar.

    Tespiti yeniden uygulamak yerine `parse_labelled_fields`'i yeniden
    kullanır, böylece bu her zaman tam olarak uygunluk hattının kendisinin
    kurtaracağı şeyi ölçer -- ayrı, sürüklenebilir bir "bulundu" kavramı
    olmadan.

    Args:
        text: Çıkarılan belge metni (genelde sadece 1. sayfa -- belge
            geneli puanlamanın neden sonraki bir sayfadaki ekli bir mektubun
            kendi başlığının arkasına bir 1. sayfa hatasını gizlediğine dair
            çıkarım-kabul kapısının kendi gerekçesine bakın).

    Returns:
        Boş olmayan ayrıştırılmış değere sahip `HEADER_FIELD` anahtarlarının
        sayısı, 0 ile `len(HEADER_FIELD)` arasında.
    """
    parsed = parse_labelled_fields(text)
    return sum(1 for name in HEADER_FIELD if parsed.get(name))


def has_signature(text: str) -> bool:
    """`imza_sahibi`nin `text`'ten kurtarılabilir olup olmadığını bildirir.

    `FallbackDocumentExtractor`'ın imza-kurtarma yükseltmesini destekler (bkz.
    o sınıfın, `count_header_fields`'in `header_field_probe` üzerinden
    enjekte edildiği şekilde enjekte edilen `signature_probe` parametresi).
    `count_header_fields`'ten farklı bir hatayı ölçer: bir sayfa her
    `HEADER_FIELD` sağlamken genel olarak düzgün Türkçe düzyazı gibi
    okunabilir, ama özellikle imza bloğu tahrip olmuş olabilir -- ıslak imza
    mürekkebinin altındaki basılı ismi gizlemesi, belge geneli bir
    `quality_ratio` veya `count_header_fields`'in asla fark edemeyeceği,
    başlık bandının tamamen dışında bir yer.

    Args:
        text: Çıkarılan belge metni (1. sayfa).

    Returns:
        `imza_sahibi` ayrıştırılabiliyorsa True.
    """
    return bool(parse_labelled_fields(text).get("imza_sahibi"))


#: Ayrıştırıcı hiçbir şey bulamamışsa ama model değeri belge metninde
#: gerçekten dayanaklıysa, kanıt temelli kurtarmaya (bkz.
#: `merge_parsed_over_model`) uygun `AUTHORITATIVE_FIELD` üyeleri. Kasıtlı
#: olarak `AUTHORITATIVE_FIELD`'dan daha dar:
#:
#: * `imza_sahibi`/`imza_unvani`'nin `_parse_signature`'ın çıktısında
#:   bulunmaması bir kapsam boşluğu değil, *düşünülmüş* bir karardır -- o
#:   fonksiyon, onu doğrulayacak bir unvan satırı, imza işareti veya antet
#:   olmadan sondaki çıplak bir ismi kasıtlı olarak reddeder (imzasız
#:   dilekçe koruması, bkz. `UNSIGNED_PETITION`'ın kendi testi). İsim her
#:   iki durumda da neredeyse her zaman metinde tam olarak orada
#:   oturuyordur, bu yüzden basit bir alt-dize dayanaklandırma kontrolü onu
#:   kurtarır ve o korumanın var olma nedeni olan eksikliği tam olarak
#:   yeniden ortaya çıkarır.
#: * `ilgi`/`ekler` belirli belge referanslarını adlandırır; uydurulmuş bir
#:   tanesi `imza_sahibi` ile aynı uydurma riskini taşır, bu yüzden onlar da
#:   katı kalır.
_EVIDENCE_RESCUABLE_FIELD: frozenset[str] = frozenset(
    {"sayi", "tarih", "konu", "muhatap", "gonderen_kurum"}
)

#: `_EVIDENCE_RESCUABLE_FIELD`'in, tam alt-dize kontrolünün altında,
#: token-örtüşmesi yedeğine de (bkz. `_token_overlap`) uygun alt kümesi.
#: Kasıtlı olarak daha da dar: `muhatap` ve `gonderen_kurum` belirli bir
#: kişi veya kurumu adlandırır; bunu bir model gerçekçi biçimde yeniden
#: sıralayabilir (isim önce yazılan bir belge için "Ankara Milletvekili
#: İdris ŞAHİN") ama toptan sentezlemez, çünkü bir kişi/kurum adı, bir
#: modelin bir konuyu yeniden ifade ettiği gibi yeniden ifade ettiği bir şey
#: değildir. `konu`/`tarih`/`sayi` yalnızca katı alt-dize kontrolünde kalır
#: -- hiç "Konu:" satırı olmayan bir belge olan CY-010'da qwen3.5:9b'ye
#: karşı canlı olarak ölçüldü: model, gövde kelime dağarcığını hafifçe
#: yeniden ifade ederek oluşturulmuş bir `konu` değeri üretti
#: ("...istemlerine ilişkin ilgi önergenizde yer alan sorularınız..."
#: ifadesini "...istemlerine ilişkin soruların cevabı"na dönüştürerek), bu
#: da çıkarılmış bir değer değil sentezlenmiş bir özet olmasına rağmen
#: `TOKEN_OVERLAP_THRESHOLD`'un rahatça üzerinde, 0.857 token örtüşmesi
#: skoru aldı. `konu`, bir modelin alıntılamak yerine doğal olarak
#: özetlemeye meyilli olduğu tam olarak bu şekildeki bir alandır, bu yüzden
#: token-örtüşmesi yedeğinin ulaşmaması gereken tek `_EVIDENCE_RESCUABLE_FIELD`
#: üyesidir; `tarih`/`sayi` de dışlanır çünkü ne birinin hata modu bir isim
#: gibi "aynı değer, farklı kelime sırası" değildir.
_TOKEN_OVERLAP_ELIGIBLE_FIELD: frozenset[str] = frozenset({"muhatap", "gonderen_kurum"})


def _header_region(text: str) -> str:
    """`text`'i ilk muhatap veya kapanış-formülü satırına kadar (hariç) döndürür.

    Başlık bloğu (Sayı/Tarih/Konu, m.11-13) düzgün oluşturulmuş bir belgede
    her zaman ikisinden de önce gelir. `merge_parsed_over_model`'daki
    `tarih`'in kanıt temelli kurtarmasının kapsamını sınırlamak için
    kullanılır: bu olmadan, gövdede oturan bir izin talebinin başlangıç
    tarihi tam da gerçek bir başlık tarihi kadar dayanaklı görünür ve alt-dize
    kontrolü başka bir şey için gevşetildiği anda `merge_parsed_over_model`'ın
    kendi docstring'inin zaten adlandırdığı belirli hata modunu ("bir izin
    başlangıç tarihini ... `tarih`'e taşımak") yeniden diriltir.

    Args:
        text: Çıkarılan belgenin tam metni.

    Returns:
        Başlangıç satırları, birleştirilmiş halde, veya ne muhatap ne de
        kapanış formülü bulunamazsa metnin tamamı.
    """
    lines = _content_lines(text)
    for index, line in enumerate(lines):
        if _ADDRESSEE_LINE.match(line) or _CLOSING_FORMULA.search(line):
            return "\n".join(lines[:index])
    return text


def _token_overlap(value: str, haystack: str) -> float:
    """`value`'nun anlamlı token'larının (uzunluk > 2) `haystack`'te bulunan payı.

    `merge_parsed_over_model`'daki tam alt-dize kontrolünün altında toleranslı
    bir yedek: bir model, kaynakta oturduğu sıraya göre yeniden sıralayarak
    da olsa bir değeri doğru bildirebilir. Gerçek bir belgede (CY-033)
    qwen3.5:9b'ye karşı canlı olarak ölçüldü, model, metnin kendisinin
    "Sayın İdris ŞAHİN\\nAnkara Milletvekili" olarak yazdığı bir `muhatap`
    için "Ankara Milletvekili İdris ŞAHİN" döndürdü -- aynı iki bilgi (isim,
    unvan), ters sırada; ki hiçbir şey uydurulmamış olsa bile basit bir
    alt-dize kontrolü bunu doğrudan reddeder.

    `app.ai.verification.draft_verifier`'ın kendi `_token_overlap`'iyle aynı
    şekil ve eşik (`TOKEN_OVERLAP_THRESHOLD`), import edilmek yerine yeniden
    uygulandı; böylece bu modülün dayanaklandırma kontrolü, `draft_verifier`'ın
    (noktalamayı koruyan) `_fold`'unu burada ikinci bir indirgeme sözleşmesi
    olarak getirmek yerine, noktalamayı kaldıran kendi mevcut kuralı olan
    `normalize_value` üzerinden indirgenir.

    Args:
        value: İndirgenmemiş aday değer.
        haystack: Karşılaştırılacak, indirgenmemiş güvenilir metin.

    Returns:
        [0, 1] aralığında örtüşme. İkiden az anlamlı token'ı olan değerler
        0.0 puan alır -- `INSTITUTION_PATTERN`'in çok-kelimeli gerekliliği
        ve `_PERSON_NAME_LINE`'ın 2-4 kelimelik şeklinin de dayandığı aynı
        gerekçeyle, tek bir token tek başına anlamlı bir kanıt değildir.
    """
    tokens = [token for token in normalize_value(value).split() if len(token) > 2]
    if len(tokens) < 2:
        return 0.0
    folded_haystack = normalize_value(haystack)
    return sum(1 for token in tokens if token in folded_haystack) / len(tokens)


def merge_parsed_over_model(
    model_fields: dict[str, Any], parsed: dict[str, Any], document_text: str = ""
) -> dict[str, Any]:
    """Deterministik olarak ayrıştırılan değerleri model çıktısıyla birleştirir.

    `AUTHORITATIVE_FIELD` için ayrıştırıcı her iki yönde de kazanır:

    * bir değer bulduğunda, o değer modelinkinin yerine geçer;
    * hiçbir şey bulamadığında, model değeri atılır -- *ancak*
      `document_text` verilmişse, alan `_EVIDENCE_RESCUABLE_FIELD` içindeyse
      ve model değeri gerçekten dayanaklıysa -- indirgenmiş bir alt-dize
      eşleşmesi (`normalize_value` üzerinden, `is_blank`'ın kendi
      indirgemesiyle aynı), veya özellikle `muhatap`/`gonderen_kurum` için
      (`_TOKEN_OVERLAP_ELIGIBLE_FIELD`) ve alt-dize kontrolü başarısız
      olursa, kaynağa göre yeniden sıralanmış ama modelin doğru bildirdiği
      bir isim için bir token-örtüşmesi eşleşmesi (`_token_overlap`,
      `draft_verifier`'ın kullandığı aynı `TOKEN_OVERLAP_THRESHOLD`) (bunun
      kapsadığı canlı CY-033 durumu için `_token_overlap`'ın kendi
      docstring'ine, ve özellikle `konu`'nun neden bu yoldan uzak tutulması
      gerektiğine dair `_TOKEN_OVERLAP_ELIGIBLE_FIELD`'ın kendi
      docstring'ine bakın -- CY-010'da, yeniden sıralanmış bir çıkarım
      yerine model tarafından sentezlenmiş bir özeti kurtardığı canlı bir
      karşı örnek). Dayanaklandırma kontrolleri belge metnine karşı çalışır
      (özellikle `tarih` için `_header_region`). Bu önemlidir: 23 elle
      etiketlenmiş gerçek belgeye karşı doğrudan ölçüldü, ayrıştırıcı bu
      değerlerin bazılarına yapısal olarak hiç ulaşamıyor -- muhatap
      yönelme ekli bir kurum değil de isimlendirilmiş bir kişi olduğunda
      `muhatap` ("Sayın Ceylan AKÇA CUPOLO"), "T.C." antet satırı olmayan bir
      `gonderen_kurum` -- oysa model aynı ölçümde bunları her seferinde
      doğru okuyor. Toptan atma bunları sessizce sahte "eksik bilgi"
      bulgularına dönüştürüyordu.
    * `_EVIDENCE_RESCUABLE_FIELD`'in dışındaki bir alan için (o kümenin
      kendi docstring'ine nedenine bakın), ve `document_text` verilmediğinde
      herhangi bir alan için atma koşulsuz kalır -- onu geçmeyen her mevcut
      çağıran, bugünkü katı davranışı tam olarak korur.

    Yönetmelik bu alanların nasıl göründüğünü öngörür, bu yüzden eksik bir
    etiketin dayanaklı bir model değeriyle birlikte olmaması alanın gerçekten
    yok olduğu anlamına gelir -- ve yine de onu dolduran bir model, eksik bir
    belgeyi görünüşte uygun bir belgeye çevirir ve bu hattın raporlamak için
    var olduğu eksikliği gizler. Orijinal, hâlâ geçerli örnek: modelin, hiç
    muhatabı olmayan bir mektup için "İLGİLİ MAKAMA" stok muhatabını
    uydurması -- "İLGİLİ MAKAMA" böyle bir mektubun metninde bizzat dayanaklı
    değildir, bu yüzden tıpkı öncekiği gibi atılır.

    `AUTHORITATIVE_FIELD` dışındaki alanlar tam olarak modelin ürettiği gibi
    bırakılır, çünkü onlar için bulunamayan bir ayrıştırma "yok" değil
    "bilinmiyor" anlamına gelir.

    Args:
        model_fields: Modelin `EvrakField` dökümü.
        parsed: `parse_labelled_fields`'in çıktısı.
        document_text: Kanıt temelli kurtarma için çıkarılan belgenin tam
            metni. Ayrıştırılmamış her `AUTHORITATIVE_FIELD` değerinin
            koşulsuz olarak atılmasını korumak için atlanabilir (varsayılan,
            `""`).

    Returns:
        Birleştirilmiş alan eşlemesi.
    """
    merged = dict(model_fields)
    header_text = _header_region(document_text) if document_text else ""
    for name in AUTHORITATIVE_FIELD:
        if name in parsed:
            continue
        if document_text and name in _EVIDENCE_RESCUABLE_FIELD:
            value = model_fields.get(name)
            if not is_blank(value):
                haystack = header_text if name == "tarih" else document_text
                text_value = str(value)
                grounded = normalize_value(text_value) in normalize_value(haystack)
                if not grounded and name in _TOKEN_OVERLAP_ELIGIBLE_FIELD:
                    grounded = _token_overlap(text_value, haystack) >= TOKEN_OVERLAP_THRESHOLD
                if grounded:
                    # Dayanaklı: model değerini koru, zaten başlangıçtaki
                    # `dict(model_fields)` kopyasından `merged` içinde
                    # oturuyor.
                    continue
        merged[name] = [] if name in _LIST_FIELD else None
    merged.update(parsed)
    return merged


def format_parsed_fields(parsed: dict[str, Any]) -> str:
    """Zaten ayrıştırılmış alanları, model bunları atlasın diye bir prompt notu olarak sunar.

    Args:
        parsed: `parse_labelled_fields`'in çıktısı.

    Returns:
        Çözülen alanları listeleyen Türkçe bir not, veya boş bir string.
    """
    if not parsed:
        return ""
    listed = ", ".join(sorted(parsed))
    return (
        f"\n\nNot: Şu alanlar zaten okundu, bunlarla ilgilenme: {listed}. "
        "Yalnızca kalan alanlara odaklan."
    )


def parsed_or_none(parsed: dict[str, Any], name: str) -> Optional[Any]:
    """Varsa ayrıştırılmış bir değeri döndürür.

    Args:
        parsed: `parse_labelled_fields`'in çıktısı.
        name: Alan adı.

    Returns:
        Ayrıştırılmış değer veya None.
    """
    return parsed.get(name)
