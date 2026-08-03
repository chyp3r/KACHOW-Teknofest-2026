import os
import random
from pathlib import Path
from fpdf import FPDF
from fpdf.enums import XPos, YPos

BASE_DIR = Path(__file__).parent.parent / "datasets" / "resmi_yazisma" / "00_gelen_kaynaklar" / "pdf"
BASE_DIR.mkdir(parents=True, exist_ok=True)

NAMES = [
    "Ahmet Yılmaz", "Mehmet Öztürk", "Ayşe Demir", "Fatma Kaya", "Mustafa Çelik",
    "Elif Aydın", "Burak Şahin", "Cemre Yıldız", "Hasan Arslan", "Zeynep Koç",
    "Ali Erdoğan", "Selin Güneş", "Emre Taş", "Derya Aktaş", "Onur Yılmaz",
    "Gülşen Polat", "Serkan Doğan", "Merve Özdemir", "Cem Acar", "Esra Çalışkan"
]

ILLER = ["Ankara", "İstanbul", "İzmir", "Bursa", "Antalya", "Konya", "Adana", "Trabzon", "Eskişehir", "Kayseri"]
ILCELER = ["Çankaya", "Keçiören", "Kadıköy", "Bornova", "Nilüfer", "Muratpaşa", "Selçuklu", "Seyhan", "Ortahisar", "Kocasinan"]

def gen_fake_tc():
    return str(random.randint(10000000000, 99999999999))

def gen_fake_phone():
    return f"05{random.randint(30,55)} {random.randint(100,999)} {random.randint(10,99)} {random.randint(10,99)}"

def gen_fake_date():
    return f"{random.randint(1,28):02d}.{random.randint(1,12):02d}.{random.randint(2020,2025)}"

def gen_fake_sayi():
    return f"E-{random.randint(10000,99999)}-{random.randint(2020,2025)}/{random.randint(100000,999999)}"

# ========== KURUM BAZLI ICERIK SABLONLARI ==========

MEB_CONTENTS = [
    ("Öğretmen Atama ve Yer Değiştirme",
     "İlgi: (a) Millî Eğitim Bakanlığı Öğretmen Atama ve Yer Değiştirme Yönetmeliği\n\n"
     "Bakanlığımızca 2024-2025 eğitim öğretim yılı için yapılan öğretmen atama ve yer değiştirme "
     "işlemleri kapsamında, ilgi Yönetmelik hükümleri çerçevesinde {il} ili {ilce} ilçesinde görev yapan "
     "öğretmenlerin yer değiştirme başvuruları değerlendirilmiştir. Yapılan inceleme neticesinde "
     "{name} (TCKN: {tc}) adlı öğretmenin {il} İl Millî Eğitim Müdürlüğü bünyesindeki başvurusu "
     "uygun görülmüş olup, ilgili atama işleminin başlatılması hususunda gereğini arz ederim."),

    ("Müfredat Güncelleme Bildirimi",
     "İlgi: (a) 1739 sayılı Millî Eğitim Temel Kanunu (b) Talim ve Terbiye Kurulu Başkanlığı'nın {date} tarihli kararı\n\n"
     "Talim ve Terbiye Kurulu Başkanlığı'nın ilgi (b) kararı gereğince, {il} ilinde faaliyet gösteren "
     "ortaöğretim kurumlarında uygulanmakta olan Matematik ve Fen Bilimleri derslerine ait müfredat "
     "programlarının güncellenmesine karar verilmiştir. Güncellenen müfredat {date} tarihinden itibaren "
     "tüm devlet ve özel öğretim kurumlarında uygulanacaktır. Söz konusu değişikliklerin okul müdürlüklerine "
     "bildirilmesi ve gerekli hazırlıkların tamamlanması hususunda bilgilerinizi ve gereğini rica ederim."),

    ("Sınav Takvimi ve Uygulama Esasları",
     "İlgi: Ölçme, Değerlendirme ve Sınav Hizmetleri Genel Müdürlüğü'nün {date} tarihli yazısı\n\n"
     "2024-2025 eğitim öğretim yılına ait merkezi sınav takvimi ilgi yazı ile belirlenmiştir. "
     "Buna göre Liselere Geçiş Sınavı (LGS) birinci dönem sınavı {date} tarihinde, ikinci dönem sınavı ise "
     "bir sonraki ayda gerçekleştirilecektir. Sınav uygulamalarında görev alacak personelin belirlenmesi, "
     "sınav binalarının hazırlanması ve güvenlik tedbirlerinin alınması konularında {il} İl Millî Eğitim "
     "Müdürlüğü'nün gerekli koordinasyonu sağlaması hususunda gereği rica olunur."),

    ("Okul Öncesi Eğitim Yaygınlaştırma Projesi",
     "İlgi: (a) 2024/15 sayılı Genelge (b) Temel Eğitim Genel Müdürlüğü Proje Onay Yazısı\n\n"
     "Bakanlığımızın 'Her Çocuğa Okul Öncesi Eğitim' projesi kapsamında, {il} ili {ilce} ilçesinde "
     "bulunan anaokulu ve anasınıflarının kapasitelerinin artırılmasına yönelik çalışmalar başlatılmıştır. "
     "Proje dahilinde toplam {sayi} adet yeni derslik açılması, mevcut dersliklerden {sayi2} adedinin "
     "modernizasyonu ve {sayi3} adet oyun alanının yenilenmesi planlanmaktadır. İlçe Millî Eğitim "
     "Müdürlüğü'nün ihtiyaç analizini tamamlayarak Bakanlığımıza iletmesi rica olunur."),

    ("Öğrenci Disiplin İşleri Hakkında Üst Yazı",
     "İlgi: Millî Eğitim Bakanlığı Ortaöğretim Kurumları Yönetmeliği Madde 164\n\n"
     "{il} İl Millî Eğitim Müdürlüğü'ne bağlı {ilce} ilçesi sınırlarında bulunan ortaöğretim kurumlarında "
     "yaşanan disiplin olaylarına ilişkin raporlar incelenmiştir. {date} tarihli toplantıda alınan karara "
     "istinaden, ilgili öğrencilerin velilerine bilgilendirme yapılması ve rehberlik servislerinin "
     "devreye alınması uygun görülmüştür. {name} (TCKN: {tc}) adlı öğrenci velisinin Müdürlüğünüzce "
     "bilgilendirilmesi hususunda gereğini rica ederim."),

    ("Hizmetiçi Eğitim Faaliyetleri",
     "İlgi: Öğretmen Yetiştirme ve Geliştirme Genel Müdürlüğü'nün {date} tarih ve {sayi} sayılı yazısı\n\n"
     "{il} ili genelinde görev yapan branş öğretmenlerine yönelik 'Dijital Okuryazarlık ve Eğitim "
     "Teknolojileri' konulu hizmetiçi eğitim programı düzenlenecektir. Eğitim programı {date} ile "
     "sonraki hafta arasında toplam 40 saat olarak planlanmış olup, {il} Öğretmenevi'nde "
     "gerçekleştirilecektir. Katılımcı listesinin en geç 10 iş günü içinde Müdürlüğümüze "
     "bildirilmesi hususunda gereğini rica ederim."),

    ("Okul Güvenliği Tedbirleri",
     "İlgi: (a) İçişleri Bakanlığı'nın {date} tarihli Genelgesi (b) 2024/8 sayılı Valilik Oluru\n\n"
     "{il} ili {ilce} ilçesindeki eğitim kurumlarının güvenlik denetimi yapılmıştır. Denetim sonucunda "
     "toplam {sayi} okulda kamera sistemlerinin güncellenmesi, {sayi2} okulda acil çıkış planlarının "
     "yenilenmesi ve {sayi3} okulda yangın söndürme ekipmanlarının bakımının yapılması gerektiği "
     "tespit edilmiştir. Eksikliklerin en geç 30 gün içinde giderilmesi ve sonucun Müdürlüğümüze "
     "bildirilmesi hususunda gereğini önemle rica ederim."),
]

ISKI_CONTENTS = [
    ("Abone Sayaç Değişim Bildirimi",
     "İlgi: İSKİ Genel Müdürlüğü Abone İşleri Daire Başkanlığı'nın {date} tarihli yazısı\n\n"
     "{il} ili {ilce} ilçesi Mahallesi'nde ikamet eden {name} (TCKN: {tc}) adlı abonemize ait "
     "su sayacının periyodik değişim süresi dolmuş olup, 6 aylık okuma döneminde sayaçta ±%4'ün "
     "üzerinde sapma tespit edilmiştir. 2560 sayılı İSKİ Kanunu'nun 18. maddesi gereğince sayaç "
     "değişimi {date} tarihinde yapılacak olup, değişim esnasında yaklaşık 2 saat su kesintisi "
     "yaşanacaktır. Aboneye SMS ve yazılı bildirim yapılması hususunda gereğini arz ederim."),

    ("İçme Suyu Kalite Analiz Raporu",
     "İlgi: TS 266 İçme Suyu Standardı ve İnsani Tüketim Amaçlı Sular Hakkında Yönetmelik\n\n"
     "{il} ili su şebekesinde {date} tarihinde yapılan rutin kalite analizleri tamamlanmıştır. "
     "Toplam {sayi} noktadan alınan numunelerin fiziksel, kimyasal ve mikrobiyolojik parametreleri "
     "incelenmiş olup, pH değerleri 6.8-7.4 aralığında, klor konsantrasyonu 0.2-0.5 mg/L arasında, "
     "koliform bakteri sayısı ise 0/100 mL olarak ölçülmüştür. Tüm parametreler yürürlükteki mevzuata "
     "uygun bulunmuştur. Detaylı analiz raporu ekte sunulmaktadır."),

    ("Altyapı Yatırım Projesi İhale Duyurusu",
     "İlgi: 4734 sayılı Kamu İhale Kanunu Madde 19\n\n"
     "{il} ili {ilce} ilçesinde toplam {sayi} km uzunluğunda içme suyu isale hattının yenilenmesi "
     "işi açık ihale usulü ile ihaleye çıkarılmıştır. İşin tahmini bedeli {sayi2}.000.000 TL olup, "
     "ihale {date} tarihinde saat 10:00'da İSKİ Genel Müdürlüğü İhale Salonu'nda gerçekleştirilecektir. "
     "İhale dokümanı mesai saatleri içinde İSKİ Genel Müdürlüğü Satınalma Daire Başkanlığı'ndan "
     "temin edilebilir. İlgililere duyurulur."),

    ("Atık Su Arıtma Tesisi Kapasite Raporu",
     "İlgi: Çevre, Şehircilik ve İklim Değişikliği Bakanlığı'nın {date} tarihli yazısı\n\n"
     "{il} ili sınırları dahilindeki atık su arıtma tesislerinin 2024 yılı kapasite kullanım raporları "
     "hazırlanmıştır. Mevcut {sayi} adet arıtma tesisinin toplam kapasitesi günlük {sayi2} milyon m³ "
     "olup, fiili kullanım oranı %{sayi3} seviyesindedir. Nüfus artışı projeksiyonlarına göre 2030 "
     "yılına kadar ek kapasite ihtiyacı doğacağı öngörülmektedir. Yeni arıtma tesisi yatırım "
     "planlamasının başlatılması hususunda Yönetim Kurulu'nun bilgisine sunulur."),

    ("Kaçak Su Kullanımı Tespit Tutanağı",
     "İlgi: 2560 sayılı İSKİ Kanunu Madde 22 ve Su Tarifeler Yönetmeliği\n\n"
     "{date} tarihinde yapılan denetimde, {il} ili {ilce} ilçesi sınırlarında {name} "
     "(TCKN: {tc}) adına kayıtlı adreste kaçak su kullanımı tespit edilmiştir. Yapılan ölçüme göre "
     "şebekeye izinsiz bağlantı yapılarak tahmini {sayi} m³ su tüketildiği belirlenmiştir. "
     "İlgili Kanun uyarınca hesaplanan {sayi2} TL tutarındaki cezai işlem ve geriye dönük faturalandırma "
     "abonenin adresine tebliğ edilecektir. Gereğini arz ederim."),
]

SGK_CONTENTS = [
    ("Emeklilik Hizmet Birleştirme Kararı",
     "İlgi: 5510 sayılı Sosyal Sigortalar ve Genel Sağlık Sigortası Kanunu Madde 41\n\n"
     "{name} (TCKN: {tc}) adlı sigortalının farklı sosyal güvenlik kurumlarında geçen hizmet "
     "sürelerinin birleştirilmesi talebi incelenmiştir. SSK kapsamında {sayi} gün, Bağ-Kur "
     "kapsamında {sayi2} gün, Emekli Sandığı kapsamında {sayi3} gün olmak üzere toplam hizmet "
     "süresi hesaplanmıştır. 5510 sayılı Kanun'un geçici maddeleri uyarınca ilgilinin emeklilik "
     "koşullarını sağlayıp sağlamadığının değerlendirilmesi için Emeklilik Hizmetleri Genel "
     "Müdürlüğü'ne sevk edilmiştir."),

    ("İş Kazası Bildirim Tutanağı",
     "İlgi: 5510 sayılı Kanun Madde 13 ve İş Kazası ve Meslek Hastalığı Bildirim Tebliği\n\n"
     "{date} tarihinde {il} ili {ilce} ilçesinde faaliyet gösteren işyerinde (Sicil No: {sayi}) "
     "meydana gelen iş kazası İl Müdürlüğümüze bildirilmiştir. Kazada {name} (TCKN: {tc}) adlı "
     "sigortalı yaralanmış olup, {il} Devlet Hastanesi'nde tedavi altına alınmıştır. SGK müfettişlerince "
     "yapılan incelemede iş güvenliği mevzuatına aykırılıklar tespit edilmiş olup, işverene idari "
     "para cezası uygulanması ve iş yerinin denetlenmesi yönünde işlem başlatılmıştır."),

    ("Prim Borcu Yapılandırma Bildirimi",
     "İlgi: 7440 sayılı Yapılandırma Kanunu ve SGK Prim Tahsilat Yönetmeliği\n\n"
     "{name} (TCKN: {tc}) adlı işverenin {il} Sosyal Güvenlik İl Müdürlüğü kayıtlarında "
     "{sayi}.{sayi2} TL tutarında gecikmiş prim borcu bulunmaktadır. 7440 sayılı Kanun kapsamında "
     "yapılandırma başvurusu {date} tarihinde kabul edilmiş olup, borcun {sayi3} eşit taksitte "
     "ödenmesi uygun görülmüştür. İlk taksitin {date} tarihine kadar ödenmemesi halinde "
     "yapılandırmanın bozulacağı ve yasal takip başlatılacağı ilgiliye tebliğ edilmiştir."),

    ("Genel Sağlık Sigortası Tescil İşlemi",
     "İlgi: 5510 sayılı Kanun Madde 60 ve Genel Sağlık Sigortası İşlemleri Yönetmeliği\n\n"
     "{il} İl Müdürlüğümüze başvuran {name} (TCKN: {tc}) adlı vatandaşın gelir testi sonucu "
     "değerlendirilmiştir. Aile hekimliği kaydı, hane halkı gelir durumu ve taşınmaz bilgileri "
     "incelenmiş olup, kişi başına düşen aylık gelirin brüt asgari ücretin 1/3'ünden az olduğu "
     "tespit edilmiştir. Bu kapsamda ilgilinin genel sağlık sigortası priminin Hazine tarafından "
     "karşılanmasına karar verilmiştir. Tescil işlemi {date} tarihi itibarıyla geçerlidir."),

    ("Yurtdışı Borçlanma İşlemi",
     "İlgi: 3201 sayılı Yurt Dışında Bulunan Türk Vatandaşlarının Yurt Dışında Geçen Sürelerinin "
     "Sosyal Güvenlikleri Bakımından Değerlendirilmesi Hakkında Kanun\n\n"
     "{name} (TCKN: {tc}) adlı vatandaşın Almanya'da geçen {sayi} gün sigortalı hizmet süresinin "
     "3201 sayılı Kanun kapsamında borçlanma yoluyla değerlendirilmesi talebi incelenmiştir. "
     "Günlük {sayi2} TL üzerinden toplam {sayi3} TL borçlanma tutarı belirlenmiştir. Ödemenin "
     "3 ay içinde peşin veya taksitle yapılması gerekmektedir. Ödeme sonrasında hizmet süresi "
     "ilgilinin SGK sicil dosyasına işlenecektir."),
]

YOK_CONTENTS = [
    ("Akademik Kadro İlanı Onayı",
     "İlgi: 2547 sayılı Yükseköğretim Kanunu Madde 23, 25, 26\n\n"
     "{il} Üniversitesi Rektörlüğü'nün {date} tarih ve {sayi} sayılı yazısı ile talep edilen "
     "akademik kadro ilanı Kurulumuzca incelenmiştir. Üniversitenin Mühendislik Fakültesi Bilgisayar "
     "Mühendisliği Bölümü'ne ait 1 adet Profesör, 2 adet Doçent ve 3 adet Dr. Öğretim Üyesi kadrosu "
     "ilan talebinin ilgili mevzuat hükümlerine uygun olduğu tespit edilmiş ve onaylanmıştır. "
     "İlanın Resmî Gazete'de yayımlanmasını müteakip başvuru sürecinin başlatılması rica olunur."),

    ("Yatay Geçiş Kontenjanları Kararı",
     "İlgi: Yükseköğretim Kurumlarında Önlisans ve Lisans Düzeyindeki Programlar Arasında Geçiş, "
     "Çift Anadal, Yan Dal ile Kurumlar Arası Kredi Transferi Yapılması Esaslarına İlişkin Yönetmelik\n\n"
     "2024-2025 akademik yılı güz dönemi kurumlar arası yatay geçiş kontenjanları belirlenmiştir. "
     "{il} Üniversitesi'nin toplam {sayi} programı için açılan kontenjan sayıları ekte sunulmuştur. "
     "Başvurular {date} ile sonraki hafta arasında alınacak olup, değerlendirme AGNO sıralamasına "
     "göre yapılacaktır. Üniversite Senatolarının kontenjan onaylarını Kurulumza bildirmesi rica olunur."),

    ("Senato Kararı: Lisansüstü Eğitim Yönetmeliği Değişikliği",
     "İlgi: {il} Üniversitesi Senato Kararı Tarih: {date} Toplantı No: 2024/{sayi}\n\n"
     "Üniversite Senatosu'nun ilgi toplantısında, Lisansüstü Eğitim ve Öğretim Yönetmeliği'nin "
     "bazı maddelerinin değiştirilmesine karar verilmiştir. Değişiklik kapsamında; tez savunma "
     "jürisinin en az 5 üyeden oluşması, tez yazım süresinin doktora programları için 8 yarıyıla "
     "çıkarılması ve yabancı dil yeterlilik sınavının her yarıyıl başında düzenlenmesi kararlaştırılmıştır. "
     "Değişikliklerin Resmî Gazete'de yayımlanmasını müteakip yürürlüğe girmesi uygun görülmüştür."),

    ("Denklik Değerlendirme Kararı",
     "İlgi: Yurtdışı Yükseköğretim Diplomaları Tanıma ve Denklik Yönetmeliği\n\n"
     "{name} (TCKN: {tc}) adlı başvuru sahibinin yurtdışında almış olduğu diplomanın denklik "
     "değerlendirmesi tamamlanmıştır. Başvuru sahibi, {il} merkezli bir yükseköğretim kurumundan "
     "Bilgisayar Bilimleri alanında lisans diploması almış olup, müfredat karşılaştırması ve "
     "akreditasyon incelemesi sonucunda diplomanın Türkiye'deki lisans düzeyine denk olduğuna "
     "karar verilmiştir. Denklik belgesi {date} tarihinden itibaren geçerlidir."),

    ("Üniversite Kurma/Bölüm Açma Değerlendirmesi",
     "İlgi: 2547 sayılı Yükseköğretim Kanunu Ek Madde 178\n\n"
     "{il} ilinde kurulması planlanan vakıf üniversitesine ait fizibilite raporu Yükseköğretim "
     "Kurulu Başkanlığı'nca incelenmiştir. Başvuru dosyasında öngörülen kampüs alanı ({sayi} dönüm), "
     "öğretim üyesi kadrosu ({sayi2} kişi) ve başlangıç bütçesi ({sayi3} milyon TL) yeterli "
     "bulunmuştur. Ancak kütüphane ve laboratuvar altyapısının güçlendirilmesi talep edilmektedir. "
     "Eksikliklerin giderilerek dosyanın yeniden sunulması hususunda bilgi verilmesini rica ederim."),
]

BOTAS_CONTENTS = [
    ("Doğal Gaz Bağlantı Başvurusu Sonucu",
     "İlgi: 4646 sayılı Doğal Gaz Piyasası Kanunu ve Dağıtım Lisansı Yönetmeliği\n\n"
     "{il} ili {ilce} ilçesi sınırlarında {name} (TCKN: {tc}) adına kayıtlı taşınmaza doğal gaz "
     "bağlantı başvurusu değerlendirilmiştir. Yapılan teknik etüt sonucunda; bağlantı hattı "
     "uzunluğu {sayi} metre, servis regülatörü tipi ve basınç kademesi belirlenmiştir. Bağlantı "
     "bedeli {sayi2} TL olarak hesaplanmış olup, ödemenin {date} tarihine kadar yapılması "
     "halinde bağlantı işlemlerinin 15 iş günü içinde tamamlanacağı bildirilmiştir."),

    ("Boru Hattı Güzergah Kamulaştırma Kararı",
     "İlgi: 2942 sayılı Kamulaştırma Kanunu ve 4646 sayılı Doğal Gaz Piyasası Kanunu\n\n"
     "{il}-{ilce} doğal gaz iletim hattı projesi kapsamında toplam {sayi} km uzunluğundaki "
     "güzergah üzerinde kamulaştırma çalışmaları başlatılmıştır. Güzergah üzerindeki {sayi2} adet "
     "parselin kamulaştırma bedelleri Kıymet Takdir Komisyonu'nca belirlenmiş olup, arazi sahiplerine "
     "tebligat yapılmıştır. Kamulaştırma bedellerine itiraz süresi tebligattan itibaren 30 gündür. "
     "İtiraz edilmeyen parsellerde çalışmalara {date} tarihinde başlanacaktır."),

    ("Doğal Gaz Tarifeleri Güncelleme Bildirimi",
     "İlgi: EPDK'nın {date} tarih ve {sayi} sayılı Kurul Kararı\n\n"
     "Enerji Piyasası Düzenleme Kurumu'nun ilgi kararı gereğince, {il} ili sınırlarındaki konut "
     "ve sanayi abonelerine uygulanan doğal gaz tarifelerinde güncelleme yapılmıştır. Konut "
     "aboneleri için birim fiyat {sayi2} kuruş/m³, sanayi aboneleri için {sayi3} kuruş/m³ "
     "olarak belirlenmiştir. Yeni tarifeler {date} tarihinden itibaren geçerli olacaktır. "
     "Abonelere faturalandırma döneminde bilgilendirme yapılması rica olunur."),

    ("Gaz Kaçağı Tespit ve Bakım Raporu",
     "İlgi: Doğal Gaz İç Tesisat Yönetmeliği ve TS 7363 Standardı\n\n"
     "{date} tarihinde {il} ili {ilce} ilçesinde yapılan periyodik denetimde {name} (TCKN: {tc}) "
     "adına kayıtlı mesken iç tesisatında gaz kaçağı tespit edilmiştir. Yapılan ölçümde; "
     "mutfak hattında {sayi} ppm, sayaç bağlantısında {sayi2} ppm seviyesinde metan gazı "
     "konsantrasyonu belirlenmiştir. İlgili mevzuat gereğince gaz arzı kesilmiş, tamirat "
     "için yetkili firma görevlendirilmiştir. Tesisatın onarım sonrası basınç testi yapılacaktır."),

    ("LNG Terminali Kapasite Tahsis Bildirimi",
     "İlgi: BOTAŞ Genel Müdürlüğü İletim ve Depolama Daire Başkanlığı\n\n"
     "{il} LNG Terminalinin 2024-2025 kış dönemi kapasite tahsis tablosu hazırlanmıştır. "
     "Terminalin toplam yıllık kapasitesi {sayi} milyar m³ olup, {sayi2} adet ithalatçı firma "
     "ile slot tahsis anlaşmaları imzalanmıştır. Dönemsel doluluk oranı %{sayi3} seviyesinde "
     "olup, acil durum kapasitesi ayrılmıştır. Enerji arz güvenliği çerçevesinde terminal "
     "bakım programının revize edilmesi hususunda Yönetim Kurulu'nun bilgisine sunulur."),
]

BELEDIYE_CONTENTS = [
    ("İmar Planı Değişikliği Meclis Kararı",
     "İlgi: 3194 sayılı İmar Kanunu Madde 8 ve Mekânsal Planlar Yapım Yönetmeliği\n\n"
     "Belediye Meclisinin {date} tarih ve {sayi} sayılı kararı ile {il} ili {ilce} ilçesi "
     "sınırlarındaki {sayi2} ada {sayi3} parselde kayıtlı taşınmazın imar planı değişikliği "
     "talebi görüşülmüştür. Söz konusu parselin 'Konut Alanı'ndan 'Ticaret + Konut Alanı'na "
     "dönüştürülmesi talebi, İmar Komisyonu'nun olumlu raporu doğrultusunda oy birliği ile "
     "kabul edilmiştir. Plan değişikliği askı sürecine çıkarılacaktır."),

    ("Belediye Encümen Kararı: Ruhsatsız Yapı",
     "İlgi: 3194 sayılı İmar Kanunu Madde 32 ve 42\n\n"
     "{il} ili {ilce} ilçesinde {name} (TCKN: {tc}) adına kayıtlı taşınmazda yapılan denetimde "
     "ruhsatsız/ruhsat ve eklerine aykırı yapı tespit edilmiştir. İmar Kanunu'nun 32. maddesi "
     "gereğince mühürleme işlemi yapılmış ve 42. madde uyarınca {sayi} TL idari para cezası "
     "kesilmiştir. İlgilinin 30 gün içinde yapıyı ruhsata uygun hale getirmesi veya yıkımını "
     "gerçekleştirmesi, aksi halde belediyece yıkım işleminin başlatılacağı tebliğ edilmiştir."),

    ("Toplu Taşıma Güzergah Değişikliği Duyurusu",
     "İlgi: Belediye Meclisi {date} tarih ve {sayi} sayılı kararı\n\n"
     "{il} Büyükşehir Belediyesi Ulaşım Dairesi Başkanlığı'nca yapılan trafik etüdü sonucunda, "
     "{ilce} bölgesinde faaliyet gösteren {sayi2} numaralı otobüs hattının güzergah değişikliği "
     "uygun görülmüştür. Yeni güzergah {date} tarihinden itibaren uygulanacak olup, mevcut "
     "güzergahtaki {sayi3} adet durak kaldırılarak yerine yeni güzergah üzerinde belirlenen "
     "konumlara taşınacaktır. Vatandaşların bilgilendirilmesi amacıyla duyuru yapılması rica olunur."),

    ("Zabıta Müdürlüğü İşyeri Denetim Raporu",
     "İlgi: 1608 sayılı Umuru Belediyeye Müteallik Ahkâmı Cezaiye Kanunu ve Belediye Zabıta Yönetmeliği\n\n"
     "{date} tarihinde {il} ili {ilce} ilçesinde yapılan olağan denetimde, {name} (TCKN: {tc}) "
     "adına işletilen gıda satış yerinde hijyen kurallarına aykırılık tespit edilmiştir. "
     "İşyerinde son kullanma tarihi geçmiş {sayi} kalem ürün bulunmuş, soğuk zincir "
     "koşullarının sağlanmadığı ve personelin hijyen eğitim belgesinin bulunmadığı "
     "belirlenmiştir. İşletmeye {sayi2} TL para cezası uygulanmıştır."),

    ("Çevre Temizlik Vergisi Bilgilendirmesi",
     "İlgi: 2464 sayılı Belediye Gelirleri Kanunu Mükerrer Madde 44\n\n"
     "{il} ili {ilce} ilçesi sınırlarında faaliyet gösteren işletmelerin 2024 yılı Çevre Temizlik "
     "Vergisi (ÇTV) tahakkukları yapılmıştır. Toplam {sayi} işletmeye ait vergi tahakkukları "
     "{date} tarihinde tebliğ edilmiş olup, birinci taksit ödeme son tarihi Mart ayı sonudur. "
     "Vadesinde ödenmeyen borçlara 6183 sayılı Kanun uyarınca gecikme zammı uygulanacaktır. "
     "{name} (TCKN: {tc}) adlı mükellefin toplam {sayi2} TL borcu bulunmaktadır."),
]

# ========== PDF SINIFI ==========

class BasePDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font('Arial', '', r'C:\Windows\Fonts\arial.ttf')
        self.add_font('Arial', 'B', r'C:\Windows\Fonts\arialbd.ttf')
        self.add_font('Arial', 'I', r'C:\Windows\Fonts\ariali.ttf')

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Sayfa {self.page_no()}', border=0, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C')

class MebPDF(BasePDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'T.C.', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'MİLLÎ EĞİTİM BAKANLIĞI', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(5)

class IskiPDF(BasePDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'T.C. İSTANBUL BÜYÜKŞEHİR BELEDİYESİ', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'İSKİ - İSTANBUL SU VE KANALİZASYON İDARESİ', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(5)

class SgkPDF(BasePDF):
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'SOSYAL GÜVENLİK KURUMU', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        self.set_font('Arial', '', 10)
        self.cell(0, 5, 'Sigorta Primleri Genel Müdürlüğü', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        self.ln(5)

class YokPDF(BasePDF):
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'YÜKSEKÖĞRETİM KURULU (YÖK)', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(5)

class BotasPDF(BasePDF):
    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'BOTAŞ - BORU HATLARI İLE PETROL TAŞIMA A.Ş.', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.set_font('Arial', '', 10)
        self.cell(0, 5, 'Doğal Gaz İşletme ve Piyasa İşlemleri Bölge Müdürlüğü', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(5)

class BelediyePDF(BasePDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'T.C. ANKARA BÜYÜKŞEHİR BELEDİYE BAŞKANLIĞI', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.set_font('Arial', 'B', 11)
        self.cell(0, 5, 'Belediye Meclisi Kararı', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(5)

# ========== PDF URETIM ==========

def generate_pdf(org_code, pdf_class, title, content, doc_id):
    pdf = pdf_class()
    pdf.add_page()

    fake_name = random.choice(NAMES)
    fake_tc = gen_fake_tc()
    fake_phone = gen_fake_phone()
    il = random.choice(ILLER)
    ilce = random.choice(ILCELER)

    # Sablondaki placeholder'lari doldur
    content = content.format(
        name=fake_name, tc=fake_tc, phone=fake_phone,
        il=il, ilce=ilce, date=gen_fake_date(),
        sayi=random.randint(5, 500), sayi2=random.randint(10, 999),
        sayi3=random.randint(3, 85)
    )

    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 10, f'Sayı: {gen_fake_sayi()}', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 10, f'Tarih: {gen_fake_date()}', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 10, f'Konu: {title}', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, 'İLGİLİ MAKAMA', border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
    pdf.ln(5)

    pdf.set_font('Arial', '', 11)
    pdf.multi_cell(0, 7, content)

    pdf.ln(15)
    pdf.set_font('Arial', 'B', 11)
    signer = random.choice(NAMES)
    pdf.cell(0, 10, signer, border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')
    pdf.set_font('Arial', 'I', 10)
    titles = ["Genel Müdür", "Daire Başkanı", "Şube Müdürü", "İl Müdürü", "Rektör Yardımcısı", "Başkan Yardımcısı"]
    pdf.cell(0, 5, random.choice(titles), border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='R')

    filename = f"{org_code}_SIMULASYON_{str(doc_id).zfill(3)}.pdf"
    pdf.output(str(BASE_DIR / filename))

def main():
    print("Cesitli Kurumlara Ozel 300 Adet ZENGIN ICERIKLI PDF Uretiliyor...")

    orgs = [
        ("MEB", MebPDF, MEB_CONTENTS),
        ("ISKI", IskiPDF, ISKI_CONTENTS),
        ("SGK", SgkPDF, SGK_CONTENTS),
        ("YOK", YokPDF, YOK_CONTENTS),
        ("BOTAS", BotasPDF, BOTAS_CONTENTS),
        ("ANKARA_BSB", BelediyePDF, BELEDIYE_CONTENTS),
    ]

    success = 0
    for org_code, pdf_class, content_list in orgs:
        for i in range(1, 51):
            title, content_template = random.choice(content_list)
            title_with_num = f"{title} - Belge No {i}"
            generate_pdf(org_code, pdf_class, title_with_num, content_template, i)
            success += 1

    print(f"Islem Basarili! Toplam {success} adet zengin icerikli PDF uretildi.")

if __name__ == "__main__":
    main()
