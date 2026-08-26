"""Amaç çözümlemesi (intent resolution) için deklaratif kanıt kuralları.

Bir mesajın karşı puanlandığı kurallar, puanlamanın kendisinden ayrı tutulur;
böylece yeni bir ifade eklemek, kontrol akışına dokunmayan salt bir veri
değişikliği olur.

Bu yapının sıralı anahtar kelime zincirinin yerini almasının nedeni
-------------------------------------------------------------------
Önceki çözümleyici, anahtar kelime gruplarını sabit bir sırayla kontrol edip
ilk eşleşmede sonucu döndürüyordu. Bu, kararı *sıraya* bağlar ve bu sorun
sırayı değiştirerek düzeltilemez: draft önce kontrol edilirse "Resmi yazı ne
demek?" bir taslak hazırlama akışı başlatır; analyze önce kontrol edilirse
"analiz sonrası taslak hazırla" bu kez analiz olarak çözümlenir. Ölçülen
başlangıç durumunda `inversion` skoru 0.00 çıktı -- sekiz vakadan sekizi de
`source=keyword` ile `draft`'a düşüyordu.

Puanlama bunu çözer çünkü kanıtlar kısa devre yapmak yerine birikir. Hem bir
taslak ifadesi hem de bir analiz ifadesi taşıyan bir mesaj, karşılaştırılabilir
iki skorla ve küçük bir farkla sonuçlanır; küçük fark da bir bilgidir: "bunlar
birbirine yakın" demektir, bu da ya bileşik bir istektir ya da üst seviyeye
taşınması gereken bir durumdur.

Ölçülen diğer başarısızlık olan `precedence` (0.00), aynı köke sahiptir:
selamlama kuralı ``document_id is None`` koşuluna bağlıydı, bu yüzden bir
belge ekliyken "Merhaba" tüm dallardan geçip hiçbirine takılmıyordu (abstain).
Burada belge durumu her zaman bir *ağırlık*tır, asla bir kapı (gate) değildir
-- ``requires_document`` yalnızca gerçekten belgesiz uygulanamayacak kurallar
için vardır (bir belgenin içeriği hakkında soru sormak gibi) ve selamlamalar
bunu kullanmaz.
"""

from dataclasses import dataclass
from typing import Literal, Optional

Intent = Literal["draft", "analyze", "assist", "revise"]

RuleKind = Literal["phrase", "structural"]


@dataclass(frozen=True)
class EvidenceRule:
    """Bir amaç (intent) için tek bir kanıt parçası.

    Attributes:
        id: Kararlı (stable) tanımlayıcı; her kararda raporlanır, böylece
            üretimdeki bir sonuç, onu tetikleyen kurala kadar izlenebilir.
        intent: Bu kanıtın lehine olduğu amaç.
        weight: Ne kadar güçlü olduğu. Kural başına değil, katman (tier)
            bazında kalibre edilir -- aşağıdaki ağırlık sabitlerine bakın.
        surfaces: Bunu tetikleyen normalize edilmiş ifadeler (ASCII'ye
            dönüştürülmüş, küçük harfli).
        requires_document: True ise kural yalnızca bir belge ekliyken
            uygulanır; False ise yalnızca belge yokken; None ise belge
            durumu önemsizdir. Az kullanılır -- burada bir kapı (gate)
            olması selamlama akışını bozan şeydi.
        requires_active_draft: `requires_document` ile aynı mekanizma, ancak
            `SessionFocus.active_draft` üzerinden kapılanır. Yalnızca
            `revise` bunu kullanır -- "kısalt" tek başına puanlandığında,
            kısaltılacak açık bir taslak olmadan bir anlam ifade etmeyecek
            kadar geneldir.
    """

    id: str
    intent: Intent
    weight: float
    surfaces: tuple[str, ...] = ()
    kind: RuleKind = "phrase"
    requires_document: Optional[bool] = None
    requires_active_draft: Optional[bool] = None


#: Belirsizliğe yer bırakmayan bir emir kipi: kullanıcı o şeyin kendisini
#: istiyor, onun hakkında değil.
WEIGHT_EXPLICIT = 3.0
#: Bir amaca işaret eden ama o amaç *hakkında* sorulan sorularda da geçen bir
#: alan ifadesi ("üst yazı ne demek"). Tek başına kazanacak kadar güçlü,
#: rakip bir sinyalle alt edilebilecek kadar zayıf.
WEIGHT_DOMAIN = 1.6
#: Bağlamsal bir ipucu: cümle yapısı, mesaj uzunluğu, önceki tur.
WEIGHT_HINT = 1.0
#: Bir amacın lehine değil, aleyhine olan bir karşıt sinyal. Açık bir ifade
#: ile bir alan ismini birlikte (3.0 + 1.6) alt edecek şekilde boyutlandırıldı,
#: çünkü "Taslak oluşturma süreci nasıl işliyor?" ikisiyle de eşleşir --
#: "taslak olustur" alt dizesi "taslak oluşturma" içinde geçer -- ama yine de
#: bir şey taslamak için bir istek değildir.
WEIGHT_COUNTER = -4.8


DRAFT_RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        id="draft.explicit_request",
        intent="draft",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "taslak hazirla", "taslak olustur", "taslak cikar", "taslagi hazirla",
            "yazi yaz", "yazi hazirla", "yazi olustur", "yaziyi hazirla",
            "cevap yaz", "cevap hazirla", "cevabi hazirla", "cevap olustur",
            "cevap yazisi olustur", "cevabini yaz", "cevabini hazirla",
            "yanit yaz", "yanit hazirla", "yanitini hazirla",
            "kaleme al", "metni yaz", "metni olustur",
            "metni uret", "metnini uret", "yazisma hazirla", "yazisma kurgula",
            "dilekceye cevap", "yaziya dok", "kaleme alinmasini",
            "kurgular misin", "tanzim et", "mukabelede bulun",
            "mukabele metni", "mukabele hazirla", "bildirim yapacak bir yazisma",
            "yazi cikar", "cevabi yaz",
            # Şartname dışı dört CorrespondenceType değerinin dışında kalan
            # belirli bir belge türü (bkz. app.ai.workflows.correspondence
            # modülünün GENRE_SURFACES'i) -- bunlar önceden daha zayıf, genel
            # ipuçlarına (ya da hiçbirine) düşüyor ve `draft`'a çözümlenmek
            # yerine rakip bir amaca kaybedebiliyordu.
            "dilekce yaz", "dilekce hazirla", "dilekcesi yaz", "dilekce olustur",
            "itiraz et", "basvuru yaz", "tutanak tut",
        ),
    ),
    EvidenceRule(
        id="draft.domain_noun",
        intent="draft",
        weight=WEIGHT_DOMAIN,
        surfaces=(
            "taslak", "ust yazi", "resmi yazi", "bilgilendirme metni",
            "cevap yazisi", "tebligat metni", "muzekkere", "tezkere", "mukabele",
            "dilekce", "itiraz dilekcesi", "muvafakatname", "taahhutname", "tutanak",
            "olur yazisi",
        ),
    ),
    #: "metni düzenle"/"cevabı düzenle" metni *düzenlemek/tertip etmek*
    #: anlamına gelir; bu da yalnızca düzenlenecek henüz açık bir şey yokken
    #: yeni bir taslak isteği olarak okunur. `draft.explicit_request`'ten
    #: ayrılmıştır ve bir taslak var olduğunda tetiklenmemesi için
    #: kapılanmıştır -- aşağıdaki `revise.arrange_request` bunun ayna
    #: görüntüsüdür. Bu ayrım olmadan, "Az önce yazdığın metni düzenler
    #: misin?" (bir revizyon isteği) bu kuralı tam ağırlıkla puanlıyor ve
    #: mesaj `revise` yerine yeni bir `draft`'a çözümleniyordu.
    EvidenceRule(
        id="draft.arrange_request",
        intent="draft",
        weight=WEIGHT_EXPLICIT,
        surfaces=("metni duzenle", "duzenlemeni", "cevabi duzenle", "cevabini duzenle"),
        requires_active_draft=False,
    ),
)

#: Aktif bir taslağa kapılanmıştır (bkz. `EvidenceRule.requires_active_draft`):
#: yalnızca `SessionFocus.active_draft is not None` iken puanlanır; bu da
#: "kısalt" ya da "daha resmi yap" gibi tek başına genel olan kısa ifadelerin,
#: başka hiçbir şeyle çakışmadan güçlü bir kanıt sayılmasını sağlar -- bir
#: taslak zaten açıkken bunların makul olarak başka bir anlamı olamaz.
REVISE_RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        id="revise.explicit_request",
        intent="revise",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "revize et", "taslagi revize et", "revizyon yap", "tekrar duzenle",
            "yeniden yaz", "tekrar yaz", "taslagi guncelle", "taslagi degistir",
            "metni degistir", "duzeltir misin", "tekrar duzenler misin",
            "daha resmi yap", "daha resmi olsun", "daha samimi yap",
            "daha kisa yap", "kisa tut", "kisalt", "uzat", "sadelestir",
            "tonunu degistir", "uslubunu degistir", "bu kismi degistir",
            "su kismi degistir", "paragrafi degistir", "cumleyi degistir",
            "imzayi degistir", "konuyu degistir",
            # "az önce yazdığın X", assist.memory_recall'ın "az once" ifadesiyle
            # çakışır ("ne konuştuk" anlamına gelir, "az önce ürettiğin şey"
            # değil) -- bu daha uzun ve daha spesifik ifadeler onunla birlikte
            # tetiklenir ve toplamı açıkça kazanacak şekilde ağırlıklandırılır;
            # "az once"un kendisini bağlam-duyarlı yapmaya çalışmak yerine.
            "yazdigin metni", "yazdigin taslagi", "yazdigin yaziyi",
            "yazdigin cevabi", "az once yazdigin", "biraz once yazdigin",
            # Genel bir fiil yerine, açık bir taslağın kendi yüzeylerine
            # yönelik hedefli düzenlemeler (bir ekleme, bir ton değişikliği,
            # bölüme özel bir şikayet) -- önceden hiç görülmemişti, bu yüzden
            # bunlardan herhangi birinin dört kelimelik bir örneği ("giriş
            # kısmını yumuşat") puanlanacak tek şey olarak
            # `assist.short_message`'ın kısalık ipucuna sahipti ve kısalık tek
            # başına, puanlanmamış bir revise okumasını rutin olarak alt
            # ediyordu.
            "sonuna ekle", "sonuna bir", "imza blogu", "sert geldi",
            "yumusat", "resmilestir", "farkli ele al", "biraz farkli ele",
            # Belirli "değiştir" fiili gerekmeden, kapanışın salt anılması --
            # "kapanışı değiştir" zaten kapsanıyordu, ama "kapanışı 'X' yap"/
            # "kapanışı X olsun" (aynı istek, farklı bir fiil) eşleşecek
            # hiçbir şeye sahip değildi ve semantik katman kullanılamazken
            # sessizce "revise" yerine "draft"a düşüyordu. Yukarıdaki
            # "kısalt"/"uzat"/"yumusat" için zaten kullanılan aynı çıplak
            # kelime deyimi -- aktif bir taslağa kapılanmış durumda,
            # "kapanış"ın makul olarak başka bir anlamı olamaz.
            "kapanisi",
        ),
        requires_active_draft=True,
    ),
    #: `draft.arrange_request`'in aynası -- aynı yüzeyler, ters kapı.
    #: Zaten bir taslak açıkken "Metni düzenler misin?" *o* taslağı düzenlemek
    #: demektir, yeni bir tane yazmak değil.
    EvidenceRule(
        id="revise.arrange_request",
        intent="revise",
        weight=WEIGHT_EXPLICIT,
        surfaces=("metni duzenle", "duzenlemeni", "cevabi duzenle", "cevabini duzenle"),
        requires_active_draft=True,
    ),
    #: (Aşağıdaki) `analyze.review_request`'in aynası -- bir taslak açıkken
    #: "gözden geçir" "taslağı gözden geçir/revize et" olarak okunur,
    #: "belgeyi analiz et" değil. Aynı yüzey, ters kapı.
    EvidenceRule(
        id="revise.review_request",
        intent="revise",
        weight=WEIGHT_EXPLICIT,
        surfaces=("gozden gecir",),
        requires_active_draft=True,
    ),
)

ANALYZE_RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        id="analyze.explicit_request",
        intent="analyze",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "analiz et", "incele", "inceleyip", "siniflandir", "turunu belirle",
            "ozetle", "ozet cikar", "degerlendir", "kontrol et", "denetle",
            "irdele", "tespit et", "tespit etmeni",
            "uygunlugunu", "uygunluk denetimi", "mevzuata uygun", "kurallara uy",
            "eksik alan", "eksik bilgi", "eksiklikleri", "bir bak",
            "olup olmadigina", "hangi kategoriye", "bulgularini raporla",
        ),
    ),
    EvidenceRule(
        id="analyze.domain_noun",
        intent="analyze",
        weight=WEIGHT_DOMAIN,
        surfaces=("uygunluk", "evrak analizi", "belge analizi"),
    ),
    #: "gözden geçir", "bu belgeyi analiz et" ile "bu taslağı revize et"
    #: arasında belirsizdir -- bkz. `revise.review_request`'in aynası.
    #: Ayrılmış ve yalnızca yerine revize edilecek açık bir şey yokken
    #: `analyze` lehine olacak şekilde kapılanmıştır.
    EvidenceRule(
        id="analyze.review_request",
        intent="analyze",
        weight=WEIGHT_EXPLICIT,
        surfaces=("gozden gecir",),
        requires_active_draft=False,
    ),
)

#: `chat` ve `document_qa` eskiden ayrı, her biri kendi skor grubuna sahip iki
#: farklı amaçtı ve bu modülün geçmişinin bir kısmı sadece ikisi arasında
#: hakemlik yapan kurallardan oluşuyordu: bir hafıza-hatırlama sorusu bir
#: belge sorusunu yenmeliydi, kibarca ifade edilmiş bir istek bir içerik
#: sorgusu olarak okunmamalıydı. İkisi de artık aynı `assist` grubuna
#: çözümleniyor (konuşma tarzında cevap veren ve gerektiğinde kendi retrieval
#: araçlarına uzanan tek bir ajan), bu yüzden hakemlik yapılacak bir şey
#: kalmadı -- her iki okumanın kanıtı da yarışmak yerine aynı skorda basitçe
#: birikir. Yalnızca aşağıdaki, salt beraberlik-bozucu (tie-breaker) olan iki
#: kural (birleşme öncesi sürümde `document_qa.request_softener_counter`,
#: `document_qa.memory_recall_counter`) kaldırıldı; gerçek pozitif kanıt
#: sağlayan her kural, `assist` altında yeniden adlandırılarak yaşamaya devam
#: ediyor.
ASSIST_RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        id="assist.greeting",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "merhaba", "selam", "gunaydin", "iyi gunler", "iyi aksamlar",
            "iyi calismalar", "gorusuruz", "hosca kal", "kolay gelsin",
        ),
    ),
    EvidenceRule(
        id="assist.courtesy",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "tesekkur", "tesekkurler", "sagol", "sag ol", "eyvallah",
            "cok iyi oldu", "yardimci oldun",
        ),
    ),
    #: Bir vedalaşma, bir devam etme değil -- "yarın devam ederiz" içinde
    #: "devam" geçer (bir `CONTINUATION_SURFACES` girdisi) ama şu an devam
    #: etmeyi kabul etmenin tam tersi anlamına gelir. `assist.greeting`/
    #: `assist.courtesy`'den farklıdır çünkü onlar *bu* turun kendi içeriği
    #: hakkındadır; bu kural özellikle `intent_scorer.score_intents`
    #: içindeki continuation kuralının `signing_off` korumasınca kontrol
    #: edilmek üzere var.
    EvidenceRule(
        id="assist.farewell",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "yarin devam", "sonra devam ederiz", "sonra bakariz",
            "simdilik bu kadar", "yarin bakariz", "simdilik yeterli",
            "gorusmek uzere", "bu kadar yeterli",
        ),
    ),
    EvidenceRule(
        id="assist.about_the_assistant",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "nasilsin", "kimsin", "sen kimsin", "ne yapabilirsin",
            "neler yapabilirsin", "nasil calisir", "nasil calisiyor",
            "yardim eder misin", "ne ise yarar",
        ),
    ),
    #: `inversion`i çözülebilir kılan karşıt sinyal. Bu ifadeler, bir mesajı
    #: bir kavramı üretme isteği yerine o kavram *hakkında* olarak
    #: işaretler: "ne demek", "fark nedir", "hangi durumlarda kullanilir".
    #: Ateşlenen hangi alan ismi olursa olsun ondan düşülür, böylece "Üst
    #: yazı ne demek?" diğer her durum için taslak ifadelerinin
    #: zayıflatılması gerekmeden `assist`e düşer.
    #:
    #: Yalın "açıklar mısın" / "anlatır mısın" ifadeleri de bir açıklama
    #: istemenin her zaman bir kavram hakkında olduğu varsayımıyla eskiden
    #: burada listeleniyordu. Bu doğru değil: "Şu belgeye bakıp durumu
    #: anlatır mısın?" aynı şeyi, ekli belirli bir belge hakkında sorar; bu
    #: bir analiz isteğidir, tanımsal (definitional) bir istek değil.
    #: Kaldırıldı -- bu ifadelerden herhangi birini kullanan mevcut her
    #: vaka, kendi tanımsal işaretini de taşıyor ("ne demek", "nasıl
    #: çalışır") ve bu olmadan da doğru çözümlenmeye devam ediyor.
    EvidenceRule(
        id="assist.definitional_question",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            # Bare "nedir" is deliberately absent: "Evrakın konusu nedir?" is a
            # question about a document's contents, not about a concept.
            "ne demek", "ne anlama", "fark nedir", "farki nedir",
            "arasindaki fark", "hangi durumlarda", "ne zaman kullanilir",
            "nasil isliyor", "nasil yapilir", "ne dusunuyorsun",
            "ornegi nedir",
        ),
    ),
    #: Yalnızca bir belge ekliyken anlamlıdır; bir belgenin ne dediğini sormak,
    #: okunacak hiçbir şeyi olmayan bir mesajın makul bir okuması değildir.
    #: İyelikler ("belgenin", "evrakın") bilinçli olarak yoktur: bunlar analiz
    #: isteklerinde de aynı sıklıkta geçer ("Belgenin hangi kategoriye
    #: girdiğini tespit et") ve bu kuralın orada analyze'yi geçmesine yol
    #: açardı.
    EvidenceRule(
        id="assist.about_the_document",
        intent="assist",
        weight=WEIGHT_DOMAIN,
        surfaces=(
            "bu belgede", "belgede", "evrakta", "bu evrak", "bu yazi",
            "belgeyi kim", "talep edilen", "yazi kime", "belgede gizlilik",
        ),
        requires_document=True,
    ),
    #: "Taslağı ilet"/"evrakı gönder" bir çıktıyı (artifact) birine iletmeyi
    #: ister -- `assist`, adımı modele `propose_transfer` aracını sunan tek
    #: amaçtır (bkz. app.ai.tools.transfer_tools ve `_run_assist`'in kendi
    #: `AI_TRANSFER_ENABLED` kapısı), bu yüzden bir iletme isteğinin `revise`
    #: yerine burada çözümlenmesi gerekir. Ele alınmazsa, yalın bir "taslağı
    #: ilet" hiçbir kuralı tetiklemez -- REVISE_RULES'da "ilet"/"gönder"
    #: yüzeyi yoktur, `assist.short_message` bir taslak açıkken bilinçli
    #: olarak devre dışı bırakılmıştır (kendi yorumuna bakın) -- bu yüzden
    #: mesaj sıfır sözlüksel kanıtla semantik/model yedek katmanına ulaşıyor
    #: ve bu katmanlar da onu yalnızca ortak "taslak" kelimesinden yola
    #: çıkarak sürekli `revise`'a çözümleyip, kullanıcının aslında istediği
    #: iletim onayı yerine sessizce bir revizyon turu açıyordu.
    #:
    #: Bilinçli olarak alıcı ("birime", "kuruma", "makama") yerine çıktı
    #: ismine ("taslağı"/"evrakı"/"belgeyi") çapalanmıştır: `_compile_surface`
    #: yalnızca sol sınırı kontrol eder, bu yüzden "birime ilet" gibi
    #: alıcı-çapalı bir yüzey "birime iletilecek" içinde de eşleşirdi --
    #: edilgen/gelecek ortacı (participle), `pdraft_06`'nın kendi taslak
    #: isteğinde ("İlgili birime iletilecek bir tezkere düzenlemeni
    #: istiyorum") *yeni* bir belgenin alıcısını tanımlamak için kullanılır,
    #: bir iletme komutu değil. Bu kod tabanındaki hiçbir taslak ifadesi çıktı
    #: ismini doğrudan bu ortacın önüne koymaz, bu yüzden oraya çapalamak
    #: çakışmayı önler.
    EvidenceRule(
        id="assist.transfer_request",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "taslagi ilet", "taslagi gonder", "taslagi yolla", "taslagi paylas",
            "evraki ilet", "evraki gonder", "evraki yolla", "evraki paylas",
            "belgeyi ilet", "belgeyi gonder", "belgeyi yolla", "belgeyi paylas",
            "kime iletebilirim", "kime gonderebilirim", "kime iletirim", "kime gonderirim",
        ),
    ),
)

#: Bir mesajı *bu konuşmanın kendi geçmişi* hakkında yapan ifadeler. Kendi
#: katmanı olarak tutulur çünkü bir hatırlama sorusu, mesaj başka ne
#: içerirse içersin `assist`e (sınırsız geçmiş erişimi) ulaşmalıdır -- bir
#: belgenin ekli olması, konuşma hakkındaki bir soruyu asla belge hakkında
#: bir soruya çevirmemelidir.
MEMORY_RECALL_RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        id="assist.memory_recall",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "az once", "biraz once", "az evvel", "biraz evvel", "demin",
            "evvelce", "evvelki", "gecen sefer", "daha once", "onceki", "onceki mesaj",
            "onceki turda", "onceki sorumda", "ilk mesajimda", "ilk talebi",
            "demistim", "dedim mi", "demis miydim", "soylemis miydim",
            "sormus muydum", "sordum mu", "sordugum", "sorduğum soruyu",
            "hatirliyor musun", "hatirliyor musunuz", "animsiyor musun",
            "hatirla", "yukarida ne dedim", "yukarida ne yazdim",
            "yukarida bahsettigim", "bu konusmada", "bu sohbette",
            "bu diyalogda", "sohbetimizin basinda", "buraya kadar",
            "sana ne sordum", "sana ne demistim", "en son ne sordum",
            "en son sana ne", "konusma gecmisi", "konusma gecmisimizi",
            "gecmis mesajlarda", "neler konustugumuzu", "ne konusmustuk",
            "konustugumuz konuyu", "bahsetmistim", "bahsettim",
            "vermistim", "verdigin cevabi", "tekrar eder misin",
            "tekrarlayabilir misin",
        ),
    ),
)

#: Hem bir soruya benzeyen hem de ekli bir belgesi olan bir mesaj, yukarıdaki
#: sözlüksel yüzeylerden hiçbiriyle eşleşmese bile `assist` için bir kanıttır
#: (ör. "Evrakın konusu nedir?") -- bkz. `intent_scorer.score_intents`'in
#: yapısal `assist.question_with_document` kuralı; bu, sözlüksel bir yüzey
#: kuralı olmadığı için bu tabloda yer almaz.
ALL_RULES: tuple[EvidenceRule, ...] = (
    *DRAFT_RULES,
    *REVISE_RULES,
    *ANALYZE_RULES,
    *ASSIST_RULES,
    *MEMORY_RECALL_RULES,
)

#: Kısa bir onay ifadesi, önceki turun konusu her ne ise onu sürdürür.
#: "peki" bilinçli olarak yoktur: bu ifade onaylamak kadar soru da açar
#: ("peki sence bu yeterli mi") ve buradaki diğerlerinin aksine tek başına
#: makul bir tek kelimelik yanıt değildir -- anlam kazanması için ardından
#: gelene ihtiyaç duyar; bunu da bu tablonun denemesi yerine zaten
#: `score_intents`'in `looks_like_question` koruması ayrıca kontrol eder.
CONTINUATION_SURFACES: tuple[str, ...] = (
    "evet", "olur", "tamam", "tamamdir", "onayliyorum", "onaylıyorum",
    "devam", "devam et", "devam edebilirsin", "hazirla", "yap", "lutfen",
    "elbette",
)

#: Sessizce devam etmek yalnızca bu amaçlar için mantıklıdır; bir chat veya
#: document_qa turundan sonra yalın bir "evet"in belirsizlik taşımayan bir
#: sonraki eylemi yoktur.
CONTINUABLE_INTENTS = frozenset({"draft", "analyze", "revise"})

#: Şu anda açık olan taslağın farklı ifade edilmesini istemek yerine onu
#: açıkça terk eden ifadeler -- bir taslak zaten açıkken "yeni bir taslak",
#: "bunu tekrar revize et" değil "farklı, alakasız bir tane" anlamına gelir.
#: ``app.ai.workflows.planning_graph``'in ``focus_node``'u tarafından,
#: ``app.ai.session.focus.ACTIVE_DRAFT_IDLE_LIMIT`` boşta bekleme
#: turlarını beklemek yerine ``SessionFocus.active_draft``'ı hemen
#: temizlemek için okunur -- bunu söyleyen bir kullanıcı boşta beklemiyor,
#: aktif olarak devam ediyordur.
RESET_SURFACES: tuple[str, ...] = (
    "yeni bir taslak", "yeni bir yazi", "yeni bir belge", "yeni bir cevap",
    "yeni taslak", "yeni yazi", "farkli bir yazi", "farkli bir taslak",
    "baska bir yazi", "baska bir taslak", "baska birine yazi",
    "bastan baslayalim", "en bastan baslayalim",
    "bu taslagi birak", "bunu birak", "vazgectim",
)

#: Soru işaretçileri; bir yönlendirme kararı olarak değil, bir şekil ipucu
#: olarak kullanılır. Yalın "ne" bilinçli olarak yoktur: "ne gerekiyorsa onu
#: uygula" bir soru değil bir talimattır ve bunu soru olarak ele almak,
#: yeterince tanımlanmamış bir komutun üst seviyeye taşınmak yerine belge
#: soru-cevabına çözümlenmesine yol açıyordu.
QUESTION_SURFACES: tuple[str, ...] = (
    "mi", "mu", "midir", "mudur", "neden", "nasil", "kim",
    "kimden", "kime", "kac", "hangi", "nerede", "nereye", "ne zaman",
    "var mi", "neydi", "nedir", "hangisiydi",
)
