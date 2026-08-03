import os
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).parent.parent / "datasets" / "resmi_yazisma" / "00_gelen_kaynaklar" / "pdf"
BASE_DIR.mkdir(parents=True, exist_ok=True)

def main():
    print("Gercek Resmi Gazete PDF'leri GENIS CAPLI (200 adet) indiriliyor...")
    
    # Geriye donuk tarih taramasi icin
    current_date = datetime(2024, 8, 1)
    
    success = 0
    target_count = 200
    
    for i in range(1000): # Geriye donuk 1000 gun taranacak (yaklasik 3 yil)
        if success >= target_count:
            break
            
        current_date = current_date - timedelta(days=1)
        yyyy = current_date.strftime("%Y")
        mm = current_date.strftime("%m")
        dd = current_date.strftime("%d")
        
        url = f"https://www.resmigazete.gov.tr/eskiler/{yyyy}/{mm}/{yyyy}{mm}{dd}-1.pdf"
        filename = f"RESMI_GAZETE_{yyyy}{mm}{dd}_1.pdf"
        file_path = BASE_DIR / filename
        
        # Eger dosya zaten varsa indirme (zaman kazanmak icin)
        if file_path.exists():
            success += 1
            continue
            
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    with open(file_path, 'wb') as f:
                        f.write(response.read())
                    print(f"[OK] Indirildi: {filename}")
                    success += 1
        except urllib.error.HTTPError as e:
            pass
        except Exception as e:
            pass
            
    print(f"\nToplam {success} adet gercek PDF ham (raw) olarak klasore eklendi.")

if __name__ == "__main__":
    main()
