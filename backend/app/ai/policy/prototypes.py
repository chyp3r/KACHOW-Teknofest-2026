"""Her karar sınıfının anlamsal olarak eşleştirildiği referans ifadeler.

``intent_rules`` içindeki sözcüksel kurallar yüzeyleri harfiyen eşleştirir, bu
yüzden yapıları gereği parafraza karşı kördürler: "cevap hazırla" demenin her
yeni yolu elle eklenmelidir ve ölçülen taban çizgisi, kimsenin listelemeyi
düşünmediği ifadelerde bütün kategorilerin başarısız olduğunu gösterdi. Bu
prototipler bunun anlamsal karşılığıdır -- her sınıf için alt dizeye göre değil
anlama göre karşılaştırılan bir avuç *örnek*.

Bunlar kural değil, örnektir. Eşleştirici hiçbir zaman tek başına bir
prototipe dayanarak karar vermez (bkz. ``semantic.prototype_matcher``): bir
isabet için hem yüksek bir benzerlik hem de bir sonrakine belirgin bir fark
gerekir, çünkü "gömme benzerliği öyle dedi" gerekçesi "kullanıcı gerçekten
'taslak hazırla' yazdı" gerekçesinden çok daha zayıftır. Sözcüksel katman hızlı
yol olmaya devam eder; bu katman yalnızca o katmanın çekimser kaldığı yerde
çalışır.

Prototip *vektörleri*, ``scripts/build_prototypes.py`` tarafından
``datasets/prototypes/`` içine önceden hesaplanır. İstek anında kullanıcının
kendi mesajı dışında burada hiçbir şey gömülmez (embed edilmez).
"""

from typing import Mapping

__all__ = ["PROTOTYPES", "FAMILIES", "prototype_texts"]

#: Aile -> etiket -> örnek ifadeler.
#:
#: İfadeler, sözcüksel yüzeyleri yinelemek yerine onlardan *farklı* olacak
#: şekilde seçilir. Kural tablosunun zaten eşleştirdiği bir ifadeyi tekrar
#: eden bir prototip hiçbir şey katmaz: o mesaj bu katmana asla ulaşmaz.
PROTOTYPES: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "intent": {
        "draft": (
            "Bu evraka resmî bir cevap metni hazırla.",
            "Gelen yazıya karşılık verecek bir yazışma kaleme al.",
            "Kuruma iletilecek bir tebligat metni düzenle.",
            "Vatandaşa dönüş yapacak resmî bir metin kurgula.",
            "Bu başvuruya mukabelede bulunacak yazıyı oluştur.",
        ),
        "analyze": (
            "Bu evrakı inceleyip bulgularını raporla.",
            "Belgenin usule uygunluğunu değerlendir.",
            "Evraktaki eksik unsurları tespit et.",
            "Bu belgenin hangi türe girdiğini belirle.",
            "Evrakı gözden geçirip özetini çıkar.",
        ),
        "assist": (
            "Bu belgede hangi bilgi geçiyor?",
            "Evrakın içeriğinde ne yazıyor?",
            "Belgede adı geçen kurum hangisi?",
            "Yazıda belirtilen süre ne kadar?",
            "Bu evrakta kimin imzası var?",
            "Merhaba, nasılsın?",
            "Bu sistem ne işe yarıyor?",
            "Resmî yazışma kuralları hakkında genel bilgi verir misin?",
            "Teşekkür ederim, çok yardımcı oldun.",
            "Daha önce ne konuşmuştuk, hatırlıyor musun?",
        ),
        #: `revise` niyetinin sözcüksel kurallarıyla birlikte eklendi (bkz.
        #: `intent_rules.REVISE_RULES`, tümü aktif bir taslak koşuluna
        #: bağlıdır). Bu yüzeylerin yeniden ifadesi değil, onlardan farklı
        #: ifadeler olacak şekilde seçildi -- eşleşen bir yüzeyi tekrar eden
        #: bir prototip bu katmana hiç ulaşmaz (bkz. bu modülün kendi
        #: docstring'i).
        "revise": (
            "Bu taslağın tonunu biraz yumuşatır mısın?",
            "Son paragrafı tekrar ele alalım.",
            "Yazıyı biraz daha resmî bir üsluba çevir.",
            "Az önceki metni gözden geçirip düzelt.",
            "Bu bölümü farklı bir şekilde ifade edelim.",
        ),
    },
    "correspondence_type": {
        "cover_letter": (
            "Ekteki belgeyi ilgili makama gönderen bir üst yazı.",
            "İletilen dayanak belgeyi ve beklenen işlemi bildiren yazı.",
        ),
        "response_letter": (
            "Gelen talebe doğrudan cevap veren resmî yazı.",
            "Başvuruda sorulan hususu karşılayan mukabele yazısı.",
        ),
        "information_notice": (
            "Bir konuda tarafsız bilgi aktaran duyuru metni.",
            "Personeli veya vatandaşı bilgilendiren açıklama yazısı.",
        ),
        "other_official": (
            "Türü net olmayan genel bir resmî yazışma.",
            "Kurum içi serbest formatlı resmî metin.",
        ),
    },
}

#: Eşleştiricinin bildiği aileler.
FAMILIES: tuple[str, ...] = tuple(PROTOTYPES)


def prototype_texts(family: str) -> list[tuple[str, str]]:
    """Bir aileyi kararlı bir sırayla ``(etiket, metin)`` çiftlerine düzleştirir.

    Args:
        family: Ailenin adı.

    Returns:
        Her prototip ifadesi, temsil ettiği etiketle birlikte, önceden
        hesaplanmış vektör dosyasının tekrar üretilebilir olmasını sağlayacak
        şekilde sıralanmış olarak.

    Raises:
        KeyError: Bilinmeyen bir aile için.
    """
    labels = PROTOTYPES[family]
    return [
        (label, text)
        for label in sorted(labels)
        for text in labels[label]
    ]
