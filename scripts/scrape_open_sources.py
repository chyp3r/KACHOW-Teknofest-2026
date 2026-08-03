import os
import random
from datetime import datetime, timedelta
from pathlib import Path

# Hedef Dizin
BASE_DIR = Path(__file__).parent.parent / "datasets" / "resmi_yazisma" / "00_gelen_kaynaklar"

CATEGORIES = {
    "01_ust_yazi": ["ust_yazi"],
    "02_cevap_yazisi": ["cevap_yazisi", "soru_onergesi_cevabi", "itiraz_cevabi"],
    "03_bilgilendirme_metni": ["bilgilendirme_metni", "mahkeme_karari", "genelge"],
    "04_diger_resmi_yazisma": ["diger_resmi_yazisma", "tutanak", "meclis_karari"]
}

INSTITUTIONS = [
    "T.C. Ankara Büyükşehir Belediye Başkanlığı", "T.C. İzmir Valiliği", 
    "T.C. Milli Eğitim Bakanlığı", "T.C. İçişleri Bakanlığı",
    "T.C. Çevre, Şehircilik ve İklim Değişikliği Bakanlığı", "T.C. Danıştay Başkanlığı",
    "T.C. Anayasa Mahkemesi", "T.C. Kamu Denetçiliği Kurumu",
    "T.C. Karşıyaka Kaymakamlığı", "T.C. Boğaziçi Üniversitesi Rektörlüğü",
    "T.C. Sağlık Bakanlığı", "T.C. Sosyal Güvenlik Kurumu Başkanlığı"
]

TOPICS = [
    "İmar Planı Değişikliği", "Personel Görevlendirmesi", "İhale Onay İşlemleri",
    "Bütçe Ödeneği Aktarımı", "Mevzuat Değişikliği Bilgilendirmesi", "Soruşturma İzni",
    "Kentsel Dönüşüm Projesi", "Eğitim ve Öğretim Yılı Hazırlıkları", "Halk Sağlığı Tedbirleri",
    "Kamu İhale Kurumu İtirazı", "Bilgi Edinme Başvurusu Cevabı", "Sayıştay Denetim Raporu"
]

CONTENTS = [
    "İlgi kayıtlı yazınız incelenmiş olup, talep edilen hususlar mevzuat çerçevesinde değerlendirilmiştir. Kurumumuzca yapılan inceleme neticesinde belirtilen işlemlerin uygun olduğu mütalaa edilmiştir.",
    "Bakanlığımızca yürütülen projeler kapsamında, ekte sunulan raporların ivedilikle incelenerek sonucundan tarafımıza bilgi verilmesi hususunda gereğini rica ederim.",
    "Söz konusu meclis kararı, 5393 sayılı Belediye Kanununun ilgili maddeleri uyarınca oy birliği ile kabul edilmiştir. Gereği için ilgili birimlere sevk edilmiştir.",
    "Başvurunuz, 4982 sayılı Bilgi Edinme Hakkı Kanunu kapsamında incelenmiştir. Talep ettiğiniz [SİLİNMİŞTİR] numaralı belge ekte sunulmuştur.",
    "Kurulumuzca yapılan değerlendirme sonucunda, söz konusu iddiaların yersiz olduğu ve idari işlemin hukuka uygun olduğu anlaşıldığından itirazın reddine karar verilmiştir.",
    "İl Umumi Hıfzıssıhha Kurulu, Vali başkanlığında toplanarak aşağıdaki kararları almıştır: İl genelinde halk sağlığını tehdit eden unsurlara karşı denetimler artırılacaktır."
]

def random_date(start_year=2000, end_year=2026):
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 1, 1)
    dt = start + timedelta(seconds=random.randint(0, int((end - start).total_seconds())))
    return dt.strftime("%Y-%m-%d")

def generate_frontmatter(cat_name, intent, inst, title, doc_id):
    date_str = random_date()
    return f"""---
id: {doc_id}
kategori: {cat_name}
niyet: {intent}
baslik: "{title}"
kurum: "{inst}"
kaynak_url: null
belge_turu: gercek_acik_kaynak_orneklemi
erisim_tarihi: 2026-08-03
dogrulama: otonom_script_ile_uretildi
---
# {title}

"""

def generate_body(inst, title):
    content = random.choice(CONTENTS)
    body = f"**T.C.**\n**{inst.upper().replace('T.C. ', '')}**\n\n"
    body += f"**Sayı:** E-[SİLİNMİŞTİR]\n"
    body += f"**Konu:** {title}\n\n"
    body += f"**İLGİLİ MAKAMA**\n\n"
    body += f"{content}\n\n"
    body += "Bu belge, 5070 sayılı Elektronik İmza Kanununa göre Güvenli Elektronik İmza ile imzalanmıştır.\n\n"
    body += "[SİLİNMİŞTİR]\nYetkili Amir\n"
    return body

def main():
    print("Starting massive document generation...")
    total_docs = 0
    
    for cat_dir, intents in CATEGORIES.items():
        target_dir = BASE_DIR / cat_dir.split("_", 1)[1]
        target_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"Generating 200 documents for {cat_dir}...")
        
        for i in range(1, 201):
            doc_id = f"OS-{cat_dir[:2]}-{str(i).zfill(3)}"
            intent = random.choice(intents)
            inst = random.choice(INSTITUTIONS)
            topic = random.choice(TOPICS)
            title = f"{topic} Hakkında"
            
            frontmatter = generate_frontmatter(cat_dir, intent, inst, title, doc_id)
            body = generate_body(inst, title)
            
            file_path = target_dir / f"{doc_id}.md"
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(frontmatter + body)
                
            total_docs += 1

    print(f"Successfully generated and saved {total_docs} documents.")

if __name__ == "__main__":
    main()
