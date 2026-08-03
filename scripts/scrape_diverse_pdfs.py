import os
import time
import requests
import uuid
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).parent.parent / "datasets" / "resmi_yazisma" / "00_gelen_kaynaklar" / "pdf"
BASE_DIR.mkdir(parents=True, exist_ok=True)

TARGETS = [
    "https://www.iski.istanbul/web/tr-TR/kurumsal/mevzuat",
    "https://www.botas.gov.tr/Sayfa/mevzuat/105",
    "https://www.teias.gov.tr/mevzuat",
    "https://www.ankara.bel.tr/meclis-kararlari",
    "https://yok.gov.tr/kurumsal/mevzuat"
]

def main():
    print("Otonom Web Crawler (Orumcek) Devrede. Hedef: 200 Cesitli PDF...")
    success_count = 0
    target_pdfs = 200
    
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    
    # Adim 1: Belirli sitelerden crawling yaparak PDF toplama
    for url in TARGETS:
        if success_count >= target_pdfs: break
        print(f"Taraniyor: {url}")
        try:
            resp = session.get(url, timeout=15, verify=False)
            soup = BeautifulSoup(resp.content, "html.parser")
            
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.lower().endswith('.pdf'):
                    pdf_url = urljoin(url, href)
                    domain = urlparse(pdf_url).netloc.replace("www.", "")
                    
                    try:
                        pdf_resp = session.get(pdf_url, timeout=10, verify=False)
                        if pdf_resp.status_code == 200 and b'%PDF' in pdf_resp.content[:10]:
                            org_name = domain.split('.')[0].upper()
                            filename = f"{org_name}_BELGE_{uuid.uuid4().hex[:6].upper()}.pdf"
                            file_path = BASE_DIR / filename
                            
                            with open(file_path, 'wb') as f:
                                f.write(pdf_resp.content)
                            print(f"  [OK] CRAWLER: {org_name} -> {filename}")
                            success_count += 1
                            if success_count >= target_pdfs: break
                    except:
                        pass
        except Exception as e:
            print(f"[{url}] Crawler Hatasi: Atlaniyor...")

    # Adim 2: Sayiyi tamamlamak icin guvenilir yapisal URL'lerden (MEB ve Resmi Gazete) destek kuvvet
    print("\nYapisal Arsivler Taranarak Hedef Tamamlaniyor...")
    
    # MEB (1 - 40)
    for i in range(1, 40):
        if success_count >= target_pdfs: break
        url = f"https://mevzuat.meb.gov.tr/dosyalar/genelge/2024_{i}.pdf"
        try:
            r = session.get(url, timeout=5, verify=False)
            if r.status_code == 200 and b'%PDF' in r.content[:10]:
                filename = f"MEB_BELGE_{uuid.uuid4().hex[:6].upper()}.pdf"
                with open(BASE_DIR / filename, 'wb') as f:
                    f.write(r.content)
                print(f"  [OK] ARSIV: MEB -> {filename}")
                success_count += 1
        except: pass
        
    # Resmi Gazete
    from datetime import datetime, timedelta
    date = datetime(2024, 6, 1)
    for i in range(200):
        if success_count >= target_pdfs: break
        date = date - timedelta(days=1)
        yyyy, mm, dd = date.strftime("%Y"), date.strftime("%m"), date.strftime("%d")
        url = f"https://www.resmigazete.gov.tr/eskiler/{yyyy}/{mm}/{yyyy}{mm}{dd}-1.pdf"
        try:
            r = session.get(url, timeout=5, verify=False)
            if r.status_code == 200 and b'%PDF' in r.content[:10]:
                filename = f"RESMI_GAZETE_{yyyy}{mm}{dd}.pdf"
                if not (BASE_DIR / filename).exists():
                    with open(BASE_DIR / filename, 'wb') as f:
                        f.write(r.content)
                    print(f"  [OK] ARSIV: RESMI_GAZETE -> {filename}")
                    success_count += 1
        except: pass

    print(f"\nOperasyon Tamamlandi. Toplam {success_count} adet gercek, ham PDF indirildi.")

if __name__ == "__main__":
    main()
