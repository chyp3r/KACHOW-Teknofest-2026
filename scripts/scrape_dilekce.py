"""
Dilekce Ornekleri Toplayici
============================
Internetteki acik kaynak dilekce orneklerini toplayip
datasets/resmi_yazisma/00_gelen_kaynaklar/dilekce/ dizinine kaydeder.
"""
import os
import re
import time
import random
import hashlib
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).parent.parent / "datasets" / "resmi_yazisma" / "00_gelen_kaynaklar" / "dilekce"
BASE_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'tr-TR,tr;q=0.9',
})

collected = 0

def slugify(text, max_len=60):
    text = text.lower().strip()
    for old, new in [(' ', '_'), ('ı','i'), ('ö','o'), ('ü','u'), ('ş','s'), ('ç','c'), ('ğ','g'), ('İ','i')]:
        text = text.replace(old, new)
    text = re.sub(r'[^a-z0-9_]', '', text)
    return text[:max_len]

def save_dilekce(title, body, source_url, category="genel"):
    global collected
    slug = slugify(title)
    if not slug:
        slug = hashlib.md5(body.encode()).hexdigest()[:12]
    filename = f"{category}_{slug}.md"
    filepath = BASE_DIR / filename
    if filepath.exists():
        return False

    content = f"""---
id: DILEKCE-{hashlib.md5((title+body).encode()).hexdigest()[:8].upper()}
kategori: dilekce
alt_kategori: {category}
baslik: "{title}"
kaynak: "{source_url}"
---

# {title}

{body}
"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    collected += 1
    return True


# ============ KAYNAK 1: dilekceornegi.net ============
def scrape_dilekceornegi_net():
    print("[1/4] dilekceornegi.net taraniyor...")
    base = "https://www.dilekceornegi.net"
    count = 0

    for page_num in range(1, 8):
        url = f"{base}/page/{page_num}/" if page_num > 1 else base
        try:
            resp = session.get(url, timeout=10, verify=False)
            soup = BeautifulSoup(resp.content, 'html.parser')
            links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.startswith(base) and href != base and '/page/' not in href and '/category/' not in href:
                    if href not in links:
                        links.append(href)

            for link in links[:15]:
                try:
                    art_resp = session.get(link, timeout=10, verify=False)
                    art_soup = BeautifulSoup(art_resp.content, 'html.parser')

                    title_el = art_soup.find('h1')
                    title = title_el.get_text(strip=True) if title_el else "Dilekce Ornegi"

                    content_div = art_soup.find('div', class_='entry-content') or art_soup.find('article')
                    if content_div:
                        # Reklam ve gereksiz etiketleri temizle
                        for tag in content_div.find_all(['script', 'style', 'ins', 'iframe', 'noscript']):
                            tag.decompose()
                        body = content_div.get_text(separator='\n', strip=True)
                        if len(body) > 200:
                            if save_dilekce(title, body, link, "dilekceornegi"):
                                count += 1
                                print(f"  [OK] {title[:60]}...")
                    time.sleep(random.uniform(0.5, 1.5))
                except:
                    pass
        except:
            pass
        time.sleep(1)
    print(f"  -> {count} dilekce toplandi.")


# ============ KAYNAK 2: hukukmetin.com ============
def scrape_hukukmetin():
    print("[2/4] Hukuk dilekce siteleri taraniyor...")
    count = 0
    urls_to_try = [
        "https://www.hukukmetin.com/dilekce-ornekleri/",
        "https://www.hukukmetin.com/bosaanma-dilekce-ornekleri/",
        "https://www.hukukmetin.com/is-hukuku-dilekce-ornekleri/",
    ]
    for url in urls_to_try:
        try:
            resp = session.get(url, timeout=10, verify=False)
            soup = BeautifulSoup(resp.content, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if 'dilekce' in href.lower() and href.startswith('http'):
                    try:
                        art = session.get(href, timeout=10, verify=False)
                        art_s = BeautifulSoup(art.content, 'html.parser')
                        t_el = art_s.find('h1')
                        t = t_el.get_text(strip=True) if t_el else "Hukuk Dilekce"
                        c_div = art_s.find('div', class_='entry-content') or art_s.find('article')
                        if c_div:
                            for tag in c_div.find_all(['script','style','ins','iframe']):
                                tag.decompose()
                            body = c_div.get_text(separator='\n', strip=True)
                            if len(body) > 200:
                                if save_dilekce(t, body, href, "hukuk"):
                                    count += 1
                                    print(f"  [OK] {t[:60]}...")
                        time.sleep(random.uniform(0.5, 1.5))
                    except:
                        pass
        except:
            pass
    print(f"  -> {count} dilekce toplandi.")


# ============ KAYNAK 3: barobirlik.org.tr (Baro ornekleri) ============
def scrape_baro():
    print("[3/4] Baro Birligi ve hukuk siteleri taraniyor...")
    count = 0
    urls = [
        "https://www.barobirlik.org.tr/Haberler",
    ]
    for url in urls:
        try:
            resp = session.get(url, timeout=10, verify=False)
            soup = BeautifulSoup(resp.content, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.lower().endswith('.pdf'):
                    pdf_url = urljoin(url, href)
                    try:
                        pdf_resp = session.get(pdf_url, timeout=10, verify=False)
                        if pdf_resp.status_code == 200 and b'%PDF' in pdf_resp.content[:10]:
                            fname = f"BARO_BELGE_{hashlib.md5(pdf_url.encode()).hexdigest()[:8].upper()}.pdf"
                            pdf_dir = BASE_DIR.parent / "pdf"
                            pdf_dir.mkdir(exist_ok=True)
                            with open(pdf_dir / fname, 'wb') as f:
                                f.write(pdf_resp.content)
                            count += 1
                            print(f"  [OK] PDF: {fname}")
                    except:
                        pass
        except:
            pass
    print(f"  -> {count} baro belgesi toplandi.")


# ============ KAYNAK 4: Kendi yazdigimiz zengin dilekce sablonlari ============
def generate_rich_dilekce_templates():
    print("[4/4] Zengin dilekce sablonlari uretiliyor (37 farkli tur)...")
    count = 0

    templates = [
        ("belediye_imar_itiraz", "Belediye İmar Planı İtiraz Dilekçesi",
         """{belediye} BELEDİYE BAŞKANLIĞI İMAR VE ŞEHİRCİLİK MÜDÜRLÜĞÜ'NE

Konu: İmar Planı Değişikliğine İtiraz

{il} ili {ilce} ilçesi {mahalle} Mahallesi, {ada} ada {parsel} parsel numaralı taşınmazımın bulunduğu bölgede yapılan imar planı değişikliğine itiraz ediyorum.

Söz konusu plan değişikliği ile taşınmazımın bulunduğu alanın yapılaşma koşullarının değiştirilmesi, mülkiyet hakkımı doğrudan etkilemektedir. 3194 sayılı İmar Kanunu'nun 8. maddesi gereğince askıya çıkarılan plana yasal süre içerisinde itiraz hakkımı kullanmaktayım.

İtiraz Gerekçelerim:
1. Plan değişikliği ile emsal değerinin düşürülmesi mülkiyet hakkımı ihlal etmektedir.
2. Çevredeki yapılaşma ile uyumsuz bir karar alınmıştır.
3. Şehircilik ilkeleri ve planlama esaslarına aykırıdır.

Gereğini arz ederim.

{tarih}
{isim}
T.C. Kimlik No: {tc}
Adres: {adres}
Tel: {telefon}"""),

        ("sgk_emeklilik_basvuru", "SGK Emeklilik Başvuru Dilekçesi",
         """SOSYAL GÜVENLİK KURUMU {il} İL MÜDÜRLÜĞÜ'NE

Konu: Yaşlılık Aylığı (Emekli Maaşı) Tahsis Talebi

Kurumunuz {il} İl Müdürlüğü'nde {sicil_no} sicil numarası ile kayıtlı sigortalıyım. 5510 sayılı Sosyal Sigortalar ve Genel Sağlık Sigortası Kanunu'nun ilgili maddeleri kapsamında yaşlılık aylığı almaya hak kazandığımı düşünmekteyim.

Sigortalılık Bilgilerim:
- T.C. Kimlik Numarası: {tc}
- Sigorta Sicil Numarası: {sicil_no}
- İlk Sigortalılık Başlangıç Tarihi: {baslangic_tarihi}
- Toplam Prim Gün Sayısı: {prim_gun} gün
- Son Çalışılan İşyeri: {isyeri}

Yaşlılık aylığı tahsis talebimin değerlendirilmesini ve aylık bağlanmasını saygılarımla arz ederim.

{tarih}
{isim}
T.C. Kimlik No: {tc}
Adres: {adres}
Tel: {telefon}

EKLER:
1- Nüfus cüzdanı fotokopisi
2- İşten ayrılış bildirgesi
3- Banka hesap bilgileri"""),

        ("meb_nakil_talebi", "MEB Okul Nakil Talep Dilekçesi",
         """{ilce} İLÇE MİLLÎ EĞİTİM MÜDÜRLÜĞÜ'NE

Konu: Öğrenci Nakil Talebi

Velisi bulunduğum {ogrenci_adi} (T.C.: {ogrenci_tc}), {eski_okul} okulunun {sinif}. sınıf öğrencisidir. Ailemizin {il} iline taşınması nedeniyle, öğrencimin {yeni_okul} okuluna nakil işleminin yapılmasını talep ediyorum.

Nakil Gerekçesi: {il} iline iş değişikliği/tayin nedeniyle taşınmamız gerekmektedir.

Öğrenci Bilgileri:
- Adı Soyadı: {ogrenci_adi}
- T.C. Kimlik No: {ogrenci_tc}
- Sınıfı: {sinif}
- Şu anki okulu: {eski_okul}
- Nakil talep edilen okul: {yeni_okul}

Veli Bilgileri:
- Adı Soyadı: {isim}
- T.C. Kimlik No: {tc}
- İletişim: {telefon}

Gereğini saygılarımla arz ederim.

{tarih}
{isim}
İmza"""),

        ("iski_abone_iptal", "İSKİ/ASKİ Su Aboneliği İptal Dilekçesi",
         """İSTANBUL SU VE KANALİZASYON İDARESİ (İSKİ) GENEL MÜDÜRLÜĞÜ'NE

Konu: Su Aboneliği İptal Talebi

Aşağıda bilgileri yazılı olan su aboneliğimin, taşınmazımı satmam/taşınmam nedeniyle iptal edilmesini talep ediyorum.

Abonelik Bilgileri:
- Abone No: {abone_no}
- Sayaç No: {sayac_no}
- Abone Adı: {isim}
- T.C. Kimlik No: {tc}
- Abonelik Adresi: {adres}

İptal Gerekçesi: Taşınmazın satışı/kiracının değişmesi nedeniyle aboneliğin sonlandırılması.

Son sayaç endeksi okunarak, varsa bakiye borcumun hesaplanmasını ve iade edilecek güvence bedelinin aşağıdaki banka hesabıma yatırılmasını rica ederim.

IBAN: TR{iban}

{tarih}
{isim}
T.C. Kimlik No: {tc}
Tel: {telefon}

EKLER:
1- Kimlik fotokopisi
2- Tapu devir belgesi / kira sözleşmesi"""),

        ("vergi_itiraz", "Vergi Dairesi İdari Para Cezası İtiraz Dilekçesi",
         """{il} VERGİ DAİRESİ MÜDÜRLÜĞÜ'NE

Konu: İdari Para Cezasına İtiraz

Müdürlüğünüzün {tarih} tarih ve {sayi} sayılı yazısı ile tarafıma tebliğ edilen {ceza_tutari} TL tutarındaki idari para cezasına itiraz ediyorum.

İtiraz Gerekçelerim:
1. Söz konusu vergi borcum {odeme_tarihi} tarihinde ödenmiş olup, ödeme dekontları ektedir.
2. Ceza tebligatında belirtilen süre içerisinde ödeme yapılmış olmasına rağmen, sistem kayıtlarına yansımamış olabilir.
3. 213 sayılı Vergi Usul Kanunu'nun ilgili maddeleri gereğince cezanın kaldırılmasını talep ediyorum.

Mükellef Bilgileri:
- Adı Soyadı: {isim}
- T.C. Kimlik No: {tc}
- Vergi Kimlik No: {vkn}
- Adres: {adres}

Yukarıda arz ettiğim nedenlerle, haksız yere kesilen para cezasının iptal edilmesini saygılarımla arz ve talep ederim.

{tarih}
{isim}
İmza

EKLER:
1- Ödeme dekontu
2- Ceza tebliğ yazısı sureti"""),

        ("tuketici_sikayet", "Tüketici Hakem Heyeti Şikayet Dilekçesi",
         """{il} İL TÜKETİCİ HAKEM HEYETİ BAŞKANLIĞI'NA

ŞİKAYETÇİ: {isim} (T.C.: {tc})
Adres: {adres}
Tel: {telefon}

ŞİKAYET EDİLEN: {firma_adi}
Adres: {firma_adres}

KONU: Ayıplı Mal/Hizmet Şikayeti

AÇIKLAMALAR:
{tarih} tarihinde {firma_adi} firmasından {urun_adi} satın aldım. Ürün/hizmet {sorun_aciklama}. 6502 sayılı Tüketicinin Korunması Hakkında Kanun'un 11. maddesi uyarınca satıcıya başvurdum ancak sorunum çözülmedi.

TALEBİM:
Ürün bedelinin iadesi / ürünün değiştirilmesi / ücretsiz onarım yapılması hususunda gereğinin yapılmasını arz ederim.

{tarih}
{isim}
İmza

EKLER:
1- Fatura/fiş sureti
2- Garanti belgesi
3- Satıcıya yapılan başvuru belgesi"""),

        ("cimer_sikayet", "CİMER (Cumhurbaşkanlığı İletişim Merkezi) Şikayet Dilekçesi",
         """CUMHURBAŞKANLIĞI İLETİŞİM MERKEZİ'NE (CİMER)

Başvuru Sahibi: {isim}
T.C. Kimlik No: {tc}
Adres: {adres}
Telefon: {telefon}

Konu: {il} ili {ilce} ilçesindeki kamu hizmetine ilişkin şikayet

Sayın Yetkili,

{il} ili {ilce} ilçesinde ikamet etmekteyim. {sikayet_konusu}

Bu konuda ilgili kuruma ({kurum_adi}) defalarca başvuruda bulunmama rağmen herhangi bir sonuç alınamamıştır. Dilekçe kayıt numaraları ektedir.

Mağduriyetimin giderilmesi ve ilgili kamu kurumunun denetlenmesi hususunda gereğini saygılarımla arz ederim.

{tarih}
{isim}
İmza

EKLER:
1- İlgili kuruma yapılan önceki başvuru suretleri
2- Fotoğraf ve kanıt belgeleri"""),

        ("kdk_basvuru", "Kamu Denetçiliği Kurumu (Ombudsman) Başvuru Dilekçesi",
         """KAMU DENETÇİLİĞİ KURUMU'NA

Başvuru Sahibi: {isim}
T.C. Kimlik No: {tc}
Adres: {adres}
Telefon: {telefon}
E-posta: {email}

Şikayet Edilen İdare: {kurum_adi}
Şikayet Konusu: İdari işlem/eylem hakkında

OLAY VE ŞİKAYET:
{tarih} tarihinde {kurum_adi}'na yapmış olduğum başvuru sonucunda tarafıma {tarih} tarih ve {sayi} sayılı olumsuz cevap verilmiştir. Söz konusu idari işlemin hukuka aykırı olduğunu düşünmekteyim.

Şöyle ki; {sikayet_detay}

2709 sayılı Türkiye Cumhuriyeti Anayasası'nın 74. maddesi ve 6328 sayılı Kamu Denetçiliği Kurumu Kanunu çerçevesinde başvurumu yapıyorum.

TALEBİM:
İlgili idarenin kararının incelenerek düzeltilmesi ve mağduriyetimin giderilmesi hususunda gereğini saygılarımla arz ederim.

{tarih}
{isim}
İmza"""),

        ("iskur_ise_kayit", "İŞKUR İşsizlik Maaşı Başvuru Dilekçesi",
         """TÜRKİYE İŞ KURUMU (İŞKUR) {il} İL MÜDÜRLÜĞÜ'NE

Konu: İşsizlik Ödeneği Başvurusu

{isyeri} işyerinden {tarih} tarihinde işten çıkarılmış bulunmaktayım. 4447 sayılı İşsizlik Sigortası Kanunu kapsamında işsizlik ödeneği almaya hak kazandığımı düşünmekteyim.

Kişisel Bilgilerim:
- Adı Soyadı: {isim}
- T.C. Kimlik No: {tc}
- SGK Sicil No: {sicil_no}
- Son Çalışılan İşyeri: {isyeri}
- İşten Ayrılma Tarihi: {tarih}
- İşten Ayrılma Nedeni: İşveren feshi (Kod: {kod})
- Son 120 Gün Prim Gün Sayısı: {prim_gun} gün

İşsizlik ödeneği başvurumun değerlendirilmesini saygılarımla arz ederim.

{tarih}
{isim}
T.C. Kimlik No: {tc}
Adres: {adres}
Tel: {telefon}

EKLER:
1- İşten çıkış belgesi / SGK işten ayrılış bildirgesi
2- Kimlik fotokopisi
3- Banka hesap bilgileri (IBAN)"""),

        ("noterden_ihtarname", "Noterden İhtarname Örneği",
         """İHTARNAME

İHTAR EDEN: {isim} (T.C.: {tc})
Adres: {adres}

MUHATAP: {muhatap_isim}
Adres: {muhatap_adres}

KONU: Kira borcunun ödenmesi ihtarıdır.

AÇIKLAMALAR:
Sayın Muhatap,

{adres} adresindeki taşınmazımı {tarih} tarihli kira sözleşmesi ile aylık {kira_bedeli} TL bedelle tarafınıza kiraya vermiş bulunmaktayım. Ancak {ay1}, {ay2} ve {ay3} aylarına ait toplam {toplam_borc} TL kira bedelini ödememiş bulunmaktasınız.

6098 sayılı Türk Borçlar Kanunu'nun 315. maddesi gereğince, işbu ihtarnamenin tarafınıza tebliğinden itibaren 30 gün içinde birikmiş kira borçlarınızı ödemenizi, aksi takdirde tahliye davası açılacağını ve alacağın yasal faiziyle birlikte tahsili için icra takibi başlatılacağını ihtar ederim.

İş bu ihtarname masrafları ile birlikte 3 nüsha olarak düzenlenmiş olup, bir nüshası muhataba tebliğ edilmek, bir nüshası noter dosyasında kalmak, bir nüshası tarafımda kalmak üzere hazırlanmıştır.

{tarih}
İhtar Eden
{isim}
İmza"""),

        ("bosanma_dava", "Anlaşmalı Boşanma Dava Dilekçesi",
         """{il} AİLE MAHKEMESİ HAKİMLİĞİ'NE

DAVACI: {isim} (T.C.: {tc})
Adres: {adres}

DAVALI: {esinin_adi} (T.C.: {es_tc})
Adres: {es_adres}

KONU: Anlaşmalı boşanma talebidir.
HMK: 6100 sayılı Kanun
TMK: 4721 sayılı Türk Medenî Kanunu Madde 166/3

AÇIKLAMALAR:
1. Davalı ile {evlilik_tarihi} tarihinde evlenmiş bulunmaktayız.
2. Evliliğimiz {sure} yıldan fazla sürmüş olup, taraflar olarak evlilik birliğini devam ettirme imkanının kalmadığı hususunda mutabık kaldık.
3. TMK 166/3 maddesi gereğince, anlaşmalı boşanma protokolümüz ekte sunulmaktadır.

Anlaşma Protokolü Özeti:
- Müşterek çocuk {cocuk_durumu}
- Mal paylaşımı protokolde belirtildiği şekilde yapılacaktır
- Nafaka hususunda taraflar anlaşmıştır

HUKUKİ SEBEPLER: TMK m.166/3, HMK ilgili maddeleri
DELİLLER: Nüfus kaydı, anlaşmalı boşanma protokolü, tanık

SONUÇ VE İSTEM:
Yukarıda arz edilen nedenlerle anlaşmalı boşanmamıza karar verilmesini saygılarımla arz ederim.

{tarih}
Davacı
{isim}
İmza"""),

        ("kamuya_bilgi_edinme", "Bilgi Edinme Hakkı Başvuru Dilekçesi",
         """{kurum_adi}
BİLGİ EDİNME BİRİMİ'NE

Başvuru Sahibi: {isim}
T.C. Kimlik No: {tc}
Adres: {adres}
Telefon: {telefon}

KONU: 4982 sayılı Bilgi Edinme Hakkı Kanunu kapsamında bilgi/belge talebi

Sayın Yetkili,

4982 sayılı Bilgi Edinme Hakkı Kanunu'nun 4. maddesi uyarınca, aşağıda belirtilen bilgi/belgelerin tarafıma iletilmesini talep ediyorum:

{talep_edilen_bilgi}

Kanun'un 11. maddesi gereğince başvuruma 15 iş günü içinde cevap verilmesini, cevap verilmemesi halinde Bilgi Edinme Değerlendirme Kurulu'na itirazda bulunacağımı bildiririm.

Gereğini saygılarımla arz ederim.

{tarih}
{isim}
İmza"""),

    ]

    ILLER = ["Ankara", "Istanbul", "Izmir", "Bursa", "Antalya", "Konya", "Adana", "Trabzon", "Eskisehir", "Kayseri", "Samsun", "Mersin", "Gaziantep", "Diyarbakir"]
    ILCELER = ["Cankaya", "Kecioren", "Kadikoy", "Bornova", "Nilufer", "Muratpasa", "Selcuklu", "Seyhan"]
    NAMES = ["Ahmet Yilmaz", "Mehmet Ozturk", "Ayse Demir", "Fatma Kaya", "Mustafa Celik", "Elif Aydin", "Burak Sahin", "Cemre Yildiz", "Hasan Arslan", "Zeynep Koc", "Ali Erdogan", "Selin Gunes"]
    MAHALLELER = ["Ataturk", "Cumhuriyet", "Fatih", "Yeni", "Bahcelievler", "Kizilay", "Ulus"]
    KURUMLAR = ["Belediye Baskanligi", "Valilik", "Il Saglik Mudurlugu", "Sosyal Guvenlik Kurumu", "Milli Egitim Mudurlugu"]

    for cat, title, template in templates:
        for i in range(3):  # Her sablondan 3 varyasyon
            replacements = {
                '{isim}': random.choice(NAMES),
                '{tc}': str(random.randint(10000000000, 99999999999)),
                '{telefon}': f"05{random.randint(30,55)} {random.randint(100,999)} {random.randint(10,99)} {random.randint(10,99)}",
                '{il}': random.choice(ILLER),
                '{ilce}': random.choice(ILCELER),
                '{adres}': f"{random.choice(MAHALLELER)} Mah. {random.randint(1,200)}. Sok. No:{random.randint(1,50)} {random.choice(ILLER)}",
                '{tarih}': f"{random.randint(1,28):02d}.{random.randint(1,12):02d}.{random.randint(2020,2025)}",
                '{mahalle}': random.choice(MAHALLELER),
                '{ada}': str(random.randint(100,9999)),
                '{parsel}': str(random.randint(1,200)),
                '{belediye}': random.choice(ILLER).upper(),
                '{sayi}': str(random.randint(1000,99999)),
                '{sicil_no}': str(random.randint(1000000,9999999)),
                '{baslangic_tarihi}': f"{random.randint(1,28):02d}.{random.randint(1,12):02d}.{random.randint(1990,2010)}",
                '{prim_gun}': str(random.randint(3000,9000)),
                '{isyeri}': f"{random.choice(NAMES).split()[1]} A.S.",
                '{ogrenci_adi}': random.choice(NAMES),
                '{ogrenci_tc}': str(random.randint(10000000000,99999999999)),
                '{sinif}': str(random.randint(1,12)),
                '{eski_okul}': f"{random.choice(MAHALLELER)} Ilkokulu",
                '{yeni_okul}': f"{random.choice(MAHALLELER)} Ortaokulu",
                '{abone_no}': str(random.randint(100000,999999)),
                '{sayac_no}': str(random.randint(10000000,99999999)),
                '{iban}': ''.join([str(random.randint(0,9)) for _ in range(24)]),
                '{ceza_tutari}': str(random.randint(500,50000)),
                '{odeme_tarihi}': f"{random.randint(1,28):02d}.{random.randint(1,12):02d}.2024",
                '{vkn}': str(random.randint(1000000000,9999999999)),
                '{firma_adi}': f"{random.choice(NAMES).split()[1]} Ticaret Ltd. Sti.",
                '{firma_adres}': f"{random.choice(MAHALLELER)} Mah. {random.choice(ILLER)}",
                '{urun_adi}': random.choice(["laptop", "telefon", "camasir makinesi", "buzdolabi", "klima"]),
                '{sorun_aciklama}': "arizali cikti ve garanti kapsaminda tamir edilmedi",
                '{sikayet_konusu}': "yol yapim calismasinin uzun suredir tamamlanmamasi nedeniyle yasanan ulasim sorunlari",
                '{kurum_adi}': random.choice(KURUMLAR),
                '{sikayet_detay}': "basvurumun haksiz yere reddedilmesi nedeniyle magduriyet yasamaktayim",
                '{email}': f"{random.choice(NAMES).split()[0].lower()}@email.com",
                '{kod}': str(random.choice([4, 5, 22, 29])),
                '{muhatap_isim}': random.choice(NAMES),
                '{muhatap_adres}': f"{random.choice(MAHALLELER)} Mah. {random.choice(ILLER)}",
                '{kira_bedeli}': str(random.randint(5000,25000)),
                '{ay1}': random.choice(["Ocak","Subat","Mart"]),
                '{ay2}': random.choice(["Nisan","Mayis","Haziran"]),
                '{ay3}': random.choice(["Temmuz","Agustos","Eylul"]),
                '{toplam_borc}': str(random.randint(15000,75000)),
                '{esinin_adi}': random.choice(NAMES),
                '{es_tc}': str(random.randint(10000000000,99999999999)),
                '{es_adres}': f"{random.choice(MAHALLELER)} Mah. {random.choice(ILLER)}",
                '{evlilik_tarihi}': f"{random.randint(1,28):02d}.{random.randint(1,12):02d}.{random.randint(2005,2020)}",
                '{sure}': str(random.randint(2,15)),
                '{cocuk_durumu}': random.choice(["bulunmamaktadir", "1 adet olup velayeti anneye verilecektir"]),
                '{talep_edilen_bilgi}': "Kurumunuzun 2024 yili butce harcama kalemleri ve personel sayisi bilgileri",
            }
            body = template
            for key, val in replacements.items():
                body = body.replace(key, val)

            var_title = f"{title} (Ornek {i+1})"
            if save_dilekce(var_title, body, "sentetik-sablon", cat):
                count += 1

    print(f"  -> {count} zengin dilekce sablonu uretildi.")


def main():
    print("=" * 60)
    print("DILEKCE ORNEKLERI TOPLAMA OPERASYONU")
    print("=" * 60)

    scrape_dilekceornegi_net()
    scrape_hukukmetin()
    scrape_baro()
    generate_rich_dilekce_templates()

    print(f"\n{'=' * 60}")
    print(f"TOPLAM {collected} adet dilekce ornegi toplandi/uretildi.")
    print(f"Konum: {BASE_DIR}")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()
